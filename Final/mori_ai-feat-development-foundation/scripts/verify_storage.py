"""Small real-R2 probe. Only generated keys in a fresh namespace are touched."""
import hashlib
from io import BytesIO
import json
import sys
import time
from urllib.parse import urlsplit, parse_qs
from xml.etree import ElementTree
from uuid import uuid4

import httpx
from PIL import Image
from backend.settings import Settings
from backend.storage.r2 import R2Storage


def report(check, passed):
    print(json.dumps({'check':check,'passed':bool(passed)}),flush=True)
    if not passed:
        raise RuntimeError('storage verification failed')


def sample(kind):
    image=Image.new('RGB',(30,40),(40,90,140))
    out=BytesIO()
    if kind=='HEIF':
        import pillow_heif
        pillow_heif.from_pillow(image).save(out)
    else:
        image.save(out,format=kind)
    return out.getvalue()


def main():
    try:
        settings=Settings()
    except Exception:
        print('Invalid storage verification settings; details suppressed.',file=sys.stderr)
        return 2
    if settings.storage_mode!='r2' or not settings.r2_key_prefix.startswith('mori-ai-storage-check/'):
        print('Refusing an unscoped storage check.',file=sys.stderr)
        return 2
    storage=R2Storage(settings)
    keys=[]
    attempt=str(uuid4())
    envelope_created=False
    success=False
    try:
        with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
            for kind,mime in [('PNG','image/png'),('JPEG','image/jpeg'),('HEIF','image/heic')]:
                data=sample(kind)
                key='/'.join(str(uuid4()) for _ in range(3))+'/source'
                keys.append(key)
                put=storage.sign_put(key,mime,len(data),60)
                headers={'Content-Type':mime,'If-None-Match':'*','Origin':settings.app_origin}
                response=client.put(put,headers=headers,content=data)
                report(kind+'_presigned_put',response.is_success)
                report(kind+'_remote_sha256',storage.stat(key).st_size==len(data)
                       and storage.checksum(key)==hashlib.sha256(data).hexdigest())
                report(kind+'_no_overwrite',client.put(put,headers=headers,content=data).status_code==412)
                report(kind+'_signed_head',client.head(storage.sign_head(key,60)).status_code==200)
                get=storage.sign_get(key,60)
                report(kind+'_signed_get',client.get(get).content==data)
                report(kind+'_unsigned_s3_denied',not client.get(get.split('?',1)[0]).is_success)
                if kind=='PNG':
                    cors=client.options(put,headers={'Origin':settings.app_origin,
                        'Access-Control-Request-Method':'PUT',
                        'Access-Control-Request-Headers':'content-type,if-none-match'})
                    allowed={x.strip().lower() for x in cors.headers.get('access-control-allow-headers','').split(',')}
                    report('cors_put_preflight',cors.is_success
                           and cors.headers.get('access-control-allow-origin')==settings.app_origin
                           and {'content-type','if-none-match'}<=allowed
                           and 'PUT' in cors.headers.get('access-control-allow-methods',''))
                    cross=client.get(get,headers={'Origin':settings.app_origin})
                    report('cors_get_etag',cross.status_code==200
                           and cross.headers.get('access-control-allow-origin')==settings.app_origin
                           and 'etag' in cross.headers.get('access-control-expose-headers','').lower())
                    wrong=client.options(put,headers={'Origin':'https://not-allowed.invalid',
                        'Access-Control-Request-Method':'PUT',
                        'Access-Control-Request-Headers':'content-type,if-none-match'})
                    report('cors_foreign_origin_not_allowed',
                           wrong.headers.get('access-control-allow-origin') not in ('*','https://not-allowed.invalid'))
                    signed=storage.sign_get(key,2)
                    report('short_url_initially_valid',client.get(signed).status_code==200)
                    query=parse_qs(urlsplit(signed).query)
                    print(json.dumps({"expiry_diagnostic":{"signed_date":query.get("X-Amz-Date"),"ttl":query.get("X-Amz-Expires"),"client_utc":time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())}}),flush=True)
                    expired=False
                    for _ in range(45):
                        time.sleep(1)
                        expiry_response=client.get(signed)
                        try:
                            error_code=ElementTree.fromstring(expiry_response.content).findtext("Code") if not expiry_response.is_success else None
                        except ElementTree.ParseError:
                            error_code=None
                        print(json.dumps({"expiry_diagnostic":{"status":expiry_response.status_code,"code":error_code,"date":expiry_response.headers.get("date"),"age":expiry_response.headers.get("age"),"cache_status":expiry_response.headers.get("cf-cache-status")}}),flush=True)
                        if expiry_response.status_code==403:
                            expired=True
                            break
                    report('short_url_really_expires',expired)
            envelope_created=True
            storage.write_envelope(attempt,b'{"synthetic":"recovery-probe"}')
            report('remote_attempt_envelope',storage.read_envelope(attempt)==b'{"synthetic":"recovery-probe"}')
            for key in keys:
                storage.delete(key)
                report('deleted_object_missing',not storage.exists(key))
            success=True
    except Exception as error:
        # Exceptions may hold signed URLs. Emit only their type, never message/context.
        print(json.dumps({'check':'storage_probe','passed':False,'error_type':type(error).__name__}),flush=True)
    finally:
        cleanup_ok=True
        for key in keys:
            try:
                storage.delete(key)
            except Exception:
                cleanup_ok=False
        if envelope_created:
            try:
                storage.delete_envelope(attempt)
            except Exception:
                cleanup_ok=False
        print(json.dumps({'check':'scoped_cleanup','passed':cleanup_ok}),flush=True)
        success=success and cleanup_ok
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())

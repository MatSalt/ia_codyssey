"""Original synthetic test data; no third-party profiles or photographs.

LittleCMS public C API is used only by tests (system liblcms2 already installed).
CMYK input profile: our analytic CMYK -> D50 Lab CLUT, not a printer profile.
"""
import ctypes as C
import ctypes.util
import struct
import zlib
from io import BytesIO
from pathlib import Path
import PIL
from PIL import Image


def synthetic_icc(mode):
    library = ctypes.util.find_library('lcms2')
    if not library:
        library = str(next((Path(PIL.__file__).parent.parent / 'pillow.libs').glob('*lcms2*')))
    lib = C.CDLL(library)
    def api(name, restype, *args):
        fn = getattr(lib, name); fn.restype = restype; fn.argtypes = list(args); return fn
    ptr = C.c_void_p; u = C.c_uint32
    close = api('cmsCloseProfile', C.c_int, ptr)
    free_curve = api('cmsFreeToneCurve', None, ptr)
    if mode == 'L':
        class XYZ(C.Structure):
            _fields_ = [('X', C.c_double), ('Y', C.c_double), ('Z', C.c_double)]
        curve = api('cmsBuildGamma', ptr, ptr, C.c_double)(None, 2.2)
        profile = api('cmsCreateGrayProfile', ptr, C.POINTER(XYZ), ptr)(C.byref(XYZ(.9642, 1., .8249)), curve)
        free_curve(curve)
    else:
        profile = api('cmsCreateProfilePlaceholder', ptr, ptr)(None)
        api('cmsSetProfileVersion', None, ptr, C.c_double)(profile, 2.1)
        sig = lambda s: int.from_bytes(s.encode(), 'big')
        api('cmsSetDeviceClass', None, ptr, u)(profile, sig('scnr'))
        api('cmsSetColorSpace', None, ptr, u)(profile, sig('CMYK'))
        api('cmsSetPCS', None, ptr, u)(profile, sig('Lab '))
        class XYZ(C.Structure):
            _fields_ = [('X', C.c_double), ('Y', C.c_double), ('Z', C.c_double)]
        write = api('cmsWriteTag', C.c_int, ptr, u, ptr)
        assert write(profile, sig('wtpt'), C.byref(XYZ(.9642, 1., .8249)))
        pipeline = api('cmsPipelineAlloc', ptr, ptr, u, u)(None, 4, 3)
        stage = api('cmsStageAllocCLut16bit', ptr, ptr, u, u, u, ptr)(None, 3, 4, 3, None)
        callback_type = C.CFUNCTYPE(C.c_int, C.POINTER(C.c_uint16), C.POINTER(C.c_uint16), ptr)
        @callback_type
        def sample(inp, out, cargo):
            c, m, y, k = [inp[i] / 65535 for i in range(4)]
            # Simple neutral-aware synthetic Lab field; bounded PCS encoding.
            out[0] = round(65535 * (1-k) * (1-(c+m+y)/3))
            out[1] = round(65535 * (128 + 40*(m-c)) / 255)
            out[2] = round(65535 * (128 + 40*(y-m)) / 255)
            return 1
        assert api('cmsStageSampleCLut16bit', C.c_int, ptr, callback_type, ptr, u)(stage, sample, None, 0)
        assert api('cmsPipelineInsertStage', C.c_int, ptr, C.c_int, ptr)(pipeline, 1, stage)
        assert write(profile, sig('A2B0'), pipeline)
        api('cmsPipelineFree', None, ptr)(pipeline)
    assert profile
    size = u()
    save = api('cmsSaveProfileToMem', C.c_int, ptr, ptr, C.POINTER(u))
    assert save(profile, None, C.byref(size))
    buf = C.create_string_buffer(size.value)
    assert save(profile, buf, C.byref(size))
    close(profile)
    return buf.raw


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def png(mode='RGB', depth=8, declarations=(), value=128):
    channels, color = {'L': (1, 0), 'LA': (2, 4), 'RGB': (3, 2), 'RGBA': (4, 6)}[mode]
    pixel = ([value] * (channels-1) + [100]) if 'A' in mode else [value] * channels
    samples = bytes(pixel) if depth == 8 else b''.join(struct.pack('>H', v*257) for v in pixel)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 3, 4, depth, color, 0, 0, 0))
            + b''.join(chunk(k, v) for k, v in declarations)
            + chunk(b'IDAT', zlib.compress((b'\0' + samples*3)*4)) + chunk(b'IEND', b''))


def icc_source(mode):
    profile = synthetic_icc('L' if mode == 'LA' else mode)
    image = Image.new(mode, (3, 4), {'CMYK': (30, 90, 150, 20), 'L': 128, 'LA': (128, 100)}[mode])
    out = BytesIO(); image.save(out, format='JPEG' if mode == 'CMYK' else 'PNG', icc_profile=profile)
    return out.getvalue()


def main():
    import hashlib
    import json
    root = Path('tests/fixtures/media/color-review')
    root.mkdir(parents=True, exist_ok=True)
    files = {f'icc-{mode.lower()}.{"jpg" if mode == "CMYK" else "png"}': icc_source(mode)
             for mode in ('CMYK', 'L', 'LA')}
    files.update({f'linear-{mode.lower()}.png': png(mode, declarations=[(b'gAMA', struct.pack('>I', 100000))])
                  for mode in ('L', 'LA', 'RGB', 'RGBA')})
    files.update({f'16bit-{mode.lower()}.png': png(mode, depth=16) for mode in ('RGB', 'RGBA')})
    files.update({f'cicp-{transfer}.png': png(declarations=[(b'cICP', bytes([9, transfer, 0, 1]))]) for transfer in (16, 18)})
    files['non-srgb-chrm.png'] = png(declarations=[(b'cHRM', struct.pack('>8I', 31270, 32900, 68000, 32000, 26500, 69000, 15000, 6000))])
    records = []
    for name, data in files.items():
        (root/name).write_bytes(data)
        records.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
    (root/'manifest.json').write_text(json.dumps({
        'ownership': 'Original synthetic pixels and analytic ICC profiles generated by this repository; no copied profile or user data.',
        'generator': 'backend/tests/media/color_fixtures.py (Python stdlib + installed Pillow/LittleCMS public API)',
        'profile_scope': 'Synthetic CMYK input CLUT in D50 Lab and gamma-2.2 gray D50; not a calibrated printer/camera profile.',
        'fixtures': records,
    }, indent=2)+'\n')


if __name__ == '__main__':
    main()

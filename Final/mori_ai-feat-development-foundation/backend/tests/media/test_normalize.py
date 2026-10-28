from io import BytesIO
import hashlib
import pytest
from PIL import Image, ImageCms
from backend.media.normalize import normalize
from backend.media.contracts import MediaValidationError


def source(size=(30,40), mode='RGB', fmt='PNG', **kwargs):
    image=Image.new(mode,size,(20,80,140,100) if mode=='RGBA' else (20,80,140))
    out=BytesIO(); image.save(out,format=fmt,**kwargs); return out.getvalue()


def decoded(data):
    assert data[:4]==b'RIFF' and data[8:12]==b'WEBP'
    image=Image.open(BytesIO(data)); image.load(); return image


def test_rotated_3_4_sets_passthrough():
    exif=Image.Exif(); exif[274]=6
    result=normalize(source((40,30),fmt='JPEG',exif=exif),'photo.JPG')
    assert (result.width,result.height)==(30,40) and result.input_is_3_4
    assert not decoded(result.webp_bytes).getexif()


def test_nearly_3_4_is_not_passthrough():
    assert not normalize(source((301,400)),'photo.png').input_is_3_4


def test_alpha_survives():
    result=normalize(source(mode='RGBA'),'photo.png')
    assert decoded(result.webp_bytes).getpixel((0,0))==(20,80,140,100)
    assert decoded(result.thumbnail_bytes).mode=='RGBA'


def test_source_bytes_unchanged():
    data=source(); before=data[:]; result=normalize(data,'misleading.heic')
    assert data==before and result.sha256==hashlib.sha256(data).hexdigest()


def test_pixel_limit_rejected():
    with pytest.raises(MediaValidationError) as error:
        normalize(source((8001,5000)),'huge.png')
    assert error.value.code=='IMAGE_PIXEL_LIMIT_EXCEEDED'


def test_corrupt_input_rejected():
    with pytest.raises(MediaValidationError) as error: normalize(b'not image','x.png')
    assert error.value.code=='IMAGE_DECODE_FAILED'


def test_input_size_rejected():
    with pytest.raises(MediaValidationError) as error: normalize(b'x'*(20*1024*1024+1),'x.png')
    assert error.value.code=='IMAGE_SIZE_LIMIT_EXCEEDED'


@pytest.mark.parametrize('orientation',range(1,9))
def test_all_exif_directions(orientation):
    from PIL import ImageOps
    image=Image.new('RGB',(40,30)); image.paste('red',(0,0,20,15)); image.paste('blue',(20,15,40,30))
    exif=Image.Exif(); exif[274]=orientation
    out=BytesIO(); image.save(out,format='PNG',exif=exif)
    expected=ImageOps.exif_transpose(Image.open(BytesIO(out.getvalue())))
    actual=decoded(normalize(out.getvalue(),'x.png').webp_bytes)
    assert actual.size==expected.size and actual.tobytes()==expected.tobytes()


def test_dates_extracted_before_metadata_removed():
    exif=Image.Exif(); exif[36867]='2026:10:16 12:30:40'; exif[36881]='+09:00'
    result=normalize(source(exif=exif),'x.png')
    assert result.captured_at_raw=='2026:10:16 12:30:40' and result.captured_timezone=='+09:00'
    assert not decoded(result.webp_bytes).info.get('exif')


def test_srgb_icc_and_alpha():
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    result=normalize(source(mode='RGBA',icc_profile=icc),'x.png')
    assert decoded(result.webp_bytes).getpixel((0,0))==(20,80,140,100)


def test_exact_ratio_resize_no_crop(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE','101')
    result=normalize(source((300,400)),'x.png')
    assert (result.width,result.height)==(75,100)
    assert decoded(result.webp_bytes).size==(75,100)


def test_thumbnail_limit():
    result=normalize(source((900,1200)),'x.png')
    assert decoded(result.thumbnail_bytes).size==(360,480)


def test_unsupported_decoded_format():
    with pytest.raises(MediaValidationError) as error: normalize(source(fmt='BMP'),'x.jpg')
    assert error.value.code=='UNSUPPORTED_MEDIA'


def test_heif_primary_selected():
    import pillow_heif
    pillow_heif.register_heif_opener()
    first=Image.new('RGB',(32,32),'red')
    primary=Image.new('RGB',(30,40),'blue')
    out=BytesIO(); first.save(out,format='HEIF',save_all=True,append_images=[primary],primary_index=1,quality=-1)
    result=normalize(out.getvalue(),'multi.heic')
    assert (result.width,result.height)==(30,40) and result.input_is_3_4
    assert decoded(result.webp_bytes).getpixel((10,10))[2]>240


def test_hdr_16bit_not_silently_truncated():
    image=Image.new('I;16',(30,40),20000); out=BytesIO(); image.save(out,format='PNG')
    with pytest.raises(MediaValidationError) as error: normalize(out.getvalue(),'hdr.png')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


def test_invalid_icc_fails_closed():
    with pytest.raises(MediaValidationError) as error:
        normalize(source(icc_profile=b'broken'),'x.png')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


def test_byte_budget_resizes_from_original(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_BYTES','1')
    with pytest.raises(MediaValidationError) as error: normalize(source(),'x.png')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


def test_fixture_manifest():
    import json
    from pathlib import Path
    root=Path('tests/fixtures/media')
    for fixture in json.loads((root/'manifest.json').read_text())['fixtures']:
        data=(root/fixture['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==fixture['sha256']
        result=normalize(data,fixture['path'])
        assert [result.width,result.height]==fixture['expected_size']
        assert result.input_is_3_4==fixture['input_is_3_4']
        assert ('A' in decoded(result.webp_bytes).getbands())==fixture['alpha']


@pytest.mark.parametrize('transfer',[16,18])
def test_heif_hdr_transfer_rejected(transfer):
    import pillow_heif
    pillow_heif.register_heif_opener()
    data=source(fmt='HEIF',nclx_profile={'color_primaries':9,'transfer_characteristics':transfer,'matrix_coefficients':9,'full_range_flag':1})
    with pytest.raises(MediaValidationError) as error: normalize(data,'hdr.heic')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


def test_heif_wide_gamut_without_icc_is_not_assumed_srgb():
    import pillow_heif
    pillow_heif.register_heif_opener()
    data=source(fmt='HEIF',nclx_profile={'color_primaries':9,'transfer_characteristics':1,'matrix_coefficients':9,'full_range_flag':1})
    with pytest.raises(MediaValidationError) as error: normalize(data,'wide.heic')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


def test_gainmap_xmp_not_assumed_sdr():
    data=source(fmt='WEBP',xmp=b'<rdf xmlns:hdrgm="http://ns.adobe.com/hdr-gain-map/1.0/"/>')
    with pytest.raises(MediaValidationError) as error: normalize(data,'gain.webp')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


@pytest.mark.parametrize('orientation',range(2,9))
def test_heif_direction_applied_once(orientation):
    import pillow_heif
    pillow_heif.register_heif_opener()
    image=Image.new('RGB',(40,30),'white'); image.paste('red',(0,0,20,15)); image.paste('blue',(20,15,40,30))
    exif=Image.Exif(); exif[274]=orientation
    out=BytesIO(); image.save(out,format='HEIF',exif=exif,quality=-1)
    result=normalize(out.getvalue(),'rotated.heic')
    from PIL import ImageOps
    image.info['exif']=exif.tobytes()
    expected=ImageOps.exif_transpose(image)
    actual=decoded(result.webp_bytes)
    assert actual.size==expected.size
    # HEVC chroma conversion may differ at borders: inspect quadrant centers.
    for x,y in [(5,5),(actual.width-5,5),(5,actual.height-5),(actual.width-5,actual.height-5)]:
        assert max(abs(a-b) for a,b in zip(actual.getpixel((x,y)),expected.getpixel((x,y))))<10


def test_heif_non_srgb_transfer_not_assumed_srgb():
    data=source(fmt='HEIF',nclx_profile={'color_primaries':1,'transfer_characteristics':1,'matrix_coefficients':1,'full_range_flag':1})
    with pytest.raises(MediaValidationError) as error: normalize(data,'bt709.heic')
    assert error.value.code=='IMAGE_NORMALIZATION_FAILED'


@pytest.fixture(autouse=True)
def reference_lossless_encoding(monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')

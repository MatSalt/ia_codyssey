"""Synthetic phone containers: primary pixels only, no private photo fixtures."""
import hashlib
import struct
from io import BytesIO

import pillow_heif
import pytest
from PIL import Image, ImageCms, ImageOps
from backend.media.normalize import normalize
from backend.media.contracts import MediaValidationError


def profile(function=3, coefficients=None):
    # Keep a real LittleCms RGB profile; replace its RGB TRCs with exact SDR curves.
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    values = coefficients or [2.4, 1 / 1.055, .055 / 1.055, 1 / 12.92, .04045]
    if function == 4 and coefficients is None:
        values += [0, 0]
    tag = b'para' + bytes(4) + struct.pack('>H', function) + bytes(2)
    tag += b''.join(struct.pack('>i', round(v * 65536)) for v in values)
    offset = len(data)
    data += tag
    for pos in range(132, 132 + struct.unpack_from('>I', data, 128)[0] * 12, 12):
        if data[pos:pos + 4] in (b'rTRC', b'gTRC', b'bTRC'):
            struct.pack_into('>II', data, pos + 4, offset, len(tag))
    struct.pack_into('>I', data, 0, len(data))
    return bytes(data)


def heif_with_metadata(monkeypatch, icc, **metadata):
    out = BytesIO()
    Image.new('RGB', (30, 40), (30, 100, 170)).save(
        out, format='HEIF', quality=-1, icc_profile=icc)
    data = out.getvalue()
    real_open = Image.open

    def open_primary(fp, *args, **kwargs):
        image = real_open(fp, *args, **kwargs)
        if image.format == 'HEIF':
            assert image.info['bit_depth'] == 8
            image.info.update(aux={'urn:com:apple:photo:2020:aux:hdrgainmap': [7]})
            image.info.update(metadata)
        return image

    def forbidden(*args, **kwargs):
        pytest.fail('auxiliary pixel decoder must never be called')

    monkeypatch.setattr(Image, 'open', open_primary)
    monkeypatch.setattr(pillow_heif.HeifImage, 'get_aux_image', forbidden)
    return data


def test_mpo_first_primary_only_with_orientation_and_source_preserved(monkeypatch):
    exif = Image.Exif(); exif[274] = 6
    out = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(
        out, format='MPO', save_all=True, append_images=[Image.new('RGB', (40, 30), 'blue')], exif=exif)
    data = out.getvalue(); before = bytes(data)
    first = Image.open(BytesIO(data))
    assert first.format == 'MPO' and first.n_frames == 2
    expected = ImageOps.exif_transpose(first).convert('RGB')
    from PIL.MpoImagePlugin import MpoImageFile
    original_seek = MpoImageFile.seek

    def primary_seek(self, frame):
        assert frame == 0, 'must not decode secondary MPO frame'
        return original_seek(self, frame)

    monkeypatch.setattr(MpoImageFile, 'seek', primary_seek)
    result = normalize(data, 'phone.JPG')
    actual = Image.open(BytesIO(result.webp_bytes))
    assert actual.size == (30, 40) and result.input_is_3_4
    assert actual.tobytes() == expected.tobytes()
    assert data == before and result.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('function', [3, 4])
def test_heif_srgb_trc_primary_ignores_aux_gainmap(monkeypatch, function):
    data = heif_with_metadata(monkeypatch, profile(function))
    result = normalize(data, 'phone.heic')
    image = Image.open(BytesIO(result.webp_bytes))
    assert image.size == (30, 40) and result.input_is_3_4
    assert max(abs(a-b) for a, b in zip(image.getpixel((10, 10)), (30, 100, 170))) <= 3
    assert not image.info.get('icc_profile') and not image.info.get('xmp')
    assert result.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('metadata', [
    {'bit_depth': 10}, {'bit_depth': 12}, {'bit_depth': 16},
    {'nclx_profile': {'transfer_characteristics': 16}},
    {'nclx_profile': {'transfer_characteristics': 18}},
    {'nclx_profile': {'transfer_characteristics': 1}},
    {'xmp': b'<hdrgm:GainMap/>'}, {'gain_map': {'present': True}},
    {'hdr_metadata': {'present': True}}, {'content_light_level': {'max': 1000}},
    {'mastering_display_colour_volume': {'max': 1000}},
])
def test_heif_aux_does_not_override_main_hdr(monkeypatch, metadata):
    data = heif_with_metadata(monkeypatch, profile(), **metadata)
    with pytest.raises(MediaValidationError, match='IMAGE_NORMALIZATION_FAILED'):
        normalize(data, 'phone.heic')


@pytest.mark.parametrize('icc', [b'', b'Display P3 sRGB', profile(0, [2.2]),
    profile(3, [2.2, 1/1.055, .055/1.055, 1/12.92, .04045])])
def test_heif_aux_requires_verified_trc_not_profile_name(monkeypatch, icc):
    data = heif_with_metadata(monkeypatch, icc)
    with pytest.raises(MediaValidationError, match='IMAGE_NORMALIZATION_FAILED'):
        normalize(data, 'phone.heic')


def damaged_profile(case):
    data = bytearray(profile())
    entries = {bytes(data[p:p+4]): p for p in range(132, 132 + struct.unpack_from('>I', data, 128)[0]*12, 12)}
    entry = entries[b'rTRC']
    curve = struct.unpack_from('>I', data, entry+4)[0]
    if case == 'size':
        struct.pack_into('>I', data, 0, len(data)-1)
    elif case == 'oversize':
        data += bytes(1024 * 1024)
        struct.pack_into('>I', data, 0, len(data))
    elif case == 'signature':
        data[36:40] = b'fake'
    elif case == 'color_space':
        data[16:20] = b'CMYK'
    elif case == 'pcs':
        data[20:24] = b'RGB '
    elif case == 'count':
        struct.pack_into('>I', data, 128, 0xffffffff)
    elif case == 'offset':
        struct.pack_into('>I', data, entry+4, 0xfffffff0)
    elif case == 'table_overlap':
        struct.pack_into('>I', data, entry+4, 132)
    elif case == 'length':
        struct.pack_into('>I', data, entry+8, 0xffffffff)
    elif case == 'missing_channel':
        data[entry:entry+4] = b'zTRC'
    elif case == 'unequal_channels':
        data += data[curve:]
        struct.pack_into('>II', data, entry+4, len(data)-32, 32)
        struct.pack_into('>i', data, len(data)-4, 0)
        struct.pack_into('>I', data, 0, len(data))
    elif case == 'curv':
        data[curve:curve+4] = b'curv'
    elif case == 'unknown_function':
        struct.pack_into('>H', data, curve+8, 5)
    elif case == 'outside_tolerance':
        value = struct.unpack_from('>i', data, curve+12)[0]
        struct.pack_into('>i', data, curve+12, value+3)
    return bytes(data)


@pytest.mark.parametrize('case', ['size', 'oversize', 'signature', 'color_space', 'pcs',
    'count', 'offset', 'table_overlap', 'length', 'missing_channel', 'unequal_channels',
    'curv', 'unknown_function', 'outside_tolerance'])
def test_malformed_or_unknown_icc_cannot_authorize_aux_primary(monkeypatch, case):
    data = heif_with_metadata(monkeypatch, damaged_profile(case))
    with pytest.raises(MediaValidationError, match='IMAGE_NORMALIZATION_FAILED'):
        normalize(data, 'phone.heic')


def test_reported_phone_trc_coefficients_are_supported(monkeypatch):
    icc = profile(3, [2.399993896484375, .9478607177734375,
                     .0521392822265625, .077392578125, .0404510498046875])
    data = heif_with_metadata(monkeypatch, icc)
    assert normalize(data, 'phone.heic').input_is_3_4


@pytest.fixture(autouse=True)
def reference_lossless_encoding(monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')

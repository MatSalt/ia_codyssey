from io import BytesIO
import struct
import pytest
from PIL import Image, ImageCms
from backend.media.normalize import normalize
from backend.media.contracts import MediaValidationError
from .color_fixtures import png, icc_source


def result(data):
    return Image.open(BytesIO(normalize(data, 'synthetic.png').webp_bytes))


@pytest.mark.parametrize('mode', ['CMYK', 'L', 'LA'])
def test_source_icc_mode_and_alpha(mode):
    data = icc_source(mode)
    original = Image.open(BytesIO(data)); original.load()
    color = original.getchannel('L') if mode == 'LA' else original
    reference = ImageCms.profileToProfile(color, ImageCms.ImageCmsProfile(BytesIO(original.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
    actual = result(data)
    assert actual.getpixel((0, 0))[:3] == reference.getpixel((0, 0))
    if mode == 'LA':
        assert actual.getpixel((0, 0))[3] == 100


@pytest.mark.parametrize('mode', ['L', 'LA', 'RGB', 'RGBA'])
def test_linear_png_is_encoded_srgb_without_changing_alpha(mode):
    actual = result(png(mode, declarations=[(b'gAMA', struct.pack('>I', 100000))]))
    assert actual.getpixel((0, 0))[:3] == (188, 188, 188)
    if 'A' in mode:
        assert actual.getpixel((0, 0))[3] == 100


def test_unvalidated_chromaticity_rejected():
    chrm = struct.pack('>8I', 31270, 32900, 68000, 32000, 26500, 69000, 15000, 6000)
    with pytest.raises(MediaValidationError) as error:
        result(png(declarations=[(b'cHRM', chrm)]))
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
def test_truecolor_16bit_rejected_before_truncation(mode):
    with pytest.raises(MediaValidationError) as error:
        result(png(mode, depth=16))
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


@pytest.mark.parametrize('transfer', [16, 18])
def test_png_cicp_hdr_rejected(transfer):
    with pytest.raises(MediaValidationError) as error:
        result(png(declarations=[(b'cICP', bytes([9, transfer, 0, 1]))]))
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


def test_srgb_declaration_overrides_fallback_gamma_chrm():
    data = png(declarations=[(b'sRGB', b'\0'), (b'gAMA', struct.pack('>I', 100000)),
                             (b'cHRM', struct.pack('>8I', *([1]*8)))])
    assert result(data).getpixel((0, 0)) == (128, 128, 128)


def test_icc_overrides_srgb_and_fallback_declarations():
    from .color_fixtures import chunk
    data = icc_source('L')
    data = data[:33] + chunk(b'sRGB', b'\0') + chunk(b'gAMA', struct.pack('>I', 100000)) + data[33:]
    original = Image.open(BytesIO(data))
    expected = ImageCms.profileToProfile(original, ImageCms.ImageCmsProfile(BytesIO(original.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
    assert result(data).tobytes() == expected.tobytes()


def test_canonical_srgb_fallback_allowed():
    from backend.media.png_color import SRGB_CHRM
    data = png(declarations=[(b'gAMA', struct.pack('>I', 45455)), (b'cHRM', struct.pack('>8I', *SRGB_CHRM))])
    assert result(data).getpixel((0, 0)) == (128, 128, 128)


@pytest.mark.parametrize('icc', [False, True])
def test_palette_and_transparent_index_preserved(icc):
    image = Image.new('P', (3, 4), 1)
    image.putpalette([0, 0, 0, 20, 80, 140] + [0]*762)
    image.info['transparency'] = bytes([255, 100])
    kwargs = {'icc_profile': ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()} if icc else {}
    out = BytesIO(); image.save(out, format='PNG', **kwargs)
    assert result(out.getvalue()).getpixel((0, 0)) == (20, 80, 140, 100)


@pytest.mark.parametrize('kind', [b'IHDR', b'IDAT', b'cICP'])
def test_png_crc_corruption_is_decode_failure(kind):
    data = bytearray(png(declarations=[(b'cICP', bytes([1, 13, 0, 1]))]))
    index = data.index(kind)
    data[index+4] ^= 1
    with pytest.raises(MediaValidationError) as error:
        result(bytes(data))
    assert error.value.code == 'IMAGE_DECODE_FAILED'


@pytest.mark.parametrize('declarations', [
    [(b'cICP', b'\x01\x0d')],
    [(b'gAMA', struct.pack('>I', 100000))]*2,
])
def test_malformed_color_chunks_rejected(declarations):
    with pytest.raises(MediaValidationError) as error:
        result(png(declarations=declarations))
    assert error.value.code == 'IMAGE_DECODE_FAILED'


def test_zero_gamma_fails_closed():
    with pytest.raises(MediaValidationError) as error:
        result(png(declarations=[(b'gAMA', bytes(4))]))
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


def test_cicp_hdr_cannot_be_overridden_by_srgb():
    with pytest.raises(MediaValidationError) as error:
        result(png(declarations=[(b'sRGB', b'\0'), (b'cICP', bytes([9, 16, 0, 1]))]))
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


def test_decoder_rejects_invalid_deflate_with_valid_crc():
    from .color_fixtures import chunk
    data = png()
    start = data.index(b'IDAT')-4
    bad = data[:start] + chunk(b'IDAT', b'not deflate') + chunk(b'IEND', b'')
    with pytest.raises(MediaValidationError) as error:
        result(bad)
    assert error.value.code == 'IMAGE_DECODE_FAILED'


def test_color_fixture_manifest_and_source_bytes():
    import hashlib
    import json
    from pathlib import Path
    root = Path('tests/fixtures/media/color-review')
    for record in json.loads((root/'manifest.json').read_text())['fixtures']:
        data = (root/record['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['sha256']
        before = data[:]
        if record['path'].startswith(('16bit', 'cicp', 'non-srgb')):
            with pytest.raises(MediaValidationError) as error:
                normalize(data, record['path'])
            assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'
        else:
            normalized = normalize(data, record['path'])
            assert normalized.sha256 == record['sha256']
            assert (normalized.width, normalized.height, normalized.input_is_3_4) == (3, 4, True)
        assert data == before


def test_linear_ramp_reference_and_alpha():
    from .color_fixtures import chunk
    import zlib
    values = (0, 1, 16, 64, 128, 192, 255)
    pixels = b''.join(bytes((v, v, v, 100)) for v in values)
    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 7, 1, 8, 6, 0, 0, 0))
            + chunk(b'gAMA', struct.pack('>I', 100000))
            + chunk(b'IDAT', zlib.compress(b'\0'+pixels)) + chunk(b'IEND', b''))
    # Independently tabulated IEC sRGB transfer reference for linear 8-bit levels.
    expected = (0, 13, 71, 137, 188, 225, 255)
    actual = result(data)
    assert [actual.getpixel((x, 0)) for x in range(7)] == [(v, v, v, 100) for v in expected]


@pytest.fixture(autouse=True)
def reference_lossless_encoding(monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')

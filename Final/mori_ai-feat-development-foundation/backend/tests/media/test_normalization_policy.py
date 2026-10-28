from io import BytesIO

import pytest
from PIL import Image
from backend.media.normalize import normalize
from backend.media.contracts import MediaValidationError
from backend.media.process import normalize_in_process


def encoded(fmt='PNG', **options):
    image = Image.effect_noise((300, 400), 40).convert('RGB')
    out = BytesIO()
    image.save(out, format=fmt, **options)
    return out.getvalue()


def test_default_is_lossy_quality_90(monkeypatch):
    monkeypatch.delenv('NORMALIZED_WEBP_LOSSLESS', raising=False)
    monkeypatch.delenv('NORMALIZED_WEBP_QUALITY', raising=False)
    data = encoded()
    expected = BytesIO()
    Image.open(BytesIO(data)).save(expected, format='WEBP', quality=90, lossless=False)
    assert normalize(data, 'photo.png').webp_bytes == expected.getvalue()


def test_explicit_legacy_lossless(monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')
    data = encoded()
    actual = Image.open(BytesIO(normalize(data, 'photo.png').webp_bytes))
    assert actual.tobytes() == Image.open(BytesIO(data)).tobytes()


@pytest.mark.parametrize('lossless', [False, True])
def test_webp_authoritatively_reencoded(lossless, monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', str(lossless).lower())
    data = encoded('WEBP', quality=75, lossless=lossless)
    expected = BytesIO()
    Image.open(BytesIO(data)).save(expected, format='WEBP', quality=90, lossless=lossless)
    assert normalize(data, 'photo.webp').webp_bytes == expected.getvalue()


def test_legacy_lossless_does_not_adopt_lossy_webp(monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')
    data = encoded('WEBP', quality=75)
    result = normalize(data, 'photo.webp')
    assert b'VP8L' in result.webp_bytes
    assert Image.open(BytesIO(result.webp_bytes)).tobytes() == Image.open(BytesIO(data)).tobytes()


def test_webp_metadata_removed_and_dates_retained():
    exif = Image.Exif(); exif[36867] = '2026:10:18 01:02:03'
    data = encoded('WEBP', exif=exif, xmp=b'private metadata')
    result = normalize(data, 'photo.webp')
    assert result.webp_bytes != data
    assert result.captured_at_raw == '2026:10:18 01:02:03'
    assert not Image.open(BytesIO(result.webp_bytes)).info.get('exif')
    assert not Image.open(BytesIO(result.webp_bytes)).info.get('xmp')


def test_webp_decode_required_before_adoption():
    data = bytearray(encoded('WEBP'))
    del data[len(data) // 2:]
    data[4:8] = (len(data) - 8).to_bytes(4, 'little')
    data[16:20] = (len(data) - 20).to_bytes(4, 'little')
    with pytest.raises(MediaValidationError):
        normalize(bytes(data), 'photo.webp')


def test_original_ratio_survives_rounding(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '40')
    out = BytesIO(); Image.new('RGB', (301, 400)).save(out, format='PNG')
    result = normalize(out.getvalue(), 'photo.png')
    assert (result.width, result.height) == (30, 40)
    assert not result.input_is_3_4


@pytest.mark.asyncio
async def test_child_quality_snapshot_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('NORMALIZED_WEBP_QUALITY', '90')
    path = tmp_path / 'photo.png'; path.write_bytes(encoded())
    low = await normalize_in_process(path, path.name, config={'NORMALIZATION_VERSION': 2, 'NORMALIZED_WEBP_QUALITY': 20})
    high = await normalize_in_process(path, path.name, config={'NORMALIZATION_VERSION': 2, 'NORMALIZED_WEBP_QUALITY': 90})
    assert len(low.webp_bytes) < len(high.webp_bytes)


@pytest.mark.parametrize('fmt', ['PNG', 'JPEG'])
@pytest.mark.parametrize('orientation', range(1, 9))
def test_resize_preserves_orientation_and_original_ratio(fmt, orientation, monkeypatch):
    from PIL import ImageOps
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '100')
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')
    image = Image.new('RGB', (400, 300), 'red')
    image.paste('blue', (200, 0, 400, 150))
    exif = Image.Exif(); exif[274] = orientation
    out = BytesIO(); image.save(out, format=fmt, exif=exif)
    expected = ImageOps.exif_transpose(Image.open(BytesIO(out.getvalue())))
    result = normalize(out.getvalue(), 'photo')
    actual = Image.open(BytesIO(result.webp_bytes))
    assert result.input_is_3_4 == (orientation >= 5)
    assert actual.size == ((75, 100) if orientation >= 5 else (100, 75))
    expected = expected.resize(actual.size)
    for x, y in [(10, 10), (60, 10), (10, 60), (60, 60)]:
        assert max(abs(a-b) for a, b in zip(actual.getpixel((x,y)), expected.getpixel((x,y)))) < 10


def test_default_lossy_keeps_alpha_exact():
    image = Image.new('RGBA', (30, 40), (20, 80, 140, 100))
    out = BytesIO(); image.save(out, format='PNG')
    actual = Image.open(BytesIO(normalize(out.getvalue(), 'alpha.png').webp_bytes))
    assert actual.getchannel('A').tobytes() == image.getchannel('A').tobytes()
    assert max(abs(a-b) for a, b in zip(actual.getpixel((10,10))[:3], (20, 80, 140))) < 5


def test_webp_over_edge_reencoded(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '100')
    data = encoded('WEBP')
    result = normalize(data, 'photo.webp')
    assert result.webp_bytes != data
    assert (result.width, result.height) == (75, 100)


def test_unknown_webp_chunk_is_not_adopted():
    data = bytearray(encoded('WEBP'))
    data.extend(b'PRIV' + (6).to_bytes(4, 'little') + b'secret')
    data[4:8] = (len(data) - 8).to_bytes(4, 'little')
    result = normalize(bytes(data), 'photo.webp')
    assert b'secret' not in result.webp_bytes


def test_animated_webp_normalizes_only_first_frame():
    out = BytesIO()
    Image.new('RGB', (30, 40), 'red').save(out, format='WEBP', save_all=True,
        append_images=[Image.new('RGB', (30, 40), 'blue')], duration=100)
    result = normalize(out.getvalue(), 'animated.webp')
    actual = Image.open(BytesIO(result.webp_bytes))
    assert actual.n_frames == 1
    assert actual.getpixel((10, 10))[0] > 240


def test_palette_is_expanded_before_resampling(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '40')
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')
    image = Image.new('P', (300, 400), 0)
    image.putpalette([20, 80, 140, 140, 80, 20] + [0]*762)
    image.info['transparency'] = bytes([100, 220])
    for x in range(0, 300, 2):
        image.paste(1, (x, 0, x+1, 400))
    out = BytesIO(); image.save(out, format='PNG')
    expected = image.convert('RGBA').resize((30, 40), Image.Resampling.LANCZOS, reducing_gap=3)
    actual = Image.open(BytesIO(normalize(out.getvalue(), 'palette.png').webp_bytes))
    assert actual.tobytes() == expected.tobytes()


def test_incomplete_trailing_webp_chunk_is_not_adopted():
    data = bytearray(encoded('WEBP'))
    data.extend(b'VP8X' + (10).to_bytes(4, 'little'))
    data[4:8] = (len(data) - 8).to_bytes(4, 'little')
    # A decoder may reject the malformed envelope or accept the valid frame;
    # either outcome must be controlled and must never adopt malformed bytes.
    try:
        result = normalize(bytes(data), 'photo.webp')
    except MediaValidationError:
        return
    assert result.webp_bytes != bytes(data)


def test_color_key_alpha_expanded_before_resampling(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '40')
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'true')
    image = Image.new('RGB', (300, 400), (255, 0, 0))
    image.paste((0, 0, 255), (150, 0, 300, 400))
    out = BytesIO(); image.save(out, format='PNG', transparency=(255, 0, 0))
    expected = Image.open(BytesIO(out.getvalue())).convert('RGBA').resize((30, 40), Image.Resampling.LANCZOS)
    actual = Image.open(BytesIO(normalize(out.getvalue(), 'key.png').webp_bytes))
    assert actual.getchannel('A').tobytes() == expected.getchannel('A').tobytes()


@pytest.mark.parametrize('placement', ['inside_bitstream', 'after_riff'])
def test_ignored_private_payload_removed_by_reencode(placement):
    original = encoded('WEBP', quality=75)
    payload = b'PRIVATE location=home user=alice ignored decoder bytes!!'
    data = bytearray(original)
    if placement == 'inside_bitstream':
        assert data[12:16] == b'VP8 '
        length = int.from_bytes(data[16:20], 'little')
        data = data[:20 + length] + payload
        data[16:20] = (length + len(payload)).to_bytes(4, 'little')
        if (length + len(payload)) % 2:
            data += b'\0'
        data[4:8] = (len(data) - 8).to_bytes(4, 'little')
    else:
        data += payload
    # The attack is a valid decoder input whose ignored bytes are private.
    clean_pixels = Image.open(BytesIO(original)); clean_pixels.load()
    dirty_pixels = Image.open(BytesIO(data)); dirty_pixels.load()
    assert dirty_pixels.tobytes() == clean_pixels.tobytes()
    clean = normalize(original, 'clean.webp')
    result = normalize(bytes(data), 'private.webp')
    assert result.webp_bytes == clean.webp_bytes
    assert result.thumbnail_bytes == clean.thumbnail_bytes
    assert payload not in result.webp_bytes + result.thumbnail_bytes


def test_webp_alpha_and_color_survive_authoritative_reencode():
    image = Image.new('RGBA', (30, 40), (20, 80, 140, 100))
    out = BytesIO(); image.save(out, format='WEBP', quality=75)
    before = Image.open(BytesIO(out.getvalue()))
    result = normalize(out.getvalue(), 'alpha.webp')
    after = Image.open(BytesIO(result.webp_bytes))
    assert after.getchannel('A').tobytes() == before.getchannel('A').tobytes()
    assert max(abs(a-b) for a, b in zip(after.getpixel((10,10))[:3], before.getpixel((10,10))[:3])) < 5

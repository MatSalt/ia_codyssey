"""Recovery compatibility with the codec at repository commit 68aff30."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from backend.media.contracts import MediaValidationError
from backend.media.process import MEDIA_ENV_KEYS, normalize_in_process


def legacy_fixture(fmt):
    image = Image.new('RGB', (900, 1200))
    image.putdata([((x * 13 + y) % 256, (x + y * 7) % 256, (x * 3 + y * 5) % 256)
                   for y in range(1200) for x in range(900)])
    exif = Image.Exif(); exif[274] = 6; exif[36867] = '2026:10:18 01:02:03'
    out = BytesIO(); image.save(out, format=fmt, exif=exif)
    return out.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [None, 1])
@pytest.mark.parametrize('fmt', ['PNG', 'JPEG'])
async def test_legacy_resized_output_matches_68aff30(tmp_path, monkeypatch, fmt, version):
    from backend.media.normalize_v1 import normalize as legacy
    for key in MEDIA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '120')
    monkeypatch.setenv('THUMBNAIL_MAX_EDGE', '80')
    data = legacy_fixture(fmt)
    baseline = legacy(data, 'photo')
    # Goldens were generated with the exact committed 68aff30 implementation.
    expected = GOLDENS[fmt]
    assert (sha256(baseline.webp_bytes).hexdigest(),
            sha256(baseline.thumbnail_bytes).hexdigest()) == expected
    path = tmp_path / 'photo'; path.write_bytes(data)
    # Deployment defaults must never leak into an old saved snapshot.
    monkeypatch.setenv('NORMALIZATION_VERSION', '2')
    monkeypatch.setenv('NORMALIZED_WEBP_LOSSLESS', 'false')
    monkeypatch.setenv('NORMALIZED_WEBP_QUALITY', '1')
    monkeypatch.setenv('THUMBNAIL_WEBP_QUALITY', '1')
    config = {'NORMALIZED_MAX_EDGE': 120, 'THUMBNAIL_MAX_EDGE': 80}
    if version is not None:
        config['NORMALIZATION_VERSION'] = version
    result = await normalize_in_process(path, 'photo', config=config)
    assert result == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [True, False, 0, 3, -1, '2', 2.0])
async def test_invalid_snapshot_version_rejected(tmp_path, version):
    path = tmp_path / 'photo'; path.write_bytes(b'unused')
    with pytest.raises(MediaValidationError) as error:
        await normalize_in_process(path, 'photo', config={'NORMALIZATION_VERSION': version})
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'


GOLDENS = {
    'PNG': ('3c5a3ea1a11038c490961731b31fe757135e84a6a10ebedd50548e7c1a60ec0d',
            '71541efb2392a1d81f475ba1188ee39a34e38f48b83f5cafb8125bbede99f9a2'),
    'JPEG': ('83810e72776180d223dfe89917ef3df6e70e3c6f623a960cf08eec66ecdf57f8',
             'db1a875ace61d59de5227420fc960ca32c21c2ca4f27f22b19b1fd6552fbd684'),
}


def test_legacy_module_frozen_at_68aff30():
    from backend.media import normalize_v1
    assert sha256(Path(normalize_v1.__file__).read_bytes()).hexdigest() == (
        '657ac0e39d7f5ffe2343d63c58d57efc86f81f0dc67a9273df037e9b2d96c1c5')

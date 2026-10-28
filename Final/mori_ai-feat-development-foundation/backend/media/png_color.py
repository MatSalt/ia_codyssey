"""PNG declarations checked before Pillow can reduce 16-bit truecolor to 8-bit.

CRC/structure errors are decode failures. Unsupported color paths are explicit
normalization failures. This module does not implement HDR tone mapping.
"""
import struct
import zlib
from .contracts import MediaValidationError

SIGNATURE = b'\x89PNG\r\n\x1a\n'
SRGB_CHRM = (31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)


def declarations(source):
    if not source.startswith(SIGNATURE):
        return None
    offset = 8
    chunks = {}
    seen_idat = False
    while offset < len(source):
        if len(source) - offset < 12:
            raise MediaValidationError('IMAGE_DECODE_FAILED')
        length = int.from_bytes(source[offset:offset+4], 'big')
        kind = source[offset+4:offset+8]
        end = offset + 12 + length
        if end > len(source):
            raise MediaValidationError('IMAGE_DECODE_FAILED')
        data = source[offset+8:end-4]
        crc = int.from_bytes(source[end-4:end], 'big')
        if zlib.crc32(kind + data) != crc:
            raise MediaValidationError('IMAGE_DECODE_FAILED')
        if offset == 8 and kind != b'IHDR':
            raise MediaValidationError('IMAGE_DECODE_FAILED')
        if kind in {b'IHDR', b'iCCP', b'sRGB', b'gAMA', b'cHRM', b'cICP'}:
            if kind in chunks or seen_idat:
                raise MediaValidationError('IMAGE_DECODE_FAILED')
            chunks[kind] = data
        if kind == b'IDAT':
            seen_idat = True
        offset = end
        if kind == b'IEND':
            if length or offset != len(source) or not seen_idat:
                raise MediaValidationError('IMAGE_DECODE_FAILED')
            break
    else:
        raise MediaValidationError('IMAGE_DECODE_FAILED')
    for kind, length in ((b'IHDR', 13), (b'sRGB', 1), (b'gAMA', 4), (b'cHRM', 32), (b'cICP', 4)):
        if kind in chunks and len(chunks[kind]) != length:
            raise MediaValidationError('IMAGE_DECODE_FAILED')
    return chunks


def validate(chunks, info):
    if chunks is None:
        return
    if chunks[b'IHDR'][8] > 8:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
    # cICP HDR must never be overridden by an SDR ICC/sRGB declaration.
    if b'cICP' in chunks and chunks[b'cICP'] != bytes((1, 13, 0, 1)):
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
    if b'iCCP' in chunks and not info.get('icc_profile'):
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
    if b'sRGB' in chunks and chunks[b'sRGB'][0] > 3:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')


def to_srgb(image, chunks):
    # Priority: valid iCCP (handled by CMS) > sRGB > gAMA/cHRM > assumed sRGB.
    # cICP SDR is accepted only when already explicitly sRGB; HDR is rejected.
    if chunks is None or b'iCCP' in chunks or b'sRGB' in chunks or b'cICP' in chunks:
        return image
    if b'cHRM' in chunks and struct.unpack('>8I', chunks[b'cHRM']) != SRGB_CHRM:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
    if b'gAMA' not in chunks:
        return image
    gamma = int.from_bytes(chunks[b'gAMA'], 'big') / 100000
    if not 0 < gamma <= 10:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
    # Canonical PNG sRGB fallback gamma is an approximation to the sRGB curve;
    # recognize it as sRGB instead of introducing a second approximate transfer.
    if gamma == .45455:
        return image
    def encode(sample):
        linear = (sample / 255) ** (1 / gamma)
        srgb = 12.92 * linear if linear <= .0031308 else 1.055 * linear ** (1 / 2.4) - .055
        return round(255 * srgb)
    lut = [encode(sample) for sample in range(256)]
    return image.point(lut * 3)

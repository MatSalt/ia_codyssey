"""Conservative ICC transfer proof for an SDR HEIF primary with auxiliary HDR.

This is not a color converter: LittleCms still validates/converts the profile.
Only RGB profiles whose three parametric TRCs encode sRGB are evidence of SDR.
"""
import struct

MAX_PROFILE_BYTES = 1024 * 1024
_TOLERANCE = 2 / 65536
_SRGB = (2.4, 1 / 1.055, .055 / 1.055, 1 / 12.92, .04045)


def has_srgb_transfer(profile: bytes) -> bool:
    if not isinstance(profile, bytes) or not 132 <= len(profile) <= MAX_PROFILE_BYTES:
        return False
    if (struct.unpack_from('>I', profile)[0] != len(profile)
            or profile[16:20] != b'RGB ' or profile[36:40] != b'acsp'
            or profile[20:24] not in {b'XYZ ', b'Lab '}):
        return False
    count = struct.unpack_from('>I', profile, 128)[0]
    table_end = 132 + 12 * count
    if table_end > len(profile):
        return False
    curves = {}
    signatures = set()
    for pos in range(132, table_end, 12):
        signature, offset, size = struct.unpack_from('>4sII', profile, pos)
        if (signature in signatures or offset < table_end or offset % 4
                or size < 8 or offset + size > len(profile)):
            return False
        signatures.add(signature)
        if signature in {b'rTRC', b'gTRC', b'bTRC'}:
            curves[signature] = profile[offset:offset + size]
    if len(curves) != 3 or len(set(curves.values())) != 1:
        return False
    curve = curves[b'rTRC']
    if len(curve) < 12 or curve[:8] != b'para' + bytes(4) or curve[10:12] != bytes(2):
        return False
    function = struct.unpack_from('>H', curve, 8)[0]
    if function not in {3, 4}:
        return False
    expected = _SRGB if function == 3 else _SRGB + (0, 0)
    if len(curve) != 12 + 4 * len(expected):
        return False
    actual = struct.unpack_from('>' + 'i' * len(expected), curve, 12)
    return all(abs(value / 65536 - target) <= _TOLERANCE
               for value, target in zip(actual, expected))

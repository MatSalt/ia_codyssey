"""Version 2 upload normalization; source bytes remain caller-owned.

HEIF plugin/libheif applies container transforms and resets EXIF orientation.
HDR without an established SDR rendition is rejected, never silently truncated.
"""
import hashlib
import os
from io import BytesIO
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
import pillow_heif
from .contracts import MediaValidationError, NormalizedImage
from . import png_color, icc_sdr

pillow_heif.register_heif_opener(thumbnails=False)
MAX_PIXELS = 40_000_000
MAX_INPUT_BYTES = 20 * 1024 * 1024


def _setting(name, default, minimum=1):
    value = int(os.environ.get(name, default))
    if value < minimum:
        raise ValueError(name)
    return value


def _size(width, height, edge, exact):
    if exact:
        k = max(1, min(width // 3, height // 4, edge // 4))
        return 3 * k, 4 * k
    factor = min(1, edge / max(width, height))
    return max(1, int(width * factor + .5)), max(1, int(height * factor + .5))


def _encode(image, lossless=False, quality=80):
    out = BytesIO()
    # Explicit empty metadata: resizing/copying retains Image.info in Pillow.
    image.save(out, format='WEBP', lossless=lossless, quality=quality,
               exif=b'', icc_profile=b'', xmp=b'')
    return out.getvalue()


def normalize(source: bytes, filename: str) -> NormalizedImage:
    if len(source) > MAX_INPUT_BYTES:
        raise MediaValidationError('IMAGE_SIZE_LIMIT_EXCEEDED')
    try:
        png = png_color.declarations(source)
        image = Image.open(BytesIO(source))
        if image.format not in {'JPEG', 'MPO', 'PNG', 'WEBP', 'HEIF'}:
            raise MediaValidationError('UNSUPPORTED_MEDIA')
        # The pinned pillow-heif plugin opens primary_index and applies
        # container transforms. MPO opens its first primary JPEG frame.
        # Do not seek/decode secondary or auxiliary frames in either container.
        if image.width * image.height > MAX_PIXELS:
            raise MediaValidationError('IMAGE_PIXEL_LIMIT_EXCEEDED')
        if png is not None:
            # verify() checks the decoder path without loading pixel samples.
            image.verify()
            image = Image.open(BytesIO(source))
            png_color.validate(png, image.info)
        exif = image.getexif()
        nested = exif.get_ifd(0x8769) if 0x8769 in exif else {}
        captured = nested.get(36867, exif.get(36867))
        timezone = nested.get(36881, exif.get(36881))
        info = image.info.copy()
        # Fail closed for unvalidated HDR / high-bit-depth transfer paths.
        nclx = info.get('nclx_profile') or {}
        transfer = nclx.get('transfer_characteristics') if isinstance(nclx, dict) else None
        xmp = str(info.get('xmp', info.get('XML:com.adobe.xmp', b''))).lower()
        aux = str(info.get('aux', {})).lower()
        hdr_tokens = ('hdr-gain-map', 'hdrgm:', 'hdrgainmap', 'gainmap', 'gain_map')
        main_hdr = any(token in xmp for token in hdr_tokens)
        aux_hdr = any(token in aux for token in hdr_tokens)
        # Auxiliary gain maps do not make the primary pixels HDR. Require
        # affirmative 8-bit/sRGB-TRC evidence; never decode/apply that gain map.
        sdr_primary = (image.format == 'HEIF' and image.mode in {'RGB', 'RGBA'}
                       and info.get('bit_depth') == 8
                       and transfer in {None, 2, 13}
                       and icc_sdr.has_srgb_transfer(info.get('icc_profile')))
        wide_without_icc = (nclx.get('color_primaries', 1) not in {1, 2}
                            and not info.get('icc_profile'))
        if (info.get('bit_depth', 8) > 8 or transfer in {16, 18}
                or main_hdr or (aux_hdr and not sdr_primary) or wide_without_icc
                or (transfer not in {None, 2, 13} and not info.get('icc_profile'))
                or info.get('content_light_level')
                or info.get('mastering_display_colour_volume')
                or info.get('hdr_metadata') or info.get('gain_map')
                or image.mode in {'I', 'F', 'I;16', 'I;16B', 'I;16L'}):
            raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
        # Decide on original oriented dimensions before any decoder reduction.
        width, height = image.size
        orientation = exif.get(274, 1)
        if orientation in {5, 6, 7, 8}:
            width, height = height, width
        exact = width * 4 == height * 3
        edge = min(_setting('NORMALIZED_MAX_EDGE', 4096), 16383, max(width, height))
        target = _size(width, height, edge, exact)
        raw_target = target[::-1] if orientation in {5, 6, 7, 8} else target
        # JPEG draft still decodes the scan, but allocates fewer output pixels.
        # Metadata/HDR checks above always inspect the original header.
        if image.format in {'JPEG', 'MPO'}:
            image.draft(image.mode, raw_target)
        image.load()
        # Shrink before transpose, color conversion, and alpha separation, which
        # otherwise keep several full-resolution buffers live at once.
        # Palette/1-bit resizing otherwise silently forces nearest-neighbor.
        if image.mode in {'P', '1'} or 'transparency' in image.info:
            mode = ('LA' if image.mode == 'L' else 'RGBA') if 'transparency' in image.info else 'RGB'
            expanded = image.convert(mode)
            image.close()
            image = expanded
        if image.size != raw_target:
            # Pillow internally premultiplies RGBA/LA during resize. Release the
            # straight-alpha original first instead of retaining both 40MP
            # buffers throughout the resampler's allocations.
            straight_mode = image.mode if image.mode in {'RGBA', 'LA'} else None
            if straight_mode:
                premultiplied = image.convert('RGBa' if straight_mode == 'RGBA' else 'La')
                image.close()
                image = premultiplied
            resized = image.resize(raw_target, Image.Resampling.LANCZOS,
                                   reducing_gap=None if straight_mode else 3)
            image.close()
            image = resized
            if straight_mode:
                straight = image.convert(straight_mode)
                image.close()
                image = straight
        ImageOps.exif_transpose(image, in_place=True)
    except MediaValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise MediaValidationError('IMAGE_DECODE_FAILED') from error
    try:
        byte_limit = _setting('NORMALIZED_MAX_BYTES', 20971520)
        lossless_value = os.environ.get('NORMALIZED_WEBP_LOSSLESS', 'false').lower()
        if lossless_value not in {'true', 'false'}:
            raise ValueError('invalid normalization mode')
        lossless = lossless_value == 'true'
        quality = _setting('NORMALIZED_WEBP_QUALITY', 90)
        if quality > 100:
            raise ValueError('invalid normalization quality')
        has_alpha = 'A' in image.getbands() or 'transparency' in image.info
        alpha = (image.getchannel('A') if image.mode in {'RGBA', 'LA'}
                 else image.convert('RGBA').getchannel('A')) if has_alpha else None
        # Palette expansion and alpha separation do not discard CMYK/L channels.
        if image.mode in {'LA', 'La'}:
            color = image.getchannel('L')
        elif image.mode in {'CMYK', 'L', 'RGB'}:
            color = image
        else:
            color = image.convert('RGB')
        if info.get('icc_profile'):
            color = ImageCms.profileToProfile(color,
                ImageCms.ImageCmsProfile(BytesIO(info['icc_profile'])),
                ImageCms.createProfile('sRGB'), outputMode='RGB')
        else:
            color = png_color.to_srgb(color if color.mode == 'RGB' else color.convert('RGB'), png)
        if image is not color:
            image.close()
        image = color
        if alpha is not None:
            image.putalpha(alpha)
            alpha.close()
        floor = min(max(width, height), 1024)
        edge = min(edge, max(width, height))
        while True:
            size = _size(width, height, edge, exact)
            scaled = image if size == image.size else image.resize(size, Image.Resampling.LANCZOS)
            # Uploaded containers can hide private bytes inside otherwise valid
            # image chunks. Only decoded pixels may cross the storage boundary.
            encoded = _encode(scaled, lossless=lossless, quality=quality)
            if scaled is not image:
                scaled.close()
            if len(encoded) <= byte_limit:
                break
            if edge <= floor:
                raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
            edge = max(floor, int(edge * .8))
        thumb_size = _size(*size, min(480, _setting('THUMBNAIL_MAX_EDGE',480)), exact)
        thumb = image if thumb_size == image.size else image.resize(thumb_size, Image.Resampling.LANCZOS)
        thumbnail = _encode(thumb, quality=_setting('THUMBNAIL_WEBP_QUALITY',80))
        if thumb is not image:
            thumb.close()
        image.close()
        return NormalizedImage(encoded, thumbnail, *size, exact,
            str(captured) if captured else None, str(timezone) if timezone else None,
            hashlib.sha256(source).hexdigest())
    except MediaValidationError:
        raise
    except (OSError, ValueError, TypeError, ImageCms.PyCMSError) as error:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED') from error

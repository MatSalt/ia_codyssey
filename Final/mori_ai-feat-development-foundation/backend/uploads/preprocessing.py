"""Bounded browser hints, checked only after authoritative image validation."""
from PIL import Image
from pydantic import Field, StrictInt, StrictStr, model_validator
from backend.http.schemas import StrictBody
from backend.media.contracts import MediaValidationError


class PreprocessingBody(StrictBody):
    version: StrictInt=Field(ge=1,le=1)
    original_width: StrictInt=Field(ge=1,le=40_000_000)
    original_height: StrictInt=Field(ge=1,le=40_000_000)
    captured_at_raw: StrictStr|None=Field(default=None,max_length=256)
    captured_timezone: StrictStr|None=Field(default=None,max_length=64)

    @model_validator(mode='after')
    def pixel_limit(self):
        if self.original_width*self.original_height>40_000_000:
            raise ValueError('original pixel limit exceeded')
        return self


def preprocessing_hints(saved, mime, source_path):
    """Check browser claims only after successful authoritative codec validation.

    A common scale must explain both dimensions within half-pixel rounding.
    Claims never alter the actual file byte, hash, pixel or codec checks.
    """
    hint = saved.get('preprocessing')
    if hint is None:
        return None
    try:
        hint = PreprocessingBody.model_validate(hint)
        if mime != 'image/webp':
            raise ValueError('preprocessed source must be WebP')
        with Image.open(source_path) as image:
            width, height = image.size
            if image.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
        original_width, original_height = hint.original_width, hint.original_height
        if original_width*4==original_height*3 and width*4!=height*3:
            raise ValueError('exact portrait claim requires exact portrait pixels')
        if width > original_width or height > original_height:
            raise ValueError('upscaled preprocessing')
        lower = max((width-.5)/original_width, (height-.5)/original_height)
        upper = min((width+.5)/original_width, (height+.5)/original_height, 1)
        if lower >= upper:
            raise ValueError('incompatible aspect ratio')
        return hint
    except (ValueError, TypeError) as exc:
        raise MediaValidationError('IMAGE_NORMALIZATION_FAILED') from exc

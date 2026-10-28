from dataclasses import dataclass


class MediaValidationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NormalizedImage:
    webp_bytes: bytes
    thumbnail_bytes: bytes
    width: int
    height: int
    input_is_3_4: bool
    captured_at_raw: str | None
    captured_timezone: str | None
    sha256: str

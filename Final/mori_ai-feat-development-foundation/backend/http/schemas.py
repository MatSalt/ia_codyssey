from typing import Literal
from pydantic import BaseModel, ConfigDict, StrictBool


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EmptyBody(StrictBody):
    pass


class DevLogin(StrictBody):
    account: Literal['alpha', 'beta']


class ConsentBody(StrictBody):
    policy_version: str
    purpose: Literal['photo_upload_and_ai_processing']
    agreed: StrictBool


CLIENT_CONFIG = {
    'auth_providers': [],
    'album_min_photos': 1, 'album_max_photos': 50, 'caption_max_chars': 80,
    'caption_ai_target_min_chars': 20, 'caption_ai_target_max_chars': 45,
    'caption_allow_empty': True,
    'upload_allowed_mimes': ['image/jpeg', 'image/png', 'image/webp', 'image/heif', 'image/heic'],
    'upload_allowed_extensions': ['.jpg', '.jpeg', '.png', '.webp', '.heif', '.heic'],
    'upload_max_file_bytes': 20971520, 'upload_max_album_bytes': 314572800,
    'upload_max_pixels': 40000000, 'char_count_mode': 'nfc_unicode_code_points',
}

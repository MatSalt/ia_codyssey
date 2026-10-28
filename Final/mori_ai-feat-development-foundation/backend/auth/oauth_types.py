"""Validated provider identity, independent of provider SDKs and persistence."""
from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    subject: str
    display_name: str

    def __post_init__(self):
        if self.provider not in ('google', 'kakao'):
            raise ValueError('Unsupported OAuth provider')
        if not isinstance(self.subject, str) or not 1 <= len(self.subject) <= 255:
            raise ValueError('Invalid OAuth subject')
        name = self.display_name if isinstance(self.display_name, str) else ''
        object.__setattr__(self, 'display_name', name[:100] if name.strip() else '사용자')

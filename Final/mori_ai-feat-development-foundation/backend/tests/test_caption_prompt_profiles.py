"""Offline profile limits and shared output safeguards; no semantic quality claims."""
import unicodedata

import pytest

from backend.generation.openai_provider import _caption
from backend.generation.prompt_profiles import caption_prompt, SUPPORTED_PROMPT_VERSIONS


@pytest.mark.parametrize('version', sorted(SUPPORTED_PROMPT_VERSIONS))
def test_prompt_stays_inside_reviewed_caption_reservation(version):
    # The reviewed $0.02 reservation assumes a fixed prompt below 2000 UTF-8 bytes.
    assert len(caption_prompt(version).encode('utf-8')) < 2000


@pytest.mark.parametrize('value', [
    '', '가' * 81, 'Only English.', '한 문장. 또 한 문장.',
    '잎 사이로\n빛이 비친다.', '빛\x00이 비친다.', '아빠와 딸이 웃는다.',
    '저 사람은 의사다.', None,
])
def test_caption_safeguards_reject_malformed_or_identity_claims(value):
    assert _caption(value) is None


@pytest.mark.parametrize('value', [
    '초록 잎 사이로 비친 빛을 다시 들여다본다.',
    '빨간 딸기에 빛이 머문다.',
    '가' * 79 + '.',
    '빛이 머문다.',  # 20–45 is a target, not a hard minimum.
])
def test_caption_safeguards_preserve_valid_text_and_normalize_nfc(value):
    assert _caption('  ' + unicodedata.normalize('NFD', value) + '  ') == value

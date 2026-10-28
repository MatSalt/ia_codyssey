from types import SimpleNamespace
from backend.generation.service import config_snapshot,require_local_ai


def settings():
    return SimpleNamespace(app_env='local',dev_ai_enabled=False,ai_real_calls_enabled=True,
        openai_caption_model='gpt-5.4-mini',openai_image_model='gpt-image-2',
        normalized_webp_lossless=True,normalized_webp_quality=90,normalized_max_edge=4096,normalized_max_bytes=20000000,
        result_webp_quality=85,thumbnail_webp_quality=75,thumbnail_max_edge=320)


def test_real_admission_snapshots_provider_models():
    cfg=config_snapshot(settings())
    assert cfg['execution_mode']=='openai'
    assert cfg['caption_model']=='gpt-5.4-mini' and cfg['image_model']=='gpt-image-2'
    assert cfg['budget_scope']=='validation_usd'
    assert cfg['prompt_version']=='openai-memory-v3'
    assert cfg['pricing_profile']=='openai-standard-2026-10-16-v1'
    require_local_ai(settings())

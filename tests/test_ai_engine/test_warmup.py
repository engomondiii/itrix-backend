from unittest.mock import patch
from apps.ai_engine.services.warmup import preload_ai_runtime


def test_preload_imports_sdks_without_provider_calls(settings):
    settings.ENABLE_AI_ENGINE = True
    with patch('apps.ai_engine.services.warmup.importlib.import_module') as load:
        preload_ai_runtime()
    assert [call.args[0] for call in load.call_args_list] == ['anthropic', 'openai', 'pinecone']


def test_disabled_engine_stays_lazy(settings):
    settings.ENABLE_AI_ENGINE = False
    with patch('apps.ai_engine.services.warmup.importlib.import_module') as load:
        preload_ai_runtime()
    load.assert_not_called()


def test_missing_optional_sdk_does_not_break_readiness(settings):
    settings.ENABLE_AI_ENGINE = True
    with patch('apps.ai_engine.services.warmup.importlib.import_module', side_effect=ImportError) as load:
        preload_ai_runtime()
    assert load.call_count == 3

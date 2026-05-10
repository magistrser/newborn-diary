import pytest
from pydantic import ValidationError

from settings import LLMSettings, LLMTaskSettings


_BASE = LLMSettings(
    base_url='http://default:41234/v1',
    api_key='default-key',
    model='default-model',
    max_tokens=2048,
    request_timeout_sec=60,
    tasks={
        'parser': LLMTaskSettings(model='parser-model'),
        'agentic_qa': LLMTaskSettings(
            base_url='http://agentic:41234/v1',
            model='agentic-model',
        ),
        'router': LLMTaskSettings(api_key='router-key'),
        'all_overrides': LLMTaskSettings(
            base_url='http://other/v1',
            api_key='other-key',
            model='other-model',
            max_tokens=512,
            request_timeout_sec=120,
        ),
        'tokens_only': LLMTaskSettings(
            max_tokens=256,
            request_timeout_sec=30,
        ),
    },
)


def test_for_task_returns_self_when_no_override() -> None:
    result = _BASE.for_task('unconfigured_task')
    assert result is _BASE


def test_for_task_overrides_model_only() -> None:
    result = _BASE.for_task('parser')
    assert result.model == 'parser-model'
    assert result.base_url == 'http://default:41234/v1'
    assert result.api_key == 'default-key'


def test_for_task_overrides_base_url_and_model() -> None:
    result = _BASE.for_task('agentic_qa')
    assert result.base_url == 'http://agentic:41234/v1'
    assert result.model == 'agentic-model'
    assert result.api_key == 'default-key'


def test_for_task_overrides_api_key_only() -> None:
    result = _BASE.for_task('router')
    assert result.api_key == 'router-key'
    assert result.base_url == 'http://default:41234/v1'
    assert result.model == 'default-model'


def test_for_task_all_fields_overridden() -> None:
    result = _BASE.for_task('all_overrides')
    assert result.base_url == 'http://other/v1'
    assert result.api_key == 'other-key'
    assert result.model == 'other-model'
    assert result.max_tokens == 512
    assert result.request_timeout_sec == 120


def test_for_task_max_tokens_and_timeout_only() -> None:
    result = _BASE.for_task('tokens_only')
    assert result.max_tokens == 256
    assert result.request_timeout_sec == 30
    assert result.base_url == 'http://default:41234/v1'
    assert result.model == 'default-model'


def test_for_task_preserves_max_tokens_and_timeout_when_not_overridden() -> None:
    result = _BASE.for_task('parser')
    assert result.max_tokens == _BASE.max_tokens
    assert result.request_timeout_sec == _BASE.request_timeout_sec


def test_for_task_unknown_task_returns_self() -> None:
    result = _BASE.for_task('nonexistent_task')
    assert result is _BASE


def test_for_task_no_tasks_configured_returns_self() -> None:
    s = LLMSettings(base_url='http://host/v1', model='m')
    assert s.for_task('parser') is s


def test_llm_settings_tasks_default_empty() -> None:
    s = LLMSettings(base_url='http://host/v1', model='m')
    assert s.tasks == {}


def test_llm_task_settings_all_none_by_default() -> None:
    t = LLMTaskSettings()
    assert t.base_url is None
    assert t.api_key is None
    assert t.model is None
    assert t.max_tokens is None
    assert t.request_timeout_sec is None


def test_for_task_partial_override_does_not_mutate_base() -> None:
    base_model = _BASE.model
    _BASE.for_task('parser')
    assert _BASE.model == base_model


def test_for_task_result_is_valid_llm_settings() -> None:
    result = _BASE.for_task('agentic_qa')
    assert isinstance(result, LLMSettings)
    assert result.base_url
    assert result.model


def test_llm_settings_requires_base_url_and_model() -> None:
    with pytest.raises(ValidationError):
        LLMSettings()  # type: ignore[call-arg]


def test_llm_settings_tasks_validated_as_task_settings() -> None:
    s = LLMSettings(
        base_url='http://h/v1',
        model='m',
        tasks={'t': LLMTaskSettings(model='override-model')},
    )
    assert isinstance(s.tasks['t'], LLMTaskSettings)
    assert s.tasks['t'].model == 'override-model'

"""Run rootと外部service制御設定を検証する。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from translate.common.settings import (
    GEMMA_MAX_CONTEXT,
    LLM_SAFETY_TOKENS,
    PROJECT_ROOT,
    load_settings,
)
from translate.tasks import translate

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.settings import Settings


def test_default_runs_dir_is_project_runs() -> None:
    """未設定時はProject直下のrunsを絶対pathで使用する。"""

    settings = load_settings("convert", env={})

    assert settings.runs_dir == (PROJECT_ROOT / "runs").resolve()


@pytest.mark.parametrize(
    "configured",
    ["var/runs", "var\\runs"],
    ids=["posix-style", "windows-style"],
)
def test_relative_runs_dir_is_resolved_from_project(configured: str) -> None:
    """OSで一般的な区切りを含む相対pathをProject基準で解決する。"""

    settings = load_settings("convert", env={"TRANSLATE_RUNS_DIR": configured})

    expected = (PROJECT_ROOT / Path(configured)).resolve()
    assert settings.runs_dir == expected
    assert settings.runs_dir.is_absolute()


def test_retry_timeout_and_deadline_are_configurable() -> None:
    """外部serviceの有限retryと時間制限を環境変数から読める。"""

    settings = load_settings(
        "convert",
        env={
            "TRANSLATE_RETRY_ATTEMPTS": "5",
            "TRANSLATE_RETRY_BASE_SECONDS": "0.25",
            "TRANSLATE_RETRY_MAX_SECONDS": "4",
            "TRANSLATE_REQUEST_TIMEOUT_SECONDS": "12.5",
            "TRANSLATE_TASK_DEADLINE_SECONDS": "90",
        },
    )

    assert settings.retry_attempts == 5
    assert settings.retry_base_seconds == 0.25
    assert settings.retry_max_seconds == 4
    assert settings.request_timeout_seconds == 12.5
    assert settings.task_deadline_seconds == 90


def test_default_llm_budget_matches_deployed_model_context() -> None:
    """既定予算は実Model context内に入力領域を確保する。"""

    settings = load_settings("convert", env={})

    assert GEMMA_MAX_CONTEXT == 30_208
    assert settings.context_tokens == 30_208
    assert settings.output_tokens == 16_384
    assert settings.image_tokens == 2_048
    assert LLM_SAFETY_TOKENS == 1_024
    assert settings.available_input_tokens == 10_752


def test_context_is_capped_at_model_limit_without_reducing_exact_limit() -> None:
    """実上限は保持し、それを超える指定だけを制限する。"""

    exact = load_settings("convert", env={"LLM_CONTEXT_TOKENS": "30208"})
    capped = load_settings("convert", env={"LLM_CONTEXT_TOKENS": "99999"})

    assert exact.context_tokens == 30_208
    assert capped.context_tokens == 30_208


def test_invalid_llm_reservations_are_rejected_instead_of_rewritten() -> None:
    """入力余白を失う設定は暗黙補正せず拒否する。"""

    with pytest.raises(ValueError, match="at least 1024 input tokens"):
        load_settings(
            "convert",
            env={
                "LLM_CONTEXT_TOKENS": "30208",
                "LLM_OUTPUT_TOKENS": "28000",
                "LLM_IMAGE_TOKENS": "2048",
            },
        )


def test_translation_chunks_use_shared_available_input_budget(
    settings_factory: Callable[..., Settings],
) -> None:
    """Chunk境界は画像予約と安全余白を含む共通予算を使う。"""

    settings = settings_factory(
        context_tokens=8_192,
        output_tokens=4_096,
        image_tokens=2_048,
    )
    values = [("first", "a" * 2_500), ("second", "b" * 2_500)]

    chunks = translate._chunks(values, settings)  # noqa: SLF001

    assert settings.available_input_tokens == 1_024
    assert chunks == [[values[0]], [values[1]]]


@pytest.mark.parametrize(
    "name",
    [
        "TRANSLATE_RETRY_ATTEMPTS",
        "TRANSLATE_RETRY_BASE_SECONDS",
        "TRANSLATE_RETRY_MAX_SECONDS",
        "TRANSLATE_REQUEST_TIMEOUT_SECONDS",
        "TRANSLATE_TASK_DEADLINE_SECONDS",
    ],
)
def test_non_positive_service_control_is_rejected(name: str) -> None:
    """無限または即時失敗を招く非正値を拒否する。"""

    with pytest.raises(ValueError, match=name):
        load_settings("convert", env={name: "0"})

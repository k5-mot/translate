"""Run rootと外部service制御設定を検証する。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from translate.common.settings import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    GEMMA_MAX_CONTEXT,
    LLM_SAFETY_TOKENS,
    PROJECT_ROOT,
    Settings,
    load_settings,
)
from translate.tasks import translate

if TYPE_CHECKING:
    from collections.abc import Callable


# All four public durations share the same finite-positive environment contract.
SERVICE_SECONDS = (
    ("TRANSLATE_RETRY_BASE_SECONDS", "retry_base_seconds"),
    ("TRANSLATE_RETRY_MAX_SECONDS", "retry_max_seconds"),
    ("TRANSLATE_REQUEST_TIMEOUT_SECONDS", "request_timeout_seconds"),
    ("TRANSLATE_TASK_DEADLINE_SECONDS", "task_deadline_seconds"),
)


def test_default_runs_dir_is_project_runs() -> None:
    """未設定時はProject直下のrunsを絶対pathで使用する。"""

    settings = load_settings("convert", env={})

    assert settings.runs_dir == (PROJECT_ROOT / "runs").resolve()


@pytest.mark.parametrize("mode", [None, "task-default", "off"])
def test_reasoning_mode_is_explicit_and_defaults_to_task_policy(
    mode: str | None,
) -> None:
    """設定追加は既定のTask方針を変えず、OFFだけを明示的に選択できる。"""

    env = {} if mode is None else {"LLM_REASONING_MODE": mode}
    settings = load_settings("convert", env=env)
    assert settings.reasoning_mode == (mode or "task-default")


@pytest.mark.parametrize("value", ["", "OFF", "high", "SECRET-INVALID"])
def test_invalid_reasoning_mode_never_echoes_input(value: str) -> None:
    """外部処理へ渡す設定を生成する前に、不正値を固定Errorで拒否する。"""

    with pytest.raises(ValueError, match="LLM_REASONING_MODE") as captured:
        load_settings("convert", env={"LLM_REASONING_MODE": value})
    assert str(captured.value) == "LLM_REASONING_MODE must be task-default or off"
    assert "SECRET-INVALID" not in "".join(traceback.format_exception(captured.value))


@pytest.mark.parametrize(
    "configured",
    ["var/runs", "var\\runs"],
    ids=["posix-style", "windows-style"],
)
def test_relative_runs_dir_is_resolved_from_project(configured: str) -> None:
    """両表記の相対pathを実行OSのPath解釈に従いProject基準で絶対化する。"""

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
    """既定のtoken予約と入力余白、timeoutが合意済みの設定値と一致する。"""

    settings = load_settings("convert", env={})

    assert GEMMA_MAX_CONTEXT == 30_208
    assert settings.context_tokens == 30_208
    assert settings.output_tokens == 16_384
    assert settings.image_tokens == 2_048
    assert LLM_SAFETY_TOKENS == 1_024
    assert settings.available_input_tokens == 10_752
    assert (
        settings.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS == 1_800.0
    )


def test_context_is_capped_at_model_limit_without_reducing_exact_limit() -> None:
    """指定値30208は保持し、99999は設定上限30208へ制限する。"""

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
    """各外部Service制御の環境変数で0を拒否し、設定名を例外へ含める。"""

    with pytest.raises(ValueError, match=name):
        load_settings("convert", env={name: "0"})


@pytest.mark.parametrize(("name", "field"), SERVICE_SECONDS)
@pytest.mark.parametrize(
    "value",
    ["nan", "NaN", "inf", "+Infinity", "-Infinity", "1e309", "0", "-1", "invalid"],
)
def test_invalid_service_seconds_are_rejected(
    name: str, field: str, value: str
) -> None:
    """秒数の非有限・非正数・変換不能を全環境変数で拒否する。"""

    assert field in Settings.model_fields
    with pytest.raises(ValueError, match=name):
        load_settings("convert", env={name: value})


@pytest.mark.parametrize("field", [field for _, field in SERVICE_SECONDS])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_direct_settings_reject_nonfinite_seconds(field: str, value: float) -> None:
    """通常のModel構築でも全秒数fieldの非有限値を拒否する。"""

    values = {"templates_dir": PROJECT_ROOT / "translate" / "templates", field: value}
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate(values)


@pytest.mark.parametrize(("name", "field"), SERVICE_SECONDS)
@pytest.mark.parametrize(
    "value",
    [
        "0.25",
        "1800",
        "21600",
        str(sys.float_info.max),
        "１８００",  # noqa: RUF001 - preserve fullwidth numeric input compatibility
        "١٨٠٠",
        " +1.8e3 ",
        "1_800",
    ],
)
def test_valid_service_seconds_preserve_numeric_value(
    name: str, field: str, value: str
) -> None:
    """従来のfloat表記と有限秒数を、独自の上限や丸めを加えず保持する。"""

    settings = load_settings("convert", env={name: value})

    assert getattr(settings, field) == float(value)


def test_internal_zero_retry_and_long_defaults_are_preserved() -> None:
    """公開envの正数制約と内部Testの待機なし設定を区別し、長い既定値を維持する。"""

    settings = Settings(
        templates_dir=PROJECT_ROOT / "translate" / "templates",
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    assert settings.retry_base_seconds == settings.retry_max_seconds == 0
    assert settings.request_timeout_seconds == 1_800
    assert settings.task_deadline_seconds == 21_600


def test_invalid_duration_does_not_echo_input_in_normal_traceback() -> None:
    """設定名と固定理由は残し、変換失敗の元入力を通常tracebackへ露出しない。"""

    name = "TRANSLATE_REQUEST_TIMEOUT_SECONDS"
    marker = "SYNTHETIC_INVALID_DURATION"
    with pytest.raises(ValueError, match=name) as captured:
        load_settings("convert", env={name: marker})

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == f"{name} must be a finite positive number"
    assert marker not in rendered
    assert captured.value.__suppress_context__
    assert "could not convert string to float" not in rendered

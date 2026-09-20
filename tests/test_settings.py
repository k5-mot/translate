"""Run rootと外部service制御設定を検証する。"""

from __future__ import annotations

from pathlib import Path

import pytest

from translate.common.settings import PROJECT_ROOT, load_settings


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

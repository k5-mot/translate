"""4つの公開CLI subcommandを実processで検証する。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.e2e
@pytest.mark.cli
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("translate", "source.pdf"), "translation_id: translate-e2e"),
        (("review", "source.pdf", "translation.pdf"), "review_id: review-e2e"),
        (("register", "reference.txt"), "registration_id: register-e2e"),
        (
            ("upgrade", "source-v1.pdf", "source-v2.pdf", "translation-v1.pdf"),
            "upgrade_id: upgrade-e2e",
        ),
    ],
)
def test_cli_subcommands_run_in_a_real_process(
    tmp_path: Path, arguments: tuple[str, ...], expected: str
) -> None:
    """Typerの引数解析から終了codeと表示までをprocess越しに通す。"""

    for name in arguments[1:]:
        (tmp_path / name).write_bytes(b"e2e")
    project = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(project / "tests/e2e/cli_process"), str(project)]
    )
    result = subprocess.run(
        [sys.executable, "-m", "translate", *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout

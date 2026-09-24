"""CLIのRun作成、Resume、候補確認、exportおよび削除を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

import cli
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes
from translate.workflows import translation as translation_workflow

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


def _templates(root: Path) -> Path:
    """fingerprintに必要な規則・用語集・TemplateのダミーFileを隔離領域へ用意する。"""

    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text(
        "english-short,japanese-short\n", encoding="utf-8"
    )
    (root / "template.docx").write_bytes(b"template")
    return root


def _fake_translation(
    _source: Path,
    output_dir: Path,
    _backend: Backend,
    _settings: Settings,
    _callback: ProgressCallback | None = None,
    _workspace_dir: Path | None = None,
) -> Path:
    """外部翻訳を使わず固定byte列の成果物を作り、Run選択・export・削除の検証へ集中する。"""

    result = output_dir / "document.ja.docx"
    atomic_write_bytes(result, b"completed document")
    return result


def test_cli_explicit_resume_compatibility_export_and_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """明示Resumeだけが同じRunを使い、非互換拒否とexport保持を保証する。"""

    templates = _templates(tmp_path / "templates")
    current = [
        settings_factory(
            runs_dir=tmp_path / "runs",
            templates_dir=templates,
            translation_model="model-a",
        )
    ]
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: current[0])
    monkeypatch.setattr(translation_workflow, "run", _fake_translation)
    # lifecycle imports the callable directly, so replace that binding as well.
    monkeypatch.setattr("translate.common.lifecycle.run_translation", _fake_translation)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    exported = tmp_path / "exported"

    first = runner.invoke(
        cli.app,
        ["translate", str(source), "--output-dir", str(exported)],
    )

    assert first.exit_code == 0, first.output
    repository = RunRepository(current[0].runs_dir)
    record = repository.list_runs().records[0]
    assert record.status == "completed"
    assert (exported / "document.ja.docx").read_bytes() == b"completed document"

    resumed = runner.invoke(
        cli.app,
        [
            "translate",
            str(source),
            "--output-dir",
            str(exported),
            "--resume",
            record.run_id,
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    assert f"run_id={record.run_id} mode=resume" in resumed.output
    assert len(repository.list_runs().records) == 1

    listed = runner.invoke(cli.app, ["runs"])
    assert listed.exit_code == 0, listed.output
    assert record.run_id in listed.output
    secondary_export = tmp_path / "secondary-export"
    exported_again = runner.invoke(
        cli.app,
        ["export", record.run_id, "--output-dir", str(secondary_export)],
    )
    assert exported_again.exit_code == 0, exported_again.output
    assert (secondary_export / "document.ja.docx").is_file()

    current[0] = current[0].model_copy(update={"translation_model": "model-b"})
    rejected = runner.invoke(
        cli.app,
        [
            "translate",
            str(source),
            "--output-dir",
            str(exported),
            "--resume",
            record.run_id,
        ],
    )
    assert rejected.exit_code != 0
    assert "models.translation" in rejected.output

    current[0] = current[0].model_copy(update={"translation_model": "model-a"})
    deleted = runner.invoke(cli.app, ["delete-run", record.run_id, "--confirm"])
    assert deleted.exit_code == 0, deleted.output
    assert not repository.paths(record.run_id).root.exists()
    assert (exported / "document.ja.docx").is_file()
    assert (secondary_export / "document.ja.docx").is_file()


def test_interactive_same_input_requires_y_and_supports_candidate_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """複数の同一入力候補からrun IDを選び、yの場合だけ再開する。"""

    templates = _templates(tmp_path / "templates")
    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=templates,
        translation_model="model-a",
    )
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr("translate.common.lifecycle.run_translation", _fake_translation)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"same input")

    for number in (1, 2):
        result = runner.invoke(
            cli.app,
            [
                "translate",
                str(source),
                "--output-dir",
                str(tmp_path / f"export-{number}"),
            ],
        )
        assert result.exit_code == 0, result.output
    repository = RunRepository(settings.runs_dir)
    records = repository.list_runs().records
    selected = records[-1].run_id

    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    resumed = runner.invoke(
        cli.app,
        ["translate", str(source), "--output-dir", str(tmp_path / "selected")],
        input=f"{selected}\ny\n",
    )

    assert resumed.exit_code == 0, resumed.output
    assert f"run_id={selected} mode=resume" in resumed.output
    assert len(repository.list_runs().records) == 2


def test_noninteractive_same_input_always_creates_new_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """redirect/CI相当では候補を質問せず、指定なしなら新規Runにする。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr("translate.common.lifecycle.run_translation", _fake_translation)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"same input")
    runner = CliRunner()

    results = [
        runner.invoke(
            cli.app,
            [
                "translate",
                str(source),
                "--output-dir",
                str(tmp_path / f"output-{index}"),
            ],
        )
        for index in (1, 2)
    ]

    assert all(result.exit_code == 0 for result in results)
    assert all("mode=new" in result.output for result in results)
    assert len(RunRepository(settings.runs_dir).list_runs().records) == 2

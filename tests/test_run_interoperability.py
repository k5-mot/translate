"""CLIとStreamlitが同じRunを相互Resumeできることを検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import cli
import main
from translate.common.runs import InvalidRunIdError, RunRepository
from translate.common.workspace import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.adapters import qdrant
    from translate.common.progress import ProgressCallback
    from translate.common.settings import Backend, Settings


def _templates(root: Path) -> Path:
    root.mkdir()
    for name in ("structure", "translation", "review"):
        (root / f"{name}-rules.md").write_text(name, encoding="utf-8")
    (root / "glossary.csv").write_text(
        "english-short,japanese-short\n", encoding="utf-8"
    )
    (root / "template.docx").write_bytes(b"template")
    return root


def test_cli_and_streamlit_resume_each_others_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """双方の作成Runが同じworkspace Artifactと最終成果物へ到達する。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
        translation_model="model",
    )

    def fake_translation(
        source: Path,
        output_dir: Path,
        backend: Backend,
        _settings: Settings,
        _callback: ProgressCallback | None = None,
        workspace_dir: Path | None = None,
    ) -> Path:
        assert workspace_dir is not None
        artifact = workspace_dir / "translate" / "artifact.bin"
        if not artifact.exists():
            atomic_write_bytes(artifact, source.read_bytes())
        result = output_dir / "document.ja.docx"
        atomic_write_bytes(result, artifact.read_bytes() + f":{backend}".encode())
        return result

    monkeypatch.setattr("translate.common.lifecycle.run_translation", fake_translation)
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()
    repository = RunRepository(settings.runs_dir)

    cli_source = tmp_path / "cli-source.pdf"
    cli_source.write_bytes(b"created-by-cli")
    created_by_cli = runner.invoke(
        cli.app,
        [
            "translate",
            str(cli_source),
            "--output-dir",
            str(tmp_path / "cli-export"),
        ],
    )
    assert created_by_cli.exit_code == 0, created_by_cli.output
    cli_record = repository.list_runs().records[0]

    ui_record, ui_outputs = main._run_selected(  # noqa: SLF001
        "translate",
        {"source": cli_source},
        settings,
        "llm",
        cli_record.run_id,
    )
    assert ui_record.run_id == cli_record.run_id
    assert ui_outputs[0].read_bytes() == b"created-by-cli:llm"
    assert (
        repository.paths(cli_record.run_id).workspace / "translate" / "artifact.bin"
    ).read_bytes() == b"created-by-cli"

    ui_source = tmp_path / "ui-source.pdf"
    ui_source.write_bytes(b"created-by-ui")
    created_ui_record, created_ui_outputs = main._run_selected(  # noqa: SLF001
        "translate",
        {"source": ui_source},
        settings,
        "llm",
        None,
    )
    assert created_ui_outputs[0].read_bytes() == b"created-by-ui:llm"

    resumed_by_cli = runner.invoke(
        cli.app,
        [
            "translate",
            str(ui_source),
            "--output-dir",
            str(tmp_path / "ui-run-export"),
            "--resume",
            created_ui_record.run_id,
        ],
    )
    assert resumed_by_cli.exit_code == 0, resumed_by_cli.output
    assert f"run_id={created_ui_record.run_id} mode=resume" in resumed_by_cli.output
    assert (tmp_path / "ui-run-export" / "document.ja.docx").read_bytes() == (
        b"created-by-ui:llm"
    )


def test_cli_and_streamlit_build_the_same_registration_source_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """同じ登録元IDとlogical pathはUI/CLIの一時pathに依存しない。"""

    settings = settings_factory(runs_dir=tmp_path / "runs")
    captured: list[str] = []
    workspaces: list[Path | None] = []

    def fake_register(
        _settings: Settings,
        sources: list[qdrant.RegistrationSource],
        _workspace: Path | None = None,
    ) -> int:
        captured.extend(item.source_key for item in sources)
        workspaces.append(_workspace)
        return len(sources)

    monkeypatch.setattr("translate.common.lifecycle.register_documents", fake_register)
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    ui_source = tmp_path / "ui" / "guide.md"
    cli_source = tmp_path / "cli" / "guide.md"
    ui_source.parent.mkdir()
    cli_source.parent.mkdir()
    ui_source.write_text("same", encoding="utf-8")
    cli_source.write_text("same", encoding="utf-8")

    main._run_selected(  # noqa: SLF001
        "register",
        {"reference": ui_source},
        settings,
        "llm",
        None,
        source_id="shared-library",
    )
    result = CliRunner().invoke(
        cli.app,
        ["register", str(cli_source), "--source-id", "shared-library"],
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 2
    assert captured[0] == captured[1]
    assert all(path is not None for path in workspaces)
    assert all(path.name == "registration" for path in workspaces if path is not None)
    assert all(
        path.parent.name == ".workspace" for path in workspaces if path is not None
    )


def test_custom_reference_docx_is_shared_between_cli_and_streamlit_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """利用者指定templateをfingerprint付きで相互Resumeする。"""

    settings = settings_factory(
        runs_dir=tmp_path / "runs",
        templates_dir=_templates(tmp_path / "templates"),
    )

    def fake_docx(markdown: Path, output: Path, template: Path) -> Path:
        atomic_write_bytes(output, markdown.read_bytes() + b":" + template.read_bytes())
        return output

    monkeypatch.setattr("translate.common.lifecycle.create_docx", fake_docx)
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()
    repository = RunRepository(settings.runs_dir)
    source = tmp_path / "source.md"
    template = tmp_path / "custom.docx"
    source.write_bytes(b"markdown")
    template.write_bytes(b"custom-template")

    created = runner.invoke(
        cli.app,
        [
            "convert",
            str(source),
            "--output",
            str(tmp_path / "cli.docx"),
            "--reference-doc",
            str(template),
        ],
    )
    assert created.exit_code == 0, created.output
    record = repository.list_runs().records[0]
    resumed, outputs = main._run_selected(  # noqa: SLF001
        "convert",
        {"source": source, "reference_doc": template},
        settings,
        "llm",
        record.run_id,
    )
    assert resumed.run_id == record.run_id
    assert outputs[0].read_bytes() == b"markdown:custom-template"

    source_two = tmp_path / "second.md"
    source_two.write_bytes(b"second")
    created_ui, _ = main._run_selected(  # noqa: SLF001
        "convert",
        {"source": source_two, "reference_doc": template},
        settings,
        "llm",
        None,
    )
    resumed_cli = runner.invoke(
        cli.app,
        [
            "convert",
            str(source_two),
            "--output",
            str(tmp_path / "ui.docx"),
            "--reference-doc",
            str(template),
            "--resume",
            created_ui.run_id,
        ],
    )
    assert resumed_cli.exit_code == 0, resumed_cli.output
    assert (tmp_path / "ui.docx").read_bytes() == b"second:custom-template"


def test_uuid4_run_is_excluded_and_all_public_operations_reject_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """旧UUIDv4 Runは一覧外となりCLI/UIの各操作で同じ理由を返す。"""

    settings = settings_factory(runs_dir=tmp_path / "runs")
    source = tmp_path / "reference.md"
    source.write_text("content", encoding="utf-8")
    repository = RunRepository(settings.runs_dir)
    current = repository.create("register", {"reference": source}, {}, "fingerprint")
    legacy_id = "00000000-0000-4000-8000-000000000001"
    legacy_root = repository.root / legacy_id
    legacy_root.mkdir()
    metadata = json.loads(repository.paths(current.run_id).metadata.read_text())
    metadata["run_id"] = legacy_id
    (legacy_root / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    runner = CliRunner()
    expected = "run_id must be a canonical UUIDv7"

    listed = runner.invoke(cli.app, ["runs"])
    resumed = runner.invoke(
        cli.app,
        ["register", str(source), "--resume", legacy_id],
    )
    exported = runner.invoke(
        cli.app,
        ["export", legacy_id, "--output-dir", str(tmp_path / "export")],
    )
    deleted = runner.invoke(cli.app, ["delete-run", legacy_id, "--confirm"])

    assert listed.exit_code == 0
    assert f"{legacy_id}\t" not in listed.output
    assert expected in listed.output
    for result in (resumed, exported, deleted):
        assert result.exit_code != 0
        assert expected in result.output
        assert "Traceback" not in result.output

    with pytest.raises(InvalidRunIdError, match="canonical UUIDv7"):
        main._run_selected(  # noqa: SLF001
            "register",
            {"reference": source},
            settings,
            "llm",
            legacy_id,
        )

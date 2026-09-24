"""StreamlitのRun管理と公開widget契約をbrowser harnessで検証する。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

import main
from translate.common.lifecycle import FailureRecord, PublicRunError
from translate.common.runs import RunRepository
from translate.common.workspace import atomic_write_bytes

if TYPE_CHECKING:
    from translate.common.runs import RunRecord


def _completed_run(root: Path, source: Path) -> RunRecord:
    """一覧・ダウンロード・削除のUI検査に使う、固定成果物付きの完了Runを作る。"""

    repository = RunRepository(root)
    record = repository.create(
        "translate",
        {"source": source},
        {"inputs": {"source": "hash"}},
        "fingerprint",
    )
    output = repository.paths(record.run_id).outputs / "document.ja.docx"
    atomic_write_bytes(output, b"document")
    return repository.save(record.model_copy(update={"status": "completed"}))


@pytest.mark.browser
def test_streamlit_lists_downloads_and_deletes_only_after_explicit_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rerunだけでは開始・削除せず、確認後のbutton操作だけがRunを削除する。"""

    runs = tmp_path / "runs"
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    record = _completed_run(runs, source)
    monkeypatch.setenv("TRANSLATE_RUNS_DIR", str(runs))

    app = AppTest.from_file(str(Path(main.__file__))).run(timeout=10)

    assert not app.exception
    assert any(widget.label == "Run一覧" for widget in app.selectbox)
    assert any(
        button.label.endswith("をダウンロード") for button in app.get("download_button")
    )
    assert runs.joinpath(record.run_id).is_dir()

    export_dir = tmp_path / "ui-export"
    app.text_input(key="manage-export-path").set_value(str(export_dir)).run(timeout=10)
    next(
        button for button in app.button if button.label == "成果物をexport"
    ).click().run(timeout=10)
    assert (export_dir / "document.ja.docx").is_file()

    app.run(timeout=10)
    assert runs.joinpath(record.run_id).is_dir()

    confirmation = next(item for item in app.checkbox if item.label.startswith("Run "))
    confirmation.set_value(True).run(timeout=10)
    delete = next(button for button in app.button if button.label == "Runを削除")
    delete.click().run(timeout=10)

    assert not runs.joinpath(record.run_id).exists()
    assert (export_dir / "document.ja.docx").is_file()


@pytest.mark.browser
def test_streamlit_entrypoint_uses_uploaded_file_and_segmented_backend() -> None:
    """main.pyが起動し、UploadedFile型とsegmented controlを公開する。"""

    app = AppTest.from_file(str(Path(main.__file__))).run(timeout=10)

    assert not app.exception
    assert main._save.__annotations__["upload"] == "UploadedFile"  # noqa: SLF001
    assert any(widget.label == "翻訳バックエンド" for widget in app.segmented_control)


@pytest.mark.browser
@pytest.mark.parametrize(
    "name",
    [
        "TRANSLATE_RETRY_BASE_SECONDS",
        "TRANSLATE_RETRY_MAX_SECONDS",
        "TRANSLATE_REQUEST_TIMEOUT_SECONDS",
        "TRANSLATE_TASK_DEADLINE_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["nan", "inf", "SYNTHETIC_INVALID_DURATION"])
def test_streamlit_invalid_seconds_stop_before_repository_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    """実UI起動時の設定例外は固定理由だけを表示し、保存処理と通信へ到達しない。"""

    runs = tmp_path / "runs"
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("TRANSLATE_RUNS_DIR", str(runs))
    monkeypatch.setenv(name, value)
    repository = Mock(side_effect=AssertionError("Repository must not be opened"))
    request = Mock(side_effect=AssertionError("External HTTP must not be used"))
    monkeypatch.setattr("translate.common.runs.RunRepository", repository)
    # AppTest needs Windows loopback sockets for its event loop, not service HTTP.
    monkeypatch.setattr("httpx.Client.send", request)

    app = AppTest.from_file(str(Path(main.__file__))).run(timeout=10)

    assert len(app.exception) == 1
    assert app.exception[0].value == f"{name} must be a finite positive number"
    assert "SYNTHETIC_INVALID_DURATION" not in str(app.exception[0])
    assert not runs.exists()
    repository.assert_not_called()
    request.assert_not_called()


def test_streamlit_registration_requires_confirmed_source_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UIは登録元IDと置換確認を共通Lifecycleへ渡す。"""

    class Upload:
        name = "guide.md"

        def getvalue(self) -> bytes:
            """
            登録UIへ渡すUploadの固定本文を返し、実アップロードなしで保存処理を通す。
            """

            return b"guide"

    captured: dict[str, object] = {}
    monkeypatch.setattr(main.st, "file_uploader", lambda *_args, **_kwargs: [Upload()])
    monkeypatch.setattr(main.st, "text_input", lambda *_args, **_kwargs: "library")
    monkeypatch.setattr(main.st, "checkbox", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        main,
        "load_settings",
        lambda *_args, **_kwargs: type("Settings", (), {"runs_dir": tmp_path})(),
    )

    def capture(
        _operation: object,
        inputs: dict[str, Path],
        _settings: object,
        _backend: object,
        _key: object,
        source_id: str | None = None,
    ) -> None:
        """
        UIが用意した入力pathと確認済み登録元IDを捕捉し、共有実行入口への引渡しを調べる。
        """

        captured["inputs"] = inputs
        captured["source_id"] = source_id

    monkeypatch.setattr(main, "_execute_ui", capture)
    main._register()  # noqa: SLF001

    assert captured["source_id"] == "library"
    assert len(captured["inputs"]) == 1  # type: ignore[arg-type]


def test_streamlit_failure_boundary_displays_only_safe_run_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UIの実行境界はraw例外ではなく共通Run失敗だけを表示する。"""

    failure = FailureRecord(
        run_id="run-ui-safe",
        task="TARGET-DOCLING",
        target_id="translation_ja",
        error_type="RemoteError",
        reason="RemoteError status=502",
        failed_at="2026-09-20T00:00:00Z",
    )
    shown: list[str] = []
    settings = type("Settings", (), {"runs_dir": tmp_path})()
    monkeypatch.setattr(main, "_resume_choice", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.st, "button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "_progress_callback", lambda: None)
    monkeypatch.setattr(main.st, "error", shown.append)

    def fail(*_args: object, **_kwargs: object) -> object:
        """
        構造化失敗を公開例外として返し、UIが安全なRun情報だけを表示するか検査する。
        """

        raise PublicRunError(failure)

    monkeypatch.setattr(main, "_run_selected", fail)
    result = main._execute_ui(  # noqa: SLF001
        "review",
        {"source_en": tmp_path / "en.pdf", "translation_ja": tmp_path / "ja.pdf"},
        settings,  # type: ignore[arg-type]
        "llm",
        "review",
    )

    assert result is None
    assert shown == [
        (
            "run_id=run-ui-safe task=TARGET-DOCLING target=translation_ja "
            "cause=RemoteError status=502"
        )
    ]
    assert "Traceback" not in shown[0]


@pytest.mark.browser
def test_streamlit_apptest_renders_structured_failure() -> None:
    """AppTest上の実button操作でも共通Run失敗だけを表示する。"""

    script = """
from pathlib import Path
import main
from translate.common.lifecycle import FailureRecord, PublicRunError

failure = FailureRecord(
    run_id="run-app-test",
    task="SOURCE-DOCLING",
    target_id="source_en",
    error_type="RemoteError",
    reason="RemoteError status=503",
    failed_at="2026-09-20T00:00:00Z",
)
settings = type("Settings", (), {"runs_dir": Path("runs-app-test")})()
main._resume_choice = lambda *_args, **_kwargs: None
def fail(*_args, **_kwargs):
    # Exercise the rendered error boundary without invoking a real workflow.
    raise PublicRunError(failure)
main._run_selected = fail
main._execute_ui(
    "review",
    {"source_en": Path("en.pdf"), "translation_ja": Path("ja.pdf")},
    settings,
    "llm",
    "failure-test",
)
"""
    app = AppTest.from_string(script).run(timeout=10)
    app.button[0].click().run(timeout=10)

    assert not app.exception
    assert len(app.error) == 1
    assert app.error[0].value == (
        "run_id=run-app-test task=SOURCE-DOCLING target=source_en "
        "cause=RemoteError status=503"
    )


@pytest.mark.browser
def test_streamlit_apptest_requires_resume_confirmation() -> None:
    """選択済みRunは確認checkboxを入れるまで開始buttonを無効にする。"""

    script = """
from pathlib import Path
import main

settings = type("Settings", (), {"runs_dir": Path("runs-resume-test")})()
record = type("Record", (), {"run_id": "existing-run"})()
main._resume_choice = lambda *_args, **_kwargs: "existing-run"
main._progress_callback = lambda: None
main._run_selected = lambda *_args, **_kwargs: (record, ())
main._execute_ui(
    "convert",
    {"source": Path("source.md")},
    settings,
    "llm",
    "resume-test",
)
"""
    app = AppTest.from_string(script).run(timeout=10)

    assert app.button[0].disabled is True
    app.checkbox[0].set_value(True).run(timeout=10)
    assert app.button[0].disabled is False
    app.button[0].click().run(timeout=10)
    assert app.success[0].value == "完了: existing-run"

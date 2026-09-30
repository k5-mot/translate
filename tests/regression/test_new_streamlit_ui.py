"""Streamlit v2の入力保存、履歴、workerと公開画面を検証する。"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from streamlit.testing.v1 import AppTest
from uuid_utils import uuid7

from translate.artifact_store import describe_artifact, sha256_file, write_model
from translate.common.config import Config
from translate.models.artifacts import (
    InputFile,
    LLMCallArtifact,
    TaskName,
    TranslationRecord,
)
from translate.pipeline import InputError
from translate.pipeline.translate import translate_pdf
from translate.tasks.translation.translate import TranslationItem, TranslationResponse
from translate.ui import (
    HistoryEntry,
    WorkerRegistry,
    _delete_history_entry,
    _history_entries,
    _live_call_counts,
    _preview,
    _safe_upload_name,
    _stage_register,
    _stage_resume_uploads,
    _stage_uploads,
    _valid_artifact,
    _verified_response,
)

if TYPE_CHECKING:
    from streamlit.runtime.uploaded_file_manager import UploadedFile

    from translate.models.artifacts import ArtifactFile


class _Upload:
    """Testで必要なUploadedFileの最小公開属性を提供する。"""

    def __init__(self, name: str, value: bytes) -> None:
        """file名と本文を保持する。"""

        self.name = name
        self._value = value

    def getvalue(self) -> bytes:
        """upload本文を返す。"""

        return self._value


def _upload(name: str, value: bytes = b"value") -> UploadedFile:
    """UI helperへ渡すTest用uploadをUploadedFile型として返す。"""

    return cast("UploadedFile", _Upload(name, value))


def _record(
    processing_id: str, source: Path, updated_at: datetime
) -> TranslationRecord:
    """履歴test用の最小TranslationRecordを作る。"""

    return TranslationRecord(
        translation_id=processing_id,
        status="processing",
        source=InputFile(
            role="source",
            logical_path=source.name,
            sha256=sha256_file(source),
            size_bytes=source.stat().st_size,
        ),
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_upload_name_rejects_paths_and_unsupported_extensions() -> None:
    """upload名を安全な対応basenameに限定する。"""

    assert _safe_upload_name("manual.PDF", {".pdf"}) == "manual.PDF"
    with pytest.raises(InputError, match="safe file basename"):
        _safe_upload_name("../manual.pdf", {".pdf"})
    with pytest.raises(InputError, match="not supported"):
        _safe_upload_name("manual.exe", {".pdf"})


def test_stage_uploads_publishes_complete_directory(tmp_path: Path) -> None:
    """upload群を確定directoryへ全件まとめて公開する。"""

    processing_id = str(uuid7())
    staged = _stage_uploads(
        processing_id,
        [
            (_upload("source.pdf", b"source"), Path("review/source/source.pdf")),
            (
                _upload("translation.pdf", b"translation"),
                Path("review/translation/translation.pdf"),
            ),
        ],
        work_root=tmp_path,
    )

    assert [path.read_bytes() for path in staged] == [b"source", b"translation"]
    assert all(path.is_relative_to(tmp_path / processing_id) for path in staged)
    assert not list(tmp_path.glob(".*.tmp"))


def test_stage_register_rejects_duplicate_basenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registerの論理pathが衝突する同名basenameを拒否する。"""

    monkeypatch.chdir(tmp_path)
    with pytest.raises(InputError, match="duplicate basenames"):
        _stage_register(
            [_upload("same.pdf", b"one"), _upload("same.pdf", b"two")],
            str(uuid7()),
        )


def test_resume_reupload_requires_saved_name_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI処理の再uploadは保存済みbasenameとhash一致時だけ保存する。"""

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"original")
    processing_id = str(uuid7())
    record = _record(processing_id, source, datetime.now(UTC)).model_copy(
        update={"status": "failed"}
    )
    entry = HistoryEntry(
        kind="translate",
        record_path=tmp_path / "outputs/manual" / processing_id / "translation.json",
        updated_at=record.updated_at,
        record=record,
    )

    paths = _stage_resume_uploads(entry, [_upload("manual.pdf", b"original")])

    assert paths[0].read_bytes() == b"original"


def test_worker_registry_rejects_duplicate_active_id() -> None:
    """未完了の同じ処理IDをworkerへ二重登録しない。"""

    gate = Event()
    registry = WorkerRegistry()

    def wait_for_gate() -> None:
        """testが解放するまでworkerを実行中に保つ。"""

        gate.wait(timeout=5)

    try:
        assert registry.submit("processing-id", wait_for_gate)
        assert not registry.submit("processing-id", wait_for_gate)
    finally:
        gate.set()


def test_delete_history_removes_only_selected_outputs_and_saved_inputs(
    tmp_path: Path,
) -> None:
    """終了済み履歴の処理directoryと同じIDの保存入力だけを削除する。"""

    processing_id = str(uuid7())
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    record = _record(processing_id, source, datetime.now(UTC)).model_copy(
        update={"status": "failed"}
    )
    processing_directory = tmp_path / "outputs/source" / processing_id
    record_path = processing_directory / "translation.json"
    write_model(record_path, record)
    staged = tmp_path / ".translate-ui" / processing_id
    staged.mkdir(parents=True)
    (staged / "source.pdf").write_bytes(b"pdf")
    untouched = tmp_path / "outputs/source/untouched"
    untouched.mkdir(parents=True)
    entry = HistoryEntry(
        kind="translate",
        record_path=record_path,
        updated_at=record.updated_at,
        record=record,
    )

    _delete_history_entry(
        entry,
        WorkerRegistry(),
        outputs_root=tmp_path / "outputs",
        work_root=tmp_path / ".translate-ui",
    )

    assert not processing_directory.exists()
    assert not staged.exists()
    assert untouched.is_dir()


def test_streamlit_delete_button_requires_confirmation_and_removes_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """画面の確認欄を選んだ後だけ選択中の終了済み履歴を削除する。"""

    monkeypatch.chdir(tmp_path)
    processing_id = str(uuid7())
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    record = _record(processing_id, source, datetime.now(UTC)).model_copy(
        update={"status": "failed"}
    )
    processing_directory = tmp_path / "outputs/source" / processing_id
    write_model(processing_directory / "translation.json", record)
    staged = tmp_path / ".translate-ui" / processing_id
    staged.mkdir(parents=True)
    (staged / "source.pdf").write_bytes(b"pdf")
    app = AppTest.from_file(str(Path(__file__).parents[2] / "main.py"))
    app.query_params["processing"] = processing_id

    app.run(timeout=10)

    delete = next(
        button for button in app.button if button.key == f"delete-{processing_id}"
    )
    assert delete.disabled
    confirmation = next(
        checkbox
        for checkbox in app.checkbox
        if checkbox.key == f"confirm-delete-{processing_id}"
    )
    confirmation.check().run(timeout=10)
    next(
        button for button in app.button if button.key == f"delete-{processing_id}"
    ).click().run(timeout=10)

    assert not processing_directory.exists()
    assert not staged.exists()


def test_live_call_counts_reads_in_progress_artifacts(tmp_path: Path) -> None:
    """Task完了前もCall Artifactから観測数と状態を表示できる。"""

    calls = tmp_path / "translation/translate/calls"
    now = datetime.now(UTC)
    for index, status in enumerate(("succeeded", "processing", "failed"), 1):
        write_model(
            calls / f"call-{index}" / "call.json",
            LLMCallArtifact(
                call_id=f"call-{index}",
                task="TRANSLATE",
                status=status,
                fingerprint="fingerprint",
                target_ids=[f"span-{index}"],
                attempts=1,
                started_at=now,
                updated_at=now,
            ),
        )

    assert _live_call_counts(tmp_path, TaskName.TRANSLATE) == (3, 1, 1)


def test_comparison_text_is_bounded_and_requires_verified_response(
    tmp_path: Path,
) -> None:
    """比較textを240文字に省略し、hash一致する確定応答だけを表示対象にする。"""

    assert len(_preview("A" * 300)) == 240
    directory = tmp_path / "translation/translate/calls/call-1"
    response = TranslationResponse(
        translations=[TranslationItem(span_id="span-1", text="確定訳")]
    )
    write_model(directory / "response.json", response)
    now = datetime.now(UTC)
    call = LLMCallArtifact(
        call_id="call-1",
        task="TRANSLATE",
        status="succeeded",
        fingerprint="fingerprint",
        target_ids=["span-1"],
        attempts=1,
        response_sha256=sha256_file(directory / "response.json"),
        started_at=now,
        updated_at=now,
    )

    assert _verified_response(tmp_path, TaskName.TRANSLATE, call) == response
    rejected = call.model_copy(update={"response_sha256": "0" * 64})
    assert _verified_response(tmp_path, TaskName.TRANSLATE, rejected) is None


def test_streamlit_default_theme_is_light() -> None:
    """初回表示の既定テーマをrepository設定でライトに固定する。"""

    config = Path(__file__).parents[2] / ".streamlit/config.toml"
    assert 'base = "light"' in config.read_text(encoding="utf-8")


def test_history_is_sorted_limited_and_keeps_invalid_records(tmp_path: Path) -> None:
    """最新100件と読込不可記録をoutputsから列挙する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    start = datetime.now(UTC)
    for index in range(101):
        processing_id = str(uuid7())
        record = _record(processing_id, source, start + timedelta(seconds=index))
        write_model(tmp_path / "source" / processing_id / "translation.json", record)
    invalid = tmp_path / "broken" / str(uuid7()) / "review.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{", encoding="utf-8")
    newest = (start + timedelta(seconds=200)).timestamp()
    os.utime(invalid, (newest, newest))

    entries = _history_entries(tmp_path)

    assert len(entries) == 100
    assert entries == sorted(entries, key=lambda item: item.updated_at, reverse=True)
    assert any(entry.error is not None for entry in entries)


def test_artifact_validation_rejects_changed_file(tmp_path: Path) -> None:
    """download対象のsizeまたはhashが変われば公開しない。"""

    path = tmp_path / "result.md"
    path.write_text("valid", encoding="utf-8")
    artifact: ArtifactFile = describe_artifact(tmp_path, path)

    assert _valid_artifact(tmp_path, artifact) == path
    path.write_text("changed", encoding="utf-8")
    assert _valid_artifact(tmp_path, artifact) is None


def test_processing_id_does_not_overwrite_existing_record(tmp_path: Path) -> None:
    """UI新規IDで既存のTranslationRecordを開かず拒否する。"""

    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    processing_id = str(uuid7())
    record_path = tmp_path / "outputs" / "source" / processing_id / "translation.json"
    write_model(record_path, _record(processing_id, source, datetime.now(UTC)))
    config = Config(
        docling_server_url="http://docling",
        openai_base_url="http://llm/v1",
        openai_structure_model="structure",
        openai_translation_model="translate",
        openai_review_model="review",
    )

    with pytest.raises(InputError, match="already exists"):
        translate_pdf(
            source,
            config,
            processing_id=processing_id,
            outputs=tmp_path / "outputs",
        )


@pytest.mark.browser
def test_streamlit_v2_renders_four_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Streamlit画面が4操作と必須入力前のdisabled buttonを表示する。"""

    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "main.py")).run(timeout=10)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Translate",
        "Review",
        "Upgrade",
        "Register",
    ]
    buttons = {button.label: button for button in app.button}
    assert buttons["翻訳を開始"].disabled
    assert buttons["レビューを開始"].disabled
    assert buttons["登録を開始"].disabled
    assert buttons["Upgradeを開始"].disabled
    assert not app.sidebar.get("status")
    assert app.sidebar.subheader[0].value == "処理履歴"
    settings = next(
        expander for expander in app.get("status") if expander.label == "入力と設定"
    )
    assert settings.label == "入力と設定"
    assert settings.proto.expanded

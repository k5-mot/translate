"""Streamlit widgetへ進捗と比較値が描画されることを検証する。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from translate.artifact_store import sha256_file, write_model
from translate.models.artifacts import (
    InputFile,
    LLMCallArtifact,
    TaskName,
    TaskState,
    TranslationRecord,
)
from translate.models.document import Block, Document, Page, TextSpan, TextUnit
from translate.tasks.translation.translate import TranslationItem, TranslationResponse


def _assert_progress_layout(app: AppTest, processing_id: str) -> None:
    """進捗領域、詳細Collapseおよびsidebar履歴の配置を検証する。"""

    settings = next(
        expander for expander in app.get("status") if expander.label == "入力と設定"
    )
    assert settings.label == "入力と設定"
    assert not settings.proto.expanded
    progress = next(
        status for status in app.get("status") if status.label == "進捗と処理内容"
    )
    assert progress.proto.expanded
    assert app.sidebar.subheader[0].value == "処理履歴"
    assert any(
        button.key == f"history-{processing_id}" for button in app.sidebar.button
    )
    detail = next(
        expander for expander in app.get("status") if expander.label == "進捗詳細"
    )
    assert not detail.proto.expanded
    details = {markdown.value for markdown in app.markdown}
    assert any(value.startswith("更新時刻: ") for value in details)
    assert any(value.startswith("REVIEW: ") for value in details)
    progress_text = app.get("progress")[0].proto.text
    assert all(value in progress_text for value in ("Task", "REVIEW", "processing"))


def test_streamlit_renders_progress_and_verified_translation_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """選択中TranslateのProgressBarと同一Callの左右TextAreaを表示する。"""

    monkeypatch.chdir(tmp_path)
    processing_id = "0199bde8-a610-7c89-8000-000000000001"
    root = tmp_path / "outputs/source" / processing_id
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    document = Document(
        pages=[
            Page(
                number=1,
                blocks=[
                    Block(
                        id="block-1",
                        order=0,
                        kind="paragraph",
                        content=TextUnit(
                            id="unit-1",
                            spans=[TextSpan(id="span-1", source="English")],
                        ),
                    )
                ],
            )
        ]
    )
    write_model(root / "preprocess/structure/document.json", document)
    call_dir = root / "translation/translate/calls/call-1"
    now = datetime.now(UTC)
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="TRANSLATE",
            status="processing",
            fingerprint="translate",
            target_ids=["span-1"],
            attempts=1,
            started_at=now,
            updated_at=now,
        ),
    )
    write_model(
        root / "translation.json",
        TranslationRecord(
            translation_id=processing_id,
            status="processing",
            source=InputFile(
                role="source",
                logical_path=source.name,
                sha256=sha256_file(source),
                size_bytes=source.stat().st_size,
            ),
            tasks=[
                TaskState(
                    task=TaskName.SPLIT,
                    status="succeeded",
                    fingerprint="split",
                    started_at=now,
                    completed_at=now,
                ),
                TaskState(
                    task=TaskName.REVIEW,
                    status="processing",
                    fingerprint="review",
                    started_at=now,
                ),
            ],
            created_at=now,
            updated_at=now,
        ),
    )
    app = AppTest.from_file(str(Path(__file__).parents[2] / "main.py"))
    app.query_params["processing"] = processing_id
    app.run(timeout=10)

    assert not app.exception
    text_areas = {area.label: area for area in app.text_area}
    assert text_areas["翻訳後 (日本語)"].value == "処理中 (確定結果なし)"

    write_model(
        call_dir / "response.json",
        TranslationResponse(
            translations=[TranslationItem(span_id="span-1", text="日本語")]
        ),
    )
    write_model(
        call_dir / "call.json",
        LLMCallArtifact(
            call_id="call-1",
            task="TRANSLATE",
            status="partial",
            fingerprint="translate",
            target_ids=["span-1"],
            attempts=1,
            response_sha256=sha256_file(call_dir / "response.json"),
            started_at=now,
            updated_at=now + timedelta(seconds=1),
        ),
    )
    write_model(
        root / "translation/translate/calls/call-2/call.json",
        LLMCallArtifact(
            call_id="call-2",
            task="TRANSLATE",
            status="processing",
            fingerprint="translate-next",
            target_ids=["span-1"],
            attempts=1,
            started_at=now + timedelta(seconds=2),
            updated_at=now + timedelta(seconds=2),
        ),
    )
    app.run(timeout=10)

    assert not app.exception
    _assert_progress_layout(app, processing_id)
    text_areas = {area.label: area for area in app.text_area}
    assert text_areas["翻訳前 (英語)"].value == "[span-1]\nEnglish"
    assert text_areas["翻訳後 (日本語)"].value == "[span-1]\n日本語"
    assert text_areas["翻訳前 (英語)"].disabled
    assert text_areas["翻訳後 (日本語)"].disabled

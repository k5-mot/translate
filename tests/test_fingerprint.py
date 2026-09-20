"""Resume fingerprintの対象と除外項目を検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from translate.common.fingerprint import (
    Fingerprint,
    build_fingerprint,
    check_resume_compatibility,
    diff_snapshots,
)
from translate.common.runs import RunRepository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Backend, Settings


def _fingerprint(
    settings: Settings,
    tmp_path: Path,
    *,
    backend: Backend = "llm",
) -> Fingerprint:
    rule = tmp_path / "translation-rules.md"
    template = tmp_path / "template.docx"
    glossary = tmp_path / "glossary.csv"
    rule.write_text("rule", encoding="utf-8")
    template.write_bytes(b"template")
    glossary.write_text("term,訳", encoding="utf-8")
    return build_fingerprint(
        operation="translate",
        backend=backend,
        input_hashes={"source": "input-sha256"},
        settings=settings,
        rule_paths={"translation": rule},
        glossary_path=glossary,
        template_path=template,
    )


def test_fingerprint_is_canonical_and_tracks_output_settings(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """同じ値は安定し、ModelやRuleの変更は差として検出する。"""

    settings = settings_factory(translation_model="model-a")
    first = _fingerprint(settings, tmp_path)
    second = _fingerprint(settings, tmp_path)
    changed = _fingerprint(
        settings.model_copy(update={"translation_model": "model-b"}), tmp_path
    )

    assert first == second
    assert first.value != changed.value
    differences = diff_snapshots(first.snapshot, changed.snapshot)
    assert [item.path for item in differences] == ["models.translation"]


def test_credentials_retry_observation_and_qdrant_are_excluded(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """運用値と可変Qdrant状態だけの変更ではResume gateを変えない。"""

    settings = settings_factory(
        openai_api_key="old-secret",
        qdrant_url="https://qdrant-a.invalid",
        qdrant_api_key="old-qdrant-secret",
        qdrant_collection="collection-a",
        langfuse_public_key="public-a",
        retry_attempts=3,
        request_timeout_seconds=30,
    )
    changed_settings = settings.model_copy(
        update={
            "openai_api_key": "new-secret",
            "qdrant_url": "https://qdrant-b.invalid",
            "qdrant_api_key": "new-qdrant-secret",
            "qdrant_collection": "collection-b",
            "langfuse_public_key": "public-b",
            "retry_attempts": 9,
            "request_timeout_seconds": 600,
        }
    )

    before = _fingerprint(settings, tmp_path)
    after = _fingerprint(changed_settings, tmp_path)

    assert before == after
    assert not diff_snapshots(before.snapshot, after.snapshot)
    serialized = str(before.snapshot)
    assert "secret" not in serialized
    assert "qdrant" not in serialized


def test_libretranslate_endpoint_only_affects_libre_backend(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """LibreTranslate固有設定は選択時だけ出力互換性へ影響する。"""

    first = settings_factory(libretranslate_url="https://libre-a.invalid")
    second = first.model_copy(update={"libretranslate_url": "https://libre-b.invalid"})

    assert _fingerprint(first, tmp_path).value == _fingerprint(second, tmp_path).value
    assert (
        _fingerprint(first, tmp_path, backend="libretranslate").value
        != _fingerprint(second, tmp_path, backend="libretranslate").value
    )


def test_resume_accepts_equal_fingerprint_and_qdrant_change(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """Qdrant接続だけが変わっても互換RunをResumeできる。"""

    settings = settings_factory(qdrant_collection="old")
    saved_fingerprint = _fingerprint(settings, tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    saved = RunRepository(tmp_path / "runs").create(
        "translate",
        {"source": source},
        saved_fingerprint.snapshot,
        saved_fingerprint.value,
    )
    current = _fingerprint(
        settings.model_copy(update={"qdrant_collection": "new"}), tmp_path
    )

    compatibility = check_resume_compatibility(saved, current)

    assert compatibility.compatible
    assert not compatibility.reasons


def test_resume_rejects_changed_settings_with_itemized_reason(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """出力影響設定が異なるRunを項目名付きで拒否する。"""

    saved_fingerprint = _fingerprint(
        settings_factory(translation_model="model-a"), tmp_path
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    saved = RunRepository(tmp_path / "runs").create(
        "translate",
        {"source": source},
        saved_fingerprint.snapshot,
        saved_fingerprint.value,
    )
    current = _fingerprint(
        settings_factory(
            translation_model="model-b",
            split_pages=20,
            docling_ocr_lang="jpn",
            context_tokens=8_000,
        ),
        tmp_path,
    )

    compatibility = check_resume_compatibility(saved, current)

    assert not compatibility.compatible
    assert {item.path for item in compatibility.differences} == {
        "docling.ocr_lang",
        "models.translation",
        "split_pages",
        "tokens.context",
    }
    assert any("models.translation" in reason for reason in compatibility.reasons)

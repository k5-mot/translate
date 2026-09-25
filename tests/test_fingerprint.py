"""Resume fingerprintの対象と除外項目を検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from translate.common.fingerprint import (
    Fingerprint,
    build_fingerprint,
    check_resume_compatibility,
    diff_snapshots,
)
from translate.common.runs import RunRepository
from translate.common.settings import load_settings, read_rules
from translate.tasks import structure
from translate.workflows import translation

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
    """
    規則・用語集・Templateを固定し、設定とbackendの差だけを比較できるfingerprintを作る。
    """

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
    """同じ入力でhashが安定し、翻訳Modelだけの変更を項目名付きで検出する。"""

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


@pytest.mark.parametrize("mode", ["task-default", "off"])
def test_rule_change_separates_public_fingerprint_and_workflow_thread(
    settings_factory: Callable[..., Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """配布ルールの変更で公開Resumeを拒否し、Workflowも異なるthreadを選ぶことを確認する。"""

    templates = tmp_path / "templates"
    templates.mkdir()
    shipped = load_settings("convert", env={})
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text(
            read_rules(shipped, name), encoding="utf-8"
        )
    settings = settings_factory(templates_dir=templates, reasoning_mode=mode)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    rule = templates / "translation-rules.md"

    def current() -> Fingerprint:
        """ルールを上書きせず、既存APIで現在の公開fingerprintを取得する。"""

        return build_fingerprint(
            operation="translate",
            backend="llm",
            input_hashes={"source": "synthetic"},
            settings=settings,
            rule_paths={"translation": rule},
        )

    def stop_before_external_call(*_args: object, **_kwargs: object) -> None:
        """Graphの初回Taskを停止し、外部通信なしで保存済みWorkflow識別を検査する。"""

        msg = "test stops at SPLIT"
        raise RuntimeError(msg)

    monkeypatch.setattr(translation.split, "run", stop_before_external_call)
    before = current()
    repository = RunRepository(tmp_path / "runs")
    saved = repository.create(
        "translate", {"source": source}, before.snapshot, before.value
    )
    metadata_path = repository.paths(saved.run_id).metadata
    original_metadata = metadata_path.read_bytes()
    with pytest.raises(RuntimeError, match="test stops at SPLIT"):
        translation.run(source, tmp_path / "before", "llm", settings)
    rule.write_text(
        rule.read_text(encoding="utf-8") + "\n追加の翻訳指示。\n", encoding="utf-8"
    )
    after = current()
    with pytest.raises(RuntimeError, match="test stops at SPLIT"):
        translation.run(source, tmp_path / "after", "llm", settings)
    assert before.value != after.value
    assert not check_resume_compatibility(saved, after).compatible
    assert metadata_path.read_bytes() == original_metadata
    metadata = [
        json.loads((tmp_path / name / ".workspace/workflow.json").read_text())
        for name in ("before", "after")
    ]
    assert metadata[0]["translation_rules"] != metadata[1]["translation_rules"]
    assert metadata[0]["thread_id"] != metadata[1]["thread_id"]


def test_credentials_retry_observation_and_qdrant_are_excluded(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """指定したCredential・retry・観測・Qdrant接続設定を変えてもfingerprintは同じ。"""

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


def test_validated_service_durations_do_not_change_fingerprint(tmp_path: Path) -> None:
    """実loaderで検証した秒数だけの変更は入力・出力影響設定の互換性を変えない。"""

    original = load_settings("convert", env={})
    changed = load_settings(
        "convert",
        env={
            "TRANSLATE_RETRY_BASE_SECONDS": "0.25",
            "TRANSLATE_RETRY_MAX_SECONDS": "4",
            "TRANSLATE_REQUEST_TIMEOUT_SECONDS": "3600",
            "TRANSLATE_TASK_DEADLINE_SECONDS": "43200",
        },
    )

    assert _fingerprint(original, tmp_path) == _fingerprint(changed, tmp_path)


def test_structure_generation_policy_stays_out_of_public_run_fingerprint(
    settings_factory: Callable[..., Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STRUCTUREの生成policy定数を変えても公開Runのfingerprintは変わらない。"""

    settings = settings_factory(structure_model="model-a")
    before = _fingerprint(settings, tmp_path)
    monkeypatch.setattr(
        structure, "STRUCTURE_REASONING_EFFORT", "changed", raising=False
    )
    monkeypatch.setattr(structure, "STRUCTURE_SCHEMA_MODE", "changed", raising=False)
    monkeypatch.setattr(
        structure, "STRUCTURE_THINKING_POLICY", "changed", raising=False
    )

    after = _fingerprint(settings, tmp_path)

    assert before == after


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


@pytest.mark.parametrize("mode", ["task-default", "off"])
def test_resume_accepts_equal_fingerprint_and_qdrant_change(
    settings_factory: Callable[..., Settings], tmp_path: Path, mode: str
) -> None:
    """QdrantのCollectionだけを変更したRunは互換性判定を通る。再実行は行わない。"""

    settings = settings_factory(qdrant_collection="old", reasoning_mode=mode)
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


def test_reasoning_policy_changes_only_the_explicit_off_fingerprint(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """旧通常snapshotを維持し、OFFだけが一つの項目差として現れる。"""

    default = _fingerprint(settings_factory(), tmp_path)
    explicit = _fingerprint(settings_factory(reasoning_mode="task-default"), tmp_path)
    off = _fingerprint(settings_factory(reasoning_mode="off"), tmp_path)
    assert default == explicit
    assert "llm_reasoning_mode" not in default.snapshot
    assert off.snapshot == {**default.snapshot, "llm_reasoning_mode": "off"}
    assert off.value != default.value
    assert [item.path for item in diff_snapshots(default.snapshot, off.snapshot)] == [
        "llm_reasoning_mode"
    ]


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
            context_tokens=20_500,
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


def test_token_default_change_rejects_old_run_without_mutating_it(
    settings_factory: Callable[..., Settings], tmp_path: Path
) -> None:
    """旧token予算Runを拒否し、新設定は別のUUIDv7 Runにする。"""

    old = settings_factory(
        context_tokens=16_384,
        output_tokens=4_096,
        image_tokens=2_048,
    )
    current = settings_factory()
    old_fingerprint = _fingerprint(old, tmp_path)
    current_fingerprint = _fingerprint(current, tmp_path)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    repository = RunRepository(tmp_path / "runs")
    saved = repository.create(
        "translate",
        {"source": source},
        old_fingerprint.snapshot,
        old_fingerprint.value,
    )
    old_metadata = repository.paths(saved.run_id).metadata.read_bytes()

    compatibility = check_resume_compatibility(saved, current_fingerprint)
    created = repository.create(
        "translate",
        {"source": source},
        current_fingerprint.snapshot,
        current_fingerprint.value,
    )

    assert not compatibility.compatible
    assert {item.path for item in compatibility.differences} == {
        "tokens.context",
        "tokens.output",
    }
    assert created.run_id != saved.run_id
    assert UUID(created.run_id).version == 7
    assert repository.paths(saved.run_id).metadata.read_bytes() == old_metadata

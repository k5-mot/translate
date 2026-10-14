"""比較Pipelineの一覧公開、失敗記録、入力照合と再開境界を検証する。"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from uuid_utils import uuid7

from translate.adapters.artifact_store import load_model, write_model
from translate.common.config import Config
from translate.models.artifacts import ReviewRecord, ReviewResult
from translate.models.document import Document
from translate.models.upgrade import UpgradePlan, UpgradeRecord
from translate.pipeline import InputError, review, upgrade


@pytest.mark.parametrize("kind", ["review", "upgrade"])
def test_comparison_pipeline_publishes_json_and_reuses_success(  # noqa: PLR0915 — 失敗から再開までの一連の境界。
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """失敗後は保存済みIDから再開し、成功後は設定変更でもAgentを再実行しない。"""
    module = review if kind == "review" else upgrade
    roles = (
        ("source", "translation")
        if kind == "review"
        else ("source_v1", "source_v2", "translation_v1")
    )
    paths = []
    for role in roles:
        path = tmp_path / f"{role}.pdf"
        path.write_bytes(b"PDF input boundary fixture")
        paths.append(path)
    config = Config(
        docling_server_url="http://docling",
        openai_base_url="http://llm",
        openai_review_model="review",
        qdrant_uri=None,
        qdrant_collection=None,
        openai_embedding_model=None,
    )
    documents = {role: Document() for role in roles}
    prepare = Mock(return_value=(documents, {}))
    monkeypatch.setattr(module, "prepare_documents", prepare)
    identifier = str(uuid7())
    root = tmp_path / "outputs"
    entry = module.review_pdfs if kind == "review" else module.upgrade_pdfs
    model = ReviewRecord if kind == "review" else UpgradeRecord
    representative = paths[-1] if kind == "review" else paths[1]
    directory = root / representative.stem / identifier
    record_path = directory / f"{kind}.json"
    fail = Mock(side_effect=RuntimeError("comparison unavailable"))
    monkeypatch.setattr(module, "run_agent", fail)
    with pytest.raises(RuntimeError, match="comparison unavailable"):
        entry(*paths, config, processing_id=identifier, outputs=root)
    failed = load_model(record_path, model)
    assert failed.status == "failed"
    assert failed.outputs == []

    def complete(_documents: object, destination: Path, *_args: object) -> None:
        """実際の保存境界へAgentの最終JSONだけを出力する。"""
        result = ReviewResult() if kind == "review" else UpgradePlan()
        write_model(
            destination / ("review.json" if kind == "review" else "plan.json"), result
        )

    agent = Mock(side_effect=complete)
    monkeypatch.setattr(module, "run_agent", agent)
    entry(*paths, config, resume_id=identifier, outputs=root)
    succeeded = load_model(record_path, model)
    assert succeeded.status == "succeeded"
    assert len(succeeded.outputs) == 1
    assert succeeded.outputs[0].relative_path.endswith(".json")
    assert (directory / "app.log").is_file()
    assert not list(directory.rglob("*.docx"))
    entry(
        *paths,
        config.model_copy(update={"openai_review_model": "changed"}),
        resume_id=identifier,
        outputs=root,
    )
    assert agent.call_count == 1
    paths[0].write_bytes(b"changed input")
    with pytest.raises(InputError, match="inputs differ"):
        entry(*paths, config, resume_id=identifier, outputs=root)
    assert agent.call_count == 1

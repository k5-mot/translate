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
    monkeypatch.setattr(module.PipelineRun, "prepare_documents", prepare)
    identifier = str(uuid7())
    root = tmp_path / "outputs"
    pipeline_type = (
        module.ReviewPipeline if kind == "review" else module.UpgradePipeline
    )
    pipeline = pipeline_type(config, outputs=root)
    model = ReviewRecord if kind == "review" else UpgradeRecord
    representative = paths[-1] if kind == "review" else paths[1]
    directory = root / representative.stem / identifier
    record_path = directory / f"state-{kind}.json"
    agent_type = module.ReviewAgent if kind == "review" else module.UpgradeAgent
    fail = Mock(side_effect=RuntimeError("comparison unavailable"))
    monkeypatch.setattr(agent_type, "run", fail)
    with pytest.raises(RuntimeError, match="comparison unavailable"):
        pipeline.run(*paths, processing_id=identifier)
    failed = load_model(record_path, model)
    assert failed.status == "failed"
    assert failed.outputs == []

    def complete(instance: review.ReviewAgent | upgrade.UpgradeAgent) -> None:
        """実際の保存境界へAgentの最終JSONだけを出力する。"""
        result = ReviewResult() if kind == "review" else UpgradePlan()
        write_model(
            instance.directory / ("review.json" if kind == "review" else "plan.json"),
            result,
        )

    monkeypatch.setattr(agent_type, "run", complete)
    pipeline.run(*paths, resume_id=identifier)
    succeeded = load_model(record_path, model)
    assert succeeded.status == "succeeded"
    assert len(succeeded.outputs) == 1
    assert succeeded.outputs[0].relative_path.endswith(".json")
    assert (directory / ("review.log" if kind == "review" else "upgrade.log")).is_file()
    assert not list(directory.rglob("*.docx"))
    monkeypatch.setattr(
        agent_type,
        "run",
        Mock(side_effect=AssertionError("completed Agent must be reused")),
    )
    pipeline_type(
        config.model_copy(update={"openai_review_model": "changed"}), outputs=root
    ).run(*paths, resume_id=identifier)
    assert len(succeeded.outputs) == 1
    paths[0].write_bytes(b"changed input")
    with pytest.raises(InputError, match="inputs differ"):
        pipeline.run(*paths, resume_id=identifier)
    assert len(succeeded.outputs) == 1

"""子processへ送る実行要求とPipelineの呼出境界を検証する。"""

import pickle
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from translate import ui
from translate.common.config import Config


@pytest.mark.parametrize("resuming", [False, True])
@pytest.mark.parametrize(
    ("kind", "pipeline_name", "count"),
    [
        ("translate", "TranslatePipeline", 1),
        ("review", "ReviewPipeline", 2),
        ("register", "RegisterPipeline", 2),
        ("upgrade", "UpgradePipeline", 3),
    ],
)
def test_pipeline_job_dispatches_serializable_request(
    monkeypatch: pytest.MonkeyPatch,
    kind: ui.ProcessingKind,
    pipeline_name: str,
    count: int,
    *,
    resuming: bool,
) -> None:
    """新規・再開の入力とIDを、直列化後も正しいPipelineへ渡す。"""
    config = Config()
    settings = MagicMock(return_value=config)
    pipeline = MagicMock()
    monkeypatch.setattr(ui, "load_config", settings)
    monkeypatch.setattr(ui, pipeline_name, pipeline)
    paths = tuple(Path(f"input-{index}.pdf") for index in range(count))
    job = ui.PipelineJob(kind, paths, "processing-id", "reference", resuming)
    # 信頼済みのテスト内で生成した値だけを、spawnと同じpickle境界へ通す。
    restored = pickle.loads(pickle.dumps(job))  # noqa: S301
    result = restored()
    settings.assert_called_once_with()
    pipeline.assert_called_once_with(config)
    options = {"resume_id" if resuming else "processing_id": "processing-id"}
    if kind == "register":
        pipeline.return_value.run.assert_called_once_with(
            list(paths), source_id="reference", **options
        )
    else:
        pipeline.return_value.run.assert_called_once_with(*paths, **options)
    assert result is pipeline.return_value.run.return_value

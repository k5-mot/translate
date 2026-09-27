"""VALIDATEのwarning通過とError停止を検証する。"""

from __future__ import annotations

import json
import socket
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from translate.adapters.checkpoint import open_checkpoint
from translate.common.lifecycle import (
    PublicRunError,
    execute_public_run,
    format_failure,
    load_failure,
    prepare_run,
)
from translate.common.runs import RunRepository
from translate.common.workspace import (
    atomic_write_bytes,
    atomic_write_json,
    sha256_file,
)
from translate.document import Block, Document, Inline, Page, TableCell
from translate.tasks import load, validate
from translate.workflows import translation

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig

    from translate.common.settings import Settings


def _document_with_unit(
    target: str,
    source: list[Inline],
    layers: tuple[list[Inline] | None, list[Inline] | None],
) -> tuple[Document, str]:
    """対象以外を空にした実Documentを作り、既存の翻訳層と行列IDを検査する。"""

    translated, final = layers
    block = Block(id="unit", order=0, kind="paragraph")
    target_id = block.id
    if target == "body":
        block.source, block.translated, block.final = source, translated, final
    elif target in {"figure-caption", "table-caption"}:
        block.kind = "figure" if target == "figure-caption" else "table"
        block.asset_path = "figure.png"
        block.cells = [TableCell(row=0, column=0)]
        block.caption = source
        block.translated_caption, block.final_caption = translated, final
        target_id += "/caption"
    else:
        assert target == "cell"
        block.kind = "table"
        block.cells = [
            TableCell(
                row=0,
                column=0,
                rowspan=2,
                colspan=2,
                source=source,
                translated=translated,
                final=final,
            )
        ]
        target_id += "/cell/0/0"
    return Document(pages=[Page(number=2, blocks=[block])]), target_id


@pytest.mark.parametrize("target", ["body", "figure-caption", "table-caption", "cell"])
@pytest.mark.parametrize(
    "layers",
    [
        (None, None),
        ([], None),
        ([Inline(id="empty", text="")], None),
        ([Inline(id="space", text=" \t\n\u3000")], None),
        ([Inline(id="break", kind="line_break", text="not rendered")], None),
        ([Inline(id="initial", text="valid initial")], []),
        ([Inline(id="initial", text="valid initial")], [Inline(id="empty", text="")]),
        (
            [Inline(id="initial", text="valid initial")],
            [Inline(id="space", text=" \t\n")],
        ),
        (
            [Inline(id="initial", text="valid initial")],
            [Inline(id="break", kind="line_break")],
        ),
    ],
)
def test_output_translation_is_required_for_every_text_unit(
    tmp_path: Path,
    target: str,
    layers: tuple[list[Inline] | None, list[Inline] | None],
) -> None:
    """空の出力訳を原文や初回訳で隠さず、本文・Caption・結合セルを同じ境界で拒否する。"""

    document, target_id = _document_with_unit(
        target, [Inline(id="source", text="PRIVATE-SOURCE")], layers
    )
    (tmp_path / "figure.png").write_bytes(b"asset fixture")
    report = tmp_path / "report.json"
    with pytest.raises(ValueError, match="missing translation") as caught:
        validate.run(document, tmp_path, report)
    assert target_id in str(caught.value)
    assert "PRIVATE-SOURCE" not in str(caught.value)
    assert not report.exists()


@pytest.mark.parametrize("target", ["body", "figure-caption", "table-caption", "cell"])
@pytest.mark.parametrize(
    "source",
    [
        [],
        [Inline(id="empty")],
        [Inline(id="space", text=" \t\n\u3000")],
        [Inline(id="break", kind="line_break")],
    ],
)
def test_empty_source_does_not_require_translation(
    tmp_path: Path, target: str, source: list[Inline]
) -> None:
    """空原文や空白・改行だけのセル等へ、存在しない訳文を強制しない。"""

    document, _target_id = _document_with_unit(target, source, (None, None))
    (tmp_path / "figure.png").write_bytes(b"asset fixture")
    report = tmp_path / "report.json"
    validate.run(document, tmp_path, report)
    assert json.loads(report.read_text(encoding="utf-8"))["valid"] is True


@pytest.mark.parametrize("target", ["body", "figure-caption", "table-caption", "cell"])
@pytest.mark.parametrize(
    "layers",
    [
        (None, [Inline(id="final", text="42")]),
        ([Inline(id="initial", text="42")], None),
        ([], [Inline(id="final", text="42")]),
    ],
)
def test_nonempty_selected_translation_is_accepted(
    tmp_path: Path,
    target: str,
    layers: tuple[list[Inline] | None, list[Inline] | None],
) -> None:
    """非空の採用訳は原文同一・日本語なしでも許可し、空の初回訳より最終訳を優先する。"""

    document, _target_id = _document_with_unit(
        target, [Inline(id="source", text="42")], layers
    )
    (tmp_path / "figure.png").write_bytes(b"asset fixture")
    validate.run(document, tmp_path, tmp_path / "report.json")


@pytest.mark.parametrize("target", ["body", "figure-caption", "table-caption", "cell"])
def test_cover_text_units_are_excluded_from_translation_requirement(
    tmp_path: Path, target: str
) -> None:
    """本文を出力しない表紙の各単位は、訳文未作成でもVALIDATEを通過する。"""

    document, _target_id = _document_with_unit(
        target, [Inline(id="source", text="cover")], (None, None)
    )
    document.pages[0].number = 1
    (tmp_path / "figure.png").write_bytes(b"asset fixture")
    validate.run(document, tmp_path, tmp_path / "report.json")


@pytest.mark.parametrize("target", ["body", "figure-caption", "table-caption", "cell"])
@pytest.mark.parametrize("existing_report", [False, True])
def test_validate_public_failure_preserves_outputs_and_resumes(  # noqa: C901, PLR0915
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    target: str,
    *,
    existing_report: bool,
) -> None:
    """合成前段の実Graphで欠落停止・秘密非保存・別SQLite接続からの再開を検査する。"""

    markers = (
        "VALIDATE-SOURCE-MARKER",
        "VALIDATE-TARGET-MARKER",
        "VALIDATE-KEY-MARKER",
    )
    calls: Counter[str] = Counter()

    def deny_network(*_args: object, **_kwargs: object) -> None:
        """この合成検証から外部Model・観測先へ接続しないことを強制する。"""

        pytest.fail("network is forbidden in VALIDATE test")

    def stop_at_split(*_args: object, **_kwargs: object) -> None:
        """製品によるthread初期化後に止め、前段Artifactを合成するfixture境界を作る。"""

        calls["split"] += 1
        msg = "fixture initialization"
        raise ValueError(msg)

    def synthetic_cover(_source: Path, output: Path) -> Path:
        """PDFの代わりに合成画像を保存し、再開時の前段再実行を計数する。"""

        calls["cover"] += 1
        atomic_write_bytes(output, b"cover fixture")
        atomic_write_json(
            output.parent / "manifest.json",
            {"image": output.name, "excluded_pages": [1]},
        )
        return output

    real_validate, real_markdown = validate.run, translation.markdown.run

    def counted_validate(document: Document, assets: Path, output: Path) -> Document:
        """判定を置換せず実VALIDATEへ渡し、失敗と再開で各1回だけ呼ばれるか数える。"""

        calls["validate"] += 1
        return real_validate(document, assets, output)

    def counted_markdown(
        document: Document, output: Path, cover: Path, assets: Path
    ) -> Path:
        """実Markdown生成へ委譲し、VALIDATE失敗時に到達しないことを数える。"""

        calls["markdown"] += 1
        return real_markdown(document, output, cover, assets)

    def synthetic_docx(_source: Path, output: Path, _template: Path) -> Path:
        """変換起動の位置だけを観測し、既存成果物を成功時にだけ置き換える。"""

        calls["docx"] += 1
        atomic_write_bytes(output, b"completed fixture")
        return output

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(translation.split, "run", stop_at_split)
    monkeypatch.setattr(translation.cover, "run", synthetic_cover)
    monkeypatch.setattr(validate, "run", counted_validate)
    monkeypatch.setattr(translation.markdown, "run", counted_markdown)
    monkeypatch.setattr(translation.docx, "run", synthetic_docx)
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("structure", "translation", "review"):
        (templates / f"{name}-rules.md").write_text("rules", encoding="utf-8")
    (templates / "glossary.csv").write_text("english,japanese\n", encoding="utf-8")
    (templates / "template.docx").write_bytes(b"unused template")
    settings = settings_factory(
        templates_dir=templates,
        runs_dir=tmp_path / "runs",
        openai_api_key=markers[2],
        reasoning_mode="off",
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic input")
    repository = RunRepository(settings.runs_dir)
    prepared = prepare_run(repository, "translate", {"source": source}, settings)
    paths = prepared.paths
    with pytest.raises(ValueError, match="fixture initialization"):
        translation.run(
            prepared.inputs["source"],
            paths.outputs,
            "llm",
            settings,
            workspace_dir=paths.workspace,
        )
    metadata = json.loads(
        (paths.workspace / "workflow.json").read_text(encoding="utf-8")
    )
    config: RunnableConfig = {
        "configurable": {"thread_id": metadata["thread_id"]},
        "max_concurrency": 1,
    }
    document, _target_id = _document_with_unit(
        target, [Inline(id="source", text=markers[0])], (None, None)
    )
    document.pages[0].blocks.append(
        Block(
            id="neighbor",
            order=1,
            kind="paragraph",
            source=[Inline(id="neighbor/source", text=markers[2])],
            translated=[Inline(id="neighbor/translated", text=markers[1])],
        )
    )
    artifact = paths.workspace / "verify" / "document.json"
    atomic_write_json(artifact, document.model_dump(mode="json"))
    reviews = paths.workspace / "review" / "findings.json"
    atomic_write_json(reviews, {})
    atomic_write_bytes(paths.workspace / "merge" / "figure.png", b"figure fixture")
    database = paths.workspace / "checkpoints.sqlite"
    # 前段全体の成功を偽装せず、このTestの開始位置だけを公式APIで合成する。
    with open_checkpoint(database) as saver:
        graph = translation.build_graph(settings).compile(checkpointer=saver)
        graph.update_state(
            config,
            {"document_path": str(artifact), "reviews_path": str(reviews)},
            as_node="verify",
        )
        assert graph.get_state(config).next == ("cover",)
    report = paths.workspace / "validate" / "report.json"
    output = paths.outputs / "document.ja.docx"
    atomic_write_bytes(output, b"existing output")
    before_output = sha256_file(output)
    if existing_report:
        atomic_write_json(report, {"valid": True, "fixture": "existing"})
    before_report = report.read_bytes() if report.exists() else None
    with pytest.raises(PublicRunError) as caught:
        execute_public_run(repository, prepared, settings)
    assert caught.value.failure.task == "VALIDATE"
    assert calls == {"split": 1, "cover": 1, "validate": 1}
    assert sha256_file(output) == before_output
    assert (report.read_bytes() if report.exists() else None) == before_report
    assert not (paths.workspace / "validate" / "document.json").exists()
    assert not (paths.workspace / "markdown").exists()
    failure = load_failure(repository, prepared.record.run_id)
    assert failure is not None
    assert failure.task == "VALIDATE"
    with open_checkpoint(database) as saver:
        graph = translation.build_graph(settings).compile(checkpointer=saver)
        snapshot = graph.get_state(config)
        saved = saver.get_tuple(config)
        assert saved is not None
        assert snapshot.next == ("validate",)
        assert snapshot.tasks[0].error == "TaskError"
        assert any(
            channel == "__error__" for _, channel, _ in saved.pending_writes or []
        )
        persisted = repr((saved, snapshot)).encode()
    # 文書Artifactは本文保持が責務なので、診断とCheckpointだけを漏えい検査する。
    persisted += format_failure(failure).encode() + str(caught.value).encode()
    persisted += (paths.workspace / "failure.json").read_bytes()
    persisted += (paths.root / "run.json").read_bytes()
    persisted += b"".join(
        path.read_bytes() for path in paths.workspace.glob("checkpoints.sqlite*")
    )
    persisted += b"".join(
        path.read_bytes() for path in (paths.workspace / "logs").glob("*.log")
    )
    for marker in markers:
        assert marker.encode() not in persisted

    # 所有fixtureだけに正常訳を与え、製品へ自動修復機構を追加せず再開境界を調べる。
    fixed, _target_id = _document_with_unit(
        target,
        [Inline(id="source", text=markers[0])],
        ([Inline(id="translated", text="valid translation")], None),
    )
    fixed.pages[0].blocks.append(document.pages[0].blocks[1])
    atomic_write_json(artifact, fixed.model_dump(mode="json"))
    resumed = prepare_run(
        repository,
        "translate",
        {"source": source},
        settings,
        resume_id=prepared.record.run_id,
    )
    record, outputs = execute_public_run(repository, resumed, settings)
    assert record.status == "completed"
    assert outputs == (output,)
    assert calls == {"split": 1, "cover": 1, "validate": 2, "markdown": 1, "docx": 1}
    assert output.read_bytes() == b"completed fixture"
    assert json.loads(report.read_text(encoding="utf-8"))["valid"] is True
    assert load_failure(repository, prepared.record.run_id) is None
    with open_checkpoint(database) as saver:
        graph = translation.build_graph(settings).compile(checkpointer=saver)
        assert graph.get_state(config).next == ()


def test_skipped_fix_is_preserved_as_warning(tmp_path: Path) -> None:
    """FIX/VERIFY skippedを成果物へ残しつつVALIDATEを通す。"""

    translated = Inline(
        id="block/translated",
        text="訳文",
        fix_status="skipped",
        fix_error="service unavailable",
    )
    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="block",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="block/source", text="source")],
                        translated=[translated],
                        final=[translated.model_copy(deep=True)],
                    )
                ],
            )
        ]
    )
    output = tmp_path / "report.json"

    assert validate.run(document, tmp_path, output) == document
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["valid"] is True
    assert report["warnings"] == [
        {
            "kind": "fix-skipped",
            "target_id": "block/translated",
            "message": "service unavailable",
        }
    ]


def test_missing_translation_stops_without_publishing_report(tmp_path: Path) -> None:
    """本文訳欠落をErrorとして停止しvalid reportを公開しない。"""

    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="missing",
                        order=0,
                        kind="paragraph",
                        source=[Inline(id="source", text="source")],
                    )
                ],
            )
        ]
    )
    output = tmp_path / "report.json"

    with pytest.raises(ValueError, match="missing translation"):
        validate.run(document, tmp_path, output)

    assert not output.exists()


def test_picture_asset_path_matches_merged_assets_root() -> None:
    """Doclingのstructured URIをMERGE後のassets rootへ正規化する。"""

    block = load._block(  # noqa: SLF001
        {},
        {
            "self_ref": "#/pictures/1",
            "label": "picture",
            "image": {"uri": "artifacts/part-0001/image.png"},
        },
        0,
    )

    assert block is not None
    assert block.asset_path == "assets/part-0001/image.png"


def test_validate_migrates_legacy_structured_asset_path(tmp_path: Path) -> None:
    """旧structured接頭辞の画像pathを、実在するassets配下のpathへ書き換える。"""

    asset = tmp_path / "assets" / "figure.png"
    asset.parent.mkdir()
    asset.write_bytes(b"png")
    document = Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id="figure",
                        order=0,
                        kind="figure",
                        asset_path="structured/assets/figure.png",
                    )
                ],
            )
        ]
    )

    output = tmp_path / "report.json"
    result = validate.run(document, tmp_path, output)

    assert result.pages[0].blocks[0].asset_path == "assets/figure.png"

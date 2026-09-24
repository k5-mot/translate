"""比較Review Capabilityの独立入力、Finding集計および0件Reportを検証する。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from markdown_it import MarkdownIt
from typer.testing import CliRunner

import cli
import main
from translate.common.lifecycle import export_run
from translate.common.runs import RunRepository
from translate.common.workspace import sha256_file
from translate.document import AlignmentGroup, Block, Document, Finding, Inline, Page
from translate.tasks import align, check, report, review
from translate.workflows.comparison_review import _comparison_document

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from translate.common.settings import Settings


def _document(block_id: str, text: str) -> Document:
    """指定した原文を一つのBlockに持つ文書を作り、独立英日入力の比較条件を固定する。"""

    return Document(
        pages=[
            Page(
                number=2,
                blocks=[
                    Block(
                        id=block_id,
                        order=0,
                        kind="paragraph",
                        source=[Inline(id=f"{block_id}/text", text=text)],
                    )
                ],
            )
        ]
    )


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["clean", "findings"])
def test_comparison_capability_reports_findings_or_explicit_zero_without_mutation(
    scenario: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
) -> None:
    """合成した英日Documentから指摘あり/なしのReportを作る。PDF解析は行わない。"""

    source_pdf = tmp_path / "independent-en.pdf"
    target_pdf = tmp_path / "independent-ja.pdf"
    source_pdf.write_bytes(b"independent source PDF fixture")
    target_pdf.write_bytes(b"independent target PDF fixture")
    before = (sha256_file(source_pdf), sha256_file(target_pdf))
    has_findings = scenario == "findings"
    source = _document("source/1", "Version 2 supports 10 MB.")
    target_number = "5" if has_findings else "10"
    target = _document("target/1", f"バージョン2は{target_number} MBを扱います。")
    settings = settings_factory(review_model="review")

    groups = align.run(source, target, tmp_path / "align")
    comparison = _comparison_document(source, target, groups)
    checks = check.run(comparison, None, tmp_path / "check")
    review_finding = Finding(
        kind="fluency",
        severity="warning",
        target_ids=["alignment/0"],
        message="日本語表現を確認してください",
        evidence="fixture evidence",
        suggestion="修正方針",
    )
    monkeypatch.setattr(
        review,
        "structured",
        lambda *_args, **_kwargs: review.ReviewResponse(
            findings=[review_finding] if has_findings else []
        ),
    )
    reviews = review.run(
        comparison,
        checks,
        "review rules",
        [],
        settings,
        tmp_path / "review",
    )
    output = tmp_path / "comparison.md"
    report.run(
        groups,
        [item for values in checks.values() for item in values],
        [item for values in reviews.values() for item in values],
        output,
        tmp_path / "report",
    )

    rendered = output.read_text(encoding="utf-8")
    stored = json.loads(
        (tmp_path / "report" / "review.json").read_text(encoding="utf-8")
    )
    if has_findings:
        assert stored["counts"] == {"error/number-unit": 1, "warning/fluency": 1}
        assert "error / number-unit" in rendered
        assert "warning / fluency" in rendered
        for finding in stored["findings"]:
            for target_id in finding["target_ids"]:
                assert target_id in rendered
            for field in ("message", "evidence", "suggestion"):
                if finding[field]:
                    assert finding[field] in rendered
    else:
        assert stored["counts"] == {}
        assert rendered.count("指摘なし") == 2
    assert (sha256_file(source_pdf), sha256_file(target_pdf)) == before


@pytest.mark.parametrize("origin", ["check", "review"])
def test_report_public_details_preserve_all_fields(tmp_path: Path, origin: str) -> None:
    """CHECK/REVIEWどちらのFindingも内部JSONだけでなく公開Markdownへ保持する。"""

    finding = Finding(
        kind="accuracy",
        severity="error",
        target_ids=["alignment/0", "unknown/target"],
        message="問題の説明",
        evidence="根拠の原文",
        suggestion="修正すべき内容",
    )
    groups = [AlignmentGroup(source_ids=["source"], target_ids=["target"])]
    output = tmp_path / "review.md"
    report.run(
        groups,
        [finding] if origin == "check" else [],
        [finding] if origin == "review" else [],
        output,
        tmp_path / "report",
    )

    rendered = output.read_text(encoding="utf-8")
    for value in (
        *finding.target_ids,
        finding.message,
        finding.evidence,
        finding.suggestion,
    ):
        assert value in rendered
    stored = json.loads((tmp_path / "report/review.json").read_text(encoding="utf-8"))
    assert stored == {
        "counts": {"error/accuracy": 1},
        "alignment": [group.model_dump() for group in groups],
        "findings": [finding.model_dump()],
    }


@pytest.mark.parametrize("value", [None, "", "  ", "根拠\n\n次の行\n"])
def test_report_optional_values_and_unassigned_targets(
    tmp_path: Path, value: str | None
) -> None:
    """未記載と空文字を区別し、空白や改行を消さず対象未指定を表示する。"""

    finding = Finding(kind="accuracy", message="説明", evidence=value, suggestion=value)
    output = tmp_path / "report.md"
    report.run([], [finding], [], output, tmp_path / "report")
    rendered = output.read_text(encoding="utf-8")

    assert "対象未指定" in rendered
    if value is None:
        assert rendered.count("未記載") == 2
    elif value == "":
        assert rendered.count("空文字") == 2
    else:
        tokens = MarkdownIt().parse(rendered)
        assert (
            sum(
                token.type == "fence" and token.content == value + "\n"
                for token in tokens
            )
            == 2
        )
    stored = json.loads((tmp_path / "report/review.json").read_text(encoding="utf-8"))
    assert stored["findings"] == [finding.model_dump()]


def test_report_alignment_labels_preserve_group_shapes_and_finding_order(
    tmp_path: Path,
) -> None:
    """多対多・片側未対応とcaption/cellのIDを既存alignment番号で追跡できる。"""

    groups = [
        AlignmentGroup(source_ids=["s/caption", "s/cell/0/0"], target_ids=["t1", "t2"]),
        AlignmentGroup(source_ids=["only-source"], kind="source_only"),
        AlignmentGroup(target_ids=["only-target"], kind="target_only"),
    ]
    checks = [Finding(kind="number-unit", message="first", target_ids=["alignment/0"])]
    reviews = [
        Finding(
            kind="fluency",
            message="second",
            target_ids=[
                "alignment/1",
                "alignment/2",
                "alignment/01",
                "alignment/0/target",
            ],
        )
    ]
    output = tmp_path / "report.md"
    report.run(groups, checks, reviews, output, tmp_path / "report")
    rendered = output.read_text(encoding="utf-8")

    for index, group in enumerate(groups):
        section = rendered.split(f"### alignment/{index}\n", 1)[1].split("\n##", 1)[0]
        assert group.kind in section
        for identifier in [*group.source_ids, *group.target_ids]:
            assert identifier in section
    assert rendered.count("対応情報なし") == 2
    assert rendered.index("first") < rendered.index("second")
    stored = json.loads((tmp_path / "report/review.json").read_text(encoding="utf-8"))
    assert stored["alignment"] == [group.model_dump() for group in groups]
    assert stored["findings"] == [item.model_dump() for item in [*checks, *reviews]]
    assert stored["counts"] == {"warning/number-unit": 1, "warning/fluency": 1}


@pytest.mark.parametrize(
    "payload",
    [
        "<img src=x onerror=alert(1)>",
        "&copy; &#60;script&#62;",
        "# injected\n\n[link](https://example.invalid)\n![image](x)",
        "before\n```\n````````\n<script>alert(1)</script>\nafter",
        "line1\r\n\r\nline2\r\n",
        "` `\t **日本語** ",
    ],
)
def test_report_free_text_remains_literal(tmp_path: Path, payload: str) -> None:
    """全自由文字列を構文にせず、parser上も内容と改行を保持する。"""

    finding = Finding(
        kind=payload,
        message=payload,
        evidence=payload,
        suggestion=payload,
        target_ids=[payload],
    )
    groups = [AlignmentGroup(source_ids=[payload], target_ids=[payload])]
    output = tmp_path / "report.md"
    report.run(groups, [finding], [], output, tmp_path / "report")
    tokens = MarkdownIt("commonmark", {"html": True}).parse(
        output.read_text(encoding="utf-8")
    )
    all_tokens = [
        child for token in tokens for child in [token, *(token.children or [])]
    ]
    assert not any(
        token.type in {"html_block", "html_inline", "link_open", "image"}
        for token in all_tokens
    )
    normalized = payload.replace("\r\n", "\n") + "\n"
    contents = [token.content for token in tokens if token.type == "fence"]
    assert contents.count(normalized) == 6
    assert f"warning / {normalized}" in contents
    assert f"warning/{normalized[:-1]}: 1\n" in contents
    stored = json.loads((tmp_path / "report/review.json").read_text(encoding="utf-8"))
    assert stored["findings"] == [finding.model_dump()]


@pytest.mark.parametrize("has_findings", [False, True])
def test_real_report_bytes_reach_cli_ui_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: Callable[..., Settings],
    *,
    has_findings: bool,
) -> None:
    """実REPORTの成果物を公開入口で渡し、DL/exportのbytesと入力不変を確認する。"""

    settings = settings_factory(runs_dir=tmp_path / "runs")
    settings.templates_dir.mkdir()
    (settings.templates_dir / "review-rules.md").write_text("rules", encoding="utf-8")
    (settings.templates_dir / "glossary.csv").write_text(
        "english-short,japanese-short\n", encoding="utf-8"
    )
    source, target = tmp_path / "source.pdf", tmp_path / "target.pdf"
    source.write_bytes(b"source fixture; no parsing")
    target.write_bytes(b"target fixture; no parsing")
    before = (sha256_file(source), sha256_file(target))
    finding = Finding(
        kind="accuracy",
        message="公開検査",
        target_ids=["alignment/0"],
        evidence="公開根拠",
        suggestion="公開修正方針",
    )

    def finish_review(
        _source: Path, _target: Path, output: Path, *_args: object
    ) -> Path:
        """外部解析/モデルを置換し、REPORT自体は製品実装を実行する。"""

        return report.run(
            [AlignmentGroup(source_ids=["source"], target_ids=["target"])],
            [],
            [finding] if has_findings else [],
            output,
            tmp_path / "diagnostic",
        )

    monkeypatch.setattr("translate.common.lifecycle.run_review", finish_review)
    monkeypatch.setattr(cli, "load_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    request = Mock(side_effect=AssertionError("External HTTP must not be used"))
    monkeypatch.setattr("httpx.Client.send", request)
    output = tmp_path / "public.md"
    result = CliRunner().invoke(
        cli.app,
        [
            "review",
            str(source),
            str(target),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    repository = RunRepository(settings.runs_dir)
    record = repository.list_runs().records[0]
    internal = repository.paths(record.run_id).outputs / "review.md"
    expected = internal.read_bytes()
    assert output.read_bytes() == expected
    exported = export_run(repository, record.run_id, tmp_path / "export")
    assert len(exported) == 1
    assert exported[0].read_bytes() == expected
    download = Mock()
    monkeypatch.setattr(main.st, "download_button", download)
    main._downloads((internal,), "review")  # noqa: SLF001
    download.assert_called_once_with(
        "review.md をダウンロード",
        expected,
        file_name="review.md",
        key="review-download-0",
    )
    if has_findings:
        assert all(
            value.encode() in expected
            for value in [
                "alignment/0",
                "公開検査",
                "公開根拠",
                "公開修正方針",
            ]
        )
    else:
        assert expected.decode().count("指摘なし") == 2
    assert (sha256_file(source), sha256_file(target)) == before
    request.assert_not_called()

"""照合候補の検索と再開用Embeddingの信頼境界を検証する。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from translate.adapters.embedding import EmbeddingClient, EmbeddingError
from translate.common.config import Config
from translate.models.document import TextSpan, TextUnit
from translate.pipeline.matching import (
    MatchingCandidates,
    _row_label,
    _row_numbers,
    _section_distance,
    _table_value,
)


@pytest.fixture
def config() -> Config:
    """外部へ接続しない候補検索の設定を作る。"""
    return Config(
        openai_base_url="http://127.0.0.1:1/v1",
        openai_embedding_model="fixture-model",
        openai_api_key=None,
        openai_llm_api_key=None,
        qdrant_api_key=None,
        docling_api_key=None,
    )


def candidates(tmp_path: Path, config: Config) -> MatchingCandidates:
    """誤った候補と、二つの文書で分割の異なる対応候補を作る。"""
    texts = {
        "source": {"first": "old first", "continuation": "old rest"},
        "translation": {
            "wrong": "unrelated",
            "correct": "new first",
            "rest": "new rest",
            "used": "confirmed",
        },
    }
    units = {
        role: {
            key: TextUnit(id=key, spans=[TextSpan(id=f"{key}/span", source=text)])
            for key, text in values.items()
        }
        for role, values in texts.items()
    }
    contexts = {
        role: {
            key: {"kind": "caption" if key == "wrong" else "paragraph"}
            for key in values
        }
        for role, values in texts.items()
    }
    return MatchingCandidates(
        units,
        contexts,
        tmp_path,
        config.model_copy(update={"openai_embedding_model": "fixture-model"}),
    )


def test_matching_searches_outside_the_selected_pool_and_keeps_fragments(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候補外の正しい相手と隣接断片を発見し、確定済みIDを再利用しない。"""
    vectors = {
        "old first": [1.0, 0.0],
        "old rest": [0.8, 0.2],
        "new first": [1.0, 0.0],
        "new rest": [0.8, 0.2],
        "unrelated": [0.0, 1.0],
    }
    embed = MagicMock(side_effect=lambda texts: [vectors[text] for text in texts])
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = candidates(tmp_path, config)
    available = {
        "source": {"first", "continuation"},
        "translation": {"wrong", "correct", "rest"},
    }
    actual = index.expand({"source": ["first"], "translation": ["wrong"]}, available, 4)
    assert actual == {
        "source": ["first", "continuation"],
        "translation": ["correct", "rest"],
    }
    assert sum(map(len, actual.values())) == 4
    assert "confirmed" not in embed.call_args.args[0]
    # 同じモデルの再開では本文のEmbeddingを再計算しない。
    assert (
        candidates(tmp_path, config).expand({"source": ["first"]}, available, 4)
        == actual
    )
    embed.assert_called_once()


def test_matching_prefers_a_nearby_heading_when_semantic_title_is_missing(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """先頭見出しの訳がLOADから欠落しても遠い関連見出しへ誤対応しない。"""
    units = {
        "source": {
            "title": TextUnit(
                id="title", spans=[TextSpan(id="title/span", source="Joint Planning")]
            )
        },
        "translation": {
            "near": TextUnit(
                id="near", spans=[TextSpan(id="near/span", source="合同計画")]
            ),
            "far": TextUnit(
                id="far",
                spans=[
                    TextSpan(
                        id="far/span",
                        source="32 Joint Strategic Planning System",
                    )
                ],
            ),
        },
    }
    contexts = {
        "source": {"title": {"kind": "heading", "position": "0.0"}},
        "translation": {
            "near": {"kind": "heading", "position": "0.02"},
            "far": {"kind": "heading", "position": "0.70"},
        },
    }
    vectors = {
        "Joint Planning": [1.0, 0.0],
        "合同計画": [0.8, 0.6],
        "Joint Strategic Planning System": [0.99, 0.1],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )

    actual = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["title"]},
        {"source": {"title"}, "translation": {"near", "far"}},
        2,
    )

    assert actual["translation"] == ["near"]


def test_matching_leaves_a_weak_distant_cover_heading_unmatched(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """弱い遠方候補は表紙見出しへ結び付けず、原文を未対応に残す。"""
    units = {
        "source": {
            "title": TextUnit(
                id="title", spans=[TextSpan(id="title/span", source="Joint Planning")]
            )
        },
        "translation": {
            "far": TextUnit(
                id="far",
                spans=[
                    TextSpan(
                        id="far/span",
                        source="7.1.5 Planning Process",
                    )
                ],
            )
        },
    }
    contexts = {
        "source": {"title": {"kind": "heading", "position": "0.0"}},
        "translation": {
            "far": {
                "kind": "heading",
                "position": "0.048",
                "section": "7.1.5 Planning Process",
            }
        },
    }
    vectors = {
        "Joint Planning": [1.0, 0.0],
        "Planning Process": [0.705, (1 - 0.705**2) ** 0.5],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )

    actual = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["title"]},
        {"source": {"title"}, "translation": {"far"}},
        2,
    )

    assert actual == {"source": ["title"], "translation": []}


def test_matching_does_not_move_an_exact_cover_title_to_another_heading(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ表紙見出しがある場合は、遠い本文見出しより一致見出しを優先する。"""
    units = {
        "source": {
            "title": TextUnit(
                id="title", spans=[TextSpan(id="title/span", source="Joint Planning")]
            )
        },
        "translation": {
            "cover": TextUnit(
                id="cover", spans=[TextSpan(id="cover/span", source="Joint Planning")]
            ),
            "far": TextUnit(
                id="far",
                spans=[
                    TextSpan(
                        id="far/span",
                        source="32 Joint Strategic Planning System",
                    )
                ],
            ),
        },
    }
    contexts = {
        "source": {"title": {"kind": "heading", "position": "0.0"}},
        "translation": {
            "cover": {"kind": "heading", "position": "0.0"},
            "far": {"kind": "heading", "position": "0.7"},
        },
    }
    vectors = {
        "Joint Planning": [1.0, 0.0],
        "Joint Strategic Planning System": [0.99, 0.1],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )

    actual = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["title"]},
        {"source": {"title"}, "translation": {"cover", "far"}},
        2,
    )

    assert actual["translation"] == ["cover"]


def test_matching_finds_a_cross_kind_counterpart_inside_a_merged_unit(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """異なるDocling種別に統合された長い訳unitをspan対応で再順位付けする。"""
    units = {
        "source": {
            "query": TextUnit(
                id="query",
                spans=[
                    TextSpan(id="q1", source="source sentence one"),
                    TextSpan(id="q2", source="source sentence two"),
                ],
            )
        },
        "translation": {
            "wrong": TextUnit(
                id="wrong",
                spans=[
                    TextSpan(id="w1", source="unrelated one"),
                    TextSpan(id="w2", source="unrelated two"),
                ],
            ),
            "merged": TextUnit(
                id="merged",
                spans=[
                    TextSpan(id=f"m{i}", source=f"merged span {i}") for i in range(8)
                ],
            ),
        },
    }
    contexts = {
        "source": {"query": {"kind": "list_item"}},
        "translation": {
            "wrong": {"kind": "list_item"},
            "merged": {"kind": "paragraph"},
        },
    }
    vectors = {
        "source sentence onesource sentence two": [1.0, 0.0],
        "unrelated oneunrelated two": [0.95, 0.312],
        "".join(f"merged span {i}" for i in range(8)): [0.8, 0.6],
        "source sentence one": [1.0, 0.0],
        "source sentence two": [1.0, 0.0],
        "unrelated one": [0.0, 1.0],
        "unrelated two": [0.0, 1.0],
        **{f"merged span {i}": [1.0, 0.0] for i in range(8)},
    }
    monkeypatch.setattr(
        MatchingCandidates,
        "_embed",
        lambda _self, texts: {text: vectors[text] for text in texts},
    )

    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["query"]},
        {"source": {"query"}, "translation": {"wrong", "merged"}},
        2,
    )

    assert selected == {"source": ["query"], "translation": ["merged"]}


def test_matching_uses_neighboring_units_to_find_a_merged_counterpart(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """単一spanの原文でも隣接unitの意味から結合訳unitを選ぶ。"""
    query = "A long source paragraph describing the naval C4I strategy."
    neighbor = "A neighboring paragraph describing the NCTC network."
    merged_spans = [
        TextSpan(id="merged/1", source="Naval C4I strategy translation."),
        TextSpan(id="merged/2", source="NCTC network translation."),
        *[
            TextSpan(id=f"merged/{index}", source=f"unrelated detail {index}.")
            for index in range(3, 7)
        ],
    ]
    merged_text = "".join(span.text("source") for span in merged_spans)
    units = {
        "source": {
            "query": TextUnit(id="query", spans=[TextSpan(id="q", source=query)]),
            "neighbor": TextUnit(
                id="neighbor", spans=[TextSpan(id="n", source=neighbor)]
            ),
        },
        "translation": {
            "wrong": TextUnit(
                id="wrong",
                spans=[TextSpan(id="w", source="A top-ranked unrelated translation.")],
            ),
            "merged": TextUnit(id="merged", spans=merged_spans),
        },
    }
    contexts = {
        "source": {
            "query": {"kind": "paragraph", "section": "Chapter IV", "position": "0.63"},
            "neighbor": {
                "kind": "paragraph",
                "section": "Chapter IV",
                "position": "0.63",
            },
        },
        "translation": {
            "wrong": {"kind": "paragraph", "position": "0.63"},
            "merged": {"kind": "paragraph", "position": "0.55"},
        },
    }
    vectors = {
        query: [1.0, 0.0],
        neighbor: [0.0, 1.0],
        "A top-ranked unrelated translation.": [0.62, 0.785],
        merged_text: [0.4, 0.916],
        "Naval C4I strategy translation.": [1.0, 0.0],
        "NCTC network translation.": [0.0, 1.0],
        **{f"unrelated detail {index}.": [0.5, 0.5] for index in range(3, 7)},
    }
    monkeypatch.setattr(
        MatchingCandidates,
        "_embed",
        lambda _self, texts: {text: vectors[text] for text in texts},
    )

    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["query"]},
        {role: set(values) for role, values in units.items()},
        4,
    )

    assert selected["source"] == ["query", "neighbor"]
    assert selected["translation"][0] == "merged"


def test_short_heading_keeps_nearby_heading_alternatives_not_long_paragraphs(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """短い見出しは長文内の偶然似たspanで再順位付けしない。"""
    units = {
        "source": {
            "preface": TextUnit(
                id="preface", spans=[TextSpan(id="preface/span", source="PREFACE")]
            )
        },
        "translation": {
            "correct": TextUnit(
                id="heading", spans=[TextSpan(id="heading/span", source="序文")]
            ),
            "nearby": TextUnit(
                id="nearby",
                spans=[TextSpan(id="nearby/span", source="意図的な白紙")],
            ),
            "paragraph": TextUnit(
                id="paragraph",
                spans=[
                    TextSpan(
                        id=f"paragraph/span-{index}",
                        source="偶然似たspan" if index == 0 else f"別の文章{index}",
                    )
                    for index in range(8)
                ],
            ),
        },
    }
    contexts = {
        "source": {
            "preface": {
                "kind": "heading",
                "section": "PREFACE",
                "position": "0.0056",
            }
        },
        "translation": {
            "correct": {"kind": "heading", "section": "1 序文", "position": "0.0053"},
            "nearby": {
                "kind": "heading",
                "section": "意図的な白紙",
                "position": "0.0133",
            },
            "paragraph": {
                "kind": "paragraph",
                "section": "14 計画の原則",
                "position": "0.0826",
            },
        },
    }

    def embed(_self: MatchingCandidates, texts: list[str]) -> dict[str, list[float]]:
        """長い段落の単独spanだけを似せ、文書全体の類似度は低くする。"""
        return {
            text: (
                [1.0, 0.0]
                if text == "PREFACE"
                else [0.5424, 0.84]
                if text == "序文"
                else [0.5914, 0.806]
                if text == "意図的な白紙"
                else [0.9, 0.436]
                if text == "偶然似たspan"
                else [0.386, 0.922]
                if text.startswith("偶然似たspan")
                else [0.0, 1.0]
            )
            for text in texts
        }

    monkeypatch.setattr(MatchingCandidates, "_embed", embed)
    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["preface"]},
        {
            "source": {"preface"},
            "translation": {"correct", "nearby", "paragraph"},
        },
        3,
    )

    assert selected == {"source": ["preface"], "translation": ["nearby", "correct"]}


def test_single_source_span_does_not_overrank_an_unrelated_long_unit(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """単一source spanの最大類似だけで長い別unitを優先しない。"""
    source_text = "Expands discussion on global campaigning and campaign planning."
    merged_spans = [
        TextSpan(
            id=f"merged/span-{index}",
            source="campaign mention" if index == 0 else f"unrelated detail {index}",
        )
        for index in range(8)
    ]
    units = {
        "source": {
            "source": TextUnit(
                id="source", spans=[TextSpan(id="source/span", source=source_text)]
            )
        },
        "translation": {
            "correct": TextUnit(
                id="correct",
                spans=[
                    TextSpan(
                        id="correct/span",
                        source="グローバル・キャンペーンおよび計画の議論を拡充する。",
                    )
                ],
            ),
            "merged": TextUnit(id="merged", spans=merged_spans),
        },
    }
    contexts = {
        "source": {
            "source": {
                "kind": "list_item",
                "section": "SUMMARY OF CHANGES",
                "position": "0.011",
            }
        },
        "translation": {
            "correct": {
                "kind": "list_item",
                "section": "意図的な白紙",
                "position": "0.013",
            },
            "merged": {
                "kind": "list_item",
                "section": "8.2.1.1 バランス",
                "position": "0.056",
            },
        },
    }

    def embed(_self: MatchingCandidates, texts: list[str]) -> dict[str, list[float]]:
        """誤候補の一spanだけを近づけ、unit全体は正解より遠くする。"""
        return {
            text: (
                [1.0, 0.0]
                if text == source_text
                else [0.58, 0.815]
                if text.startswith("グローバル")
                else [0.9, 0.436]
                if text == "campaign mention"
                else [0.38, 0.925]
                if text.startswith("campaign mention")
                else [0.0, 1.0]
            )
            for text in texts
        }

    monkeypatch.setattr(MatchingCandidates, "_embed", embed)
    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": ["source"]},
        {"source": {"source"}, "translation": {"correct", "merged"}},
        2,
    )

    assert selected == {"source": ["source"], "translation": ["correct"]}


def test_matching_keeps_all_fragments_of_a_numbered_list(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """番号付き段落が複数unitへ分かれた場合、候補上限を隣接断片へ使う。"""
    source_ids = ["before", "list", "after"]
    translation_ids = [f"item-{index}" for index in range(1, 8)]
    source_texts = {
        "before": "C4 systems support the commanders.",
        "list": (
            "Multinational operations: (1) liaison; (2) resources; (3) principles; "
            "(4) policy; (5) interpreters; (6) cryptographic systems."
        ),
        "after": "Employment follows the next section.",
    }
    translation_texts = {
        identifier: f"Japanese list item {index} about multinational operations."
        for index, identifier in enumerate(translation_ids, start=1)
    }
    units = {
        "source": {
            key: TextUnit(id=key, spans=[TextSpan(id=f"{key}/span", source=text)])
            for key, text in source_texts.items()
        },
        "translation": {
            key: TextUnit(id=key, spans=[TextSpan(id=f"{key}/span", source=text)])
            for key, text in translation_texts.items()
        },
    }
    contexts = {
        role: {key: {"kind": "paragraph", "section": "1 Operations"} for key in values}
        for role, values in units.items()
    }
    vectors = {
        text: [1.0, 0.0]
        for text in (*source_texts.values(), *translation_texts.values())
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, values: [vectors[text] for text in values],
    )
    index = MatchingCandidates(units, contexts, tmp_path, config)

    actual = index.expand(
        {"source": ["list"]},
        {"source": set(source_ids), "translation": set(translation_ids)},
        8,
    )

    assert actual == {"source": ["list"], "translation": translation_ids}


def test_matching_keeps_query_when_no_compatible_counterpart_exists(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """構造種別が合わない候補しかない場合、検索失敗にせず起点を残す。"""
    units = {
        "source": {
            "heading": TextUnit(
                id="heading", spans=[TextSpan(id="heading/span", source="Heading")]
            )
        },
        "translation": {
            "item": TextUnit(id="item", spans=[TextSpan(id="item/span", source="項目")])
        },
    }
    contexts = {
        "source": {"heading": {"kind": "heading"}},
        "translation": {"item": {"kind": "list_item"}},
    }
    embed = MagicMock()
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = MatchingCandidates(units, contexts, tmp_path, config)

    actual = index.expand(
        {"source": ["heading"]},
        {"source": {"heading"}, "translation": {"item"}},
        4,
    )

    assert actual == {"source": ["heading"], "translation": []}
    embed.assert_not_called()


def test_matching_does_not_add_a_neighbor_with_a_different_topic(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """近くに並んだ別主題のunitを同じLLM照合へ混ぜない。"""
    index = candidates(tmp_path, config)
    index.units["source"]["unrelated"] = TextUnit(
        id="unrelated", spans=[TextSpan(id="unrelated/span", source="clean coal")]
    )
    index.contexts["source"]["unrelated"] = {"kind": "paragraph"}
    vectors = {
        "old first": [1.0, 0.0],
        "old rest": [0.8, 0.6],
        "clean coal": [0.638, 0.77],
        "new first": [1.0, 0.0],
        "new rest": [0.0, 1.0],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )
    actual = index.expand(
        {"source": ["first"]},
        {
            "source": {"first", "continuation", "unrelated"},
            "translation": {"correct", "rest"},
        },
        8,
    )
    assert actual["source"] == ["first", "continuation"]
    assert actual["translation"] == ["correct"]


def test_matching_prefers_the_same_table_row_label(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同内容の表行が複数ある場合、OCR空白を除いた同一行ラベルを優先する。"""
    index = candidates(tmp_path, config)
    assert _row_label("Parameter_01") == _row_label("Parameter _01")
    assert _row_label("Thread Pool") != _row_label("ThreadPool")
    index.contexts = {
        "source": {"first": {"kind": "table_cell", "row_label": "Parameter_01"}},
        "translation": {
            "wrong": {"kind": "table_cell", "row_label": "Parameter_02"},
            "correct": {"kind": "table_cell", "row_label": "Parameter _01"},
        },
    }
    embed = MagicMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    actual = index.expand(
        {"source": ["first"]},
        {"source": {"first"}, "translation": {"wrong", "correct"}},
        3,
    )
    assert actual == {"source": ["first"], "translation": ["correct"]}
    assert all("Parameter_02" not in text for text in embed.call_args.args[0])


def test_table_value_removes_numeric_line_wrap_spaces() -> None:
    """狭いPDF表セルで改行された数字を元の数値へ戻す。"""
    assert _table_value("7,43 4") == "7,434"
    assert _table_value("1,79\n6") == "1,796"
    assert _table_value("12 34") == "12 34"
    assert _table_value("1,234 567") == "1,234 567"
    assert _table_value("Budget 2005") == "Budget 2005"


def test_matching_uses_translated_row_label_for_repeated_page_numbers(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ列のページ番号を、翻訳された行見出しの意味で区別する。"""
    source = "#/tables/1/cell-r0001-c0002/content"
    correct = "#/tables/3/cell-r0001-c0002/content"
    wrong = "#/tables/3/cell-r0011-c0002/content"
    units = {
        "source": {
            source: TextUnit(id=source, spans=[TextSpan(id="s", source="III-1")])
        },
        "translation": {
            correct: TextUnit(id=correct, spans=[TextSpan(id="c", source="図-1")]),
            wrong: TextUnit(id=wrong, spans=[TextSpan(id="w", source="IV-1")]),
        },
    }
    contexts = {
        "source": {source: {"kind": "table_cell", "row_label": "Planning Teams"}},
        "translation": {
            correct: {"kind": "table_cell", "row_label": "計画チーム"},
            wrong: {"kind": "table_cell", "row_label": "作戦設計の概要"},
        },
    }
    vectors = {
        "III-1\nrow_label: Planning Teams": [1.0, 0.0],
        "図-1\nrow_label: 計画チーム": [0.99, 0.1],
        "IV-1\nrow_label: 作戦設計の概要": [0.6, 0.8],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )
    index = MatchingCandidates(units, contexts, tmp_path, config)

    actual = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {correct, wrong}},
        2,
    )

    assert actual == {"source": [source], "translation": [correct]}


def test_matching_uses_column_position_within_a_matching_table_row(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ行に説明文と値があるとき、同じ列のセルを候補にする。"""
    source = "#/tables/0/cell-r0005-c0001/content"
    wrong_column = "#/tables/1/cell-r0005-c0002/content"
    correct_column = "#/tables/1/cell-r0005-c0001/content"
    index = candidates(tmp_path, config)
    index.units = {
        "source": {
            source: TextUnit(id=source, spans=[TextSpan(id="s", source="Description")])
        },
        "translation": {
            wrong_column: TextUnit(
                id=wrong_column, spans=[TextSpan(id="w", source="5")]
            ),
            correct_column: TextUnit(
                id=correct_column, spans=[TextSpan(id="c", source="説明文")]
            ),
        },
    }
    index.contexts = {
        "source": {source: {"kind": "table_cell", "row_label": "Record 05"}},
        "translation": {
            wrong_column: {"kind": "table_cell", "row_label": "Record 05"},
            correct_column: {"kind": "table_cell", "row_label": "Record 05"},
        },
    }
    embed = MagicMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(EmbeddingClient, "embed", embed)

    actual = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {wrong_column, correct_column}},
        3,
    )

    assert actual == {"source": [source], "translation": [correct_column]}
    assert all("/c0002/" not in text for text in embed.call_args.args[0])


def test_matching_embeds_only_the_structural_table_candidates(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表セルは最終順位付けに使う列だけをEmbeddingする。"""
    source = "#/tables/0/cell-r0000-c0000/content"
    correct = "#/tables/1/cell-r0000-c0000/content"
    unrelated = "#/tables/2/cell-r0000-c0001/content"
    units = {
        "source": {
            source: TextUnit(id=source, spans=[TextSpan(id="s", source="name")])
        },
        "translation": {
            correct: TextUnit(id=correct, spans=[TextSpan(id="c", source="名前")]),
            unrelated: TextUnit(
                id=unrelated,
                spans=[TextSpan(id="u", source="長い無関係な表セル" * 500)],
            ),
        },
    }
    contexts = {
        "source": {source: {"kind": "table_cell"}},
        "translation": {
            correct: {"kind": "table_cell"},
            unrelated: {"kind": "table_cell"},
        },
    }
    embed = MagicMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = MatchingCandidates(units, contexts, tmp_path, config)

    actual = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {correct, unrelated}},
        3,
    )

    assert actual == {"source": [source], "translation": [correct]}
    assert all("無関係" not in text for text in embed.call_args.args[0])


def test_matching_ignores_leading_numbers_on_heading_text(
    tmp_path: Path, config: Config
) -> None:
    """節番号は別の構造情報で扱い、翻訳語の候補検索からは除く。"""
    index = candidates(tmp_path, config)
    index.contexts["translation"]["correct"] = {"kind": "heading"}
    index.units["translation"]["correct"] = TextUnit(
        id="correct",
        spans=[TextSpan(id="correct/span", source="11 付録 A")],
    )
    assert index._text("translation", "correct") == "付録 A"  # noqa: SLF001


def test_matching_uses_numbered_sections_to_break_close_embedding_ties() -> None:
    """近い類似度なら離れた節より近い節の候補を優先する。"""
    assert _section_distance("5 Discussion", "3 考察") == 2
    assert _section_distance("5 Discussion", "1 Introduction") == 4
    assert _section_distance("Discussion", "3 考察") is None


def test_matching_uses_section_proximity_to_select_a_close_translation_candidate(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedding順位が僅差なら原文に近い節番号の翻訳unitを選ぶ。"""
    index = candidates(tmp_path, config)
    index.contexts["source"]["first"] = {
        "kind": "paragraph",
        "section": "5 Discussion",
    }
    index.contexts["translation"]["wrong"] = {
        "kind": "caption",
        "section": "1 Introduction",
    }
    index.contexts["translation"]["correct"] = {
        "kind": "caption",
        "section": "3 考察",
    }
    index.units["translation"]["abstract"] = TextUnit(
        id="abstract", spans=[TextSpan(id="abstract/span", source="similar abstract")]
    )
    index.contexts["translation"]["abstract"] = {
        "kind": "caption",
        "section": "Abstract",
    }
    vectors = {
        "old first": [1.0, 0.0],
        "unrelated": [0.811, 0.585],
        "new first": [0.792, 0.611],
        "similar abstract": [0.8, 0.6],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )
    actual = index.expand(
        {"source": ["first"]},
        {"source": {"first"}, "translation": {"wrong", "correct", "abstract"}},
        4,
    )
    assert actual["translation"] == ["correct"]


def test_matching_prefers_same_section_for_split_table_rows(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docling表分割で行番号がずれても同じ表の候補を優先する。"""
    index = candidates(tmp_path, config)
    index.contexts = {
        "source": {
            "first": {
                "kind": "table_cell",
                "row_label": "page_split_13",
                "section": "3 Table",
            }
        },
        "translation": {
            "wrong": {
                "kind": "table_cell",
                "row_label": "page_split_08",
                "section": "3 Table",
            },
            "correct": {
                "kind": "table_cell",
                "row_label": "page_split_1 3",
                "section": "3 Table",
            },
            "other": {
                "kind": "table_cell",
                "row_label": "page_split_13",
                "section": "4 Other Table",
            },
        },
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )
    actual = index.expand(
        {"source": ["first"]},
        {"source": {"first"}, "translation": {"wrong", "correct", "other"}},
        3,
    )
    assert actual == {"source": ["first"], "translation": ["correct"]}


def test_matching_uses_section_distance_to_disambiguate_conclusion_from_introduction(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """近い節の訳文を、Embedding差が大きい序論候補より優先する。"""
    index = candidates(tmp_path, config)
    index.units = {
        "source": {
            "query": TextUnit(
                id="query", spans=[TextSpan(id="q", source="conclusion result")]
            )
        },
        "translation": {
            "introduction": TextUnit(
                id="introduction",
                spans=[TextSpan(id="i", source="similar introduction")],
            ),
            "conclusion": TextUnit(
                id="conclusion",
                spans=[TextSpan(id="c", source="translated conclusion")],
            ),
        },
    }
    index.contexts = {
        "source": {"query": {"kind": "paragraph", "section": "7 Conclusion"}},
        "translation": {
            "introduction": {"kind": "paragraph", "section": "1 Introduction"},
            "conclusion": {"kind": "paragraph", "section": "5 結論"},
        },
    }
    vectors = {
        "conclusion result": [1.0, 0.0],
        "similar introduction": [0.852, 0.523],
        "translated conclusion": [0.708, 0.706],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )

    actual = index.expand(
        {"source": ["query"]},
        {"source": {"query"}, "translation": {"introduction", "conclusion"}},
        2,
    )

    assert actual == {"source": ["query"], "translation": ["conclusion"]}


def test_matching_prefers_same_section_heading_over_a_similar_unrelated_heading(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedding上位でも別節の見出しを避ける。"""
    source = "#/texts/44/content"
    correct = "#/texts/44/content"
    wrong = "#/texts/69/content"
    units = {
        "source": {
            source: TextUnit(
                id=source,
                spans=[
                    TextSpan(
                        id="source/span",
                        source=(
                            "1.1.3 Encouraging Next Generation Nuclear Power and Fusion"
                        ),
                    )
                ],
            )
        },
        "translation": {
            correct: TextUnit(
                id=correct,
                spans=[
                    TextSpan(
                        id="correct/span",
                        source="1.1.3 次世代原子力発電と核融合の推進",
                    )
                ],
            ),
            wrong: TextUnit(
                id=wrong,
                spans=[
                    TextSpan(id="wrong/span", source="1.1.8 過去の拠点の浄化の加速")
                ],
            ),
        },
    }
    contexts = {
        "source": {
            source: {
                "kind": "heading",
                "section": "1.1.3 Encouraging Next Generation Nuclear Power and Fusion",
            }
        },
        "translation": {
            correct: {
                "kind": "heading",
                "section": "1.1.3 次世代原子力発電と核融合の推進",
            },
            wrong: {"kind": "heading", "section": "1.1.8 過去の拠点の浄化の加速"},
        },
    }
    vectors = {
        "Encouraging Next Generation Nuclear Power and Fusion": [1.0, 0.0],
        "次世代原子力発電と核融合の推進": [0.8, 0.6],
        "過去の拠点の浄化の加速": [0.9, 0.436],
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [vectors[text] for text in texts],
    )
    index = MatchingCandidates(units, contexts, tmp_path, config)

    actual = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {correct, wrong}},
        2,
    )

    assert actual == {"source": [source], "translation": [correct]}


def test_matching_keeps_table_column_when_header_labels_are_not_embedded(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表見出しunitに列labelがない場合も列位置を維持する。"""
    index = candidates(tmp_path, config)
    source = "#/tables/4/cell-r0000-c0000/content"
    wrong = "#/tables/3/cell-r0000-c0001/content"
    correct = "#/tables/3/cell-r0000-c0000/content"
    index.units["source"] = {
        source: TextUnit(
            id=source, spans=[TextSpan(id="source/span", source="Parameter")]
        )
    }
    index.units["translation"] = {
        wrong: TextUnit(id=wrong, spans=[TextSpan(id="wrong/span", source="説明")]),
        correct: TextUnit(
            id=correct, spans=[TextSpan(id="correct/span", source="パラメータ")]
        ),
    }
    index.contexts = {
        "source": {source: {"kind": "table_cell", "section": "3 Table"}},
        "translation": {
            wrong: {"kind": "table_cell", "section": "3 表"},
            correct: {"kind": "table_cell", "section": "3 表"},
        },
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )
    actual = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {wrong, correct}},
        3,
    )
    assert actual == {"source": [source], "translation": [correct]}


def test_matching_uses_adjacent_rows_to_disambiguate_repeated_table_headers(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重複する分割表の見出しを次行の識別子で区別する。"""
    source = "#/tables/5/cell-r0000-c0002/content"
    wrong = "#/tables/2/cell-r0000-c0002/content"
    correct = "#/tables/4/cell-r0000-c0002/content"
    units = {
        "source": {
            source: TextUnit(
                id=source, spans=[TextSpan(id="s/span", source="Default")]
            ),
            "#/tables/5/cell-r0001-c0002/content": TextUnit(
                id="s/next", spans=[TextSpan(id="s/next/span", source="9")]
            ),
        },
        "translation": {
            wrong: TextUnit(id=wrong, spans=[TextSpan(id="w/span", source="Default")]),
            "#/tables/2/cell-r0001-c0002/content": TextUnit(
                id="w/next", spans=[TextSpan(id="w/next/span", source="system default")]
            ),
            correct: TextUnit(
                id=correct, spans=[TextSpan(id="c/span", source="Default")]
            ),
            "#/tables/4/cell-r0001-c0002/content": TextUnit(
                id="c/next", spans=[TextSpan(id="c/next/span", source="page_split_0 9")]
            ),
        },
    }
    contexts = {
        "source": {
            source: {"kind": "table_cell", "row_label": "Parameter"},
            "#/tables/5/cell-r0001-c0002/content": {
                "kind": "table_cell",
                "row_label": "page_split_09",
            },
        },
        "translation": {
            wrong: {"kind": "table_cell", "row_label": "Parameter"},
            "#/tables/2/cell-r0001-c0002/content": {
                "kind": "table_cell",
                "row_label": "configPath",
            },
            correct: {"kind": "table_cell", "row_label": "Parameter"},
            "#/tables/4/cell-r0001-c0002/content": {
                "kind": "table_cell",
                "row_label": "page_split_0 9",
            },
        },
    }
    monkeypatch.setattr(
        EmbeddingClient,
        "embed",
        lambda _self, texts: [
            [1.0, 0.0] if "page_split_09" in text else [0.8, 0.6] for text in texts
        ],
    )
    index = MatchingCandidates(units, contexts, tmp_path, config)
    selected = index.expand(
        {"source": [source]},
        {"source": {source}, "translation": {wrong, correct}},
        3,
    )
    assert selected == {"source": [source], "translation": [correct]}


def test_matching_uses_sibling_cells_to_disambiguate_table_rows(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """行見出しのない表でも同じ行の別セルを候補検索に使う。"""
    source = "#/tables/0/cell-r0007-c0000/content"
    correct = "#/tables/1/cell-r0003-c0000/content"
    wrong = "#/tables/12/cell-r0006-c0000/content"
    units = {
        "source": {
            source: TextUnit(
                id=source, spans=[TextSpan(id="s", source="Planning Products")]
            ),
            "#/tables/0/cell-r0007-c0001/content": TextUnit(
                id="s/page", spans=[TextSpan(id="s/page-span", source="1-7")]
            ),
        },
        "translation": {
            correct: TextUnit(
                id=correct, spans=[TextSpan(id="c", source="計画成果物")]
            ),
            "#/tables/1/cell-r0003-c0001/content": TextUnit(
                id="c/page", spans=[TextSpan(id="c/page-span", source="1-7")]
            ),
            wrong: TextUnit(id=wrong, spans=[TextSpan(id="w", source="計画機能")]),
            "#/tables/12/cell-r0006-c0001/content": TextUnit(
                id="w/context",
                spans=[TextSpan(id="w/context-span", source="戦略的指導")],
            ),
        },
    }
    contexts = {
        role: {key: {"kind": "table_cell"} for key in role_units}
        for role, role_units in units.items()
    }

    def embed(_self: EmbeddingClient, texts: list[str]) -> list[list[float]]:
        """同じ行にページ参照がある候補を、無関係な本文表より上位にする。"""
        return [[1.0, 0.0] if "1-7" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": [source]},
        {"source": set(units["source"]), "translation": set(units["translation"])},
        3,
    )
    assert selected["translation"] == [correct]


def test_matching_uses_matching_numeric_sibling_cells_to_select_table_row(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """異なる表に同列見出しがあっても、数値列が一致する行を優先する。"""
    source = "#/tables/2/cell-r0012-c0000/content"
    source_value = "#/tables/2/cell-r0012-c0001/content"
    correct = "#/tables/2/cell-r0012-c0000/content"
    correct_value = "#/tables/2/cell-r0012-c0001/content"
    wrong = "#/tables/3/cell-r0002-c0000/content"
    wrong_value = "#/tables/3/cell-r0002-c0001/content"
    units = {
        "source": {
            source: TextUnit(
                id=source, spans=[TextSpan(id="s", source="Total budget")]
            ),
            source_value: TextUnit(
                id=source_value, spans=[TextSpan(id="sv", source="20,025")]
            ),
        },
        "translation": {
            correct: TextUnit(id=correct, spans=[TextSpan(id="c", source="総計 予算")]),
            correct_value: TextUnit(
                id=correct_value, spans=[TextSpan(id="cv", source="20,0 25")]
            ),
            wrong: TextUnit(id=wrong, spans=[TextSpan(id="w", source="総計 支出")]),
            wrong_value: TextUnit(
                id=wrong_value, spans=[TextSpan(id="wv", source="17,7 03")]
            ),
        },
    }
    contexts = {
        role: {key: {"kind": "table_cell"} for key in values}
        for role, values in units.items()
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )

    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": [source]},
        {role: set(values) for role, values in units.items()},
        2,
    )

    assert selected["translation"] == [correct]


def test_matching_uses_page_number_sibling_to_disambiguate_toc_rows(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCRで表記の違うページ番号の数字部分を使って目次行を区別する。"""
    source = "#/tables/1/cell-r0000-c0001/content"
    source_page = "#/tables/1/cell-r0000-c0002/content"
    correct = "#/tables/3/cell-r0000-c0001/content"
    correct_page = "#/tables/3/cell-r0000-c0002/content"
    wrong = "#/tables/3/cell-r0005-c0001/content"
    wrong_page = "#/tables/3/cell-r0005-c0002/content"
    units = {
        "source": {
            source: TextUnit(
                id=source,
                spans=[TextSpan(id="s", source="Planning is Commander's Business")],
            ),
            source_page: TextUnit(
                id=source_page, spans=[TextSpan(id="sp", source="Ill-1")]
            ),
        },
        "translation": {
            correct: TextUnit(
                id=correct,
                spans=[TextSpan(id="c", source="計画は指揮官の責務である")],
            ),
            correct_page: TextUnit(
                id=correct_page, spans=[TextSpan(id="cp", source="図-1")]
            ),
            wrong: TextUnit(id=wrong, spans=[TextSpan(id="w", source="計画機能")]),
            wrong_page: TextUnit(
                id=wrong_page, spans=[TextSpan(id="wp", source="111-5")]
            ),
        },
    }
    contexts = {
        role: {key: {"kind": "table_cell"} for key in values}
        for role, values in units.items()
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )

    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": [source]},
        {role: set(values) for role, values in units.items()},
        2,
    )

    assert selected["translation"] == [correct]


def test_matching_keeps_nearby_same_page_toc_rows_for_llm_disambiguation(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じページの目次項目は近い候補を両方LLMへ渡す。"""
    source = "#/tables/1/cell-r0000-c0001/content"
    source_page = "#/tables/1/cell-r0000-c0002/content"
    correct = "#/tables/3/cell-r0000-c0001/content"
    correct_page = "#/tables/3/cell-r0000-c0002/content"
    nearby = "#/tables/3/cell-r0001-c0001/content"
    nearby_page = "#/tables/3/cell-r0001-c0002/content"
    distant = "#/tables/3/cell-r0005-c0001/content"
    distant_page = "#/tables/3/cell-r0005-c0002/content"
    units = {
        "source": {
            source: TextUnit(
                id=source,
                spans=[TextSpan(id="s", source="Planning is Commander's Business")],
            ),
            source_page: TextUnit(
                id=source_page, spans=[TextSpan(id="sp", source="Ill-1")]
            ),
        },
        "translation": {
            nearby: TextUnit(id=nearby, spans=[TextSpan(id="n", source="計画チーム")]),
            nearby_page: TextUnit(
                id=nearby_page, spans=[TextSpan(id="np", source="図-1")]
            ),
            correct: TextUnit(
                id=correct,
                spans=[TextSpan(id="c", source="計画は指揮官の責務である")],
            ),
            correct_page: TextUnit(
                id=correct_page, spans=[TextSpan(id="cp", source="図-1")]
            ),
            distant: TextUnit(id=distant, spans=[TextSpan(id="d", source="計画機能")]),
            distant_page: TextUnit(
                id=distant_page, spans=[TextSpan(id="dp", source="111-5")]
            ),
        },
    }
    contexts = {
        role: {key: {"kind": "table_cell"} for key in values}
        for role, values in units.items()
    }

    def embed(_self: EmbeddingClient, texts: list[str]) -> list[list[float]]:
        """わずかに高い誤候補と近い正候補を同じページへ置く。"""
        return [
            [1.0, 0.0]
            if "Planning is Commander's Business" in text
            else [0.999, 0.0447]
            if "計画チーム" in text
            else [0.995, 0.1]
            if "計画は指揮官の責務である" in text
            else [0.99, 0.141]
            for text in texts
        ]

    monkeypatch.setattr(EmbeddingClient, "embed", embed)

    selected = MatchingCandidates(units, contexts, tmp_path, config).expand(
        {"source": [source]},
        {role: set(values) for role, values in units.items()},
        4,
    )

    assert _row_numbers(["Ill-1"]) == _row_numbers(["図-1"])
    assert _row_numbers(["111-5"]) != _row_numbers(["図-1"])
    assert set(selected["translation"]) == {correct, nearby}


def test_matching_normalizes_ocr_spaces_inside_roman_page_references() -> None:
    """ローマ数字付きページ参照の途中で改行された数字を結合する。"""
    assert _row_numbers(["V-1 2"]) == _row_numbers(["V-12"])
    assert _row_numbers(["III-1 0"]) == _row_numbers(["III-10"])
    assert _row_numbers(["1 2"]) != _row_numbers(["12"])


def test_matching_does_not_pair_a_heading_with_an_unrelated_paragraph(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """話題の近い本文を選ぶより、同じ構造役割の見出しを優先する。"""
    index = candidates(tmp_path, config)
    index.units["translation"]["filler"] = TextUnit(
        id="filler", spans=[TextSpan(id="filler/span", source="nearby content")]
    )
    index.units["translation"] = {
        key: index.units["translation"][key]
        for key in ("correct", "rest", "used", "filler", "wrong")
    }
    index.contexts["source"]["first"] = {"kind": "heading", "section": "2 Lists"}
    index.contexts["translation"]["wrong"] = {
        "kind": "paragraph",
        "section": "2 Lists",
    }
    index.contexts["translation"]["correct"] = {
        "kind": "heading",
        "section": "2 リスト",
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )
    actual = index.expand(
        {"source": ["first"]},
        {"source": {"first"}, "translation": {"wrong", "correct", "rest"}},
        4,
    )
    assert "correct" in actual["translation"]
    assert "wrong" not in actual["translation"]


def test_matching_processes_only_one_search_origin_per_scope(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """遠い照合起点の候補を同じmatchへ混ぜず、次のAgent操作に残す。"""
    index = candidates(tmp_path, config)
    for offset in range(3):
        key = f"near-{offset}"
        index.units["source"][key] = TextUnit(
            id=key, spans=[TextSpan(id=f"{key}/span", source="nearby")]
        )
        index.contexts["source"][key] = {"kind": "paragraph"}
    index.units["source"]["far"] = TextUnit(
        id="far", spans=[TextSpan(id="far/span", source="far topic")]
    )
    index.contexts["source"]["far"] = {"kind": "paragraph"}
    index.units["translation"]["far-topic"] = TextUnit(
        id="far-topic", spans=[TextSpan(id="far-topic/span", source="far topic 日本語")]
    )
    index.contexts["translation"]["far-topic"] = {"kind": "caption"}
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[1.0, 0.0] for _ in texts]
    )
    actual = index.expand(
        {"source": ["first", "far"]},
        {role: set(values) for role, values in index.units.items()},
        32,
    )
    assert "first" in actual["source"]
    assert "far" not in actual["source"]
    assert "far-topic" not in actual["translation"]


def test_matching_without_embedding_preserves_the_original_pool(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedding未設定の構成では、従来のLLM照合を利用できる。"""
    index = candidates(tmp_path, config)
    index.enabled = False
    embed = MagicMock()
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    references = {"source": ["first"], "translation": ["wrong"]}
    assert (
        index.expand(
            references, {role: set(values) for role, values in index.units.items()}, 4
        )
        == references
    )
    embed.assert_not_called()


def test_matching_recomputes_vectors_when_the_model_changes(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """異なるモデルのベクトルを同じ検索空間として再利用しない。"""
    embed = MagicMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = candidates(tmp_path, config)
    available = {role: set(values) for role, values in index.units.items()}
    index.expand({"source": ["first"]}, available, 4)
    other = MatchingCandidates(
        index.units,
        index.contexts,
        tmp_path,
        index.config.model_copy(update={"openai_embedding_model": "changed"}),
    )
    other.expand({"source": ["first"]}, available, 4)
    assert embed.call_count == 2


def test_matching_rejects_zero_vectors_before_saving(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """検索に使えないゼロベクトルを保存して再開を繰り返し失敗させない。"""
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, texts: [[0.0, 0.0] for _ in texts]
    )
    index = candidates(tmp_path, config)
    with pytest.raises(EmbeddingError, match="nonzero"):
        index.expand(
            {"source": ["first"]},
            {role: set(values) for role, values in index.units.items()},
            4,
        )
    assert not index.path.exists()


def test_matching_keeps_four_definition_fragments_for_one_translation(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """見出しと説明が英語4要素・日本語1要素に分かれていても、比較候補を揃える。"""
    texts = {
        "source": {
            "timeout": "Timeout",
            "description": "Request timeout in seconds.",
            "retry": "Retry",
            "count": "Retry count before failing.",
        },
        "translation": {
            "definition": (
                "タイムアウト 秒単位の要求タイムアウト。再試行 失敗する前の再試行回数。"
            )
        },
    }
    units = {
        role: {
            key: TextUnit(id=key, spans=[TextSpan(id=f"{key}/span", source=text)])
            for key, text in values.items()
        }
        for role, values in texts.items()
    }
    contexts = {
        "source": {
            key: {"kind": "heading" if key in {"timeout", "retry"} else "paragraph"}
            for key in texts["source"]
        },
        "translation": {"definition": {"kind": "paragraph"}},
    }
    monkeypatch.setattr(
        EmbeddingClient, "embed", lambda _self, values: [[1.0, 0.0] for _ in values]
    )
    index = MatchingCandidates(units, contexts, tmp_path, config)
    selected = index.expand(
        {"source": ["timeout"]},
        {role: set(values) for role, values in units.items()},
        8,
    )
    assert set(selected["source"]) == set(texts["source"])
    assert selected["translation"] == ["definition"]


def test_matching_resumes_after_a_later_embedding_batch_fails(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """途中のEmbedding失敗後も、成功済みbatchを保存して未計算分だけ再開する。"""
    texts = {
        "source": {"query": "original"},
        "translation": {f"target-{i}": f"translation {i}" for i in range(17)},
    }
    units = {
        role: {
            key: TextUnit(id=key, spans=[TextSpan(id=f"{key}/span", source=text)])
            for key, text in values.items()
        }
        for role, values in texts.items()
    }
    calls = []

    def embed(_self: EmbeddingClient, values: list[str]) -> list[list[float]]:
        """2つ目のbatchだけ失敗させ、再開時の要求件数を記録する。"""
        calls.append(values)
        if len(calls) == 2:
            message = "temporary failure"
            raise EmbeddingError(message)
        return [[1.0, 0.0] for _ in values]

    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    available = {role: set(values) for role, values in units.items()}
    with pytest.raises(EmbeddingError, match="temporary"):
        MatchingCandidates(units, {}, tmp_path, config).expand(
            {"source": ["query"]}, available, 4
        )
    MatchingCandidates(units, {}, tmp_path, config).expand(
        {"source": ["query"]}, available, 4
    )
    assert [len(values) for values in calls] == [16, 2, 2]
    assert set(calls[0]).isdisjoint(calls[-1])

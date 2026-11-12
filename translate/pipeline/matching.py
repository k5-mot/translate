"""既知の文書内から対応候補を検索し、照合範囲へ補う。"""

import math
import re
from pathlib import Path
from typing import Literal

from pydantic import FiniteFloat

from translate.adapters.artifact_store import canonical_hash, load_model, write_model
from translate.adapters.embedding import EmbeddingClient, EmbeddingError
from translate.common.config import Config
from translate.models.artifacts import ArtifactModel
from translate.models.document import TextUnit

# sample4's intended split scored 0.70; retain it while excluding weaker neighbors.
_MIN_NEIGHBOR_SIMILARITY = 0.69
# Focused sample1-5 checks needed span scoring for long units, not short paragraphs.
_SPAN_RERANK_MIN_SPANS = 8
# sample2's translated merged unit has six spans.
_MERGED_UNIT_MIN_SPANS = 6
# A short title can match one sentence inside an unrelated long paragraph by chance.
_SPAN_RERANK_MIN_SOURCE_CHARS = 24
# Give the matcher two nearby heading choices when the semantic scores are close.
_SHORT_HEADING_CANDIDATE_MARGIN = 0.12
# Same-page TOC entries need nearby translation rows so the LLM can distinguish their labels.
_TABLE_ROW_CANDIDATE_MARGIN = 0.03
# Keep the rerank pool bounded; expand it when a verified counterpart ranks below it.
_SPAN_RERANK_CANDIDATES = 8
_SPAN_RERANK_CROSS_KIND_CANDIDATES = 16
# Front-page headings need a stronger semantic score before crossing into distant sections.
_POSITION_PENALTY = 3.0
# sample1's omitted cover title ranked a distant heading at 0.561 after position penalty.
_MIN_FRONT_PAGE_HEADING_SCORE = 0.60


def _row_label(value: str) -> str:
    """表の行見出しからOCRが追加した空白を除く。

    Args:
        value: LOADで抽出した行見出し。

    Returns:
        str: 下線・ハイフン・数字周辺の空白を除いたcasefold文字列。
    """
    return re.sub(
        r"\s*([_-])\s*|\s+(?=\d)", lambda match: match[1] or "", value.casefold()
    )


def _table_value(value: str) -> str:
    """表セルの数値内にあるOCR折り返し空白を除く。

    Args:
        value: LOADが抽出した表セル本文。

    Returns:
        str: 数字間の折り返し空白を除いた表セル本文。
    """
    # shortcut: normalize standalone comma-grouped values only; widen if LOAD wraps
    # other numeric formats.
    match = re.fullmatch(
        r"\s*(?P<number>[+-]?\d{1,3}(?:,\d{1,3})*)\s+(?P<tail>\d{1,3})\s*",
        value,
    )
    if match:
        number, tail = match["number"], match["tail"]
        last_group = number.rsplit(",", maxsplit=1)[-1]
        if "," in number and len(last_group) + len(tail) == 3:
            return number + tail
    return value


def _row_numbers(values: list[str]) -> tuple[str, ...]:
    """表行の数値値を順序付きで正規化する。"""
    numbers = []
    for value in values:
        normalized = _table_value(value)
        if re.fullmatch(
            r"\s*[ivxlcdm]+\s*-\s*\d+(?:\s+\d+)*\s*",
            normalized,
            re.IGNORECASE,
        ):
            normalized = re.sub(r"(?<=\d)\s+(?=\d)", "", normalized)
        numbers.extend(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", normalized))
    return tuple(numbers)


def _cell_column(identifier: str) -> str | None:
    """表セルIDからDoclingの列位置を返す。

    Args:
        identifier: 表セルunit ID。

    Returns:
        str | None: 列番号。表セルIDの形式でなければNone。
    """
    match = re.search(r"-c(\d+)/content$", identifier)
    return match[1] if match else None


def _section_distance(left: str, right: str) -> int | None:
    """二つの文書の節番号間の距離を返す。

    Args:
        left: 原文unitの節文脈。
        right: 候補unitの節文脈。

    Returns:
        int | None: 節番号ごとの距離。どちらかが無番号ならNone。
    """
    numbers = [re.match(r"\s*(\d+(?:\.\d+)*)", value) for value in (left, right)]
    if not all(numbers):
        return None
    parts = [tuple(map(int, match[1].split("."))) for match in numbers if match]
    width = max(map(len, parts))
    padded = [part + (0,) * (width - len(part)) for part in parts]
    return sum(abs(a - b) for a, b in zip(*padded, strict=True))


def _section_penalty(left: str, right: str) -> float:
    """近い節番号を優先し、番号付き本文をAbstractから分ける。

    Args:
        left: 原文unitの節文脈。
        right: 候補unitの節文脈。

    Returns:
        float: 類似度から差し引く節の距離ペナルティ。
    """
    distance = _section_distance(left, right)
    if distance is not None:
        return min(0.30, 0.05 * distance)
    if re.match(r"\s*\d+(?:\.\d+)*", left) and not re.match(r"\s*\d+(?:\.\d+)*", right):
        return 0.30
    return 0.0


def _position_penalty(left: str, right: str) -> float:
    """遠く離れたPDF位置の候補を弱く降順する。

    Args:
        left: 原文側の正規化ページ位置。
        right: 候補側の正規化ページ位置。

    Returns:
        float: 類似度から差し引く位置ペナルティ。
    """
    try:
        distance = abs(float(left) - float(right))
    except ValueError:
        return 0.0
    return min(_POSITION_PENALTY, distance * _POSITION_PENALTY)


def _compatible_kinds(source: str, target: str) -> bool:
    """対応候補として許容できる二つの構造種別かを返す。

    Args:
        source: 原文unitの種別。
        target: 候補unitの種別。

    Returns:
        bool: 同種、または本文との対応が許容される場合はTrue。
    """
    return source == target or {source, target} in (
        {"table_cell", "paragraph"},
        {"formula", "paragraph"},
        {"caption", "paragraph"},
        {"list_item", "paragraph"},
        {"heading", "paragraph"},
    )


class _Vectors(ArtifactModel):
    """Embeddingの設定と本文hashに対応する検証済みベクトル。"""

    schema_version: Literal[1] = 1
    fingerprint: str
    vectors: dict[str, list[FiniteFloat]]


class MatchingCandidates:
    """対応を確定せず、別文書の有力候補と隣接断片を照合範囲へ追加する。"""

    def __init__(
        self,
        units: dict[str, dict[str, TextUnit]],
        contexts: dict[str, dict[str, dict[str, str]]],
        directory: Path,
        config: Config,
    ) -> None:
        """比較文書と、再開時に再利用するEmbeddingの保存先を受け取る。

        Args:
            units: 文書role別の本文索引。
            contexts: TextUnitの構造情報。表セルは行・列の意味も検索へ使う。
            directory: Agent TaskのArtifact保存先。
            config: 既存Embedding接続。未設定の場合は候補を変更しない。
        """
        self.units = units
        self.contexts = contexts
        self.path = directory / "candidate-vectors.json"
        self.config = config
        self.enabled = bool(config.openai_base_url and config.openai_embedding_model)
        fingerprint = canonical_hash(
            {"endpoint": config.openai_base_url, "model": config.openai_embedding_model}
        )
        self.cache = _Vectors(fingerprint=fingerprint, vectors={})
        if self.path.exists():
            try:
                cached = load_model(self.path, _Vectors)
            except (OSError, ValueError):
                return
            dimensions = {len(vector) for vector in cached.vectors.values()}
            if (
                cached.fingerprint == fingerprint
                and 0 not in dimensions
                and len(dimensions) <= 1
                and all(
                    any(vector) and math.isfinite(math.hypot(*vector))
                    for vector in cached.vectors.values()
                )
            ):
                self.cache = cached

    def _text(self, role: str, identifier: str) -> str:
        """本文と、表セルの検索に必要な行・列の意味を取得する。

        Args:
            role: 検索対象文書のrole。
            identifier: 文書内のTextUnit ID。

        Returns:
            Embedding入力。構造情報は本文の対応を確定する根拠にはしない。
        """
        context = self.contexts.get(role, {}).get(identifier, {})
        text = self.units[role][identifier].text("source")
        if context.get("kind") == "heading":
            text = re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", text)
        if context.get("kind") == "table_cell":
            text = _table_value(text)
            text += "\n" + "\n".join(
                f"{key}: {context[key]}"
                for key in ("row_label", "column_label")
                if context.get(key)
            )
            cell = re.search(r"#/tables/(\d+)/cell-r(\d+)-c\d+/content$", identifier)
            row_cells = [
                _table_value(unit.text("source"))
                for key, unit in self.units[role].items()
                if key != identifier
                and cell
                and re.search(rf"#/tables/{cell[1]}/cell-r{cell[2]}-c\d+/content$", key)
            ]
            if row_cells:
                text += "\nrow cells: " + " | ".join(row_cells)
            cell = re.search(r"#/tables/(\d+)/cell-r(\d+)-c(\d+)/content$", identifier)
            if cell and int(cell[2]) == 0:
                table, row, column = cell.groups()
                neighbors = [
                    self.contexts.get(role, {})
                    .get(
                        f"#/tables/{table}/cell-r{int(row) + offset:04d}-c{int(column):04d}/content",
                        {},
                    )
                    .get("row_label")
                    for offset in (-1, 1)
                ]
                if any(neighbors):
                    text += "\nadjacent rows: " + " | ".join(
                        _row_label(label) if label else "" for label in neighbors
                    )
        return text

    def _adjacent_row_label(self, role: str, identifier: str) -> str:
        """同じ表・列の次行ラベルをOCR空白を除いて返す。

        Args:
            role: 文書のrole。
            identifier: 表セルunit ID。

        Returns:
            str: 正規化した次行見出し。隣接セルがなければ空文字列。
        """
        cell = re.search(r"#/tables/(\d+)/cell-r(\d+)-c(\d+)/content$", identifier)
        if cell is None:
            return ""
        table, row, column = cell.groups()
        context = self.contexts.get(role, {}).get(
            f"#/tables/{table}/cell-r{int(row) + 1:04d}-c{int(column):04d}/content",
            {},
        )
        return _row_label(context.get("row_label", ""))

    def _sibling_cells(self, role: str, identifier: str) -> list[str]:
        """同じ表行の他セルから検索可能な値を返す。

        Args:
            role: 文書のrole。
            identifier: 表セルunit ID。

        Returns:
            list[str]: 数字の改行空白を正規化した兄弟セル値。
        """
        match = re.search(r"#/tables/(\d+)/cell-r(\d+)-c\d+/content$", identifier)
        if not match:
            return []
        table, row = match.groups()
        prefix = f"#/tables/{table}/cell-r{row}-c"
        return [
            _table_value(unit.text("source"))
            for key, unit in self.units[role].items()
            if key != identifier and key.startswith(prefix)
        ]

    def _embed(self, texts: list[str]) -> dict[str, list[float]]:
        """未計算の本文だけを16件ずつ計算し、batch完了ごとに保存する。

        Args:
            texts: 検索本文と照合候補の本文。

        Returns:
            本文をkeyとする長さ1へ正規化したベクトル。

        Raises:
            EmbeddingError: ベクトルがゼロ、または次元が変化した場合。
        """
        missing = list(
            dict.fromkeys(
                text for text in texts if canonical_hash(text) not in self.cache.vectors
            )
        )
        dimension = next((len(vector) for vector in self.cache.vectors.values()), None)
        for first in range(0, len(missing), 16):
            batch = missing[first : first + 16]
            vectors = EmbeddingClient(self.config).embed(batch)
            for text, vector in zip(batch, vectors, strict=True):
                if not any(vector) or not math.isfinite(math.hypot(*vector)):
                    raise EmbeddingError(
                        "Matching Embedding vector must have a finite nonzero norm"
                    )
                if dimension is not None and len(vector) != dimension:
                    raise EmbeddingError("Matching Embedding dimensions changed")
                dimension = len(vector)
                self.cache.vectors[canonical_hash(text)] = vector
            write_model(self.path, self.cache)
        normalized = {}
        for text in texts:
            vector = self.cache.vectors[canonical_hash(text)]
            norm = math.hypot(*vector)
            if not norm:
                raise EmbeddingError("Matching Embedding vector must not be zero")
            normalized[text] = [value / norm for value in vector]
        return normalized

    def expand(
        self,
        references: dict[str, list[str]],
        available: dict[str, set[str]],
        maximum_ids: int,
    ) -> dict[str, list[str]]:
        """選択英文を上限内へ分割し、別文書から有力な相手と隣接断片を集める。

        Args:
            references: Agentが選んだ検索の起点。範囲から外した候補は未処理のまま残る。
            available: 確定済み対応に使用されていないID。
            maximum_ids: 補完後の全role合計の最大ID数。

        Returns:
            検索の起点、有力候補、必要な隣接断片を含む参照。

        Raises:
            EmbeddingError: 既存Embedding接続または応答が不正な場合。
        """
        original = {role: list(references.get(role, [])) for role in self.units}
        if not self.enabled:
            return original
        sources = [
            role for role in self.units if role in {"source", "source_v1", "source_v2"}
        ]
        primary = next(
            (role for role in [*sources, *self.units] if original[role]), None
        )
        if primary is None or not set(original[primary]).issubset(available[primary]):
            return original
        # 同じ照合へ別の話題の候補を混ぜない。
        queries = original[primary][:1]
        selected = {role: queries if role == primary else [] for role in self.units}
        searches = []
        texts = []
        for role in [primary]:
            for identifier in selected[role]:
                query = self._text(role, identifier)
                source_context = self.contexts.get(role, {}).get(identifier, {})
                for opposite in self.units:
                    if opposite == role or not available[opposite]:
                        continue
                    source_kind = source_context.get("kind", "paragraph")
                    candidates = [
                        (key, self._text(opposite, key))
                        for key in self.units[opposite]
                        if key in available[opposite]
                        and _compatible_kinds(
                            source_kind,
                            self.contexts.get(opposite, {})
                            .get(key, {})
                            .get("kind", "paragraph"),
                        )
                    ]
                    exact_kind = [
                        item
                        for item in candidates
                        if self.contexts.get(opposite, {})
                        .get(item[0], {})
                        .get("kind", "paragraph")
                        == source_kind
                    ]
                    if exact_kind:
                        merged_cross_kind = [
                            item
                            for item in candidates
                            if item not in exact_kind
                            and len(self.units[opposite][item[0]].spans)
                            >= _SPAN_RERANK_MIN_SPANS
                        ]
                        candidates = [*exact_kind, *merged_cross_kind]
                    source_row = _row_label(source_context.get("row_label", ""))
                    same_row = [
                        item
                        for item in candidates
                        if source_row
                        and self.contexts.get(opposite, {}).get(item[0], {}).get("kind")
                        == "table_cell"
                        and _row_label(
                            self.contexts.get(opposite, {})
                            .get(item[0], {})
                            .get("row_label", "")
                        )
                        == source_row
                    ]
                    if same_row:
                        candidates = same_row
                    same_row = [
                        item
                        for item in candidates
                        if source_context.get("kind") == "table_cell"
                        and self.contexts.get(opposite, {}).get(item[0], {}).get("kind")
                        == "table_cell"
                        and _row_label(
                            self.contexts.get(opposite, {})
                            .get(item[0], {})
                            .get("row_label", "")
                        )
                        == source_row
                        and source_row
                    ]
                    same_section = [
                        item
                        for item in candidates
                        if source_context.get("kind") == "table_cell"
                        and self.contexts.get(opposite, {}).get(item[0], {}).get("kind")
                        == "table_cell"
                        and source_context.get("section")
                        and self.contexts.get(opposite, {})
                        .get(item[0], {})
                        .get("section")
                        == source_context["section"]
                    ]
                    same_column = [
                        item
                        for item in candidates
                        if source_context.get("kind") == "table_cell"
                        and self.contexts.get(opposite, {}).get(item[0], {}).get("kind")
                        == "table_cell"
                        and _cell_column(identifier) == _cell_column(item[0])
                    ]
                    adjacent_row = self._adjacent_row_label(role, identifier)
                    same_adjacent_row = [
                        item
                        for item in candidates
                        if adjacent_row
                        and _cell_column(identifier) == _cell_column(item[0])
                        and self._adjacent_row_label(opposite, item[0]) == adjacent_row
                    ]
                    same_row_column = [item for item in same_row if item in same_column]
                    choices = (
                        same_row_column
                        or same_row
                        or same_adjacent_row
                        or same_column
                        or same_section
                        or candidates
                    )
                    if not choices:
                        continue
                    texts.extend([query, *(text for _, text in choices)])
                    list_items = set(re.findall(r"(?<!\d)\(\s*(\d+)\s*\)", query))
                    neighbor_window = (
                        min(max(3, len(list_items)), max(1, maximum_ids - 2))
                        if len(list_items) >= 4
                        else 3
                    )
                    searches.append(
                        (role, identifier, query, opposite, choices, neighbor_window)
                    )
                    ids = list(self.units[role])
                    index = ids.index(identifier)
                    neighbors = (
                        ids[max(0, index - 3) : index] + ids[index + 1 : index + 4]
                    )
                    for neighbor in neighbors:
                        neighbor_kind = (
                            self.contexts.get(role, {})
                            .get(neighbor, {})
                            .get("kind", "paragraph")
                        )
                        if neighbor not in available[role] or neighbor_kind not in {
                            "paragraph",
                            "list_item",
                            "heading",
                            "formula",
                        }:
                            continue
                        texts.append(self._text(role, neighbor))
                        possible = [
                            (key, self._text(opposite, key))
                            for key in self.units[opposite]
                            if key in available[opposite]
                            and _compatible_kinds(
                                neighbor_kind,
                                self.contexts.get(opposite, {})
                                .get(key, {})
                                .get("kind", "paragraph"),
                            )
                        ]
                        exact_kind = [
                            item
                            for item in possible
                            if self.contexts.get(opposite, {})
                            .get(item[0], {})
                            .get("kind", "paragraph")
                            == neighbor_kind
                        ]
                        if exact_kind:
                            possible = exact_kind
                        texts.extend(text for _, text in possible)
        if not searches or sum(map(len, selected.values())) >= maximum_ids:
            return selected
        vectors = self._embed(list(dict.fromkeys(texts)))
        ranked = []

        def similarity(left: str, right: str) -> float:
            """Embeddingの正規化済みベクトル間の類似度を返す。

            Args:
                left: 左側のEmbedding入力。
                right: 右側のEmbedding入力。

            Returns:
                float: Cosine類似度。
            """
            return math.sumprod(vectors[left], vectors[right])

        for role, identifier, query, opposite, choices, neighbor_window in searches:
            source_context = self.contexts.get(role, {}).get(identifier, {})
            source_section = source_context.get("section", "")
            source_position = source_context.get("position", "")

            def score(
                item: tuple[str, str],
                query: str = query,
                source_section: str = source_section,
                source_position: str = source_position,
                opposite: str = opposite,
                source_context: dict[str, str] = source_context,
                role: str = role,
                identifier: str = identifier,
            ) -> float:
                """本文類似度から節番号差のペナルティを引く。

                Args:
                    item: 候補unit IDと照合用本文。
                    query: 原文側のEmbedding入力。
                    source_section: 原文側の節文脈。
                    opposite: 候補側の文書role。

                Returns:
                    float: 節番号差を加味した本文類似度。
                """
                semantic = (
                    math.sumprod(vectors[query], vectors[item[1]])
                    - _section_penalty(
                        source_section,
                        self.contexts.get(opposite, {})
                        .get(item[0], {})
                        .get("section", ""),
                    )
                    - _position_penalty(
                        source_position,
                        self.contexts.get(opposite, {})
                        .get(item[0], {})
                        .get("position", ""),
                    )
                )
                if source_context.get("kind") == "table_cell":
                    source_numbers = _row_numbers(self._sibling_cells(role, identifier))
                    target_numbers = _row_numbers(
                        self._sibling_cells(opposite, item[0])
                    )
                    if source_numbers and source_numbers == target_numbers:
                        semantic += 0.20
                return semantic

            order = sorted(choices, key=score, reverse=True)
            source_kind = self.contexts.get(role, {}).get(identifier, {}).get("kind")
            if (
                role == "source"
                and opposite == "translation"
                and source_kind == "heading"
                and source_position == "0.0"
                and _position_penalty(
                    source_position,
                    self.contexts.get(opposite, {})
                    .get(order[0][0], {})
                    .get("position", ""),
                )
                >= 0.10
                and score(order[0]) < _MIN_FRONT_PAGE_HEADING_SCORE
            ):
                continue
            source_spans = [
                span.text("source").strip()
                for span in self.units[role][identifier].spans
                if span.text("source").strip()
            ]
            source_ids = list(self.units[role])
            source_index = source_ids.index(identifier)
            source_neighbors = [
                key
                for key in source_ids[max(0, source_index - 3) : source_index]
                + source_ids[source_index + 1 : source_index + 4]
                if key in available[role]
                and self.contexts.get(role, {}).get(key, {}).get("kind")
                in {source_kind, "paragraph", "list_item"}
                and (
                    not source_context.get("section")
                    or not self.contexts.get(role, {}).get(key, {}).get("section")
                    or self.contexts[role][key]["section"] == source_context["section"]
                )
            ]
            long_candidates = []
            if (
                len(source_spans) > 1
                and sum(map(len, source_spans)) >= _SPAN_RERANK_MIN_SOURCE_CHARS
            ):
                long_candidates = [
                    item
                    for item in order
                    if len(self.units[opposite][item[0]].spans)
                    >= _SPAN_RERANK_MIN_SPANS
                    and self.contexts.get(opposite, {})
                    .get(item[0], {})
                    .get("kind", "paragraph")
                    == source_kind
                ][:_SPAN_RERANK_CANDIDATES]
                # A single source span can match one sentence by chance inside a long, unrelated unit.
                long_candidates.extend(
                    [
                        item
                        for item in order
                        if len(self.units[opposite][item[0]].spans)
                        >= _SPAN_RERANK_MIN_SPANS
                        and self.contexts.get(opposite, {})
                        .get(item[0], {})
                        .get("kind", "paragraph")
                        != source_kind
                    ][:_SPAN_RERANK_CROSS_KIND_CANDIDATES]
                )
            elif (
                len(source_spans) == 1
                and source_neighbors
                and source_kind in {"paragraph", "list_item"}
            ):
                long_candidates = [
                    item
                    for item in order
                    if len(self.units[opposite][item[0]].spans)
                    >= _MERGED_UNIT_MIN_SPANS
                    and self.contexts.get(opposite, {})
                    .get(item[0], {})
                    .get("kind", "paragraph")
                    == source_kind
                ][:_SPAN_RERANK_CANDIDATES]
            # shortcut: span reranking covers 16 cross-kind merged units; widen if a verified match ranks lower.
            if long_candidates:
                scores = {item[0]: score(item) for item in order}
                if len(source_spans) > 1:
                    span_texts = [
                        span.text("source").strip()
                        for item in long_candidates
                        for span in self.units[opposite][item[0]].spans
                        if span.text("source").strip()
                    ]
                    span_vectors = self._embed(
                        list(dict.fromkeys([*source_spans, *span_texts]))
                    )
                    for item in long_candidates:
                        candidate_spans = [
                            span.text("source").strip()
                            for span in self.units[opposite][item[0]].spans
                            if span.text("source").strip()
                        ]
                        coverage = sum(
                            max(
                                math.sumprod(span_vectors[source], span_vectors[target])
                                for target in candidate_spans
                            )
                            for source in source_spans
                        ) / len(source_spans)
                        # 長い結合unitは複数節をまたぐため、section labelよりspan対応を優先する。
                        scores[item[0]] = max(scores[item[0]], coverage)
                else:
                    for item in long_candidates:
                        neighbor_scores = [
                            similarity(self._text(role, neighbor), item[1])
                            for neighbor in source_neighbors
                        ]
                        neighbor_scores = [
                            value
                            for value in neighbor_scores
                            if value >= _MIN_NEIGHBOR_SIMILARITY
                        ]
                        if neighbor_scores:
                            evidence = (
                                similarity(query, item[1]) + sum(neighbor_scores)
                            ) / (1 + len(neighbor_scores))
                            # 結合unitは先頭ページしか位置に残らないため、隣接unitで確認した類似度も順位へ使う。
                            scores[item[0]] = max(scores[item[0]], evidence)
                order = sorted(order, key=lambda item: scores[item[0]], reverse=True)
            candidate_ids = [order[0][0]]
            if source_kind == "table_cell":
                source_numbers = _row_numbers(self._sibling_cells(role, identifier))
                candidate_ids.extend(
                    item[0]
                    for item in order[1:]
                    if source_numbers
                    and _row_numbers(self._sibling_cells(opposite, item[0]))
                    == source_numbers
                    and score(item) >= score(order[0]) - _TABLE_ROW_CANDIDATE_MARGIN
                )
                candidate_ids = candidate_ids[:2]
            if (
                source_kind == "heading"
                and sum(map(len, source_spans)) < _SPAN_RERANK_MIN_SOURCE_CHARS
                and sum(map(len, selected.values())) + 2 <= maximum_ids
            ):
                headings = [
                    item
                    for item in order
                    if self.contexts.get(opposite, {})
                    .get(item[0], {})
                    .get("kind", "paragraph")
                    == "heading"
                ]
                if len(headings) > 1 and score(headings[1]) >= score(headings[0]) - (
                    _SHORT_HEADING_CANDIDATE_MARGIN
                ):
                    candidate_ids.append(headings[1][0])
            ranked.append(
                (role, identifier, query, opposite, candidate_ids, neighbor_window)
            )

        target_neighbors = []
        for _, _, _, opposite, candidates, neighbor_window in ranked:
            identifier = candidates[0]
            if self.contexts.get(opposite, {}).get(identifier, {}).get("kind") not in {
                "paragraph",
                "list_item",
                "heading",
                "formula",
            }:
                continue
            ids = list(self.units[opposite])
            index = ids.index(identifier)
            neighbors = ids[index + 1 : index + neighbor_window + 1] + list(
                reversed(ids[max(0, index - neighbor_window) : index])
            )
            target_neighbors.extend(
                self._text(opposite, neighbor)
                for neighbor in neighbors
                if neighbor in available[opposite]
                and self.contexts.get(opposite, {}).get(neighbor, {}).get("kind")
                in {"paragraph", "list_item", "heading", "formula"}
            )
        vectors.update(self._embed(list(dict.fromkeys(target_neighbors))))

        def add(role: str, identifier: str) -> None:
            """確定済みIDを再使用せず、選択枠が残る場合だけ候補を追加する。

            Args:
                role: 候補を加える文書のrole。
                identifier: 追加するTextUnit ID。
            """
            if (
                identifier in available[role]
                and identifier not in selected[role]
                and sum(map(len, selected.values())) < maximum_ids
            ):
                selected[role].append(identifier)

        # 各英文の最上位候補を先に確保し、隣接断片で片側の枠を使い切らないようにする。
        for _, _, _, opposite, candidates, _ in ranked:
            for candidate in candidates:
                add(opposite, candidate)
        for role, identifier, query, opposite, candidates, neighbor_window in ranked:
            side_keys = [
                (role, identifier),
                *[(opposite, candidate) for candidate in candidates[:1]],
            ]
            if neighbor_window > 3:
                side_keys.reverse()
            for side, key in side_keys:
                if self.contexts.get(side, {}).get(key, {}).get("kind") not in {
                    "paragraph",
                    "list_item",
                    "heading",
                    "formula",
                }:
                    continue
                ids = list(self.units[side])
                index = ids.index(key)
                # shortcut: 原文側は前後3要素まで。より大きい分割箇条書きを検出したら拡張する。
                window = neighbor_window if side == opposite else 3
                neighbors = ids[index + 1 : index + window + 1] + list(
                    reversed(ids[max(0, index - window) : index])
                )
                base_key = identifier if side == role else candidates[0]
                base_section = (
                    self.contexts.get(side, {}).get(base_key, {}).get("section")
                )
                for neighbor in neighbors:
                    if neighbor not in available[side]:
                        continue
                    if self.contexts.get(side, {}).get(neighbor, {}).get("kind") in {
                        "paragraph",
                        "list_item",
                        "formula",
                        "heading",
                    }:
                        neighbor_section = (
                            self.contexts.get(side, {}).get(neighbor, {}).get("section")
                        )
                        if side == role and candidates:
                            neighbor_text = self._text(side, neighbor)
                            possible = [
                                (candidate, self._text(opposite, candidate))
                                for candidate in self.units[opposite]
                                if candidate in available[opposite]
                                and _compatible_kinds(
                                    self.contexts.get(side, {})
                                    .get(neighbor, {})
                                    .get("kind", "paragraph"),
                                    self.contexts.get(opposite, {})
                                    .get(candidate, {})
                                    .get("kind", "paragraph"),
                                )
                            ]
                            exact_kind = [
                                item
                                for item in possible
                                if self.contexts.get(opposite, {})
                                .get(item[0], {})
                                .get("kind", "paragraph")
                                == self.contexts.get(side, {})
                                .get(neighbor, {})
                                .get("kind", "paragraph")
                            ]
                            if exact_kind:
                                possible = exact_kind
                            if not possible:
                                continue
                            best_neighbor = max(
                                possible,
                                key=lambda item: similarity(neighbor_text, item[1]),
                            )[0]
                            mutually_best = best_neighbor == candidates[0]
                            relatedness = similarity(
                                neighbor_text, self._text(opposite, candidates[0])
                            )
                        elif side == opposite:
                            if (
                                base_section
                                and neighbor_section
                                and base_section != neighbor_section
                            ):
                                continue
                            relatedness = similarity(query, self._text(side, neighbor))
                        else:
                            continue
                        # shortcut: numbered lists may span six adjacent units; raise the limit when needed.
                        # cosine 0.69 keeps close fragments; cross-section merges require mutual best.
                        if relatedness >= _MIN_NEIGHBOR_SIMILARITY or (
                            side == role and mutually_best
                        ):
                            add(side, neighbor)
        return selected

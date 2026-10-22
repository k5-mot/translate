"""Streamlit UI comparisons module."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import streamlit as st

from translate.adapters.artifact_store import (
    ArtifactError,
    load_model,
    sha256_file,
)
from translate.models.artifacts import (
    FixResult,
    LLMCallArtifact,
    ReviewResult,
    TaskName,
)
from translate.models.document import Block, Document, TextLayer, TextUnit
from translate.models.review import AlignmentResponse, ReviewResponse, ReviewTarget
from translate.models.upgrade import (
    DiffResponse,
    UpgradePlan,
    VersionChange,
)

from .types import StructurePatch, StructureResponse, TranslationResponse


def _upgrade_context(root: Path) -> tuple[str, str, str] | None:  # noqa: PLR0911 - 未確定または不正な成果物を各境界で表示から除外する。
    """同一VersionChangeの英文v1、日本語v1、英文v2を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        tuple[str, str, str] | None: 同一VersionChangeの英文v1、日本語v1、英文v2を返す。
    """

    plan_path = root / "tasks/21-diff/plan.json"
    source_v1 = _load_first_document(root, ["tasks/12-load/source-v1/document.json"])
    source_v2 = _load_first_document(root, ["tasks/12-load/source-v2/document.json"])
    translation_v1 = _load_first_document(
        root, ["tasks/12-load/translation-v1/document.json"]
    )
    if source_v1 is None or source_v2 is None or translation_v1 is None:
        return None
    if plan_path.is_file():
        try:
            plan = load_model(plan_path, UpgradePlan)
        except ArtifactError:
            return None
    else:
        call = _latest_verified_call(root, TaskName.DIFF)
        response = _verified_response(root, TaskName.DIFF, call) if call else None
        if call is None or not isinstance(response, DiffResponse):
            return None
        plan = UpgradePlan(
            changes=[
                VersionChange(id=f"{call.call_id}/{index}", **item.model_dump())
                for index, item in enumerate(response.changes)
                if item.kind != "unchanged"
            ]
        )
    requested = set(_call_v2_unit_ids(root, source_v2))
    changes = (
        [
            change
            for change in plan.changes
            if requested.intersection(change.source_v2_ids)
        ]
        if requested
        else plan.changes[:3]
    )
    if not changes:
        return None
    source_v1_units = source_v1.unit_index()
    source_v2_units = source_v2.unit_index()
    translation_v1_units = translation_v1.unit_index()
    rows: list[tuple[str, str, str, str]] = []
    for change in changes[:3]:
        value_v1 = _unit_text(change.source_v1_ids, source_v1_units, "source")
        value_v2 = _unit_text(change.source_v2_ids, source_v2_units, "source")
        value_ja = _unit_text(
            change.translation_v1_ids, translation_v1_units, "revised"
        )
        if change.kind == "added":
            value_v1 = "該当なし"
            value_ja = "該当なし"
        elif value_ja is None:
            value_ja = "対応訳なし"
        if change.kind == "deleted":
            value_v2 = "該当なし"
        if value_v1 is None or value_v2 is None:
            return None
        rows.append((change.id, value_v1, value_ja, value_v2))
    return (
        _comparison_text([(item[0], item[1]) for item in rows]),
        _comparison_text([(item[0], item[2]) for item in rows]),
        _comparison_text([(item[0], item[3]) for item in rows]),
    )


def _llm_call_directory(root: Path, task: TaskName) -> Path | None:
    """処理種類によるSTRUCTURE配置差を吸収してCall directoryを返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。

    Returns:
        Path | None: 処理種類によるSTRUCTURE配置差を吸収してCall directoryを返す。
    """

    candidates = {
        TaskName.STRUCTURE: [
            root / "tasks/13-structure/source-v2/calls",
            root / "tasks/13-structure/calls",
        ],
        TaskName.TRANSLATE: [root / "tasks/30-translate/calls"],
        TaskName.REVIEW: [root / "tasks/41-review/calls"],
        TaskName.DIFF: [root / "tasks/21-diff/calls"],
    }.get(task, [])
    return next((directory for directory in candidates if directory.is_dir()), None)


def _render_upgrade_context(root: Path, processing_id: str) -> None:
    """Upgrade tabへ三版の対応表示を描画する。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        processing_id (str): 新規処理またはResume対象の処理ID。
    """

    values = _upgrade_context(root)
    if values is None:
        st.caption("対応確認中")
        return
    st.subheader("版間の対応")
    _render_text_areas(
        ("英語v1", "日本語v1", "英語v2"),
        values,
        f"upgrade-context-{processing_id}",
    )
    _render_diff(values[0], values[2], "英語v1", "英語v2")


def _live_call_counts(root: Path, task: TaskName) -> tuple[int, int, int]:
    """実行中LLM TaskのCall Artifactから観測数、完了数、失敗数を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。

    Returns:
        tuple[int, int, int]: 実行中LLM TaskのCall Artifactから観測数、完了数、失敗数を返す。
    """

    calls = _llm_calls(root, task)
    completed = sum(call.status in {"succeeded", "partial", "split"} for call in calls)
    failed = sum(call.status == "failed" for call in calls)
    return len(calls), completed, failed


def _review_targets(root: Path) -> dict[str, tuple[str, str]]:
    """Review対象をIDで取得する。

    検証済みREVIEW結果またはDocumentから、原文と現在訳を対象IDごとに取得する。

    Args:
        root (Path): 処理成果物のルートディレクトリ。

    Returns:
        dict[str, tuple[str, str]]: 対象IDを原文と現在訳へ対応付けた辞書。
    """

    values: dict[str, tuple[str, str]] = {}
    path = root / "tasks/41-review/review.json"
    if path.is_file():
        try:
            reviewed = load_model(path, ReviewResult)
        except ArtifactError:
            reviewed = ReviewResult()
        for target in reviewed.targets:
            value = (target.source, target.translation)
            values[target.id] = value
            values.update(dict.fromkeys(target.target_ids, value))
    else:
        source = _load_first_document(root, ["tasks/12-load/source/document.json"])
        translated = _load_first_document(
            root, ["tasks/12-load/translation/document.json"]
        )
        if source is not None and translated is not None:
            source_units = source.unit_index()
            translated_units = translated.unit_index()
            groups = []
            for call in sorted(
                _llm_calls(root, TaskName.REVIEW), key=lambda item: item.round
            ):
                response = _verified_response(root, TaskName.REVIEW, call)
                if call.operation == "match" and isinstance(
                    response, AlignmentResponse
                ):
                    groups.extend(response.groups)
            for index, group in enumerate(groups, 1):
                if group.kind != "matched":
                    continue
                original = _unit_text(group.source_ids, source_units, "source")
                translation = _unit_text(
                    group.translation_ids, translated_units, "source"
                )
                if original is None or translation is None:
                    continue
                value = (original, translation)
                values[f"review/alignment-{index:06d}"] = value
                values.update(dict.fromkeys(group.translation_ids, value))
    document = _load_first_document(
        root,
        [
            "tasks/42-fix/document.json",
            "tasks/30-translate/document.json",
        ],
    )
    if document is not None:
        for target in ReviewTarget.from_document(document):
            value = (target.source, target.translation)
            values[target.id] = value
            values.update(dict.fromkeys(target.target_ids, value))
    return values


def _render_review_context(root: Path, processing_id: str) -> None:
    """Review tabへ英語原文と日本語訳の対応表示を描画する。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        processing_id (str): 新規処理またはResume対象の処理ID。
    """

    values = _review_context(root)
    if values is None:
        st.caption("対応確認中")
        return
    st.subheader("レビュー対象")
    _render_text_areas(
        ("英語原文", "日本語訳"), values, f"review-context-{processing_id}"
    )


def _render_diff(before: str, after: str, before_label: str, after_label: str) -> None:
    """TextAreaの下へ追加・削除行を強調する差分Collapseを表示する。

    Args:
        before (str): 変更前として表示するText。
        after (str): 変更後として表示するText。
        before_label (str): 変更前TextのLabel。
        after_label (str): 変更後TextのLabel。
    """

    st.subheader("差分")
    diff = _diff_text(before, after, before_label, after_label)
    if diff:
        st.code(diff, language="diff")
    else:
        st.caption("差分はありません。")


def _unit_text(
    unit_ids: list[str], units: dict[str, TextUnit], layer: TextLayer
) -> str | None:
    """複数TextUnit IDを検証済み索引から一つの表示textへ解決する。

    Args:
        unit_ids (list[str]): Textを結合するTextUnit ID列。
        units (dict[str, TextUnit]): TextUnit IDからTextUnitへの索引。
        layer (TextLayer): 取得するTextの優先Layer。

    Returns:
        str | None: 複数TextUnit IDを検証済み索引から一つの表示textへ解決する。
    """

    if not unit_ids or any(unit_id not in units for unit_id in unit_ids):
        return None
    return "\n".join(units[unit_id].text(layer) for unit_id in unit_ids)


def _comparison_text(rows: list[tuple[str, str]], empty: str = "") -> str:
    """同じ対象順の最大3件をTextArea用plain textへ整形する。

    Args:
        rows (list[tuple[str, str]]): CSVまたは比較表示を構成する行。
        empty (str): 表示対象がない場合の代替Text。

    Returns:
        str: 同じ対象順の最大3件をTextArea用plain textへ整形する。
    """

    if not rows:
        return empty
    return "\n\n".join(
        f"[{target_id}]\n{_preview(value) if value else '空'}"
        for target_id, value in rows[:3]
    )


def _load_first_document(root: Path, candidates: list[str]) -> Document | None:
    """候補から最初に存在する検証済みDocumentを読む。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        candidates (list[str]): 読込み候補のDocument File名。

    Returns:
        Document | None: 候補から最初に存在する検証済みDocumentを読む。
    """

    for relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        try:
            return load_model(path, Document)
        except ArtifactError:
            continue
    return None


def _structure_block_text(block: Block, patch: StructurePatch | None = None) -> str:
    """Blockの本文と構造を、提案された変更を含めて比較用に整形する。"""

    return "\n".join(
        (
            f"種別: {(patch.kind if patch and patch.kind is not None else block.kind)}",
            f"見出しレベル: {(patch.level if patch and patch.level is not None else block.level) or '-'}",
            f"注意種別: {(patch.alert_kind if patch and patch.alert_kind is not None else block.alert_kind) or '-'}",
            f"キャプション元: {(patch.caption_source_id if patch else None) or '-'}",
            f"本文: {_preview(block.content.text('source')) if block.content else '空'}",
        )
    )


def _markdown_code(value: str) -> str:
    """Artifact由来textを安全な一つのMarkdown inline codeへ変換する。

    Args:
        value (str): Inline Codeとして表示するArtifact Text。

    Returns:
        str: Artifact由来textを安全な一つのMarkdown inline codeへ変換する。
    """

    normalized = " ".join(value.split())
    longest = max((len(item) for item in re.findall(r"`+", normalized)), default=0)
    fence = "`" * (longest + 1)
    return f"{fence}{normalized}{fence}"


def _render_text_areas(
    labels: tuple[str, ...], values: tuple[str, ...], key: str
) -> None:
    """同じ件数の読取専用TextAreaを横並びで表示する。

    Args:
        labels (tuple[str, ...]): 比較TextAreaへ付けるLabel列。
        values (tuple[str, ...]): 一括処理する入力Text列。
        key (str): Table DataまたはWidgetの識別Key。
    """

    columns = st.columns(len(labels))
    for index, (column, label, value) in enumerate(
        zip(columns, labels, values, strict=True)
    ):
        with column:
            widget_key = f"{key}-{index}"
            st.session_state[widget_key] = value
            st.text_area(
                label,
                height=180,
                disabled=True,
                key=widget_key,
            )


def _render_latest_comparison(root: Path) -> None:
    """既存Artifactから最新の処理前後比較を表示する。

    Args:
        root (Path): 対象処理の成果物Root Directory。
    """

    fixed = _fix_comparison(root)
    reviewed = _review_comparison(root)
    translated = _translation_comparison(root)
    structured = _structure_comparison(root)
    if fixed is not None:
        st.subheader("FIXの処理前・処理後")
        _render_text_areas(("修正前", "修正後"), fixed, "fix-comparison")
        _render_diff(fixed[0], fixed[1], "修正前", "修正後")
        rejected = _fix_rejections(root)
        if rejected:
            with st.expander(f"拒否された修正候補 ({len(rejected)})", expanded=False):
                for revision_id, reason_code in rejected:
                    st.markdown(
                        f"- **Revision ID:** {_markdown_code(revision_id)}  \n"
                        f"  **拒否理由:** {_markdown_code(reason_code)}"
                    )
    elif reviewed is not None:
        st.subheader("REVIEWの処理前・処理後")
        _render_text_areas(("修正前", "修正候補"), reviewed, "review-comparison")
        _render_diff(reviewed[0], reviewed[1], "修正前", "修正候補")
    elif translated is not None:
        st.subheader("TRANSLATEの処理前・処理後")
        _render_text_areas(
            ("翻訳前 (英語)", "翻訳後 (日本語)"),
            translated,
            "translate-comparison",
        )
        _render_diff(translated[0], translated[1], "翻訳前", "翻訳後")
    elif structured is not None:
        st.subheader("STRUCTUREの処理前・処理後")
        _render_text_areas(
            ("構造判定前", "構造判定後 (提案)"), structured, "structure-comparison"
        )
        _render_diff(structured[0], structured[1], "構造判定前", "構造判定後 (提案)")


def _fix_rejections(root: Path) -> list[tuple[str, str]]:
    """FIXが拒否したRevision IDと理由codeの組を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        list[tuple[str, str]]: FIXが拒否したRevision IDと理由codeの組を返す。
    """

    path = root / "tasks/42-fix/outcomes.json"
    if not path.is_file():
        return []
    try:
        result = load_model(path, FixResult)
    except ArtifactError:
        return []
    return [
        (item.revision_id, item.reason_code)
        for item in result.outcomes
        if item.status == "rejected"
    ]


def _llm_calls(root: Path, task: TaskName) -> list[LLMCallArtifact]:
    """一階層のCall記録だけを読み、壊れた途中fileを無視する。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。

    Returns:
        list[LLMCallArtifact]: 一階層のCall記録だけを読み、壊れた途中fileを無視する。
    """

    directory = _llm_call_directory(root, task)
    if directory is None:
        return []
    calls: list[LLMCallArtifact] = []
    for path in directory.glob("*/call.json"):
        try:
            calls.append(load_model(path, LLMCallArtifact))
        except ArtifactError:
            continue
    return calls


def _translation_comparison(root: Path) -> tuple[str, str] | None:
    """直近の同一TRANSLATE Callから英語と検証済み日本語を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        tuple[str, str] | None: 直近の同一TRANSLATE Callから英語と検証済み日本語を返す。
    """

    document = _load_first_document(
        root,
        ["upgrade/reuse/document.json", "tasks/13-structure/document.json"],
    )
    if document is None:
        return None
    sources = {
        span.id: span.source for _, unit in document.text_units() for span in unit.spans
    }
    confirmed = _latest_verified_call(root, TaskName.TRANSLATE)
    if confirmed is not None:
        response = _verified_response(root, TaskName.TRANSLATE, confirmed)
        if not isinstance(response, TranslationResponse):
            return None
        translated = {item.span_id: item.text for item in response.translations}
        target_ids = [
            target_id
            for target_id in confirmed.target_ids
            if target_id in sources and target_id in translated
        ]
        return (
            _comparison_text([(item, sources[item]) for item in target_ids]),
            _comparison_text([(item, translated[item]) for item in target_ids]),
        )
    active = _latest_call(root, TaskName.TRANSLATE, "processing")
    if active is None:
        return None
    target_ids = [item for item in active.target_ids if item in sources]
    return (
        _comparison_text([(item, sources[item]) for item in target_ids]),
        "処理中 (確定結果なし)",
    )


def _preview(value: str) -> str:
    """文書由来textを一行240文字以内のplain textへ省略する。

    Args:
        value (str): 一行のPreviewへ短縮する文書Text。

    Returns:
        str: 文書由来textを一行240文字以内のplain textへ省略する。
    """

    normalized = " ".join(value.split())
    return normalized if len(normalized) <= 240 else f"{normalized[:239]}…"


def _verified_response(
    root: Path, task: TaskName, call: LLMCallArtifact
) -> (
    StructureResponse
    | TranslationResponse
    | AlignmentResponse
    | ReviewResponse
    | DiffResponse
    | None
):
    """確定状態、hashおよびSchemaを検証したLLM応答だけを返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。
        call (LLMCallArtifact): 応答Fileを検証するLLM Call Artifact。

    Returns:
        StructureResponse | TranslationResponse | AlignmentResponse | ReviewResponse | DiffResponse | None: 確定状態、hashおよびSchemaを検証したLLM応答だけを返す。
    """

    if call.status not in {"succeeded", "partial"} or call.response_sha256 is None:
        return None
    directory = _llm_call_directory(root, task)
    if directory is None:
        return None
    path = directory / call.call_id / "response.json"
    models = {
        TaskName.STRUCTURE: StructureResponse,
        TaskName.TRANSLATE: TranslationResponse,
        TaskName.REVIEW: AlignmentResponse
        if call.operation == "match"
        else ReviewResponse,
        TaskName.DIFF: DiffResponse,
    }
    model = models.get(task)
    try:
        if (
            model is None
            or not path.is_file()
            or sha256_file(path) != call.response_sha256
        ):
            return None
        return load_model(path, model)
    except (ArtifactError, OSError):
        return None


def _review_context(root: Path) -> tuple[str, str] | None:
    """同一ReviewTargetの英語原文と日本語訳を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        tuple[str, str] | None: 同一ReviewTargetの英語原文と日本語訳を返す。
    """

    targets = _review_targets(root)
    by_id = {key: value for key, value in targets.items() if key.startswith("review/")}
    call = _latest_call(root, TaskName.REVIEW, "processing") or _latest_call(
        root, TaskName.REVIEW, "succeeded"
    )
    requested = (
        [item.removeprefix("review:").split("/part-", 1)[0] for item in call.target_ids]
        if call
        else []
    )
    selected = [key for key in requested if key in by_id] or list(by_id)[:3]
    if not selected:
        return None
    return (
        _comparison_text([(key, by_id[key][0]) for key in selected]),
        _comparison_text([(key, by_id[key][1]) for key in selected]),
    )


def _call_v2_unit_ids(root: Path, document: Document) -> list[str]:
    """Upgradeの実行中または直近Call対象を英文v2 TextUnit IDへ解決する。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        document (Document): 変換または検証対象のDocument。

    Returns:
        list[str]: Upgradeの実行中または直近Call対象を英文v2 TextUnit IDへ解決する。
    """

    call = _latest_call(root, TaskName.DIFF, "processing") or _latest_verified_call(
        root, TaskName.DIFF
    )
    known = document.unit_index()
    return [
        key
        for reference in (call.target_ids if call else [])
        if reference.startswith("source_v2:")
        and (key := reference.removeprefix("source_v2:")) in known
    ]


def _review_comparison(root: Path) -> tuple[str, str] | None:
    """直近の同一REVIEW Callから現在訳と修正候補を返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        tuple[str, str] | None: 直近の同一REVIEW Callから現在訳と修正候補を返す。
    """

    targets = _review_targets(root)
    confirmed = _latest_verified_call(root, TaskName.REVIEW)
    if confirmed is not None:
        response = _verified_response(root, TaskName.REVIEW, confirmed)
        if not isinstance(response, ReviewResponse):
            return None
        revisions = {
            item.target_id.split("/part-", 1)[0]: item
            for item in response.assessments
            if item.edits
        }
        target_ids = [
            key
            for item in confirmed.target_ids
            if (key := item.removeprefix("review:").split("/part-", 1)[0]) in targets
        ]
        target_ids = [key for key in revisions if key in targets] or target_ids
        before = [(item, targets[item][1]) for item in target_ids]
        after = [
            (
                item,
                " / ".join(edit.text for edit in revisions[item].edits)
                if item in revisions
                else "修正候補なし",
            )
            for item in target_ids
        ]
        return _comparison_text(before), _comparison_text(after)
    active = _latest_call(root, TaskName.REVIEW, "processing")
    if active is None:
        return None
    target_ids = [
        key
        for item in active.target_ids
        if (key := item.removeprefix("review:").split("/part-", 1)[0]) in targets
    ]
    return (
        _comparison_text([(item, targets[item][1]) for item in target_ids]),
        "処理中 (確定結果なし)",
    )


def _fix_comparison(root: Path) -> tuple[str, str] | None:
    """適用済みRevision対象のFIX前後を同じTextUnit IDで返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。

    Returns:
        tuple[str, str] | None: 適用済みRevision対象のFIX前後を同じTextUnit IDで返す。
    """

    outcomes_path = root / "tasks/42-fix/outcomes.json"
    review_path = root / "tasks/41-review/review.json"
    before = _load_first_document(
        root,
        [
            "tasks/30-translate/document.json",
        ],
    )
    if not outcomes_path.is_file() or not review_path.is_file() or before is None:
        return None
    try:
        fixed = load_model(outcomes_path, FixResult)
        review = load_model(review_path, ReviewResult)
    except ArtifactError:
        return None
    applied = {
        outcome.revision_id for outcome in fixed.outcomes if outcome.status == "applied"
    }
    target_ids = [item.target_id for item in review.revisions if item.id in applied]
    before_units = before.unit_index()
    after_units = fixed.document.unit_index()
    target_ids = [
        item for item in target_ids if item in before_units and item in after_units
    ]
    if not target_ids:
        return None
    return (
        _comparison_text(
            [(item, before_units[item].text("revised")) for item in target_ids]
        ),
        _comparison_text(
            [(item, after_units[item].text("revised")) for item in target_ids]
        ),
    )


def _latest_call(root: Path, task: TaskName, status: str) -> LLMCallArtifact | None:
    """指定状態で更新時刻が最も新しいLLM Callを返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。
        status (str): 抽出対象のLLM Call状態。

    Returns:
        LLMCallArtifact | None: 指定状態で更新時刻が最も新しいLLM Callを返す。
    """

    calls = [call for call in _llm_calls(root, task) if call.status == status]
    return max(calls, key=lambda item: item.updated_at) if calls else None


def _diff_text(before: str, after: str, before_label: str, after_label: str) -> str:
    """二つの表示textから行単位のunified diffを作る。

    Args:
        before (str): 変更前として表示するText。
        after (str): 変更後として表示するText。
        before_label (str): 変更前TextのLabel。
        after_label (str): 変更後TextのLabel。

    Returns:
        str: 二つの表示textから行単位のunified diffを作る。
    """

    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=before_label,
            tofile=after_label,
            lineterm="",
        )
    )


def _structure_comparison(root: Path) -> tuple[str, str] | None:
    """直近の同一STRUCTURE Callから補正前と構造提案を返す。"""

    confirmed = _latest_verified_call(root, TaskName.STRUCTURE)
    active = _latest_call(root, TaskName.STRUCTURE, "processing")
    call = confirmed or active
    document = _load_first_document(
        root,
        [
            "tasks/12-load/source-v2/document.json",
            "tasks/12-load/document.json",
        ],
    )
    if call is None or document is None:
        return None
    blocks = {block.id: block for page in document.pages for block in page.blocks}
    target_ids = [target_id for target_id in call.target_ids if target_id in blocks][:3]
    if not target_ids:
        return None
    before = "\n\n".join(
        f"[{target_id}]\n{_structure_block_text(blocks[target_id])}"
        for target_id in target_ids
    )
    if confirmed is None:
        return before, "処理中 (確定結果なし)"
    response = _verified_response(root, TaskName.STRUCTURE, confirmed)
    if not isinstance(response, StructureResponse):
        return None
    patches = {patch.block_id: patch for patch in response.patches}
    after = "\n\n".join(
        f"[{target_id}]\n{_structure_block_text(blocks[target_id], patches.get(target_id))}"
        for target_id in target_ids
    )
    return before, after


def _latest_verified_call(root: Path, task: TaskName) -> LLMCallArtifact | None:
    """hashとSchemaを検証できる最新の確定済みLLM Callを返す。

    Args:
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。

    Returns:
        LLMCallArtifact | None: hashとSchemaを検証できる最新の確定済みLLM Callを返す。
    """

    calls = sorted(
        _llm_calls(root, task), key=lambda item: item.updated_at, reverse=True
    )
    return next(
        (call for call in calls if _verified_response(root, task, call) is not None),
        None,
    )

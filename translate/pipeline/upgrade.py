"""英文二版と既存日本語版から日本語新版を生成するUpgrade Pipeline。"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict

from translate.artifact_store import (
    ProcessingLock,
    cancel_processing,
    canonical_hash,
    describe_artifact,
    fail_task,
    finish_task,
    load_model,
    reusable_task,
    sha256_file,
    start_task,
    task_artifacts,
    write_model,
)
from translate.models.artifacts import (
    AlignmentResult,
    CheckResult,
    CoverResult,
    DoclingManifest,
    InputFile,
    LintResult,
    LLMCallArtifact,
    LLMCallIndex,
    LLMProgress,
    ProcessingError,
    ReviewResult,
    SplitManifest,
    TaskName,
    UnpackManifest,
)
from translate.models.document import Document
from translate.models.upgrade import ReuseReport, UpgradePlan, UpgradeRecord
from translate.pipeline import InputError, resolve_processing_id
from translate.pipeline.translate import PipelineError
from translate.tasks.converter.docling import convert as convert_with_docling
from translate.tasks.converter.merge import merge
from translate.tasks.converter.split import split
from translate.tasks.converter.unpack import unpack
from translate.tasks.preprocess.load import load
from translate.tasks.preprocess.normalize import normalize
from translate.tasks.preprocess.position import position
from translate.tasks.preprocess.structure import structure
from translate.tasks.publisher.cover import create_cover
from translate.tasks.publisher.docx import publish
from translate.tasks.publisher.lint import lint
from translate.tasks.publisher.markdown import convert_document
from translate.tasks.review.align import align
from translate.tasks.review.check import check, targets_from_document
from translate.tasks.review.diff import diff
from translate.tasks.review.fix import apply_revisions
from translate.tasks.review.review import review
from translate.tasks.translation.reuse import previous_context, reuse
from translate.tasks.translation.translate import translate as translate_with_llm
from translate.tasks.translation.translate_lite import translate_lite

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from translate.common.config import Config
    from translate.models.artifacts import LLMTaskName
    from translate.models.review import ReviewTarget

_Role = Literal["source-v1", "source-v2", "translation-v1"]


class UpgradeOutcome(BaseModel):
    """CLIへ返すUpgrade IDと最終DOCX path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    upgrade_id: str
    processing_directory: Path
    docx: Path


def upgrade_pdfs(
    source_v1: Path,
    source_v2: Path,
    translation_v1: Path,
    config: Config,
    *,
    backend: str = "llm",
    processing_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> UpgradeOutcome:
    """三つのPDFを比較し、再利用可能な既存訳を保った日本語v2を生成する。

    Args:
        source_v1 (Path): 比較基準にする英文v1。
        source_v2 (Path): 変更を反映する英文v2。
        translation_v1 (Path): 比較基準にする日本語v1。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        backend (str): 翻訳に使用するBackend名。
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。
        outputs (Path | None): 成果物Root Directory。

    Returns:
        UpgradeOutcome: 三つのPDFを比較し、再利用可能な既存訳を保った日本語v2を生成する。

    Raises:
        InputError: `backend must be llm or libretranslate`、`processing ID already
            exists`のいずれかと判定した場合。
    """

    source_v1 = source_v1.resolve()
    source_v2 = source_v2.resolve()
    translation_v1 = translation_v1.resolve()
    for path, role in (
        (source_v1, "source_v1"),
        (source_v2, "source_v2"),
        (translation_v1, "translation_v1"),
    ):
        _validate_pdf(path, role)
    if backend not in {"llm", "libretranslate"}:
        raise InputError("backend must be llm or libretranslate")
    config.require_translate(backend)
    upgrade_id = resolve_processing_id(processing_id, resume_id)
    outputs_root = (outputs or Path.cwd() / "outputs").resolve()
    root = outputs_root / source_v2.stem / upgrade_id
    record_path = root / "upgrade.json"
    inputs = (
        _input(source_v1, "source_v1"),
        _input(source_v2, "source_v2"),
        _input(translation_v1, "translation_v1"),
    )
    with ProcessingLock(root):
        if processing_id is not None and record_path.is_file():
            raise InputError("processing ID already exists")
        record = _upgrade_record(
            record_path,
            upgrade_id,
            *inputs,
            backend,
            resume_id is not None,
        )
        try:
            return _upgrade_locked(
                {
                    "source-v1": source_v1,
                    "source-v2": source_v2,
                    "translation-v1": translation_v1,
                },
                config,
                root,
                record_path,
                record,
            )
        except KeyboardInterrupt:
            cancel_processing(record, record_path)
            raise


def _upgrade_locked(
    files: dict[_Role, Path],
    config: Config,
    root: Path,
    record_path: Path,
    record: UpgradeRecord,
) -> UpgradeOutcome:
    """排他取得後のUpgrade Task列を実行する。

    Args:
        files (dict[_Role, Path]): Role別の入力File。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        root (Path): 対象処理の成果物Root Directory。
        record_path (Path): 処理Record JSONのPath。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        UpgradeOutcome: 排他取得後のUpgrade Task列を実行する。
    """

    template_root = Path(__file__).parents[1] / "templates"
    structure_rules = (template_root / "structure-rules.md").read_text(encoding="utf-8")
    translation_rules = (template_root / "translation-rules.md").read_text(
        encoding="utf-8"
    )
    review_rules = (template_root / "review-rules.md").read_text(encoding="utf-8")
    glossary = (template_root / "glossary.csv").read_text(encoding="utf-8")

    merge_dirs = _convert_inputs(files, config, root, record_path, record)
    loaded = _preprocess_inputs(merge_dirs, root, record_path, record)
    source_v1 = loaded["source-v1"]
    source_v2 = loaded["source-v2"]
    translation_v1 = loaded["translation-v1"]

    structure_dir = root / "preprocess" / "source-v2" / "structure"
    structure_fp = canonical_hash(
        {
            "task": "STRUCTURE",
            "document": canonical_hash(source_v2),
            "source": record.source_v2.sha256,
            "rules": canonical_hash(structure_rules),
            "model": config.openai_structure_model,
            "mode": config.llm_structured_output_mode,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
            "call_index": 3,
            "caption_guard": True,
        }
    )
    reused_structure = reusable_task(record, TaskName.STRUCTURE, structure_fp, root)
    _perform(
        record,
        record_path,
        root,
        TaskName.STRUCTURE,
        structure_fp,
        [structure_dir],
        partial(
            structure,
            source_v2,
            files["source-v2"],
            structure_dir,
            root,
            config,
            structure_rules,
        ),
    )
    _update_llm_progress(
        record, record_path, structure_dir, "STRUCTURE", reused_structure
    )
    structured_v2 = load_model(structure_dir / "document.json", Document)

    align_dir = root / "upgrade" / "align"
    align_fp = canonical_hash(
        {
            "task": "ALIGN",
            "source": canonical_hash(source_v1),
            "translation": canonical_hash(translation_v1),
            "schema": 1,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.ALIGN,
        align_fp,
        [align_dir],
        partial(_align_and_write, source_v1, translation_v1, align_dir),
    )
    alignment = load_model(align_dir / "result.json", AlignmentResult)

    diff_dir = root / "upgrade" / "diff"
    diff_fp = canonical_hash(
        {
            "task": "DIFF",
            "source_v1": canonical_hash(source_v1),
            "source_v2": canonical_hash(source_v2),
            "alignment": canonical_hash(alignment),
            "schema": 1,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.DIFF,
        diff_fp,
        [diff_dir],
        partial(diff, source_v1, source_v2, translation_v1, alignment, diff_dir),
    )
    plan = load_model(diff_dir / "plan.json", UpgradePlan)

    reuse_dir = root / "upgrade" / "reuse"
    reuse_fp = canonical_hash(
        {
            "task": "REUSE",
            "document": canonical_hash(structured_v2),
            "translation": canonical_hash(translation_v1),
            "plan": canonical_hash(plan),
            "schema": 1,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.REUSE,
        reuse_fp,
        [reuse_dir],
        partial(reuse, structured_v2, translation_v1, plan, reuse_dir),
    )
    document = load_model(reuse_dir / "document.json", Document)
    reuse_report = load_model(reuse_dir / "report.json", ReuseReport)
    context = previous_context(plan, source_v1, source_v2, translation_v1)
    document = _translate_changes(
        document,
        reuse_report,
        context,
        config,
        record,
        record_path,
        root,
        translation_rules,
        glossary,
    )
    document = _review_changes(
        document,
        set(reuse_report.translation_target_ids),
        config,
        record,
        record_path,
        root,
        review_rules,
        glossary,
    )
    return _publish(
        document,
        files["source-v2"],
        merge_dirs["source-v2"],
        config,
        record,
        record_path,
        root,
        template_root,
    )


def _convert_inputs(
    files: dict[_Role, Path],
    config: Config,
    root: Path,
    record_path: Path,
    record: UpgradeRecord,
) -> dict[_Role, Path]:
    """三入力へconverter Taskを同じ順序で適用する。

    Args:
        files (dict[_Role, Path]): Role別の入力File。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        root (Path): 対象処理の成果物Root Directory。
        record_path (Path): 処理Record JSONのPath。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        dict[_Role, Path]: 三入力へconverter Taskを同じ順序で適用する。
    """

    inputs = {
        "source-v1": record.source_v1,
        "source-v2": record.source_v2,
        "translation-v1": record.translation_v1,
    }
    split_dirs = {role: root / "converter" / role / "split" for role in files}
    split_fp = canonical_hash(
        {
            "task": "SPLIT",
            "inputs": {role: value.sha256 for role, value in inputs.items()},
            "pages": config.pdf_split_pages,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.SPLIT,
        split_fp,
        list(split_dirs.values()),
        partial(
            _call_all,
            [
                partial(
                    split, files[role], split_dirs[role], root, config.pdf_split_pages
                )
                for role in files
            ],
        ),
    )
    splits = {
        role: load_model(directory / "manifest.json", SplitManifest)
        for role, directory in split_dirs.items()
    }

    docling_dirs = {role: root / "converter" / role / "docling" for role in files}
    docling_fp = canonical_hash(
        {
            "task": "DOCLING",
            "inputs": {role: canonical_hash(value) for role, value in splits.items()},
            "url": config.docling_server_url,
            "ocr": [
                config.docling_ocr_preset,
                config.docling_ocr_lang,
                config.docling_force_ocr,
            ],
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.DOCLING,
        docling_fp,
        list(docling_dirs.values()),
        partial(
            _call_all,
            [
                partial(
                    convert_with_docling,
                    splits[role],
                    docling_dirs[role],
                    root,
                    config,
                )
                for role in files
            ],
        ),
    )
    docling = {
        role: load_model(directory / "manifest.json", DoclingManifest)
        for role, directory in docling_dirs.items()
    }

    unpack_dirs = {role: root / "converter" / role / "unpack" for role in files}
    unpack_fp = canonical_hash(
        {
            "task": "UNPACK",
            "inputs": {role: canonical_hash(value) for role, value in docling.items()},
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.UNPACK,
        unpack_fp,
        list(unpack_dirs.values()),
        partial(
            _call_all,
            [partial(unpack, docling[role], unpack_dirs[role], root) for role in files],
        ),
    )
    unpacked = {
        role: load_model(directory / "manifest.json", UnpackManifest)
        for role, directory in unpack_dirs.items()
    }

    merge_dirs = {role: root / "converter" / role / "merge" for role in files}
    merge_fp = canonical_hash(
        {
            "task": "MERGE",
            "inputs": {role: canonical_hash(value) for role, value in unpacked.items()},
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.MERGE,
        merge_fp,
        list(merge_dirs.values()),
        partial(
            _call_all,
            [
                partial(
                    merge,
                    unpacked[role],
                    files[role],
                    merge_dirs[role],
                    root,
                )
                for role in files
            ],
        ),
    )
    return merge_dirs


def _preprocess_inputs(
    merge_dirs: dict[_Role, Path],
    root: Path,
    record_path: Path,
    record: UpgradeRecord,
) -> dict[_Role, Document]:
    """三入力へ決定的な前処理を同じ順序で適用する。

    Args:
        merge_dirs (dict[_Role, Path]): Role別の統合済みDocument Directory。
        root (Path): 対象処理の成果物Root Directory。
        record_path (Path): 処理Record JSONのPath。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        dict[_Role, Document]: 三入力へ決定的な前処理を同じ順序で適用する。
    """

    current = {
        role: directory / "document.json" for role, directory in merge_dirs.items()
    }
    for task, function, name in (
        (TaskName.POSITION, position, "position"),
        (TaskName.NORMALIZE, normalize, "normalize"),
        (TaskName.LOAD, load, "load"),
    ):
        directories = {role: root / "preprocess" / role / name for role in current}
        fingerprint = canonical_hash(
            {
                "task": task.value,
                "inputs": {role: sha256_file(path) for role, path in current.items()},
                "schema": 2 if task == TaskName.LOAD else 1,
            }
        )
        _perform(
            record,
            record_path,
            root,
            task,
            fingerprint,
            list(directories.values()),
            partial(
                _call_all,
                [
                    partial(function, current[role], directories[role])
                    for role in current
                ],
            ),
        )
        current = {
            role: directory / "document.json" for role, directory in directories.items()
        }
    return {role: load_model(path, Document) for role, path in current.items()}


def _translate_changes(
    document: Document,
    report: ReuseReport,
    context: dict[str, tuple[str, str]],
    config: Config,
    record: UpgradeRecord,
    record_path: Path,
    root: Path,
    rules: str,
    glossary: str,
) -> Document:
    """再利用できなかったTextUnitだけを選択backendで翻訳する。

    Args:
        document (Document): 変換または検証対象のDocument。
        report (ReuseReport): 再利用結果または診断Report。
        context (dict[str, tuple[str, str]]): 変更対象別の原文と旧訳。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        rules (str): LLM Promptへ含める追加規則。
        glossary (str): 対象文書へ適用するCSV形式の用語集。

    Returns:
        Document: 再利用できなかったTextUnitだけを選択backendで翻訳する。
    """

    task = TaskName.TRANSLATE if record.backend == "llm" else TaskName.TRANSLATE_LITE
    name = "translate" if record.backend == "llm" else "translate-lite"
    directory = root / "translation" / name
    fingerprint = canonical_hash(
        {
            "task": task.value,
            "document": canonical_hash(document),
            "targets": report.translation_target_ids,
            "context": canonical_hash(context),
            "rules": canonical_hash(rules),
            "glossary": canonical_hash(glossary),
            "backend": record.backend,
            "model": config.openai_translation_model
            if record.backend == "llm"
            else config.libretranslate_url,
            "reasoning_effort": "none" if record.backend == "llm" else None,
            "llm_endpoint": (
                config.openai_llm_base_url or config.openai_base_url
                if record.backend == "llm"
                else None
            ),
            "temperature": 0.7 if record.backend == "llm" else None,
            "repetition_penalty": 1.01 if record.backend == "llm" else None,
            "call_index": 2 if record.backend == "llm" else None,
        }
    )
    if not report.translation_target_ids:
        finish_task(record, record_path, task, fingerprint, [], skipped=True)
        return document
    reused = reusable_task(record, task, fingerprint, root)
    action = (
        partial(
            translate_with_llm,
            document,
            directory,
            root,
            config,
            rules,
            glossary,
            context,
        )
        if record.backend == "llm"
        else partial(translate_lite, document, directory, config)
    )
    _perform(
        record,
        record_path,
        root,
        task,
        fingerprint,
        [directory],
        action,
    )
    if record.backend == "llm":
        _update_llm_progress(record, record_path, directory, "TRANSLATE", reused)
    return load_model(directory / "document.json", Document)


def _review_changes(
    document: Document,
    changed_unit_ids: set[str],
    config: Config,
    record: UpgradeRecord,
    record_path: Path,
    root: Path,
    rules: str,
    glossary: str,
) -> Document:
    """全文をCHECKし、今回翻訳したTextUnitだけをLLM REVIEWへ渡す。

    Args:
        document (Document): 変換または検証対象のDocument。
        changed_unit_ids (set[str]): 再翻訳またはReview対象のTextUnit ID集合。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        rules (str): LLM Promptへ含める追加規則。
        glossary (str): 対象文書へ適用するCSV形式の用語集。

    Returns:
        Document: 全文をCHECKし、今回翻訳したTextUnitだけをLLM REVIEWへ渡す。
    """

    check_dir = root / "review" / "check"
    targets = targets_from_document(document)
    initial_fp = canonical_hash(
        {
            "task": "CHECK",
            "phase": "initial",
            "targets": [item.model_dump(mode="json") for item in targets],
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.CHECK,
        initial_fp,
        [check_dir],
        partial(_check_and_write, targets, check_dir / "findings.json"),
    )
    checked = load_model(check_dir / "findings.json", CheckResult)
    review_targets = [
        target for target in targets if changed_unit_ids.intersection(target.target_ids)
    ]
    review_dir = root / "review" / "review"
    review_fp = canonical_hash(
        {
            "task": "REVIEW",
            "targets": [item.model_dump(mode="json") for item in review_targets],
            "check": canonical_hash(checked),
            "rules": canonical_hash(rules),
            "glossary": canonical_hash(glossary),
            "model": config.openai_review_model,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
            "call_index": 2,
        }
    )
    if review_targets:
        relevant = CheckResult(
            findings=[
                item
                for item in checked.findings
                if changed_unit_ids.intersection(item.target_ids)
            ]
        )
        reused = reusable_task(record, TaskName.REVIEW, review_fp, root)
        _perform(
            record,
            record_path,
            root,
            TaskName.REVIEW,
            review_fp,
            [review_dir],
            partial(
                review,
                review_targets,
                relevant,
                review_dir,
                root,
                config,
                rules,
                glossary,
            ),
        )
        _update_llm_progress(record, record_path, review_dir, "REVIEW", reused)
        reviewed = load_model(review_dir / "review.json", ReviewResult)
    else:
        finish_task(record, record_path, TaskName.REVIEW, review_fp, [], skipped=True)
        reviewed = ReviewResult(findings=[], revisions=[])

    fix_dir = root / "review" / "fix"
    fix_fp = canonical_hash(
        {
            "task": "FIX",
            "document": canonical_hash(document),
            "review": canonical_hash(reviewed),
        }
    )
    if reviewed.revisions:
        _perform(
            record,
            record_path,
            root,
            TaskName.FIX,
            fix_fp,
            [fix_dir],
            partial(_fix_and_write, document, reviewed, fix_dir),
        )
        document = load_model(fix_dir / "document.json", Document)
    else:
        finish_task(record, record_path, TaskName.FIX, fix_fp, [], skipped=True)

    final_targets = targets_from_document(document)
    final_fp = canonical_hash(
        {
            "task": "CHECK",
            "phase": "final",
            "targets": [item.model_dump(mode="json") for item in final_targets],
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.CHECK,
        final_fp,
        [check_dir],
        partial(_check_and_write, final_targets, check_dir / "final-findings.json"),
    )
    final = load_model(check_dir / "final-findings.json", CheckResult)
    if any(item.category == "empty_translation" for item in final.findings):
        _stop(
            record,
            record_path,
            "empty_translation",
            "Empty translations remain after review.",
        )
    return document


def _publish(
    document: Document,
    source_v2: Path,
    merge_dir: Path,
    config: Config,
    record: UpgradeRecord,
    record_path: Path,
    root: Path,
    template_root: Path,
) -> UpgradeOutcome:
    """全文検査後のDocumentを英文v2 assetからDOCXへ公開する。

    Args:
        document (Document): 変換または検証対象のDocument。
        source_v2 (Path): 変更を反映する英文v2。
        merge_dir (Path): 統合済みDocument Directory。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        template_root (Path): Publisher Template Directory。

    Returns:
        UpgradeOutcome: 全文検査後のDocumentを英文v2 assetからDOCXへ公開する。
    """

    lint_dir = root / "publisher" / "lint"
    lint_fp = canonical_hash(
        {
            "task": "LINT",
            "document": canonical_hash(document),
            "assets": _tree_hash(merge_dir / "assets"),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.LINT,
        lint_fp,
        [lint_dir],
        partial(_lint_and_write, document, merge_dir, lint_dir),
    )
    if not load_model(lint_dir / "report.json", LintResult).valid:
        _stop(
            record,
            record_path,
            "lint_failed",
            "Document structure is not publishable.",
        )

    cover_dir = root / "publisher" / "cover"
    cover_fp = canonical_hash(
        {"task": "COVER", "source": record.source_v2.sha256, "dpi": 150}
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.COVER,
        cover_fp,
        [cover_dir],
        partial(create_cover, source_v2, cover_dir, root),
    )
    cover = load_model(cover_dir / "manifest.json", CoverResult)

    markdown_dir = root / "publisher" / "markdown"
    markdown_path = markdown_dir / "document.ja.md"
    markdown_fp = canonical_hash(
        {
            "task": "MARKDOWN",
            "document": canonical_hash(document),
            "cover": canonical_hash(cover),
            "assets": _tree_hash(merge_dir / "assets"),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.MARKDOWN,
        markdown_fp,
        [markdown_dir],
        partial(
            convert_document,
            document,
            markdown_path,
            root / Path(cover.image.relative_path),
            merge_dir,
            set(cover.excluded_page_numbers),
            config.http_request_timeout_seconds,
        ),
    )

    docx_dir = root / "publisher" / "docx"
    docx_path = docx_dir / "document.ja.docx"
    docx_fp = canonical_hash(
        {
            "task": "DOCX",
            "markdown": sha256_file(markdown_path),
            "template": sha256_file(template_root / "template.docx"),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.DOCX,
        docx_fp,
        [docx_dir],
        partial(
            publish,
            markdown_path,
            docx_path,
            template_root / "template.docx",
            config.http_request_timeout_seconds,
        ),
    )
    record.status = "succeeded"
    record.outputs = [describe_artifact(root, docx_path)]
    record.updated_at = datetime.now(UTC)
    record.error = None
    write_model(record_path, record)
    return UpgradeOutcome(
        upgrade_id=record.upgrade_id,
        processing_directory=root,
        docx=docx_path,
    )


def _perform[ResultT](
    record: UpgradeRecord,
    record_path: Path,
    root: Path,
    task: TaskName,
    fingerprint: str,
    task_directories: list[Path],
    action: Callable[[], ResultT],
) -> ResultT | None:
    """一つのUpgrade Taskを再利用または状態更新付きで実行する。

    Args:
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。
        fingerprint (str): 入力と設定から算出した再利用判定Hash。
        task_directories (list[Path]): 再利用判定用のTask Directory列。
        action (Callable[[], ResultT]): Task本体として実行するCallable。

    Returns:
        ResultT | None: 一つのUpgrade Taskを再利用または状態更新付きで実行する。
    """

    if reusable_task(record, task, fingerprint, root):
        return None
    start_task(record, record_path, task, fingerprint)
    try:
        result = action()
    except KeyboardInterrupt:
        raise
    except Exception as error:
        fail_task(record, record_path, task, fingerprint, error)
        raise
    artifacts = [
        artifact
        for directory in task_directories
        for artifact in task_artifacts(root, directory)
    ]
    finish_task(record, record_path, task, fingerprint, artifacts)
    return result


def _call_all(actions: Sequence[Callable[[], object]]) -> list[object]:
    """同じTaskの三入力分岐を決定的な順序で実行する。

    Args:
        actions (Sequence[Callable[[], object]]): 並列実行するTask Callable列。

    Returns:
        list[object]: 同じTaskの三入力分岐を決定的な順序で実行する。
    """

    return [action() for action in actions]


def _align_and_write(
    source: Document,
    translation: Document,
    directory: Path,
) -> AlignmentResult:
    """英文v1と日本語v1のALIGN結果を保存する。

    Args:
        source (Document): 変換または検証対象の入力Source。
        translation (Document): Review対象の日本語訳。
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        AlignmentResult: 英文v1と日本語v1のALIGN結果を保存する。
    """

    result = align(source, translation)
    write_model(directory / "result.json", result)
    return result


def _check_and_write(targets: list[ReviewTarget], path: Path) -> CheckResult:
    """CHECK結果を指定phaseのfileへ保存する。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。
        path (Path): CHECK結果を書き込むJSON FileのPath。

    Returns:
        CheckResult: CHECK結果を指定phaseのfileへ保存する。
    """

    result = check(targets)
    write_model(path, result)
    return result


def _fix_and_write(document: Document, reviewed: ReviewResult, directory: Path) -> None:
    """FIX結果のDocumentと適用結果を保存する。

    Args:
        document (Document): 変換または検証対象のDocument。
        reviewed (ReviewResult): 修正候補を含むReview結果。
        directory (Path): LLM Call Artifactの保存Directory。
    """

    result = apply_revisions(document, reviewed)
    write_model(directory / "document.json", result.document)
    write_model(directory / "outcomes.json", result)


def _lint_and_write(document: Document, asset_root: Path, directory: Path) -> None:
    """LINT結果を公開判定用に保存する。

    Args:
        document (Document): 変換または検証対象のDocument。
        asset_root (Path): 参照先Assetを検証するRoot Directory。
        directory (Path): LLM Call Artifactの保存Directory。
    """

    write_model(directory / "report.json", lint(document, asset_root))


def _input(path: Path, role: str) -> InputFile:
    """指定PDFのResume比較用入力情報を作る。

    Args:
        path (Path): Resume比較用情報を作成するPDFのPath。
        role (str): 入力または比較要素のRole。

    Returns:
        InputFile: 指定PDFのResume比較用入力情報を作る。
    """

    return InputFile(
        role=role,
        logical_path=path.name,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _upgrade_record(
    path: Path,
    upgrade_id: str,
    source_v1: InputFile,
    source_v2: InputFile,
    translation_v1: InputFile,
    backend: str,
    resuming: bool,
) -> UpgradeRecord:
    """新規記録を作るか、三入力一致後に保存済み記録を返す。

    Args:
        path (Path): Upgrade Recordを書き込むPath。
        upgrade_id (str): 作成またはResumeするUpgrade処理ID。
        source_v1 (InputFile): 比較基準にする英文v1。
        source_v2 (InputFile): 変更を反映する英文v2。
        translation_v1 (InputFile): 比較基準にする日本語v1。
        backend (str): 翻訳に使用するBackend名。
        resuming (bool): 既存処理をResumeしているかどうか。

    Returns:
        UpgradeRecord: 新規記録を作るか、三入力一致後に保存済み記録を返す。

    Raises:
        InputError: `resume inputs do not match the saved upgrade`、`resume backend does not
            match the saved upgrade`、`upgrade to resume does not exist`のいずれかと判定した場合。
    """

    if path.is_file():
        record = load_model(path, UpgradeRecord)
        if (
            record.upgrade_id != upgrade_id
            or record.source_v1 != source_v1
            or record.source_v2 != source_v2
            or record.translation_v1 != translation_v1
        ):
            raise InputError("resume inputs do not match the saved upgrade")
        if record.backend != backend:
            raise InputError("resume backend does not match the saved upgrade")
        return record
    if resuming:
        raise InputError("upgrade to resume does not exist")
    now = datetime.now(UTC)
    record = UpgradeRecord(
        upgrade_id=upgrade_id,
        status="processing",
        source_v1=source_v1,
        source_v2=source_v2,
        translation_v1=translation_v1,
        backend=cast("Literal['llm', 'libretranslate']", backend),
        created_at=now,
        updated_at=now,
    )
    write_model(path, record)
    return record


def _validate_pdf(path: Path, role: str) -> None:
    """Upgrade入力を存在するPDF fileへ限定する。

    Args:
        path (Path): 入力条件を検証するPDFのPath。
        role (str): 入力または比較要素のRole。

    Raises:
        InputError: `f'{role} must be a PDF file'`と判定した場合。
    """

    if not path.is_file() or path.suffix.casefold() != ".pdf":
        raise InputError(f"{role} must be a PDF file")


def _tree_hash(directory: Path) -> str:
    """directory配下fileの相対pathとhashをfingerprint化する。

    Args:
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        str: directory配下fileの相対pathとhashをfingerprint化する。
    """

    if not directory.exists():
        return canonical_hash([])
    return canonical_hash(
        [
            (path.relative_to(directory).as_posix(), sha256_file(path))
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        ]
    )


def _update_llm_progress(
    record: UpgradeRecord,
    record_path: Path,
    task_directory: Path,
    task: LLMTaskName,
    reused: bool,
) -> None:
    """Call ArtifactからUpgradeのLLM集約進捗を再計算する。

    Args:
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        task_directory (Path): 対象Taskの成果物Directory。
        task (LLMTaskName): 状態またはCallを記録するTask名。
        reused (bool): LLM Callを再利用できたかどうか。
    """

    calls = [
        load_model(path, LLMCallArtifact)
        for path in sorted((task_directory / "calls").glob("*/call.json"))
    ]
    index_path = task_directory / "call-index.json"
    indexed = (
        set(load_model(index_path, LLMCallIndex).call_ids)
        if index_path.is_file()
        else {call.call_id for call in calls}
    )
    active = [call for call in calls if call.call_id in indexed]
    state = next(item for item in record.tasks if item.task.value == task)
    reused_calls = (
        len(active)
        if reused
        else sum(call.started_at < state.started_at for call in active)
    )
    progress = LLMProgress(
        task=task,
        planned_calls=len(active),
        completed_calls=len(active),
        reused_calls=reused_calls,
        failed_calls=0,
        updated_at=datetime.now(UTC),
    )
    record.llm_progress = [item for item in record.llm_progress if item.task != task]
    record.llm_progress.append(progress)
    record.updated_at = datetime.now(UTC)
    write_model(record_path, record)


def _stop(
    record: UpgradeRecord,
    record_path: Path,
    code: str,
    message: str,
) -> None:
    """公開条件を満たさないUpgradeを説明可能な失敗として停止する。

    Args:
        record (UpgradeRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        code (str): 診断または停止理由を識別するCode。
        message (str): 診断または停止理由のMessage。

    Raises:
        PipelineError: 公開条件を満たさないUpgradeを説明可能な失敗として停止する処理を完了できない場合。
    """

    record.status = "failed"
    record.error = ProcessingError(code=code, message=message, retryable=False)
    record.updated_at = datetime.now(UTC)
    write_model(record_path, record)
    raise PipelineError(message)

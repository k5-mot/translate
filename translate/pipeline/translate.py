"""英語PDFを日本語MarkdownとDOCXへ変換するTranslate Pipeline。"""

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
    TranslationRecord,
    UnpackManifest,
)
from translate.models.document import Document
from translate.pipeline import InputError, resolve_processing_id
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
from translate.tasks.review.check import check, targets_from_document
from translate.tasks.review.fix import apply_revisions
from translate.tasks.review.review import review
from translate.tasks.translation.translate import translate as translate_with_llm
from translate.tasks.translation.translate_lite import translate_lite

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.config import Config
    from translate.models.artifacts import LLMTaskName
    from translate.models.review import ReviewTarget


class PipelineError(RuntimeError):
    """Pipelineが公開条件を満たさず終了したことを表す。"""


class TranslationOutcome(BaseModel):
    """CLIへ返す処理IDと最終成果物path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    translation_id: str
    processing_directory: Path
    markdown: Path
    docx: Path


def translate_pdf(
    source: Path,
    config: Config,
    *,
    backend: str = "llm",
    processing_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> TranslationOutcome:
    """仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        backend (str): 翻訳に使用するBackend名。
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。
        outputs (Path | None): 成果物Root Directory。

    Returns:
        TranslationOutcome: 仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

    Raises:
        InputError: `backend must be llm or libretranslate`、`processing ID already
            exists`のいずれかと判定した場合。
    """

    source = source.resolve()
    _validate_source(source)
    if backend not in {"llm", "libretranslate"}:
        raise InputError("backend must be llm or libretranslate")
    config.require_translate(backend)
    translation_id = resolve_processing_id(processing_id, resume_id)
    outputs_root = (outputs or Path.cwd() / "outputs").resolve()
    processing_directory = outputs_root / source.stem / translation_id
    record_path = processing_directory / "translation.json"
    source_input = InputFile(
        role="source",
        logical_path=source.name,
        sha256=sha256_file(source),
        size_bytes=source.stat().st_size,
    )
    with ProcessingLock(processing_directory):
        if processing_id is not None and record_path.is_file():
            raise InputError("processing ID already exists")
        record = _translation_record(
            record_path,
            translation_id,
            source_input,
            backend,
            resume_id is not None,
        )
        try:
            return _translate_locked(
                source,
                config,
                backend,
                processing_directory,
                record_path,
                record,
            )
        except KeyboardInterrupt:
            cancel_processing(record, record_path)
            raise


def _translate_locked(
    source: Path,
    config: Config,
    backend: str,
    root: Path,
    record_path: Path,
    record: TranslationRecord,
) -> TranslationOutcome:
    """排他取得後のTranslate Task列を実行する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        backend (str): 翻訳に使用するBackend名。
        root (Path): 対象処理の成果物Root Directory。
        record_path (Path): 処理Record JSONのPath。
        record (TranslationRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        TranslationOutcome: 排他取得後のTranslate Task列を実行する。
    """

    template_root = Path(__file__).parents[1] / "templates"
    structure_rules = (template_root / "structure-rules.md").read_text(encoding="utf-8")
    translation_rules = (template_root / "translation-rules.md").read_text(
        encoding="utf-8"
    )
    review_rules = (template_root / "review-rules.md").read_text(encoding="utf-8")
    glossary = (template_root / "glossary.csv").read_text(encoding="utf-8")

    split_dir = root / "converter" / "split"
    split_fp = canonical_hash(
        {
            "task": "SPLIT",
            "source": record.source.sha256,
            "pages": config.pdf_split_pages,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.SPLIT,
        split_fp,
        split_dir,
        partial(split, source, split_dir, root, config.pdf_split_pages),
    )
    split_manifest = load_model(split_dir / "manifest.json", SplitManifest)

    docling_dir = root / "converter" / "docling"
    docling_fp = canonical_hash(
        {
            "task": "DOCLING",
            "split": canonical_hash(split_manifest),
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
        docling_dir,
        partial(convert_with_docling, split_manifest, docling_dir, root, config),
    )
    docling_manifest = load_model(docling_dir / "manifest.json", DoclingManifest)

    unpack_dir = root / "converter" / "unpack"
    unpack_fp = canonical_hash(
        {"task": "UNPACK", "input": canonical_hash(docling_manifest)}
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.UNPACK,
        unpack_fp,
        unpack_dir,
        partial(unpack, docling_manifest, unpack_dir, root),
    )
    unpack_manifest = load_model(unpack_dir / "manifest.json", UnpackManifest)

    merge_dir = root / "converter" / "merge"
    merge_fp = canonical_hash(
        {
            "task": "MERGE",
            "input": canonical_hash(unpack_manifest),
            "source": record.source.sha256,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.MERGE,
        merge_fp,
        merge_dir,
        partial(merge, unpack_manifest, source, merge_dir, root),
    )

    position_dir = root / "preprocess" / "position"
    position_fp = canonical_hash(
        {"task": "POSITION", "input": sha256_file(merge_dir / "document.json")}
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.POSITION,
        position_fp,
        position_dir,
        partial(position, merge_dir / "document.json", position_dir),
    )

    normalize_dir = root / "preprocess" / "normalize"
    normalize_fp = canonical_hash(
        {"task": "NORMALIZE", "input": sha256_file(position_dir / "document.json")}
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.NORMALIZE,
        normalize_fp,
        normalize_dir,
        partial(normalize, position_dir / "document.json", normalize_dir),
    )

    load_dir = root / "preprocess" / "load"
    load_fp = canonical_hash(
        {
            "task": "LOAD",
            "input": sha256_file(normalize_dir / "document.json"),
            "schema": 2,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.LOAD,
        load_fp,
        load_dir,
        partial(load, normalize_dir / "document.json", load_dir),
    )
    document = load_model(load_dir / "document.json", Document)

    structure_dir = root / "preprocess" / "structure"
    structure_fp = canonical_hash(
        {
            "task": "STRUCTURE",
            "document": canonical_hash(document),
            "source": record.source.sha256,
            "rules": canonical_hash(structure_rules),
            "model": config.openai_structure_model,
            "mode": config.llm_structured_output_mode,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
            "call_index": 4,
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
        structure_dir,
        partial(
            structure, document, source, structure_dir, root, config, structure_rules
        ),
    )
    _update_llm_progress(
        record, record_path, structure_dir, "STRUCTURE", reused_structure
    )
    document = load_model(structure_dir / "document.json", Document)

    translation_task = (
        TaskName.TRANSLATE if backend == "llm" else TaskName.TRANSLATE_LITE
    )
    translation_name = "translate" if backend == "llm" else "translate-lite"
    translation_dir = root / "translation" / translation_name
    translation_fp = canonical_hash(
        {
            "task": translation_task.value,
            "document": canonical_hash(document),
            "rules": canonical_hash(translation_rules),
            "glossary": canonical_hash(glossary),
            "backend": backend,
            "model": config.openai_translation_model
            if backend == "llm"
            else config.libretranslate_url,
            "reasoning_effort": "none" if backend == "llm" else None,
            "llm_endpoint": (
                config.openai_llm_base_url or config.openai_base_url
                if backend == "llm"
                else None
            ),
            "temperature": 0.7 if backend == "llm" else None,
            "repetition_penalty": 1.01 if backend == "llm" else None,
            "call_index": 8 if backend == "llm" else None,
        }
    )
    reused_translation = reusable_task(record, translation_task, translation_fp, root)
    action = (
        partial(
            translate_with_llm,
            document,
            translation_dir,
            root,
            config,
            translation_rules,
            glossary,
        )
        if backend == "llm"
        else partial(translate_lite, document, translation_dir, config)
    )
    _perform(
        record,
        record_path,
        root,
        translation_task,
        translation_fp,
        translation_dir,
        action,
    )
    if backend == "llm":
        _update_llm_progress(
            record, record_path, translation_dir, "TRANSLATE", reused_translation
        )
    document = load_model(translation_dir / "document.json", Document)

    check_dir = root / "review" / "check"
    initial_targets = targets_from_document(document)
    initial_check_fp = canonical_hash(
        {
            "task": "CHECK",
            "phase": "initial",
            "targets": [item.model_dump(mode="json") for item in initial_targets],
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.CHECK,
        initial_check_fp,
        check_dir,
        partial(_check_and_write, initial_targets, check_dir / "findings.json"),
    )
    checked = load_model(check_dir / "findings.json", CheckResult)

    review_dir = root / "review" / "review"
    review_fp = canonical_hash(
        {
            "task": "REVIEW",
            "targets": [item.model_dump(mode="json") for item in initial_targets],
            "check": canonical_hash(checked),
            "rules": canonical_hash(review_rules),
            "glossary": canonical_hash(glossary),
            "model": config.openai_review_model,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
            "call_index": 3,
        }
    )
    reused_review = reusable_task(record, TaskName.REVIEW, review_fp, root)
    _perform(
        record,
        record_path,
        root,
        TaskName.REVIEW,
        review_fp,
        review_dir,
        partial(
            review,
            initial_targets,
            checked,
            review_dir,
            root,
            config,
            review_rules,
            glossary,
        ),
    )
    _update_llm_progress(record, record_path, review_dir, "REVIEW", reused_review)
    reviewed = load_model(review_dir / "review.json", ReviewResult)

    fix_dir = root / "review" / "fix"
    fix_fp = canonical_hash(
        {
            "task": "FIX",
            "revision_guard": 3,
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
            fix_dir,
            partial(_fix_and_write, document, reviewed, fix_dir),
        )
        document = load_model(fix_dir / "document.json", Document)
    else:
        finish_task(record, record_path, TaskName.FIX, fix_fp, [], skipped=True)

    final_targets = targets_from_document(document)
    final_check_fp = canonical_hash(
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
        final_check_fp,
        check_dir,
        partial(_check_and_write, final_targets, check_dir / "final-findings.json"),
    )
    final_check = load_model(check_dir / "final-findings.json", CheckResult)
    if any(finding.category == "empty_translation" for finding in final_check.findings):
        _stop(
            record,
            record_path,
            "empty_translation",
            "Empty translations remain after review.",
        )

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
        lint_dir,
        partial(_lint_and_write, document, merge_dir, lint_dir),
    )
    linted = load_model(lint_dir / "report.json", LintResult)
    if not linted.valid:
        _stop(
            record, record_path, "lint_failed", "Document structure is not publishable."
        )

    cover_dir = root / "publisher" / "cover"
    cover_fp = canonical_hash(
        {"task": "COVER", "source": record.source.sha256, "dpi": 150}
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.COVER,
        cover_fp,
        cover_dir,
        partial(create_cover, source, cover_dir, root),
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
        markdown_dir,
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
        docx_dir,
        partial(
            publish,
            markdown_path,
            docx_path,
            template_root / "template.docx",
            config.http_request_timeout_seconds,
        ),
    )
    record.status = "succeeded"
    record.outputs = [
        describe_artifact(root, markdown_path),
        describe_artifact(root, docx_path),
    ]
    record.updated_at = datetime.now(UTC)
    record.error = None
    write_model(record_path, record)
    return TranslationOutcome(
        translation_id=record.translation_id,
        processing_directory=root,
        markdown=markdown_path,
        docx=docx_path,
    )


def _perform[ResultT](
    record: TranslationRecord,
    record_path: Path,
    root: Path,
    task: TaskName,
    fingerprint: str,
    task_directory: Path,
    action: Callable[[], ResultT],
) -> ResultT | None:
    """一つのTaskを再利用または状態更新付きで実行する。

    Args:
        record (TranslationRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。
        fingerprint (str): 入力と設定から算出した再利用判定Hash。
        task_directory (Path): 対象Taskの成果物Directory。
        action (Callable[[], ResultT]): Task本体として実行するCallable。

    Returns:
        ResultT | None: 一つのTaskを再利用または状態更新付きで実行する。
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
    finish_task(
        record,
        record_path,
        task,
        fingerprint,
        task_artifacts(root, task_directory),
    )
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
    """FIX結果のDocumentとoutcomeを別fileへ保存する。

    Args:
        document (Document): 変換または検証対象のDocument。
        reviewed (ReviewResult): 修正候補を含むReview結果。
        directory (Path): LLM Call Artifactの保存Directory。
    """

    result = apply_revisions(document, reviewed)
    directory.mkdir(parents=True, exist_ok=True)
    write_model(directory / "document.json", result.document)
    write_model(directory / "outcomes.json", result)


def _lint_and_write(document: Document, asset_root: Path, directory: Path) -> None:
    """LINTを実行し、valid=falseも正常な検査結果として保存する。

    Args:
        document (Document): 変換または検証対象のDocument。
        asset_root (Path): 参照先Assetを検証するRoot Directory。
        directory (Path): LLM Call Artifactの保存Directory。
    """

    result = lint(document, asset_root)
    directory.mkdir(parents=True, exist_ok=True)
    write_model(directory / "report.json", result)


def _translation_record(
    path: Path,
    translation_id: str,
    source: InputFile,
    backend: str,
    resuming: bool,
) -> TranslationRecord:
    """新規記録を作るか、入力一致を確認して保存済み記録を返す。

    Args:
        path (Path): Translation Recordを書き込むPath。
        translation_id (str): 作成またはResumeするTranslate処理ID。
        source (InputFile): 変換または検証対象の入力Source。
        backend (str): 翻訳に使用するBackend名。
        resuming (bool): 既存処理をResumeしているかどうか。

    Returns:
        TranslationRecord: 新規記録を作るか、入力一致を確認して保存済み記録を返す。

    Raises:
        InputError: `resume input does not match the saved translation`、`resume backend does
            not match the saved translation`、`translation to resume does not
            exist`のいずれかと判定した場合。
    """

    if path.is_file():
        record = load_model(path, TranslationRecord)
        if record.translation_id != translation_id or record.source != source:
            raise InputError("resume input does not match the saved translation")
        if record.backend != backend:
            raise InputError("resume backend does not match the saved translation")
        return record
    if resuming:
        raise InputError("translation to resume does not exist")
    now = datetime.now(UTC)
    record = TranslationRecord(
        translation_id=translation_id,
        status="processing",
        source=source,
        backend=cast("Literal['llm', 'libretranslate']", backend),
        created_at=now,
        updated_at=now,
    )
    write_model(path, record)
    return record


def _validate_source(source: Path) -> None:
    """Translate入力を存在するPDF fileへ限定する。

    Args:
        source (Path): 変換または検証対象の入力Source。

    Raises:
        InputError: `translate source must be a PDF file`と判定した場合。
    """

    if not source.is_file() or source.suffix.casefold() != ".pdf":
        raise InputError("translate source must be a PDF file")


def _tree_hash(directory: Path) -> str:
    """directory配下fileの相対pathとhashから決定的なfingerprintを作る。

    Args:
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        str: directory配下fileの相対pathとhashから決定的なfingerprintを作る。
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
    record: TranslationRecord,
    record_path: Path,
    task_directory: Path,
    task: LLMTaskName,
    reused: bool,
) -> None:
    """Call Artifactを正本としてTaskのLLM集約進捗を再計算する。

    Args:
        record (TranslationRecord): 状態またはTask情報を更新する処理Record。
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
    record: TranslationRecord,
    record_path: Path,
    code: str,
    message: str,
) -> None:
    """公開条件を満たさない処理を説明可能な最上位失敗として停止する。

    Args:
        record (TranslationRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        code (str): 診断または停止理由を識別するCode。
        message (str): 診断または停止理由のMessage。

    Raises:
        PipelineError: 公開条件を満たさない処理を説明可能な最上位失敗として停止する処理を完了できない場合。
    """

    record.status = "failed"
    record.error = ProcessingError(code=code, message=message, retryable=False)
    record.updated_at = datetime.now(UTC)
    write_model(record_path, record)
    raise PipelineError(message)

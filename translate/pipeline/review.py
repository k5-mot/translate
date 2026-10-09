"""独立した英語原文と日本語訳文を比較するReview Pipeline。"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

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
    DoclingManifest,
    InputFile,
    LLMCallArtifact,
    LLMCallIndex,
    LLMProgress,
    ReviewRecord,
    ReviewResult,
    SplitManifest,
    TaskName,
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
from translate.tasks.publisher.report import create_report
from translate.tasks.review.align import align
from translate.tasks.review.check import check
from translate.tasks.review.review import review

if TYPE_CHECKING:
    from collections.abc import Callable

    from translate.common.config import Config
    from translate.models.artifacts import LLMTaskName
    from translate.models.review import ReviewTarget


class ReviewOutcome(BaseModel):
    """CLIへ返すReview IDとReport path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    review_id: str
    processing_directory: Path
    report: Path


def review_pdfs(
    source: Path,
    translation: Path,
    config: Config,
    *,
    processing_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> ReviewOutcome:
    """二つのPDFを独立に前処理し、ALIGN、CHECK、REVIEW、REPORTを実行する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        translation (Path): Review対象の日本語訳。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。
        outputs (Path | None): 成果物Root Directory。

    Returns:
        ReviewOutcome: 二つのPDFを独立に前処理し、ALIGN、CHECK、REVIEW、REPORTを実行する。

    Raises:
        InputError: `processing ID already exists`と判定した場合。
    """

    source = source.resolve()
    translation = translation.resolve()
    _validate_pdf(source, "source")
    _validate_pdf(translation, "translation")
    config.require_review()
    review_id = resolve_processing_id(processing_id, resume_id)
    outputs_root = (outputs or Path.cwd() / "outputs").resolve()
    root = outputs_root / translation.stem / review_id
    record_path = root / "review.json"
    source_input = _input(source, "source")
    translation_input = _input(translation, "translation")
    with ProcessingLock(root):
        if processing_id is not None and record_path.is_file():
            raise InputError("processing ID already exists")
        record = _review_record(
            record_path,
            review_id,
            source_input,
            translation_input,
            resume_id is not None,
        )
        try:
            return _review_locked(
                source, translation, config, root, record_path, record
            )
        except KeyboardInterrupt:
            cancel_processing(record, record_path)
            raise


def _review_locked(
    source: Path,
    translation: Path,
    config: Config,
    root: Path,
    record_path: Path,
    record: ReviewRecord,
) -> ReviewOutcome:
    """排他取得後の比較Review Task列を実行する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        translation (Path): Review対象の日本語訳。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        root (Path): 対象処理の成果物Root Directory。
        record_path (Path): 処理Record JSONのPath。
        record (ReviewRecord): 状態またはTask情報を更新する処理Record。

    Returns:
        ReviewOutcome: 排他取得後の比較Review Task列を実行する。
    """

    template_root = Path(__file__).parents[1] / "templates"
    rules = (template_root / "review-rules.md").read_text(encoding="utf-8")
    glossary = (template_root / "glossary.csv").read_text(encoding="utf-8")

    source_split_dir = root / "converter" / "source" / "split"
    translation_split_dir = root / "converter" / "translation" / "split"
    split_fp = canonical_hash(
        {
            "task": "SPLIT",
            "source": record.source.sha256,
            "translation": record.translation.sha256,
            "pages": config.pdf_split_pages,
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.SPLIT,
        split_fp,
        [source_split_dir, translation_split_dir],
        partial(
            _call_pair,
            partial(split, source, source_split_dir, root, config.pdf_split_pages),
            partial(
                split, translation, translation_split_dir, root, config.pdf_split_pages
            ),
        ),
    )
    source_split = load_model(source_split_dir / "manifest.json", SplitManifest)
    translation_split = load_model(
        translation_split_dir / "manifest.json", SplitManifest
    )

    source_docling_dir = root / "converter" / "source" / "docling"
    translation_docling_dir = root / "converter" / "translation" / "docling"
    docling_fp = canonical_hash(
        {
            "task": "DOCLING",
            "source": canonical_hash(source_split),
            "translation": canonical_hash(translation_split),
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
        [source_docling_dir, translation_docling_dir],
        partial(
            _call_pair,
            partial(
                convert_with_docling, source_split, source_docling_dir, root, config
            ),
            partial(
                convert_with_docling,
                translation_split,
                translation_docling_dir,
                root,
                config,
            ),
        ),
    )
    source_docling = load_model(source_docling_dir / "manifest.json", DoclingManifest)
    translation_docling = load_model(
        translation_docling_dir / "manifest.json", DoclingManifest
    )

    source_unpack_dir = root / "converter" / "source" / "unpack"
    translation_unpack_dir = root / "converter" / "translation" / "unpack"
    unpack_fp = canonical_hash(
        {
            "task": "UNPACK",
            "source": canonical_hash(source_docling),
            "translation": canonical_hash(translation_docling),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.UNPACK,
        unpack_fp,
        [source_unpack_dir, translation_unpack_dir],
        partial(
            _call_pair,
            partial(unpack, source_docling, source_unpack_dir, root),
            partial(unpack, translation_docling, translation_unpack_dir, root),
        ),
    )
    source_unpack = load_model(source_unpack_dir / "manifest.json", UnpackManifest)
    translation_unpack = load_model(
        translation_unpack_dir / "manifest.json", UnpackManifest
    )

    source_merge_dir = root / "converter" / "source" / "merge"
    translation_merge_dir = root / "converter" / "translation" / "merge"
    merge_fp = canonical_hash(
        {
            "task": "MERGE",
            "source": canonical_hash(source_unpack),
            "translation": canonical_hash(translation_unpack),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.MERGE,
        merge_fp,
        [source_merge_dir, translation_merge_dir],
        partial(
            _call_pair,
            partial(merge, source_unpack, source, source_merge_dir, root),
            partial(
                merge, translation_unpack, translation, translation_merge_dir, root
            ),
        ),
    )

    source_document, translation_document = _preprocess_pair(
        record,
        record_path,
        root,
        source_merge_dir,
        translation_merge_dir,
    )

    align_dir = root / "review" / "align"
    align_fp = canonical_hash(
        {
            "task": "ALIGN",
            "source": canonical_hash(source_document),
            "translation": canonical_hash(translation_document),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.ALIGN,
        align_fp,
        [align_dir],
        partial(_align_and_write, source_document, translation_document, align_dir),
    )
    alignment = load_model(align_dir / "alignment.json", AlignmentResult)

    check_dir = root / "review" / "check"
    check_fp = canonical_hash(
        {
            "task": "CHECK",
            "targets": [item.model_dump(mode="json") for item in alignment.targets],
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.CHECK,
        check_fp,
        [check_dir],
        partial(_check_and_write, alignment.targets, check_dir),
    )
    checked = load_model(check_dir / "findings.json", CheckResult)

    review_dir = root / "review" / "review"
    review_fp = canonical_hash(
        {
            "task": "REVIEW",
            "targets": [item.model_dump(mode="json") for item in alignment.targets],
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
            alignment.targets,
            checked,
            review_dir,
            root,
            config,
            rules,
            glossary,
        ),
    )
    _update_llm_progress(record, record_path, review_dir, "REVIEW", reused)
    reviewed = load_model(review_dir / "review.json", ReviewResult)

    report_dir = root / "publisher" / "report"
    report_path = report_dir / "review.md"
    report_fp = canonical_hash(
        {
            "task": "REPORT",
            "alignment": canonical_hash(alignment),
            "check": canonical_hash(checked),
            "review": canonical_hash(reviewed),
        }
    )
    _perform(
        record,
        record_path,
        root,
        TaskName.REPORT,
        report_fp,
        [report_dir],
        partial(create_report, alignment, checked, reviewed, report_path),
    )
    record.status = "succeeded"
    record.outputs = [describe_artifact(root, report_path)]
    record.updated_at = datetime.now(UTC)
    record.error = None
    write_model(record_path, record)
    return ReviewOutcome(
        review_id=record.review_id,
        processing_directory=root,
        report=report_path,
    )


def _preprocess_pair(
    record: ReviewRecord,
    record_path: Path,
    root: Path,
    source_merge_dir: Path,
    translation_merge_dir: Path,
) -> tuple[Document, Document]:
    """POSITION、NORMALIZE、LOADを原文と訳文の両方へ同じ順序で適用する。

    Args:
        record (ReviewRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        source_merge_dir (Path): 原文側の統合済みDocument Directory。
        translation_merge_dir (Path): 訳文側の統合済みDocument Directory。

    Returns:
        tuple[Document, Document]: POSITION、NORMALIZE、LOADを原文と訳文の両方へ同じ順序で適用する。
    """

    current_source = source_merge_dir / "document.json"
    current_translation = translation_merge_dir / "document.json"
    paths = {
        "source": root / "preprocess" / "source",
        "translation": root / "preprocess" / "translation",
    }
    for task, function, name in (
        (TaskName.POSITION, position, "position"),
        (TaskName.NORMALIZE, normalize, "normalize"),
        (TaskName.LOAD, load, "load"),
    ):
        source_dir = paths["source"] / name
        translation_dir = paths["translation"] / name
        fingerprint = canonical_hash(
            {
                "task": task.value,
                "source": sha256_file(current_source),
                "translation": sha256_file(current_translation),
                "schema": 2 if task == TaskName.LOAD else 1,
            }
        )
        _perform(
            record,
            record_path,
            root,
            task,
            fingerprint,
            [source_dir, translation_dir],
            partial(
                _call_pair,
                partial(function, current_source, source_dir),
                partial(function, current_translation, translation_dir),
            ),
        )
        current_source = source_dir / "document.json"
        current_translation = translation_dir / "document.json"
    return (
        load_model(current_source, Document),
        load_model(current_translation, Document),
    )


def _perform[ResultT](
    record: ReviewRecord,
    record_path: Path,
    root: Path,
    task: TaskName,
    fingerprint: str,
    task_directories: list[Path],
    action: Callable[[], ResultT],
) -> ResultT | None:
    """比較Reviewの一Taskを再利用または状態更新付きで実行する。

    Args:
        record (ReviewRecord): 状態またはTask情報を更新する処理Record。
        record_path (Path): 処理Record JSONのPath。
        root (Path): 対象処理の成果物Root Directory。
        task (TaskName): 状態またはCallを記録するTask名。
        fingerprint (str): 入力と設定から算出した再利用判定Hash。
        task_directories (list[Path]): 再利用判定用のTask Directory列。
        action (Callable[[], ResultT]): Task本体として実行するCallable。

    Returns:
        ResultT | None: 比較Reviewの一Taskを再利用または状態更新付きで実行する。
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


def _call_pair[FirstT, SecondT](
    first: Callable[[], FirstT], second: Callable[[], SecondT]
) -> tuple[FirstT, SecondT]:
    """同じTaskの原文分岐と訳文分岐を順に実行する。

    Args:
        first (Callable[[], FirstT]): 原文側処理を実行するCallable。
        second (Callable[[], SecondT]): 訳文側処理を実行するCallable。

    Returns:
        tuple[FirstT, SecondT]: 同じTaskの原文分岐と訳文分岐を順に実行する。
    """

    return first(), second()


def _align_and_write(
    source: Document,
    translation: Document,
    directory: Path,
) -> AlignmentResult:
    """ALIGN結果を専用directoryへ保存する。

    Args:
        source (Document): 変換または検証対象の入力Source。
        translation (Document): Review対象の日本語訳。
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        AlignmentResult: ALIGN結果を専用directoryへ保存する。
    """

    result = align(source, translation)
    write_model(directory / "alignment.json", result)
    return result


def _check_and_write(targets: list[ReviewTarget], directory: Path) -> CheckResult:
    """CHECK結果を専用directoryへ保存する。

    Args:
        targets (list[ReviewTarget]): CHECKまたはREVIEW対象一覧。
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        CheckResult: CHECK結果を専用directoryへ保存する。
    """

    result = check(targets)
    write_model(directory / "findings.json", result)
    return result


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


def _review_record(
    path: Path,
    review_id: str,
    source: InputFile,
    translation: InputFile,
    resuming: bool,
) -> ReviewRecord:
    """新規Review記録を作るか、二入力一致後に保存済み記録を返す。

    Args:
        path (Path): Review Recordを書き込むPath。
        review_id (str): 作成またはResumeするReview処理ID。
        source (InputFile): 変換または検証対象の入力Source。
        translation (InputFile): Review対象の日本語訳。
        resuming (bool): 既存処理をResumeしているかどうか。

    Returns:
        ReviewRecord: 新規Review記録を作るか、二入力一致後に保存済み記録を返す。

    Raises:
        InputError: `resume inputs do not match the saved review`、`review to resume does not
            exist`のいずれかと判定した場合。
    """

    if path.is_file():
        record = load_model(path, ReviewRecord)
        if (
            record.review_id != review_id
            or record.source != source
            or record.translation != translation
        ):
            raise InputError("resume inputs do not match the saved review")
        return record
    if resuming:
        raise InputError("review to resume does not exist")
    now = datetime.now(UTC)
    record = ReviewRecord(
        review_id=review_id,
        status="processing",
        source=source,
        translation=translation,
        created_at=now,
        updated_at=now,
    )
    write_model(path, record)
    return record


def _validate_pdf(path: Path, role: str) -> None:
    """Review入力roleを存在するPDF fileへ限定する。

    Args:
        path (Path): 入力条件を検証するPDFのPath。
        role (str): 入力または比較要素のRole。

    Raises:
        InputError: `f'{role} must be a PDF file'`と判定した場合。
    """

    if not path.is_file() or path.suffix.casefold() != ".pdf":
        raise InputError(f"{role} must be a PDF file")


def _update_llm_progress(
    record: ReviewRecord,
    record_path: Path,
    task_directory: Path,
    task: LLMTaskName,
    reused: bool,
) -> None:
    """Call Artifactを正本としてREVIEWの集約進捗を再計算する。

    Args:
        record (ReviewRecord): 状態またはTask情報を更新する処理Record。
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

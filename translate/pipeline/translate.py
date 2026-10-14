"""英語PDFを日本語MarkdownとDOCXへ変換するTranslate Pipeline。"""

from datetime import UTC, datetime
from functools import partial
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ProcessingLock,
    cancel_processing,
    canonical_hash,
    describe_artifact,
    finish_task,
    load_model,
    sha256_file,
    write_model,
)
from translate.common.config import Config, validate_config
from translate.common.logger import processing_logging
from translate.models.artifacts import (
    CoverResult,
    InputFile,
    LintResult,
    LLMCallArtifact,
    LLMCallIndex,
    LLMProgress,
    LLMTaskName,
    ProcessingError,
    ReviewResult,
    TaskName,
    TranslationRecord,
)
from translate.models.document import Document
from translate.models.review import targets_from_document
from translate.pipeline import (
    InputError,
    perform_task,
    prepare_documents,
    resolve_processing_id,
)

structure = import_module("translate.tasks.13_structure").structure
create_cover = import_module("translate.tasks.51_cover").create_cover
publish_pandoc = import_module("translate.tasks.53_pandoc").publish
publish_ooxml = import_module("translate.tasks.54_ooxml").publish
lint = import_module("translate.tasks.50_lint").lint
convert_document = import_module("translate.tasks.52_markdown").convert_document
apply_revisions = import_module("translate.tasks.42_fix").apply_revisions
review = import_module("translate.tasks.41_review").review
translate_with_llm = import_module("translate.tasks.30_translate").translate


class PipelineError(RuntimeError):
    """Pipelineが公開条件を満たさず終了したことを表す。"""


class TranslationOutcome(BaseModel):
    """UIへ返す処理IDと最終成果物path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    translation_id: str
    processing_directory: Path
    markdown: Path
    docx: Path


def translate_pdf(
    source: Path,
    config: Config,
    *,
    processing_id: str | None = None,
    resume_id: str | None = None,
    outputs: Path | None = None,
) -> TranslationOutcome:
    """仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

    Args:
        source (Path): 変換または検証対象の入力Source。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。
        outputs (Path | None): 成果物Root Directory。

    Returns:
        TranslationOutcome: 仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

    Raises:
        InputError: 入力PDFまたは処理IDが不正な場合。
    """

    source = source.resolve()
    _validate_source(source)
    validate_config(config, "translate")
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
    with (
        ProcessingLock(processing_directory),
        processing_logging(processing_directory, config.log_level),
    ):
        if processing_id is not None and record_path.is_file():
            raise InputError("processing ID already exists")
        record = _translation_record(
            record_path,
            translation_id,
            source_input,
            resume_id is not None,
        )
        try:
            return _translate_locked(
                source,
                config,
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
    root: Path,
    record_path: Path,
    record: TranslationRecord,
) -> TranslationOutcome:
    """前処理、翻訳、レビューと修正を経てMarkdownとDOCXを公開する。

    Args:
        source: 入力PDF。
        config: 外部接続とLLM予算の設定。
        root: 処理IDの成果物directory。
        record_path: 処理記録の保存先。
        record: 入力照合済みの処理記録。

    Returns:
        公開したMarkdownと最終DOCXのPath。

    Raises:
        PipelineError: LINTが文書構造の問題を検出した場合。
        Exception: Taskが失敗した場合。
    """
    templates = Path(__file__).parents[1] / "templates"
    rules = {
        task: (templates / f"{name}-rules.md").read_text(encoding="utf-8")
        for task, name in (
            ("STRUCTURE", "structure"),
            ("TRANSLATE", "translation"),
            ("REVIEW", "review"),
        )
    }
    glossary = (templates / "glossary.csv").read_text(encoding="utf-8")
    documents, assets = prepare_documents(
        {"": source}, record, record_path, root, config
    )
    document, merge_dir = documents[""], assets[""]
    run = partial(perform_task, record, record_path, root)

    structure_dir = root / "preprocess" / "structure"
    reused = run(
        TaskName.STRUCTURE,
        {"document": document, "source": record.source.sha256},
        [
            (
                structure_dir,
                partial(
                    structure,
                    document,
                    source,
                    structure_dir,
                    root,
                    config,
                    rules["STRUCTURE"],
                ),
            )
        ],
    )
    _update_llm_progress(record, record_path, structure_dir, "STRUCTURE", reused)
    document = load_model(structure_dir / "document.json", Document)

    translation_dir = root / "translation" / "translate"
    reused = run(
        TaskName.TRANSLATE,
        document,
        [
            (
                translation_dir,
                partial(
                    translate_with_llm,
                    document,
                    translation_dir,
                    root,
                    config,
                    rules["TRANSLATE"],
                    glossary,
                ),
            )
        ],
    )
    _update_llm_progress(record, record_path, translation_dir, "TRANSLATE", reused)
    document = load_model(translation_dir / "document.json", Document)

    review_dir = root / "review" / "review"
    targets = targets_from_document(document)
    reused = run(
        TaskName.REVIEW,
        targets,
        [
            (
                review_dir,
                partial(
                    review,
                    targets,
                    review_dir,
                    root,
                    config,
                    rules["REVIEW"],
                    glossary,
                ),
            )
        ],
    )
    _update_llm_progress(record, record_path, review_dir, "REVIEW", reused)
    reviewed = load_model(review_dir / "review.json", ReviewResult)

    fix_dir = root / "review" / "fix"
    fix_inputs = {"document": document, "review": reviewed}
    if reviewed.revisions:
        run(
            TaskName.FIX,
            fix_inputs,
            [(fix_dir, partial(_fix_and_write, document, reviewed, fix_dir))],
        )
        document = load_model(fix_dir / "document.json", Document)
    else:
        finish_task(
            record,
            record_path,
            TaskName.FIX,
            canonical_hash({"task": "FIX", "inputs": fix_inputs}),
            [],
            skipped=True,
        )

    lint_dir = root / "publisher" / "lint"
    run(
        TaskName.LINT,
        {"document": document, "assets": _tree_hash(merge_dir / "assets")},
        [(lint_dir, partial(_lint_and_write, document, merge_dir, lint_dir))],
    )
    if not load_model(lint_dir / "report.json", LintResult).valid:
        _stop(
            record, record_path, "lint_failed", "Document structure is not publishable."
        )

    cover_dir = root / "publisher" / "cover"
    run(
        TaskName.COVER,
        record.source.sha256,
        [(cover_dir, partial(create_cover, source, cover_dir, root))],
    )
    cover = load_model(cover_dir / "manifest.json", CoverResult)
    markdown_dir = root / "publisher" / "markdown"
    markdown_path = markdown_dir / "document.ja.md"
    run(
        TaskName.MARKDOWN,
        {
            "document": document,
            "cover": cover,
            "assets": _tree_hash(merge_dir / "assets"),
        },
        [
            (
                markdown_dir,
                partial(
                    convert_document,
                    document,
                    markdown_path,
                    root / cover.image.relative_path,
                    merge_dir,
                    set(cover.excluded_page_numbers),
                    config.http_request_timeout_seconds,
                ),
            )
        ],
    )
    pandoc_dir = root / "publisher" / "pandoc"
    raw_docx = pandoc_dir / "document.raw.docx"
    run(
        TaskName.PANDOC,
        sha256_file(markdown_path),
        [
            (
                pandoc_dir,
                partial(
                    publish_pandoc,
                    markdown_path,
                    raw_docx,
                    templates / "template.docx",
                    config.http_request_timeout_seconds,
                ),
            )
        ],
    )
    docx_dir = root / "publisher" / "ooxml"
    docx_path = docx_dir / "document.ja.docx"
    run(
        TaskName.OOXML,
        sha256_file(raw_docx),
        [(docx_dir, partial(publish_ooxml, raw_docx, docx_path))],
    )
    record.status = "succeeded"
    record.outputs = [
        describe_artifact(root, path) for path in (markdown_path, docx_path)
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
    resuming: bool,
) -> TranslationRecord:
    """新規記録を作るか、入力一致を確認して保存済み記録を返す。

    Args:
        path (Path): Translation Recordを書き込むPath。
        translation_id (str): 作成またはResumeするTranslate処理ID。
        source (InputFile): 変換または検証対象の入力Source。
        resuming (bool): 既存処理をResumeしているかどうか。

    Returns:
        TranslationRecord: 新規記録を作るか、入力一致を確認して保存済み記録を返す。

    Raises:
        InputError: Resume対象がない、または入力が一致しない場合。
    """

    if path.is_file():
        record = load_model(path, TranslationRecord)
        if record.translation_id != translation_id or record.source != source:
            raise InputError("resume input does not match the saved translation")
        return record
    if resuming:
        raise InputError("translation to resume does not exist")
    now = datetime.now(UTC)
    record = TranslationRecord(
        translation_id=translation_id,
        status="processing",
        source=source,
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

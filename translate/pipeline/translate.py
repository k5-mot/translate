"""英語PDFを日本語MarkdownとDOCXへ変換するTranslate Pipeline。"""

from datetime import UTC, datetime
from functools import partial
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ArtifactStore,
    ProcessingLock,
    canonical_hash,
    describe_artifact,
    load_model,
    sha256_file,
    write_model,
)
from translate.adapters.pandoc import Pandoc
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
from translate.models.review import ReviewTarget
from translate.pipeline import (
    InputError,
    PipelineRun,
    resolve_processing_id,
)

StructureTask = import_module("translate.tasks.13_structure").StructureTask
create_cover = import_module("translate.tasks.51_cover").create_cover
publish_pandoc = import_module("translate.tasks.53_pandoc").publish
publish_ooxml = import_module("translate.tasks.54_ooxml").publish
lint = import_module("translate.tasks.50_lint").lint
MarkdownTask = import_module("translate.tasks.52_markdown").MarkdownTask
apply_revisions = import_module("translate.tasks.42_fix").apply_revisions
ReviewTask = import_module("translate.tasks.41_review").ReviewTask
TranslationTask = import_module("translate.tasks.30_translate").TranslationTask


class PipelineError(RuntimeError):
    """Pipelineが公開条件を満たさず終了したことを表す。"""


class TranslationOutcome(BaseModel):
    """UIへ返す処理IDと最終成果物path。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    translation_id: str
    processing_directory: Path
    markdown: Path
    docx: Path


class TranslatePipeline:
    """Translateの設定と実行記録を保持し、入力検証から成果物公開まで進める。"""

    def __init__(self, config: Config, outputs: Path | None = None) -> None:
        """外部接続の設定と成果物の基準ディレクトリを受け取る。

        Args:
            config: 操作で使用する接続と処理上限。
            outputs: 出力先。省略時は実行時の作業ディレクトリ内のoutputs。
        """
        self.config = config
        self.outputs = outputs

    def run(
        self,
        source: Path,
        *,
        processing_id: str | None = None,
        resume_id: str | None = None,
    ) -> TranslationOutcome:
        """仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

        Args:
            source (Path): 変換または検証対象の入力Source。
            processing_id (str | None): 新規処理またはResume対象の処理ID。
            resume_id (str | None): Resume対象として指定された処理ID。

        Returns:
            TranslationOutcome: 仕様順にTaskを実行し、有効なTaskとLLM Callだけを再利用する。

        Raises:
            InputError: 入力PDFまたは処理IDが不正な場合。
        """

        source = source.resolve()
        _validate_source(source)
        validate_config(self.config, "translate")
        translation_id = resolve_processing_id(processing_id, resume_id)
        outputs_root = (self.outputs or Path.cwd() / "outputs").resolve()
        self.root = outputs_root / source.stem / translation_id
        self.record_path = self.root / "translation.json"
        source_input = InputFile(
            role="source",
            logical_path=source.name,
            sha256=sha256_file(source),
            size_bytes=source.stat().st_size,
        )
        with (
            ProcessingLock(self.root),
            processing_logging(self.root, self.config.log_level),
        ):
            if processing_id is not None and self.record_path.is_file():
                raise InputError("processing ID already exists")
            self.record = _translation_record(
                self.record_path,
                translation_id,
                source_input,
                resume_id is not None,
            )
            try:
                return self._translate_locked(source)
            except KeyboardInterrupt:
                ArtifactStore(self.record, self.record_path).cancel_processing()
                raise

    def _translate_locked(
        self,
        source: Path,
    ) -> TranslationOutcome:
        """前処理、翻訳、レビューと修正を経てMarkdownとDOCXを公開する。

        Args:
            source: 入力PDF。

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
        self.execution = PipelineRun(
            ArtifactStore(self.record, self.record_path), self.config
        )
        documents, assets = self.execution.prepare_documents({"": source})
        document, merge_dir = documents[""], assets[""]
        run = self.execution.perform_task

        structure_dir = self.root / "preprocess" / "structure"
        reused = run(
            TaskName.STRUCTURE,
            {"document": document, "source": self.record.source.sha256},
            [
                (
                    structure_dir,
                    partial(
                        StructureTask(
                            self.config, structure_dir, rules["STRUCTURE"]
                        ).run,
                        document,
                        source,
                        self.root,
                    ),
                )
            ],
        )
        self._update_llm_progress(structure_dir, "STRUCTURE", reused)
        document = load_model(structure_dir / "document.json", Document)

        translation_dir = self.root / "translation" / "translate"
        reused = run(
            TaskName.TRANSLATE,
            document,
            [
                (
                    translation_dir,
                    partial(
                        TranslationTask(
                            self.config, translation_dir, rules["TRANSLATE"], glossary
                        ).run,
                        document,
                        self.root,
                    ),
                )
            ],
        )
        self._update_llm_progress(translation_dir, "TRANSLATE", reused)
        document = load_model(translation_dir / "document.json", Document)

        review_dir = self.root / "review" / "review"
        targets = ReviewTarget.from_document(document)
        reused = run(
            TaskName.REVIEW,
            targets,
            [
                (
                    review_dir,
                    partial(
                        ReviewTask(
                            self.config, review_dir, rules["REVIEW"], glossary
                        ).run,
                        targets,
                        self.root,
                    ),
                )
            ],
        )
        self._update_llm_progress(review_dir, "REVIEW", reused)
        reviewed = load_model(review_dir / "review.json", ReviewResult)

        fix_dir = self.root / "review" / "fix"
        fix_inputs = {"document": document, "review": reviewed}
        if reviewed.revisions:
            run(
                TaskName.FIX,
                fix_inputs,
                [(fix_dir, partial(_fix_and_write, document, reviewed, fix_dir))],
            )
            document = load_model(fix_dir / "document.json", Document)
        else:
            self.execution.store.finish_task(
                TaskName.FIX,
                canonical_hash({"task": "FIX", "inputs": fix_inputs}),
                [],
                skipped=True,
            )

        lint_dir = self.root / "publisher" / "lint"
        run(
            TaskName.LINT,
            {"document": document, "assets": _tree_hash(merge_dir / "assets")},
            [(lint_dir, partial(_lint_and_write, document, merge_dir, lint_dir))],
        )
        if not load_model(lint_dir / "report.json", LintResult).valid:
            self._stop("lint_failed", "Document structure is not publishable.")

        cover_dir = self.root / "publisher" / "cover"
        run(
            TaskName.COVER,
            self.record.source.sha256,
            [(cover_dir, partial(create_cover, source, cover_dir, self.root))],
        )
        cover = load_model(cover_dir / "manifest.json", CoverResult)
        markdown_dir = self.root / "publisher" / "markdown"
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
                        MarkdownTask(
                            Pandoc(self.config.http_request_timeout_seconds)
                        ).run,
                        document,
                        markdown_path,
                        self.root / cover.image.relative_path,
                        merge_dir,
                        set(cover.excluded_page_numbers),
                    ),
                )
            ],
        )
        pandoc_dir = self.root / "publisher" / "pandoc"
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
                        self.config.http_request_timeout_seconds,
                    ),
                )
            ],
        )
        docx_dir = self.root / "publisher" / "ooxml"
        docx_path = docx_dir / "document.ja.docx"
        run(
            TaskName.OOXML,
            sha256_file(raw_docx),
            [(docx_dir, partial(publish_ooxml, raw_docx, docx_path))],
        )
        self.record.status = "succeeded"
        self.record.outputs = [
            describe_artifact(self.root, path) for path in (markdown_path, docx_path)
        ]
        self.record.updated_at = datetime.now(UTC)
        self.record.error = None
        write_model(self.record_path, self.record)
        return TranslationOutcome(
            translation_id=self.record.translation_id,
            processing_directory=self.root,
            markdown=markdown_path,
            docx=docx_path,
        )

    def _update_llm_progress(
        self,
        task_directory: Path,
        task: LLMTaskName,
        reused: bool,
    ) -> None:
        """Call Artifactを正本としてTaskのLLM集約進捗を再計算する。

        Args:
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
        state = next(item for item in self.record.tasks if item.task.value == task)
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
        self.record.llm_progress = [
            item for item in self.record.llm_progress if item.task != task
        ]
        self.record.llm_progress.append(progress)
        self.record.updated_at = datetime.now(UTC)
        write_model(self.record_path, self.record)

    def _stop(
        self,
        code: str,
        message: str,
    ) -> None:
        """公開条件を満たさない処理を説明可能な最上位失敗として停止する。

        Args:
            code (str): 診断または停止理由を識別するCode。
            message (str): 診断または停止理由のMessage。

        Raises:
            PipelineError: 公開条件を満たさない処理を説明可能な最上位失敗として停止する処理を完了できない場合。
        """

        self.record.status = "failed"
        self.record.error = ProcessingError(code=code, message=message, retryable=False)
        self.record.updated_at = datetime.now(UTC)
        write_model(self.record_path, self.record)
        raise PipelineError(message)


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

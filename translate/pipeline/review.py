"""原文と訳文をAgentで対応付け、指摘と修正提案を一覧化する。"""

import logging
from datetime import UTC, datetime
from difflib import SequenceMatcher
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from translate.adapters.artifact_store import (
    ArtifactStore,
    ProcessingLock,
    describe_artifact,
    load_model,
    write_model,
)
from translate.adapters.llm import (
    LLMClient,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.common.config import Config, validate_config
from translate.common.logger import processing_logging
from translate.models.artifacts import (
    LLMCallIndex,
    ReviewRecord,
    ReviewResult,
    TaskName,
)
from translate.models.document import Document
from translate.models.review import (
    AlignmentCandidate,
    AlignmentGroup,
    ReviewTarget,
)
from translate.pipeline import (
    MAX_REFERENCE_IDS,
    InputError,
    PipelineRun,
    agent_deadline,
    agent_units,
    completed_agent_calls,
    narrowed,
    pdf_inputs,
    positional_candidates,
    resolve_processing_id,
    translator_notes,
)
from translate.pipeline.matching import MatchingCandidates
from translate.tasks import MATCHING_VERSION

ReviewTask = import_module("translate.tasks.41_review").ReviewTask
logger = logging.getLogger(__name__)
# 起点の原文ごとに、候補を替えて照合する回数。
_MATCH_ATTEMPTS = 3
_DUPLICATE_FRONT_PAGE_MIN_CHARS = 100
_DUPLICATE_FRONT_PAGE_MIN_SIMILARITY = 0.85


def _copied_translation_front_page_ids(
    source: Document, translation: Document
) -> set[str]:
    """訳文の先頭に複製された英語原文ページがあれば、そのTextUnit IDを返す。

    Args:
        source: 英語原文。
        translation: Review対象の訳文。

    Returns:
        set[str]: OCR差の比較基準に原文LOAD本文を使う訳文unitのID。
    """
    if not source.pages or not translation.pages:
        return set()
    source_units = [
        unit
        for block in source.pages[0].blocks
        for unit in ([block.content] if block.content else [])
        + [cell.content for cell in block.cells]
    ]
    translation_units = [
        unit
        for block in translation.pages[0].blocks
        for unit in ([block.content] if block.content else [])
        + [cell.content for cell in block.cells]
    ]
    source_text = " ".join(unit.text("source") for unit in source_units)
    translation_text = " ".join(unit.text("source") for unit in translation_units)
    normalized_source = " ".join(source_text.casefold().split())
    normalized_translation = " ".join(translation_text.casefold().split())
    if min(len(normalized_source), len(normalized_translation)) < (
        _DUPLICATE_FRONT_PAGE_MIN_CHARS
    ):
        return set()
    japanese = sum(
        "\u3040" <= character <= "\u30ff" or "\u4e00" <= character <= "\u9fff"
        for character in normalized_translation
    )
    if japanese / len(normalized_translation) > 0.01:
        return set()
    # shortcut: checks only page 1; extend to later page pairs if copied originals can appear elsewhere.
    if (
        SequenceMatcher(None, normalized_source, normalized_translation).ratio()
        < _DUPLICATE_FRONT_PAGE_MIN_SIMILARITY
    ):
        return set()
    return {unit.id for unit in translation_units}


class ReviewOutcome(BaseModel):
    """UIへ返すReview IDと結果JSON。"""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)
    review_id: str
    processing_directory: Path
    result: Path


class ReviewPipeline:
    """Reviewの設定と実行記録を保持し、入力検証から成果物公開まで進める。"""

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
        translation: Path,
        *,
        processing_id: str | None = None,
        resume_id: str | None = None,
    ) -> ReviewOutcome:
        """二つのPDFを解析し、Agentが確定した一覧だけを公開する。

        Args:
            source: 英語原文PDF。
            translation: 日本語訳文PDF。
            processing_id: UIが発行した新規ID。
            resume_id: 再開するID。

        Returns:
            処理IDと指摘・修正提案のJSON。

        Raises:
            InputError: 入力・IDまたは再開条件が不正な場合。
            Exception: 前処理またはAgent操作が失敗した場合。
        """
        sources = {"source": source.resolve(), "translation": translation.resolve()}
        inputs = pdf_inputs(sources)
        validate_config(self.config, "review")
        identifier = resolve_processing_id(processing_id, resume_id)
        self.root = (
            (self.outputs or Path.cwd() / "outputs").resolve()
            / translation.stem
            / identifier
        )
        self.record_path = self.root / "state-review.json"
        with ProcessingLock(self.root):
            if self.record_path.is_file():
                self.record = load_model(self.record_path, ReviewRecord)
                if (
                    not resume_id
                    or self.record.review_id != identifier
                    or self.record.source != inputs["source"]
                    or self.record.translation != inputs["translation"]
                ):
                    raise InputError("Review ID already exists or resume inputs differ")
            else:
                if resume_id:
                    raise InputError("Review to resume does not exist")
                now = datetime.now(UTC)
                self.record = ReviewRecord(
                    review_id=identifier,
                    status="processing",
                    source=inputs["source"],
                    translation=inputs["translation"],
                    created_at=now,
                    updated_at=now,
                )
                write_model(self.record_path, self.record)
            with processing_logging(self.root, self.config.log_level, "review.log"):
                try:
                    self.execution = PipelineRun(
                        ArtifactStore(self.record, self.record_path), self.config
                    )
                    documents, _ = self.execution.prepare_documents(sources)
                    directory = self.root / "tasks" / "41-review"
                    self.execution.perform_task(
                        TaskName.REVIEW,
                        documents,
                        [
                            (
                                directory,
                                ReviewAgent(
                                    documents, directory, self.root, self.config
                                ).run,
                            )
                        ],
                    )
                    self.record.status, self.record.error = "succeeded", None
                    result_path = directory / "review.json"
                    self.record.outputs = [describe_artifact(self.root, result_path)]
                    self.record.updated_at = datetime.now(UTC)
                    write_model(self.record_path, self.record)
                except KeyboardInterrupt:
                    ArtifactStore(self.record, self.record_path).cancel_processing()
                    raise
        return ReviewOutcome(
            review_id=identifier, processing_directory=self.root, result=result_path
        )


class ReviewAgent:
    """原文unitを文書順に照合し、対応した組だけを評価して一覧を作る。"""

    def __init__(
        self,
        documents: dict[str, Document],
        directory: Path,
        root: Path,
        config: Config,
    ) -> None:
        """比較対象と処理の依存関係を受け取る。

        Args:
            documents: 役割名で区別した比較対象文書。
            directory: 操作の記録と最終一覧の保存先。
            root: 処理IDの保存先。
            config: LLMの接続と処理予算。
        """
        self.units = agent_units(documents)
        self.documents = documents
        self.notes = translator_notes(self.units["translation"])
        self.copied_front_page_ids = _copied_translation_front_page_ids(
            documents["source"], documents["translation"]
        )
        self.contexts = {
            role: document.unit_contexts() for role, document in documents.items()
        }
        self.candidates = MatchingCandidates(
            self.units, self.contexts, directory, config
        )
        self.directory = directory
        self.config = config
        self.root = root

    def run(self) -> ReviewResult:
        """照合、評価、対応のない要素の記録を順に行い、一覧を保存する。

        処理の順序は文書と保存済みCallだけで決まるため、再開時は同じ順序で
        保存済みの応答を再利用し、未完了の要求から続ける。

        Returns:
            対応関係、全指摘、修正提案および確認範囲。

        Raises:
            LLMError: 最小の範囲へ縮めても外部要求が失敗した場合。
        """
        self.client = LLMClient(self.config)
        self.client.deadline = agent_deadline(self.config, len(self.units["source"]))
        try:
            templates = Path(__file__).parents[1] / "templates"
            rules = (templates / "review-rules.md").read_text(encoding="utf-8")
            glossary = (templates / "glossary.csv").read_text(encoding="utf-8")
            # 対応群ごとに品質確認し、別の対象の不備を混入させない。
            self.review = ReviewTask(
                self.config.model_copy(update={"review_max_targets": 1}),
                self.directory,
                rules,
                glossary,
                contexts=self.contexts,
            )
            self.result = ReviewResult()
            self.matched: dict[str, set[str]] = {role: set() for role in self.units}
            self.call_ids: list[str] = []
            self.group_number = 0
            self.round_number = 0
            self._align()
            self._evaluate()
            self._record_unmatched()
            write_model(
                self.directory / "call-index.json",
                LLMCallIndex(
                    task="REVIEW", call_ids=list(dict.fromkeys(self.call_ids))
                ),
            )
            write_model(self.directory / "review.json", self.result)
            return self.result
        finally:
            self.client.client.close()

    def _next_round(self) -> int:
        """保存Callの連番を払い出す。

        Returns:
            int: 次の要求に使う連番。
        """
        self.round_number += 1
        return self.round_number - 1

    def _align(self) -> None:
        """原文unitを文書順に起点とし、候補を替えながら訳文との対応を確定する。"""
        for source_id in self.units["source"]:
            offered: set[str] = set()
            for _ in range(_MATCH_ATTEMPTS):
                if source_id in self.matched["source"]:
                    break
                available = {
                    "source": set(self.units["source"]) - self.matched["source"],
                    "translation": set(self.units["translation"])
                    - self.matched["translation"]
                    - self.notes
                    - offered,
                }
                if not available["translation"]:
                    break
                references = self.candidates.expand(
                    {"source": [source_id]}, available, MAX_REFERENCE_IDS
                )
                if not self.candidates.enabled:
                    references = positional_candidates(
                        self.units, references, available, "source"
                    )
                if not references.get("translation"):
                    break
                offered.update(references["translation"])
                self._match(references)

    def _match(self, references: dict[str, list[str]]) -> None:
        """候補集合を照合し、要求が失敗したら範囲を縮めて照合し直す。

        Args:
            references: 起点の原文を先頭に置いた照合範囲。
        """
        primary = references["source"][0]
        scope: dict[str, list[str]] | None = references
        while scope is not None and primary not in self.matched["source"]:
            chosen = {
                role: [
                    key for key in scope.get(role, []) if key not in self.matched[role]
                ]
                for role in self.units
            }
            if not chosen["translation"]:
                return
            try:
                call_id, response = self.review.match_documents(
                    {
                        role: [self.units[role][key] for key in ids]
                        for role, ids in chosen.items()
                    },
                    self.client,
                    self._next_round(),
                )
            except (
                LLMInputExceededError,
                LLMOutputExceededError,
                LLMInvalidResponseError,
            ) as error:
                logger.info(
                    "Narrowing Review match scope source=%s after %s",
                    primary,
                    type(error).__name__,
                )
                scope = narrowed(chosen, "source", ("translation",), 1)
                continue
            self.call_ids.append(call_id)
            for candidate in response.groups:
                if candidate.kind == "matched":
                    self._add_match(candidate)
            return

    def _add_match(self, candidate: AlignmentCandidate) -> None:
        """確定した対応を記録し、評価対象を作る。

        Args:
            candidate: 原文と訳文の両方を含む検証済みの対応。
        """
        self.group_number += 1
        group = AlignmentGroup(
            id=f"alignment-{self.group_number:06d}", **candidate.model_dump()
        )
        self.result.groups.append(group)
        self.matched["source"].update(group.source_ids)
        self.matched["translation"].update(group.translation_ids)
        # 数式とコードは翻訳せず原文の記法を残すため、訳文の評価対象にしない。
        if all(
            span.kind == "code"
            for key in group.source_ids
            for span in self.units["source"][key].spans
        ):
            group.reason = "数式・コードは翻訳の対象外のため、Reviewで評価しません。"
            return
        copied_page = set(group.translation_ids).issubset(self.copied_front_page_ids)
        translated = [self.units["translation"][key] for key in group.translation_ids]
        source_text = "\n".join(
            self.units["source"][key].text("source") for key in group.source_ids
        )
        # 複製された英語表紙は原文PDFが表しているため、OCR差を比較しない。
        self.result.targets.append(
            ReviewTarget(
                id=f"review/{group.id}",
                source=source_text,
                translation=source_text
                if copied_page
                else "\n".join(unit.text("source") for unit in translated),
                target_ids=group.translation_ids,
                spans=[]
                if copied_page
                else [span for unit in translated for span in unit.spans],
            )
        )

    def _evaluate(self) -> None:
        """対応した組ごとに訳文を評価し、指摘と修正提案を集める。"""
        if not self.result.targets:
            return
        round_number = self._next_round()
        evaluated = self.review.run(
            self.result.targets,
            self.root,
            operation="evaluate",
            round_number=round_number,
            publish=False,
            client=self.client,
            span_owners={
                span.id: key
                for target in self.result.targets
                for key in target.target_ids
                for span in self.units["translation"][key].spans
            },
        )
        self.result.findings = evaluated.findings
        self.result.revisions = evaluated.revisions
        self.result.reviewed_target_ids = [target.id for target in self.result.targets]
        self.call_ids.extend(
            call.call_id
            for call in completed_agent_calls(
                self.directory, matching_version=MATCHING_VERSION
            )
            if call.round == round_number and call.operation == "evaluate"
        )

    def _record_unmatched(self) -> None:
        """照合後も対応のない原文と訳文を、片側だけの対応として記録する。

        訳文だけの要素は訳者による補足などとみなし、評価も修正もしない。
        """
        for role, kind, reason in (
            (
                "source",
                "source_only",
                "対応する訳文が見つかりませんでした。訳抜けの可能性があります。",
            ),
            (
                "translation",
                "translation_only",
                "対応する英文がない訳文です。訳者による補足などとして、Reviewの対象外とし、指摘・修正しません。",
            ),
        ):
            for identifier in self.units[role]:
                if identifier in self.matched[role]:
                    continue
                self.group_number += 1
                self.result.groups.append(
                    AlignmentGroup(
                        id=f"alignment-{self.group_number:06d}",
                        kind=kind,
                        source_ids=[identifier] if role == "source" else [],
                        translation_ids=[identifier] if role == "translation" else [],
                        reason=reason,
                    )
                )

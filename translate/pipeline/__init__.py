"""Translate、Review、RegisterのTask順序と再開制御。"""

import math
import re
import time
from collections.abc import Callable, Mapping
from functools import partial
from importlib import import_module
from pathlib import Path
from uuid import UUID

from uuid_utils import uuid7

from translate.adapters.artifact_store import (
    ArtifactStore,
    canonical_hash,
    load_model,
    sha256_file,
    task_artifacts,
)
from translate.common.config import Config
from translate.models.artifacts import (
    DoclingManifest,
    InputFile,
    LLMCallArtifact,
    SplitManifest,
    TaskName,
    UnpackManifest,
)
from translate.models.document import Document, TextUnit


class InputError(ValueError):
    """入力またはResume指定の不備。"""


def resolve_processing_id(processing_id: str | None, resume_id: str | None) -> str:
    """UI指定ID、Resume IDまたは新規UUIDv7を一意に決定する。

    Args:
        processing_id (str | None): 新規処理またはResume対象の処理ID。
        resume_id (str | None): Resume対象として指定された処理ID。

    Returns:
        str: UUIDv7形式の処理ID。

    Raises:
        InputError: `processing ID and resume ID cannot be used together`、`processing ID
            must be a canonical UUIDv7`のいずれかと判定した場合。
    """

    if processing_id is not None and resume_id is not None:
        raise InputError("processing ID and resume ID cannot be used together")
    value = processing_id or resume_id
    if value is None:
        return str(uuid7())
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise InputError("processing ID must be a canonical UUIDv7") from error
    if parsed.version != 7 or str(parsed) != value.casefold():
        raise InputError("processing ID must be a canonical UUIDv7")
    return value


class PipelineRun:
    """共通の前処理とTask実行を、一つの保存記録と設定で進める。"""

    def __init__(self, store: ArtifactStore, config: Config) -> None:
        """Task実行に使用する記録管理と接続設定を受け取る。

        Args:
            store: 実行中の処理記録と成果物の保存先。
            config: PDF分割、DoclingおよびLLMの設定。
        """
        self.store = store
        self.config = config

    def perform_task(
        self,
        task: TaskName,
        inputs: object,
        jobs: list[tuple[Path, Callable[[], object]]],
    ) -> bool:
        """文書入力の一致と成果物の検証後に再利用し、必要なTaskだけ実行する。

        Args:
            task: 今回実行する工程名。
            inputs: 再開判定に使う文書由来の入力。設定・規則は含めない。
            jobs: 成果物directoryと実行処理の組。複数文書は同じ工程内で処理する。

        Returns:
            成功済みTaskを再利用した場合はTrue。

        Raises:
            Exception: Taskの失敗。記録に原因の種別を保存して伝播する。
        """
        fingerprint = canonical_hash({"task": task.value, "inputs": inputs})
        if self.store.reusable_task(task, fingerprint):
            return True
        self.store.start_task(task, fingerprint)
        try:
            for _, action in jobs:
                action()
            artifacts = [
                artifact
                for directory, _ in jobs
                for artifact in task_artifacts(self.store.root, directory)
            ]
            self.store.finish_task(task, fingerprint, artifacts)
        except Exception as error:
            self.store.fail_task(task, fingerprint, error)
            raise
        return False

    def prepare_documents(
        self,
        sources: dict[str, Path],
    ) -> tuple[dict[str, Document], dict[str, Path]]:
        """各PDFを同じ前処理工程へ通し、文書と原本assetの場所を返す。

        Translate・Review・Upgradeで共通の変換、保存、再開判定を使用する。

        Args:
            sources: 入力roleとPDFの組。Translateの単一文書だけroleを空文字にする。

        Returns:
            role別のDocumentとMERGE directoryの辞書。

        Raises:
            Exception: PDF解析・変換・成果物検証の失敗。
        """
        stages = (
            (TaskName.SPLIT, "00-split", "00_split", "split"),
            (TaskName.DOCLING, "01-docling", "01_docling", "convert"),
            (TaskName.UNPACK, "02-unpack", "02_unpack", "unpack"),
            (TaskName.MERGE, "03-merge", "03_merge", "merge"),
            (TaskName.POSITION, "10-position", "10_position", "position"),
            (TaskName.NORMALIZE, "11-normalize", "11_normalize", "normalize"),
            (TaskName.LOAD, "12-load", "12_load", "load"),
        )
        previous = dict(sources)
        originals = {role: sha256_file(path) for role, path in sources.items()}
        merge_roots: dict[str, Path] = {}
        for task, category, module, function in stages:
            action = getattr(import_module(f"translate.tasks.{module}"), function)
            jobs: list[tuple[Path, Callable[[], object]]] = []
            next_inputs: dict[str, Path] = {}
            for role, source in sources.items():
                directory = (
                    self.store.root / "tasks" / category / role.replace("_", "-")
                )
                current = previous[role]
                if task == TaskName.SPLIT:
                    arguments = (
                        source,
                        directory,
                        self.store.root,
                        self.config.pdf_split_pages,
                    )
                elif task == TaskName.DOCLING:
                    arguments = (
                        load_model(current, SplitManifest),
                        directory,
                        self.store.root,
                        self.config,
                    )
                elif task == TaskName.UNPACK:
                    arguments = (
                        load_model(current, DoclingManifest),
                        directory,
                        self.store.root,
                    )
                elif task == TaskName.MERGE:
                    arguments = (
                        load_model(current, UnpackManifest),
                        source,
                        directory,
                        self.store.root,
                    )
                    merge_roots[role] = directory
                elif task == TaskName.POSITION:
                    arguments = (current, directory, source)
                else:
                    arguments = (current, directory)
                jobs.append((directory, partial(action, *arguments)))
                name = (
                    "manifest.json"
                    if task in {TaskName.SPLIT, TaskName.DOCLING, TaskName.UNPACK}
                    else "document.json"
                )
                next_inputs[role] = directory / name
            self.perform_task(
                task,
                {
                    "originals": originals,
                    "documents": {
                        role: sha256_file(path) for role, path in previous.items()
                    },
                },
                jobs,
            )
            previous = next_inputs
        return {
            role: load_model(path, Document) for role, path in previous.items()
        }, merge_roots


def pdf_inputs(sources: dict[str, Path]) -> dict[str, InputFile]:
    """PDFの存在を確認し、roleと内容の再開照合情報を作る。

    Args:
        sources: role別の入力PDF。

    Returns:
        role別の入力file情報。

    Raises:
        InputError: 入力がPDF fileでない場合。
    """
    result = {}
    for role, path in sources.items():
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            raise InputError(f"{role} must be a PDF file")
        result[role] = InputFile(
            role=role,
            logical_path=path.name,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
        )
    return result


def agent_units(documents: dict[str, Document]) -> dict[str, dict[str, TextUnit]]:
    """意味のある本文を文書role別に索引化し、空の表セルを比較対象から除く。

    Args:
        documents: 比較する全Document。

    Returns:
        roleごとのTextUnit ID索引。
    """
    return {
        role: {
            unit.id: unit
            for _, unit in document.text_units()
            if unit.text("source").strip()
        }
        for role, document in documents.items()
    }


# 訳者が追加したコラムや注記の見出し。英文に対応がないため照合候補にしない。
_TRANSLATOR_NOTE = re.compile(r"\s*(?:コラム|訳注|訳者注|補足)\s*[\uff1a:]")


def translator_notes(units: Mapping[str, TextUnit]) -> set[str]:
    """訳者が追加したコラムや注記の見出しで始まるunitのIDを返す。

    LLMへの指示だけでは、見出しが本文の見出しと似ている場合に対応付けられるため、
    見出しの表記で照合候補から除く。

    Args:
        units: 訳文のunit索引。

    Returns:
        set[str]: 照合候補から除くunit ID。
    """
    return {
        identifier
        for identifier, unit in units.items()
        if _TRANSLATOR_NOTE.match(unit.text("source"))
    }


# 一回の照合・比較へ含める全role合計の最大unit数。
MAX_REFERENCE_IDS = 32
# LLM_TASK_DEADLINE_SECONDSを適用する英文unit数。88ページ、824 unitの実文書が収まる規模とする。
DEADLINE_UNITS = 1000
# Embeddingを使えない場合に、位置から補う相手側候補の数。
POSITIONAL_CANDIDATES = 8


def agent_deadline(config: Config, units: int) -> float:
    """Review・Upgradeの期限を、英文unit数に比例して決める。

    Args:
        config: `llm_task_deadline_seconds`を持つ設定。
        units: 起点となる英文unitの数。

    Returns:
        float: 処理全体の期限となるMonotonic Clock上の時刻。
    """
    periods = max(1, math.ceil(units / DEADLINE_UNITS))
    return time.monotonic() + config.llm_task_deadline_seconds * periods


def positional_candidates(
    units: Mapping[str, Mapping[str, TextUnit]],
    references: dict[str, list[str]],
    available: Mapping[str, set[str]],
    primary_role: str,
) -> dict[str, list[str]]:
    """候補のない文書roleへ、起点と文書内の相対位置が近い未使用unitを補う。

    Args:
        units: 文書roleごとのTextUnit索引。
        references: 起点と、検索で得た候補。
        available: 確定済みの対応に使われていないID。
        primary_role: 起点の文書role。

    Returns:
        dict[str, list[str]]: 候補が空だったroleへ近傍unitを文書順で加えた参照。
    """
    primary = references[primary_role][0]
    ids = list(units[primary_role])
    ratio = ids.index(primary) / max(1, len(ids) - 1)
    result = {role: list(values) for role, values in references.items()}
    for role, values in units.items():
        if role == primary_role or result.get(role):
            continue
        order = {key: index for index, key in enumerate(values)}
        center = ratio * max(0, len(order) - 1)
        nearby = sorted(
            (key for key in order if key in available[role]),
            key=lambda key: abs(order[key] - center),
        )[:POSITIONAL_CANDIDATES]
        if nearby:
            result[role] = sorted(nearby, key=order.__getitem__)
    return result


def narrowed(
    references: dict[str, list[str]],
    primary_role: str,
    order: tuple[str, ...],
    minimum: int,
) -> dict[str, list[str]] | None:
    """失敗した照合・比較の範囲を縮め、起点を残した次の範囲を返す。

    起点以外の起点側unitを先に外し、次に`order`の順で候補を上位半分へ絞る。
    外した候補は未処理のまま残り、それぞれの順番で改めて処理される。

    Args:
        references: 失敗した範囲。各roleの候補は有力な順に並ぶ。
        primary_role: 起点の文書role。
        order: 候補を絞る文書roleの優先順。
        minimum: 各roleに残す最小の候補数。

    Returns:
        dict[str, list[str]] | None: 縮めた範囲。これ以上縮められなければNone。
    """
    if len(references.get(primary_role, [])) > 1:
        return {**references, primary_role: references[primary_role][:1]}
    for role in order:
        values = references.get(role, [])
        if len(values) > minimum:
            return {**references, role: values[: max(minimum, len(values) // 2)]}
    return None


def completed_agent_calls(
    directory: Path, *, matching_version: int | None = None
) -> list[LLMCallArtifact]:
    """再開時に再検証する成功操作を実行順で返す。

    Args:
        directory: AgentのTask directory。
        matching_version: 指定時は同じ照合世代で保存した操作だけを返す。

    Returns:
        成功Callの一覧。応答と入力の検証は各Taskの再利用処理で行う。
    """
    calls = [
        load_model(path, LLMCallArtifact)
        for path in (directory / "calls").glob("*/call.json")
    ]
    return sorted(
        (
            call
            for call in calls
            if call.status == "succeeded"
            and (matching_version is None or call.matching_version == matching_version)
        ),
        key=lambda call: call.round,
    )

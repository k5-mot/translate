"""視覚情報を使って意味構造を補正するSTRUCTURE Task。"""

import json
import math
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from translate.adapters.artifact_store import (
    begin_llm_call,
    canonical_hash,
    complete_llm_call,
    fail_llm_call,
    llm_call_id,
    load_model,
    load_reusable_llm_response,
    mark_split_llm_call,
    sha256_file,
    write_model,
)
from translate.adapters.llm import (
    LLMClient,
    LLMError,
    LLMInputExceededError,
    LLMInvalidResponseError,
    LLMOutputExceededError,
)
from translate.adapters.pdf import render_page
from translate.common.config import Config
from translate.models.artifacts import LLMCallArtifact, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import (
    AlertKind,
    Block,
    BlockKind,
    Document,
    Page,
    TextSpan,
)
from translate.models.document import (
    Image as DocumentImage,
)

# ローカルGemma VLMで安定して処理できる実測上限にpage画像を収める。
MAX_VISION_PIXELS = 1_000_000


class StructureModel(BaseModel):
    """未知fieldを無視するSTRUCTURE応答モデルの設定。"""

    model_config = ConfigDict(extra="ignore")


class StructurePatch(StructureModel):
    """既存Blockへ適用する意味構造だけの差分。"""

    block_id: str
    kind: BlockKind | None = None
    level: int | None = Field(default=None, ge=1, le=6)
    alert_kind: AlertKind | None = None
    caption_source_id: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def ignore_caption_as_kind(cls, value: object) -> object:
        """captionをBlock種別と誤認した応答だけを未指定として扱う。

        Args:
            value (object): STRUCTURE応答が返したBlock種別候補。

        Returns:
            object: captionをBlock種別と誤認した応答だけを未指定として扱う。
        """

        if isinstance(value, str) and value.strip().casefold() == "caption":
            return None
        return value


class StructureResponse(StructureModel):
    """一回のSTRUCTURE Callが返すBlock差分一覧。"""

    patches: list[StructurePatch] = Field(default_factory=list)


class StructureTask:
    """構造補正の設定と保存先を保持し、文書を通して見出し階層を確認する。"""

    def __init__(self, config: Config, task_directory: Path, rules: str) -> None:
        """構造補正に使う設定・規則と保存先を受け取る。

        Args:
            config: VLMの接続と要求・再試行の上限。
            task_directory: Page画像、Callおよび補正後文書の保存先。
            rules: 構造補正Promptに追加する判断規則。
        """
        self.config = config
        self.task_directory = task_directory
        self.rules = rules
        self.heading_history: list[dict[str, object]] = []

    def run(
        self,
        document: Document,
        source_pdf: Path,
        processing_directory: Path,
    ) -> Document:
        """page画像ごとにBlock差分を取得し、整合するpatchだけを適用する。

        Args:
            document (Document): 変換または検証対象のDocument。
            source_pdf (Path): Page画像を取得する原文PDF Path。
            processing_directory (Path): 対象処理の成果物Directory。

        Returns:
            Document: page画像ごとにBlock差分を取得し、整合するpatchだけを適用する。

        Raises:
            ValueError: `structure model is required`と判定した場合。
        """

        if self.config.openai_structure_model is None:
            raise ValueError("structure model is required")
        self.task_directory.mkdir(parents=True, exist_ok=True)
        original_assets = processing_directory / "tasks" / "03-merge" / "assets"
        if original_assets.is_dir():
            shutil.copytree(
                original_assets, self.task_directory / "assets", dirs_exist_ok=True
            )
        diagnostics_path = processing_directory / "task-structure.json"
        diagnostics: list[str] = []
        _write_diagnostics(diagnostics_path, diagnostics)
        updated = document.model_copy(deep=True)
        baseline_levels = {
            block.id: block.level
            for page in updated.pages
            for block in page.blocks
            if block.kind == "heading"
        }
        client = LLMClient(self.config)
        client.deadline = time.monotonic() + self.config.llm_task_deadline_seconds
        try:
            used_call_ids: list[str] = []
            self.heading_history: list[dict[str, object]] = []
            for page in updated.pages:
                native_formulas = {
                    block.id for block in page.blocks if block.kind == "formula"
                }
                page_responses: list[tuple[str, StructureResponse]] = []
                image = self.task_directory / "pages" / f"page-{page.number:04d}.png"
                if not image.is_file():
                    render_page(source_pdf, page.number, image, 144)
                _bound_image(image)
                overhead = len(self.rules.encode("utf-8")) + 2048
                chunks = _chunks(
                    page.blocks,
                    self.config.structure_max_blocks,
                    self.config.structure_input_tokens - overhead,
                )
                for index, blocks in enumerate(chunks):
                    page_responses.extend(
                        self._execute(
                            client=client,
                            blocks=blocks,
                            image=image,
                            lineage=[f"page-{page.number:04d}", f"chunk-{index:04d}"],
                            depth=0,
                        )
                    )
                used_call_ids.extend(call_id for call_id, _ in page_responses)
                _apply_page(page, page_responses, diagnostics)
                for block in page.blocks:
                    if block.kind == "formula" and block.id not in native_formulas:
                        self._preserve_formula(block, page, source_pdf)
                self.heading_history.extend(_page_heading_history(page))
                del self.heading_history[:-8]
                write_model(
                    self.task_directory / "pages" / f"page-{page.number:04d}.json", page
                )
            _normalize_heading_levels(updated, baseline_levels, diagnostics)
            for page in updated.pages:
                write_model(
                    self.task_directory / "pages" / f"page-{page.number:04d}.json", page
                )
            _write_diagnostics(diagnostics_path, diagnostics)
            write_model(
                self.task_directory / "call-index.json",
                LLMCallIndex(task="STRUCTURE", call_ids=used_call_ids),
            )
            write_model(self.task_directory / "document.json", updated)
            return updated
        finally:
            client.client.close()

    def _preserve_formula(self, block: Block, page: Page, source: Path) -> None:
        """文字抽出では再現できない数式を原本画像と物理寸法で保持する。

        Args:
            block: 画像から新たに数式と判定されたBlock。
            page: 左上原点のBlock座標とページ寸法。
            source: 切出し元の原本PDF。

        Raises:
            ValueError: 数式の領域またはページ寸法が欠損・不正な場合。
        """
        if block.bbox is None or page.width is None or page.height is None:
            raise ValueError(
                "Formula image requires page dimensions and a bounding box"
            )
        left, top, right, bottom = block.bbox
        # 旧LOAD成果物はDoclingのBOTTOMLEFT座標をそのまま保存していた。
        if top > bottom:
            top, bottom = page.height - top, page.height - bottom
        if not (
            all(
                math.isfinite(value) for value in (*block.bbox, page.width, page.height)
            )
            and 0 <= left < right <= page.width
            and 0 <= top < bottom <= page.height
        ):
            raise ValueError("Formula image bounds must lie within the page")
        # 字形の端を切らないよう2 ptの余白を付け、数式には印刷用の300 DPIを使う。
        clip = (
            max(0, left - 2),
            max(0, top - 2),
            min(page.width, right + 2),
            min(page.height, bottom + 2),
        )
        relative = f"assets/formulas/{canonical_hash(block.id)}.png"
        render_page(source, page.number, self.task_directory / relative, 300, clip=clip)
        block.image = DocumentImage(
            id=f"{block.id}/formula-image",
            asset_path=relative,
            alt_text="数式 (原本画像)",
            width_pt=clip[2] - clip[0],
            height_pt=clip[3] - clip[1],
        )

    def _execute(
        self,
        *,
        client: LLMClient,
        blocks: list[Block],
        image: Path,
        lineage: list[str],
        depth: int,
    ) -> list[tuple[str, StructureResponse]]:
        """一つのSTRUCTURE Callを再利用または送信し、出力超過時は分割する。

        Args:
            client (LLMClient): 外部処理を呼び出すClient。
            blocks (list[Block]): STRUCTURE Callへ含めるBlock列。
            image (Path): Multimodal Callへ添付する画像File。
            lineage (list[str]): 親から子へ連なるLLM Call ID列。
            depth (int): 分割LLM Callの現在の深さ。

        Returns:
            list[tuple[str, StructureResponse]]: 一つのSTRUCTURE Callを再利用または送信し、出力超過時は分割する。
        """

        target_ids = [block.id for block in blocks]
        required_kinds = {
            block.id
            for block in blocks
            if block.kind == "heading"
            or (block.kind == "table" and len(block.cells) == 1)
        }

        def validate(response: StructureResponse) -> None:
            """見出し候補と1セル表を未確認のまま残す応答を訂正対象にする。

            Args:
                response: LLMまたは保存済みCallの構造判定。

            Raises:
                ValueError: 見出しまたは1セル表の明示的な種別判定がない場合。
            """
            missing = required_kinds - {
                patch.block_id for patch in response.patches if patch.kind is not None
            }
            if missing:
                raise ValueError(
                    f"Classify every existing heading and single-cell table with an explicit kind; missing={sorted(missing)}"
                )

        call_id = llm_call_id("STRUCTURE", target_ids, lineage)
        call_directory = self.task_directory / "calls" / call_id
        fingerprint = canonical_hash(
            {
                "task": "STRUCTURE",
                "operation": "structure",
                "blocks": [block.model_dump(mode="json") for block in blocks],
                "image": sha256_file(image),
            }
        )
        reusable = load_reusable_llm_response(
            call_directory,
            call_id=call_id,
            fingerprint=fingerprint,
            response_type=StructureResponse,
        )
        if reusable is not None:
            try:
                validate(reusable[1])
            except ValueError:
                pass
            else:
                return [(call_id, reusable[1])]
        artifact = begin_llm_call(
            call_directory,
            call_id=call_id,
            task="STRUCTURE",
            fingerprint=fingerprint,
            target_ids=target_ids,
            previous_attempts=_previous_attempts(call_directory),
        )
        try:
            result = client.structured(
                task="STRUCTURE",
                model=self.config.openai_structure_model or "",
                response_type=StructureResponse,
                system=(
                    "Inspect the page image and explicitly classify every existing heading and single-cell table, "
                    "including unchanged ones. Existing kinds are extraction candidates, not confirmed facts. "
                    "Demote ordinary body sentences to paragraph. For other blocks return only necessary patches. "
                    "Never rewrite text or IDs. Caption is not a block kind; associate a "
                    "caption only with caption_source_id. Heading levels are document-global; "
                    "do not reset them at a page boundary.\n\n" + self.rules
                ),
                user=json.dumps(
                    {
                        "heading_history": self.heading_history,
                        "blocks": [_block_payload(block) for block in blocks],
                    },
                    ensure_ascii=False,
                ),
                contract=(
                    '{"patches":[{"block_id":string,"kind"?:string,"level"?:integer,'
                    '"alert_kind"?:string,"caption_source_id"?:string}]}. '
                    f"At most {len(blocks)} patches. Explicit kind is required for every existing heading and single-cell table."
                ),
                native_schema=_schema(len(blocks)),
                input_tokens=self.config.structure_input_tokens,
                output_tokens=self.config.structure_output_tokens,
                image=image,
                validate=validate,
            )
        except (LLMInputExceededError, LLMOutputExceededError) as error:
            if len(blocks) < 2 or depth >= self.config.llm_split_max_depth:
                fail_llm_call(call_directory, artifact, error, attempts=1)
                raise
            split = True
        except LLMInvalidResponseError as error:
            if len(blocks) < 2 or depth >= self.config.llm_split_max_depth:
                fail_llm_call(call_directory, artifact, error, attempts=1)
                raise
            split = True
        except LLMError as error:
            fail_llm_call(call_directory, artifact, error, attempts=1)
            raise
        else:
            split = False
        if split:
            middle = len(blocks) // 2
            groups = (blocks[:middle], blocks[middle:])
            child_ids = [
                llm_call_id(
                    "STRUCTURE", [block.id for block in group], [*lineage, str(index)]
                )
                for index, group in enumerate(groups)
            ]
            artifact = mark_split_llm_call(call_directory, artifact, child_ids)
            values: list[tuple[str, StructureResponse]] = []
            for index, group in enumerate(groups):
                values.extend(
                    self._execute(
                        client=client,
                        blocks=group,
                        image=image,
                        lineage=[*lineage, str(index)],
                        depth=depth + 1,
                    )
                )
            return values
        complete_llm_call(
            call_directory,
            artifact,
            result.response,
            attempts=result.attempts,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return [(call_id, result.response)]


def _chunks(
    blocks: list[Block], maximum_blocks: int, maximum_bytes: int
) -> list[list[Block]]:
    """連続Blockを件数と保守的UTF-8 byte上限内へ分割する。

    Args:
        blocks (list[Block]): STRUCTURE Callへ含めるBlock列。
        maximum_blocks (int): 一つのSTRUCTURE Callへ含める最大Block数。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        list[list[Block]]: 連続Blockを件数と保守的UTF-8 byte上限内へ分割する。

    Raises:
        ValueError: `f'single Block exceeds structure input limit: {block.id}'`と判定した場合。
    """

    result: list[list[Block]] = []
    current: list[Block] = []
    for block in blocks:
        if _block_bytes([block]) > maximum_bytes:
            if current:
                result.append(current)
                current = []
            if block.content is None or not block.content.spans:
                raise ValueError(
                    f"single Block exceeds structure input limit: {block.id}"
                )
            spans = []
            for span in block.content.spans:
                content = block.content.model_copy(update={"spans": [*spans, span]})
                piece = block.model_copy(update={"content": content})
                if _block_bytes([piece]) > maximum_bytes:
                    if spans:
                        result.append(
                            [
                                block.model_copy(
                                    update={
                                        "content": block.content.model_copy(
                                            update={"spans": spans}
                                        )
                                    }
                                )
                            ]
                        )
                        spans = []
                    single = block.model_copy(
                        update={
                            "content": block.content.model_copy(
                                update={"spans": [span]}
                            )
                        }
                    )
                    if _block_bytes([single]) > maximum_bytes:
                        result.extend(
                            [
                                block.model_copy(
                                    update={
                                        "content": block.content.model_copy(
                                            update={"spans": [part]}
                                        )
                                    }
                                )
                            ]
                            for part in _split_span(block, span, maximum_bytes)
                        )
                        continue
                    spans = [span]
                else:
                    spans.append(span)
            if spans:
                result.append(
                    [
                        block.model_copy(
                            update={
                                "content": block.content.model_copy(
                                    update={"spans": spans}
                                )
                            }
                        )
                    ]
                )
            continue
        if current and (
            len(current) >= maximum_blocks
            or _block_bytes([*current, block]) > maximum_bytes
        ):
            result.append(current)
            current = []
        current.append(block)
    if current:
        result.append(current)
    return result


def _split_span(block: Block, span: TextSpan, maximum_bytes: int) -> list[TextSpan]:
    """単一SpanをSTRUCTURE payloadのbyte上限に収まる連続片へ分ける。

    Args:
        block (Block): 分割するSpanを含む元Block。
        span (TextSpan): 分割するTextSpan。
        maximum_bytes (int): 一つのpayloadへ含める最大byte数。

    Returns:
        list[TextSpan]: 元の文字列を欠落・重複なく分割したTextSpan。

    Raises:
        ValueError: 一文字を含むpayloadもbyte上限を超える場合。
    """
    if block.content is None or not span.source:
        raise ValueError(f"single sentence exceeds structure input limit: {span.id}")
    text = span.source
    parts = []
    start = 0
    while start < len(text):
        low, high, end = start + 1, len(text), start
        while low <= high:
            middle = (low + high) // 2
            part = span.model_copy(update={"source": text[start:middle]})
            content = block.content.model_copy(update={"spans": [part]})
            candidate = block.model_copy(update={"content": content})
            if _block_bytes([candidate]) <= maximum_bytes:
                end = middle
                low = middle + 1
            else:
                high = middle - 1
        if end == start:
            raise ValueError(
                f"single sentence exceeds structure input limit: {span.id}"
            )
        parts.append(span.model_copy(update={"source": text[start:end]}))
        start = end
    return parts


def _block_bytes(blocks: list[Block]) -> int:
    """STRUCTURE promptへ渡すBlock要約の保守的byte数を返す。

    Args:
        blocks (list[Block]): STRUCTURE Callへ含めるBlock列。

    Returns:
        int: STRUCTURE promptへ渡すBlock要約の保守的byte数を返す。
    """

    value = [_block_payload(block) for block in blocks]
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 1024


def _block_payload(block: Block) -> dict[str, object]:
    """分類対象の本文を省略せずSTRUCTURE入力へ含める。

    Args:
        block (Block): 変換または検証対象のDocument Block。

    Returns:
        dict[str, object]: 分類対象の本文を省略せずSTRUCTURE入力へ含める。
    """

    text = block.content.text("source") if block.content is not None else ""
    return {
        "block_id": block.id,
        "kind": block.kind,
        "text": text,
        "level": block.level,
        "bbox": block.bbox,
        "cell_count": len(block.cells),
    }


def _bound_image(path: Path) -> None:
    """縦横比を保ったままSTRUCTURE画像を画素数上限内へ縮小する。

    Args:
        path (Path): 画素数上限へ縮小するPage画像のPath。
    """

    with Image.open(path) as source:
        width, height = source.size
        if width * height <= MAX_VISION_PIXELS:
            return
        scale = math.sqrt(MAX_VISION_PIXELS / (width * height))
        resized = source.resize(
            (max(1, math.floor(width * scale)), max(1, math.floor(height * scale))),
            Image.Resampling.LANCZOS,
        )
    try:
        resized.save(path, format="PNG")
    finally:
        resized.close()


def _apply_page(
    page: Page,
    responses: list[tuple[str, StructureResponse]],
    diagnostics: list[str],
) -> None:
    """既存Blockと整合するpatchだけをpageへ順序どおり適用する。

    Args:
        page (Page): 処理対象のPageまたはPage番号。
        responses (list[tuple[str, StructureResponse]]): Block IDとSTRUCTURE応答の一覧。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    blocks = {block.id: block for block in page.blocks}
    caption_sources: set[str] = set()
    for call_id, response in responses:
        for patch in response.patches:
            block = blocks.get(patch.block_id)
            if block is None:
                diagnostics.append(f"{call_id} unknown_block {patch.block_id}")
                continue
            if patch.kind is not None and not _kind_is_compatible(block, patch):
                diagnostics.append(
                    f"{call_id} invalid_kind {patch.block_id} {patch.kind}"
                )
            elif patch.kind is not None:
                if patch.kind == "formula":
                    if block.kind == "table":
                        block.content = block.cells[0].content
                        block.cells = []
                    if block.content is not None:
                        for span in block.content.spans:
                            if span.kind != "line_break":
                                span.kind = "code"
                block.kind = patch.kind
            if patch.level is not None and block.kind == "heading":
                block.level = patch.level
            elif patch.level is not None:
                diagnostics.append(f"{call_id} invalid_level {patch.block_id}")
            if patch.alert_kind is not None and block.kind == "alert":
                block.alert_kind = patch.alert_kind
            elif patch.alert_kind is not None:
                diagnostics.append(f"{call_id} invalid_alert_kind {patch.block_id}")
    # Captionの所属判定は、応答内の並び順ではなく補正後の種別に基づく。
    for call_id, response in responses:
        for patch in response.patches:
            block = blocks.get(patch.block_id)
            if block is None:
                continue
            if patch.caption_source_id is not None:
                if block.kind not in {"figure", "table"}:
                    diagnostics.append(f"{call_id} invalid_caption_target {block.id}")
                    continue
                source = blocks.get(patch.caption_source_id)
                if (
                    source is None
                    or source.content is None
                    or source.kind == "heading"
                    or source.id == block.id
                    or source.id in caption_sources
                ):
                    diagnostics.append(
                        f"{call_id} invalid_caption_source {patch.caption_source_id}"
                    )
                    continue
                existing_caption = (
                    block.image.caption
                    if block.kind == "figure" and block.image is not None
                    else block.caption
                )
                if existing_caption is not None:
                    diagnostics.append(f"{call_id} caption_already_present {block.id}")
                    continue
                if block.kind == "figure" and block.image is not None:
                    block.image.caption = source.content
                else:
                    block.caption = source.content
                caption_sources.add(source.id)
    if caption_sources:
        page.blocks = [
            block for block in page.blocks if block.id not in caption_sources
        ]
        for order, block in enumerate(page.blocks):
            block.order = order


def _page_heading_history(page: Page) -> list[dict[str, object]]:
    """表紙を除く処理済みページから、本文の見出し履歴を作る。

    Args:
        page (Page): 処理対象のPageまたはPage番号。

    Returns:
        list[dict[str, object]]: 本文の見出し履歴。表紙では空のList。
    """

    if page.number == 1:
        return []
    return [
        {
            "level": block.level,
            "text": block.content.text("source") if block.content is not None else "",
        }
        for block in sorted(page.blocks, key=lambda item: item.order)
        if block.kind == "heading"
        and block.level is not None
        and block.content is not None
    ]


_TOP_LEVEL_MARKER = re.compile(
    r"^\s*(?:chapter\b|part\b|appendix\b|付録\b|第\s*\d+\s*[章編])",
    re.IGNORECASE,
)
_NUMBERED_HEADING = re.compile(r"^\s*([0-9]{1,3}(?:\.[0-9]+)*)[.)、\uFF1A:]?\s+")


def _normalize_heading_levels(
    document: Document,
    baseline_levels: dict[str, int | None],
    diagnostics: list[str],
) -> None:
    """章節番号の深さを揃え、番号のない見出しのページ境界リセットを補正する。

    Args:
        document (Document): 変換または検証対象のDocument。
        baseline_levels (dict[str, int | None]): 補正前のBlock ID別見出しLevel。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    previous_level: int | None = None
    previous_page_number: int | None = None
    for page in sorted(document.pages, key=lambda item: item.number):
        # 先頭ページは表紙画像として公開するため、本文の親階層にはしない。
        if page.number == 1:
            continue
        page_boundary = (
            previous_page_number is not None and page.number > previous_page_number
        )
        for block in sorted(page.blocks, key=lambda item: item.order):
            if block.kind != "heading" or block.level is None:
                continue
            baseline = baseline_levels.get(block.id)
            text = block.content.text("source").strip() if block.content else ""
            section = _NUMBERED_HEADING.match(text)
            if section is not None:
                level = min(6, section.group(1).count(".") + 1)
                if block.level != level:
                    diagnostics.append(
                        f"{block.id} level_normalized llm={block.level} "
                        f"numbered={level} reason=section_depth"
                    )
                    block.level = level
            elif (
                previous_level is not None
                and page_boundary
                and block.level == 1
                and baseline is not None
                and baseline > 1
                and not _TOP_LEVEL_MARKER.search(text)
            ):
                diagnostics.append(
                    f"{block.id} level_normalized llm=1 baseline={baseline} "
                    "reason=page_boundary_reset"
                )
                block.level = baseline
            previous_level = block.level
        previous_page_number = page.number


def _kind_is_compatible(block: Block, patch: StructurePatch) -> bool:
    """番号付き見出しを維持し、提案kindの必須fieldが成立するか返す。

    Args:
        block (Block): 変換または検証対象のDocument Block。
        patch (StructurePatch): Blockへ適用予定のSTRUCTURE変更。

    Returns:
        bool: 番号付き見出しを失わず、変更後の必須fieldを満たす場合にTrue。
    """

    kind = patch.kind
    if kind is None:
        return True
    formula_cell = (
        kind == "formula"
        and block.kind == "table"
        and len(block.cells) == 1
        and not block.cells[0].images
        and block.content is None
        and block.image is None
        and block.caption is None
    )
    if kind == "formula" and block.kind == "table" and not formula_cell:
        return False
    if (
        kind == "formula"
        and block.kind != "formula"
        and (block.bbox is None or block.caption is not None)
    ):
        return False
    # 章節番号付きの見出しを段落化すると、Wordの採番と目次から章が欠落する。
    if (
        block.kind == "heading"
        and kind != "heading"
        and block.content is not None
        and _NUMBERED_HEADING.match(block.content.text("source"))
    ):
        return False
    content_required = kind in {
        "paragraph",
        "heading",
        "blockquote",
        "list_item",
        "alert",
        "code",
        "formula",
        "footnote",
    }
    return not (
        (content_required and block.content is None and not formula_cell)
        or (kind == "heading" and patch.level is None and block.level is None)
        or (kind == "alert" and patch.alert_kind is None and block.alert_kind is None)
        or (kind == "figure" and block.image is None)
        or (kind == "table" and not block.cells)
    )


def _schema(maximum_items: int) -> dict[str, object]:
    """STRUCTURE専用の浅いnative JSON Schemaを作る。

    Args:
        maximum_items (int): Structured Outputへ含める最大要素数。

    Returns:
        dict[str, object]: STRUCTURE専用の浅いnative JSON Schemaを作る。
    """

    return {
        "type": "object",
        "properties": {
            "patches": {
                "type": "array",
                "maxItems": maximum_items,
                "items": {
                    "type": "object",
                    "properties": {
                        "block_id": {"type": "string"},
                        "kind": {
                            "type": "string",
                            "enum": list(get_args(BlockKind)),
                        },
                        "level": {"type": "integer", "minimum": 1, "maximum": 6},
                        "alert_kind": {
                            "type": "string",
                            "enum": list(get_args(AlertKind)),
                        },
                        "caption_source_id": {"type": "string"},
                    },
                    "required": ["block_id"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["patches"],
        "additionalProperties": False,
    }


def _previous_attempts(directory: Path) -> int:
    """Resume前の累計試行数を読める場合だけ引き継ぐ。

    Args:
        directory (Path): LLM Call Artifactの保存Directory。

    Returns:
        int: Resume前の累計試行数を読める場合だけ引き継ぐ。
    """

    path = directory / "call.json"
    if not path.is_file():
        return 0
    try:
        return load_model(path, LLMCallArtifact).attempts
    except Exception:  # noqa: BLE001
        return 0


def _write_diagnostics(path: Path, diagnostics: list[str]) -> None:
    """STRUCTUREの適用外項目を処理ディレクトリ直下へ保存する。

    Args:
        path (Path): STRUCTURE診断を書き込むJSON FileのPath。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    write_model(
        path,
        LLMTaskDiagnostics(
            task="STRUCTURE",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )

"""視覚情報を使って意味構造を補正するSTRUCTURE Task。"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, get_args

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from translate.adapters.llm import (
    LLMClient,
    LLMError,
    LLMInputExceededError,
    LLMOutputExceededError,
)
from translate.adapters.pdf import render_page
from translate.artifact_store import (
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
from translate.models.artifacts import LLMCallArtifact, LLMCallIndex, LLMTaskDiagnostics
from translate.models.document import (
    AlertKind,
    Block,
    BlockKind,
    Document,
    Page,
)

if TYPE_CHECKING:
    from pathlib import Path

    from translate.common.config import Config


# ローカルGemma VLMで安定して処理できる実測上限にpage画像を収める。
MAX_VISION_PIXELS = 1_000_000
MAX_BLOCK_EXCERPT_BYTES = 1024


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


def structure(
    document: Document,
    source_pdf: Path,
    task_directory: Path,
    processing_directory: Path,
    config: Config,
    rules: str,
) -> Document:
    """page画像ごとにBlock差分を取得し、整合するpatchだけを適用する。

    Args:
        document (Document): 変換または検証対象のDocument。
        source_pdf (Path): Page画像を取得する原文PDF Path。
        task_directory (Path): 対象Taskの成果物Directory。
        processing_directory (Path): 対象処理の成果物Directory。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        rules (str): LLM Promptへ含める追加規則。

    Returns:
        Document: page画像ごとにBlock差分を取得し、整合するpatchだけを適用する。

    Raises:
        ValueError: `structure model is required`と判定した場合。
    """

    if config.openai_structure_model is None:
        raise ValueError("structure model is required")
    task_directory.mkdir(parents=True, exist_ok=True)
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
    client = LLMClient(config)
    used_call_ids: list[str] = []
    heading_history: list[dict[str, object]] = []
    for page in updated.pages:
        page_responses: list[tuple[str, StructureResponse]] = []
        image = task_directory / "pages" / f"page-{page.number:04d}.png"
        if not image.is_file():
            render_page(source_pdf, page.number, image, 144)
        _bound_image(image)
        overhead = len(rules.encode("utf-8")) + 2048
        chunks = _chunks(
            page.blocks,
            config.structure_max_blocks,
            config.structure_input_tokens - overhead,
        )
        for index, blocks in enumerate(chunks):
            page_responses.extend(
                _execute(
                    client=client,
                    config=config,
                    blocks=blocks,
                    image=image,
                    task_directory=task_directory,
                    rules=rules,
                    heading_history=heading_history,
                    lineage=[f"page-{page.number:04d}", f"chunk-{index:04d}"],
                    depth=0,
                )
            )
        used_call_ids.extend(call_id for call_id, _ in page_responses)
        _apply_page(page, page_responses, diagnostics)
        heading_history.extend(_page_heading_history(page))
        del heading_history[:-8]
        write_model(task_directory / "pages" / f"page-{page.number:04d}.json", page)
    _normalize_heading_levels(updated, baseline_levels, diagnostics)
    for page in updated.pages:
        write_model(task_directory / "pages" / f"page-{page.number:04d}.json", page)
    _write_diagnostics(diagnostics_path, diagnostics)
    write_model(
        task_directory / "call-index.json",
        LLMCallIndex(task="STRUCTURE", call_ids=used_call_ids),
    )
    write_model(task_directory / "document.json", updated)
    return updated


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
            raise ValueError(f"single Block exceeds structure input limit: {block.id}")
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
    """分類に十分な先頭・末尾の本文だけをSTRUCTURE入力へ含める。

    Args:
        block (Block): 変換または検証対象のDocument Block。

    Returns:
        dict[str, object]: 分類に十分な先頭・末尾の本文だけをSTRUCTURE入力へ含める。
    """

    text = block.content.text("source") if block.content is not None else ""
    return {
        "block_id": block.id,
        "kind": block.kind,
        "text": _excerpt(text, MAX_BLOCK_EXCERPT_BYTES),
        "level": block.level,
    }


def _excerpt(value: str, maximum_bytes: int) -> str:
    """UTF-8を壊さず、長文の先頭と末尾を指定byte内へ収める。

    Args:
        value (str): 先頭と末尾を残して短縮するText。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        str: UTF-8を壊さず、長文の先頭と末尾を指定byte内へ収める。
    """

    if len(value.encode("utf-8")) <= maximum_bytes:
        return value
    marker = "\n…\n"
    side = (maximum_bytes - len(marker.encode("utf-8"))) // 2
    head = _take_utf8(value, side)
    tail = _take_utf8(value[::-1], side)[::-1]
    return f"{head}{marker}{tail}"


def _take_utf8(value: str, maximum_bytes: int) -> str:
    """文字境界を保って先頭から指定byteまで返す。

    Args:
        value (str): 先頭からByte上限まで切り出すText。
        maximum_bytes (int): Payloadへ含められるUTF-8 Byte数の上限。

    Returns:
        str: 文字境界を保って先頭から指定byteまで返す。
    """

    result: list[str] = []
    size = 0
    for character in value:
        encoded = len(character.encode("utf-8"))
        if size + encoded > maximum_bytes:
            break
        result.append(character)
        size += encoded
    return "".join(result)


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


def _execute(
    *,
    client: LLMClient,
    config: Config,
    blocks: list[Block],
    image: Path,
    task_directory: Path,
    rules: str,
    heading_history: list[dict[str, object]],
    lineage: list[str],
    depth: int,
) -> list[tuple[str, StructureResponse]]:
    """一つのSTRUCTURE Callを再利用または送信し、出力超過時は分割する。

    Args:
        client (LLMClient): 外部処理を呼び出すClient。
        config (Config): 接続先、上限値および処理Optionを保持する設定。
        blocks (list[Block]): STRUCTURE Callへ含めるBlock列。
        image (Path): Multimodal Callへ添付する画像File。
        task_directory (Path): 対象Taskの成果物Directory。
        rules (str): LLM Promptへ含める追加規則。
        heading_history (list[dict[str, object]]): 前Pageまでの確定見出し階層。
        lineage (list[str]): 親から子へ連なるLLM Call ID列。
        depth (int): 分割LLM Callの現在の深さ。

    Returns:
        list[tuple[str, StructureResponse]]: 一つのSTRUCTURE Callを再利用または送信し、出力超過時は分割する。
    """

    target_ids = [block.id for block in blocks]
    call_id = llm_call_id("STRUCTURE", target_ids, lineage)
    call_directory = task_directory / "calls" / call_id
    fingerprint = canonical_hash(
        {
            "task": "STRUCTURE",
            "schema": 3,
            "blocks": [block.model_dump(mode="json") for block in blocks],
            "image": sha256_file(image),
            "rules": canonical_hash(rules),
            "heading_history": heading_history,
            "model": config.openai_structure_model,
            "mode": config.llm_structured_output_mode,
            "reasoning_effort": "none",
            "llm_endpoint": config.openai_llm_base_url or config.openai_base_url,
            "temperature": 0.7,
            "repetition_penalty": 1.01,
            "input_tokens": config.structure_input_tokens,
            "output_tokens": config.structure_output_tokens,
        }
    )
    reusable = load_reusable_llm_response(
        call_directory,
        call_id=call_id,
        fingerprint=fingerprint,
        response_type=StructureResponse,
    )
    if reusable is not None:
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
            model=config.openai_structure_model or "",
            response_type=StructureResponse,
            system=(
                "Inspect the page image and return only necessary structural patches. "
                "Never rewrite text or IDs. Caption is not a block kind; associate a "
                "caption only with caption_source_id. Heading levels are document-global; "
                "do not reset them at a page boundary.\n\n" + rules
            ),
            user=json.dumps(
                {
                    "heading_history": heading_history,
                    "blocks": [_block_payload(block) for block in blocks],
                },
                ensure_ascii=False,
            ),
            contract=(
                '{"patches":[{"block_id":string,"kind"?:string,"level"?:integer,'
                '"alert_kind"?:string,"caption_source_id"?:string}]}. '
                f"At most {len(blocks)} patches."
            ),
            native_schema=_schema(len(blocks)),
            input_tokens=config.structure_input_tokens,
            output_tokens=config.structure_output_tokens,
            image=image,
        )
    except (LLMInputExceededError, LLMOutputExceededError) as error:
        if len(blocks) < 2 or depth >= config.llm_split_max_depth:
            fail_llm_call(call_directory, artifact, error, attempts=1)
            raise
        middle = len(blocks) // 2
        groups = (blocks[:middle], blocks[middle:])
        child_ids = [
            llm_call_id(
                "STRUCTURE", [block.id for block in group], [*lineage, str(index)]
            )
            for index, group in enumerate(groups)
        ]
        mark_split_llm_call(call_directory, artifact, child_ids)
        values: list[tuple[str, StructureResponse]] = []
        for index, group in enumerate(groups):
            values.extend(
                _execute(
                    client=client,
                    config=config,
                    blocks=group,
                    image=image,
                    task_directory=task_directory,
                    rules=rules,
                    heading_history=heading_history,
                    lineage=[*lineage, str(index)],
                    depth=depth + 1,
                )
            )
        return values
    except LLMError as error:
        fail_llm_call(call_directory, artifact, error, attempts=1)
        raise
    complete_llm_call(
        call_directory,
        artifact,
        result.response,
        attempts=result.attempts,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return [(call_id, result.response)]


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
                block.kind = patch.kind
            if patch.level is not None and block.kind == "heading":
                block.level = patch.level
            elif patch.level is not None:
                diagnostics.append(f"{call_id} invalid_level {patch.block_id}")
            if patch.alert_kind is not None and block.kind == "alert":
                block.alert_kind = patch.alert_kind
            elif patch.alert_kind is not None:
                diagnostics.append(f"{call_id} invalid_alert_kind {patch.block_id}")
            if patch.caption_source_id is not None:
                source = blocks.get(patch.caption_source_id)
                if (
                    source is None
                    or source.content is None
                    or source.id == block.id
                    or source.id in caption_sources
                ):
                    diagnostics.append(
                        f"{call_id} invalid_caption_source {patch.caption_source_id}"
                    )
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
    """処理済みページから次ページへ渡す短い見出し履歴を作る。

    Args:
        page (Page): 処理対象のPageまたはPage番号。

    Returns:
        list[dict[str, object]]: 処理済みページから次ページへ渡す短い見出し履歴を作る。
    """

    return [
        {
            "level": block.level,
            "text": _excerpt(block.content.text("source"), 256)
            if block.content is not None
            else "",
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
_NUMBERED_TOP_LEVEL = re.compile(r"^\s*\d+[.)、\uFF1A:]\s+")


def _normalize_heading_levels(
    document: Document,
    baseline_levels: dict[str, int | None],
    diagnostics: list[str],
) -> None:
    """ページ境界でのlevel=1リセットを初期階層へ戻す。

    Args:
        document (Document): 変換または検証対象のDocument。
        baseline_levels (dict[str, int | None]): 補正前のBlock ID別見出しLevel。
        diagnostics (list[str]): 検証中に追記する診断Message列。
    """

    previous_level: int | None = None
    previous_page_number: int | None = None
    for page in sorted(document.pages, key=lambda item: item.number):
        page_boundary = (
            previous_page_number is not None and page.number > previous_page_number
        )
        for block in sorted(page.blocks, key=lambda item: item.order):
            if block.kind != "heading" or block.level is None:
                continue
            baseline = baseline_levels.get(block.id)
            text = block.content.text("source").strip() if block.content else ""
            if (
                previous_level is not None
                and page_boundary
                and block.level == 1
                and baseline is not None
                and baseline > 1
                and not _is_top_level_marker(text)
            ):
                diagnostics.append(
                    f"{block.id} level_normalized llm=1 baseline={baseline} "
                    "reason=page_boundary_reset"
                )
                block.level = baseline
            previous_level = block.level
        previous_page_number = page.number


def _is_top_level_marker(text: str) -> bool:
    """章・付録など明示的な最上位見出し表現か判定する。

    Args:
        text (str): 正規化、検索または表示するText。

    Returns:
        bool: 章・付録など明示的な最上位見出し表現か判定する。
    """

    return bool(_TOP_LEVEL_MARKER.search(text) or _NUMBERED_TOP_LEVEL.search(text))


def _kind_is_compatible(block: Block, patch: StructurePatch) -> bool:
    """提案kindが既存Blockの保持する必須fieldだけで成立するか返す。

    Args:
        block (Block): 変換または検証対象のDocument Block。
        patch (StructurePatch): Blockへ適用予定のSTRUCTURE変更。

    Returns:
        bool: 提案kindが既存Blockの保持する必須fieldだけで成立するか返す。
    """

    kind = patch.kind
    if kind is None:
        return True
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
        (content_required and block.content is None)
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

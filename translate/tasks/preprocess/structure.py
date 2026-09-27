"""視覚情報を使って意味構造を補正するSTRUCTURE Task。"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, get_args

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from translate.adapters.llm import LLMClient, LLMError, LLMOutputExceededError
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


class StructureModel(BaseModel):
    """未知fieldを無視するSTRUCTURE応答モデルの設定。"""

    model_config = ConfigDict(extra="ignore")


class StructurePatch(StructureModel):
    """既存Blockへ適用する意味構造だけの差分。"""

    block_id: str
    kind: BlockKind | None = None
    level: int | None = None
    alert_kind: AlertKind | None = None
    caption_source_id: str | None = None


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
    """page画像ごとにBlock差分を取得し、整合するpatchだけを適用する。"""

    if config.openai_structure_model is None:
        raise ValueError("structure model is required")
    task_directory.mkdir(parents=True, exist_ok=True)
    diagnostics_path = processing_directory / "task-structure.json"
    diagnostics: list[str] = []
    _write_diagnostics(diagnostics_path, diagnostics)
    updated = document.model_copy(deep=True)
    client = LLMClient(config)
    used_call_ids: list[str] = []
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
                    lineage=[f"page-{page.number:04d}", f"chunk-{index:04d}"],
                    depth=0,
                )
            )
        used_call_ids.extend(call_id for call_id, _ in page_responses)
        _apply_page(page, page_responses, diagnostics)
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
    """連続Blockを件数と保守的UTF-8 byte上限内へ分割する。"""

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
    """STRUCTURE promptへ渡すBlock要約の保守的byte数を返す。"""

    value = [
        {
            "block_id": block.id,
            "kind": block.kind,
            "text": block.content.text("source") if block.content is not None else "",
            "level": block.level,
        }
        for block in blocks
    ]
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 1024


def _bound_image(path: Path) -> None:
    """縦横比を保ったままSTRUCTURE画像を画素数上限内へ縮小する。"""

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
    lineage: list[str],
    depth: int,
) -> list[tuple[str, StructureResponse]]:
    """一つのSTRUCTURE Callを再利用または送信し、出力超過時は分割する。"""

    target_ids = [block.id for block in blocks]
    call_id = llm_call_id("STRUCTURE", target_ids, lineage)
    call_directory = task_directory / "calls" / call_id
    fingerprint = canonical_hash(
        {
            "task": "STRUCTURE",
            "schema": 1,
            "blocks": [block.model_dump(mode="json") for block in blocks],
            "image": sha256_file(image),
            "rules": canonical_hash(rules),
            "model": config.openai_structure_model,
            "mode": config.llm_structured_output_mode,
            "thinking": "disabled",
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
            model=config.openai_structure_model or "",
            response_type=StructureResponse,
            system=(
                "Inspect the page image and return only necessary structural patches. "
                "Never rewrite text or IDs.\n\n" + rules
            ),
            user=json.dumps(
                {
                    "blocks": [
                        {
                            "block_id": block.id,
                            "kind": block.kind,
                            "level": block.level,
                            "text": block.content.text("source")
                            if block.content is not None
                            else "",
                        }
                        for block in blocks
                    ]
                },
                ensure_ascii=False,
            ),
            contract=(
                '{"patches":[{"block_id":string,"kind"?:string,"level"?:integer,'
                '"alert_kind"?:string,"caption_source_id"?:string}]}. '
                f"At most {len(blocks)} patches."
            ),
            native_schema=_schema(len(blocks)),
            output_tokens=config.structure_output_tokens,
            image=image,
        )
    except LLMOutputExceededError as error:
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
    """既存Blockと整合するpatchだけをpageへ順序どおり適用する。"""

    blocks = {block.id: block for block in page.blocks}
    caption_sources: set[str] = set()
    for call_id, response in responses:
        for patch in response.patches:
            block = blocks.get(patch.block_id)
            if block is None:
                diagnostics.append(f"{call_id} unknown_block {patch.block_id}")
                continue
            if patch.kind is not None:
                block.kind = patch.kind
            if patch.level is not None:
                block.level = patch.level
            if patch.alert_kind is not None:
                block.alert_kind = patch.alert_kind
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


def _schema(maximum_items: int) -> dict[str, object]:
    """STRUCTURE専用の浅いnative JSON Schemaを作る。"""

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
                        "level": {"type": "integer"},
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
    """Resume前の累計試行数を読める場合だけ引き継ぐ。"""

    path = directory / "call.json"
    if not path.is_file():
        return 0
    try:
        return load_model(path, LLMCallArtifact).attempts
    except Exception:  # noqa: BLE001
        return 0


def _write_diagnostics(path: Path, diagnostics: list[str]) -> None:
    """STRUCTUREの適用外項目を処理ディレクトリ直下へ保存する。"""

    write_model(
        path,
        LLMTaskDiagnostics(
            task="STRUCTURE",
            diagnostics=diagnostics,
            updated_at=datetime.now(UTC),
        ),
    )

"""STRUCTURE: rulesとVLMで見出し、code、captionを補正する。"""

from __future__ import annotations

import hashlib
import json
import math
from functools import partial
from typing import TYPE_CHECKING, Literal

from PIL import Image
from pydantic import BaseModel, Field

from translate_v1.adapters import pdf
from translate_v1.adapters.llm import (
    LLMError,
    LLMStage,
    ReasoningEffort,
    StructuredOutputMode,
    ThinkingPolicy,
    structured,
)
from translate_v1.common.workspace import (
    atomic_directory,
    atomic_write_bytes,
    atomic_write_json,
    sha256_file,
)
from translate_v1.document import BlockKind, Document, Page, inline_text
from translate_v1.tasks.base import BaseTask

if TYPE_CHECKING:
    from pathlib import Path

    from translate_v1.common.settings import Settings


class StructurePatch(BaseModel):
    """一つのblock構造修正。"""

    block_id: str
    kind: BlockKind | None = None
    level: int | None = None
    alert_kind: Literal["note", "tip", "important", "warning", "caution"] | None = None
    caption_source_id: str | None = None
    reason: str = ""


class StructureResponse(BaseModel):
    """ページの構造修正一覧。"""

    patches: list[StructurePatch] = Field(default_factory=list)


class StructurePageError(RuntimeError):
    """STRUCTURE失敗を本文なしのpage診断へ正規化する。"""

    def __init__(self, page: int, target_id: str, cause: LLMError) -> None:
        """構造推定が停止したページ・対象と安全なLLM診断値を保持し、応答本文は公開しない。"""

        self.page = page
        self.target_id = target_id
        self.stage: LLMStage = cause.stage
        self.cause_type = cause.cause_type
        self.failure_kind = cause.failure_kind
        self.finish_reason = cause.finish_reason
        self.input_tokens = cause.input_tokens
        self.output_tokens = cause.output_tokens
        self.total_tokens = cause.total_tokens
        super().__init__(
            f"STRUCTURE page failed: page={page} "
            f"stage={self.stage} cause={self.cause_type}"
        )


def _structure_request(
    settings: Settings,
    model: str,
    response_type: type[StructureResponse],
    system: str,
    user: str,
    *,
    reasoning: ReasoningEffort,
    schema_mode: StructuredOutputMode = "prompt",
    thinking: ThinkingPolicy = "provider-default",
    image: Path | None = None,
) -> StructureResponse:
    """LLM診断の原因型がConnectionErrorを含むときだけ、一回追加で逐次再送する。"""

    request = partial(
        structured,
        settings,
        model,
        response_type,
        system,
        user,
        reasoning=reasoning,
        schema_mode=schema_mode,
        thinking=thinking,
        image=image,
    )
    try:
        return request()
    except LLMError as error:
        if "ConnectionError" not in error.cause_type:
            raise
        return request()


# Keep Gemma4 vision input below the local runtime's observed high-resolution
# failure boundary. This is a pixel count, not a PDF rendering DPI.
MAX_VISION_PIXELS = 1_000_000
# Bump this version whenever the meaning of a persisted page changes.
PAGE_CHECKPOINT_VERSION = 4
STRUCTURE_REASONING_EFFORT: ReasoningEffort = "none"
STRUCTURE_SCHEMA_MODE: StructuredOutputMode = "json-schema"
STRUCTURE_THINKING_POLICY: ThinkingPolicy = "disabled"
# Keep private page reuse tied to the Adapter's fixed per-request policy.
STRUCTURE_THINKING_BUDGET_TOKENS = 0


def _response_schema_hash() -> str:
    """Response schema変更時に旧page checkpointを無効化する。"""

    encoded = json.dumps(
        StructureResponse.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bound_image(path: Path) -> Path:
    """画像全域を縦横比がおおむね保たれる整数寸法へ縮小し、画素数上限内で上書きする。"""

    with Image.open(path) as source:
        width, height = source.size
        if width * height <= MAX_VISION_PIXELS:
            return path
        scale = math.sqrt(MAX_VISION_PIXELS / (width * height))
        resized = source.resize(
            (max(1, math.floor(width * scale)), max(1, math.floor(height * scale))),
            Image.Resampling.LANCZOS,
        )
    try:
        if resized.width * resized.height > MAX_VISION_PIXELS:
            msg = "STRUCTURE image cannot fit pixel limit"
            raise ValueError(msg)
        resized.save(path, format="PNG")
    finally:
        resized.close()
    return path


def _page_key(page: Page, source_hash: str, rules: str, settings: Settings) -> str:
    """入力pageと出力に影響する設定だけをprivate checkpointへ結び付ける。"""

    values = {
        "version": PAGE_CHECKPOINT_VERSION,
        "source_hash": source_hash,
        "page": page.model_dump(mode="json"),
        "rules_hash": hashlib.sha256(rules.encode()).hexdigest(),
        "model": settings.structure_model,
        "base_url": settings.openai_base_url,
        "context_tokens": settings.context_tokens,
        "output_tokens": settings.output_tokens,
        "image_tokens": settings.image_tokens,
        "max_vision_pixels": MAX_VISION_PIXELS,
        "reasoning_effort": STRUCTURE_REASONING_EFFORT,
        "schema_mode": STRUCTURE_SCHEMA_MODE,
        "thinking_policy": STRUCTURE_THINKING_POLICY,
        "thinking_budget_tokens": STRUCTURE_THINKING_BUDGET_TOKENS,
        "response_schema_hash": _response_schema_hash(),
    }
    encoded = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_page_checkpoint(
    directory: Path, key: str, number: int
) -> tuple[Page, bytes, bytes] | None:
    """完全性と入力一致を確認し、信用できないprogressは再計算へ回す。"""

    files = [
        directory / name
        for name in (".complete.json", "meta.json", "page.json", "audit.json")
    ]
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or any(path.is_symlink() or not path.is_file() for path in files)
    ):
        return None
    try:
        if files[0].read_bytes() != b'{"complete":true}\n':
            return None
        meta = json.loads(files[1].read_text(encoding="utf-8"))
        page_bytes = files[2].read_bytes()
        audit_bytes = files[3].read_bytes()
        page = Page.model_validate_json(page_bytes)
        audit = json.loads(audit_bytes)
        if (
            not isinstance(meta, dict)
            or meta.get("key") != key
            or meta.get("page") != number
            or meta.get("page_sha256") != hashlib.sha256(page_bytes).hexdigest()
            or meta.get("audit_sha256") != hashlib.sha256(audit_bytes).hexdigest()
            or page.number != number
            or not isinstance(audit, list)
            or any(not isinstance(item, dict) for item in audit)
        ):
            return None
    except (OSError, ValueError, TypeError):
        return None
    return page, page_bytes, audit_bytes


def _save_page_checkpoint(
    directory: Path, key: str, page: Page, audit: list[dict[str, object]]
) -> tuple[bytes, bytes]:
    """完全な補正pageだけをatomicなprivate directoryへ保存する。"""

    page_bytes = (page.model_dump_json(indent=2) + "\n").encode("utf-8")
    audit_bytes = (json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    with atomic_directory(directory) as temporary:
        atomic_write_bytes(temporary / "page.json", page_bytes)
        atomic_write_bytes(temporary / "audit.json", audit_bytes)
        atomic_write_json(
            temporary / "meta.json",
            {
                "key": key,
                "page": page.number,
                "page_sha256": hashlib.sha256(page_bytes).hexdigest(),
                "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
            },
        )
    return page_bytes, audit_bytes


def _heading_jumps(page: Page) -> None:
    """非見出しのlevelを除去し、直前の見出しから二段以上深くなる階層を一段までに抑える。"""

    previous = 0
    for block in page.blocks:
        if block.kind != "heading":
            block.level = None
            continue
        level = block.level or 1
        block.level = min(level, previous + 1) if previous else level
        previous = block.level


def _merge_code(page: Page) -> None:
    """隣接するcode Blockの原文Inlineを先頭Blockへまとめ、ページ内の順序番号を振り直す。"""

    merged = []
    for block in page.blocks:
        if merged and merged[-1].kind == block.kind == "code":
            merged[-1].source.extend(block.source)
            continue
        merged.append(block)
    page.blocks = merged
    for order, block in enumerate(page.blocks):
        block.order = order


def _is_text_output_truncated(error: LLMError) -> bool:
    """Textの出力枯渇だけをSTRUCTUREのprompt fallback対象にする。"""

    return (
        error.stage == "text-output"
        and error.failure_kind == "output-truncated"
        and error.finish_reason == "length"
    )


def _apply(page: Page, response: StructureResponse) -> list[dict[str, object]]:
    """既知Blockへの構造提案とcaption移動を反映し、階層とcode連結を補正して変更監査を返す。"""

    blocks = {block.id: block for block in page.blocks}
    audit: list[dict[str, object]] = []
    for patch in response.patches:
        block = blocks.get(patch.block_id)
        if block is None:
            continue
        before = {
            "kind": block.kind,
            "level": block.level,
            "alert_kind": block.alert_kind,
        }
        if patch.kind is not None:
            if patch.kind != "table" and any(cell.images for cell in block.cells):
                raise ValueError("structure change would hide cell images")
            block.kind = patch.kind
        block.level = patch.level if block.kind == "heading" else None
        block.alert_kind = patch.alert_kind if block.kind == "alert" else None
        caption = blocks.get(patch.caption_source_id or "")
        if caption is not None and caption is not block:
            block.caption = caption.source
            caption.source = []
        audit.append(
            {
                "block_id": block.id,
                "before": before,
                "after": {
                    "kind": block.kind,
                    "level": block.level,
                    "alert_kind": block.alert_kind,
                },
                "reason": patch.reason,
            }
        )
    _heading_jumps(page)
    _merge_code(page)
    return audit


def _run_into(
    document: Document,
    source_pdf: Path,
    rules: str,
    settings: Settings,
    output_dir: Path,
    progress_dir: Path,
) -> Document:
    """本文ページをVLMで構造補正しpage別Artifactを保存する。"""

    result = document.model_copy(deep=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source_pdf)
    for index, page in enumerate(result.pages):
        if page.number == 1:
            continue
        key = _page_key(page, source_hash, rules, settings)
        cached = _read_page_checkpoint(
            progress_dir / f"page-{page.number:04d}", key, page.number
        )
        if cached is not None:
            result.pages[index], page_bytes, audit_bytes = cached
            atomic_write_bytes(output_dir / f"page-{page.number:04d}.json", page_bytes)
            atomic_write_bytes(
                output_dir / f"audit-{page.number:04d}.json", audit_bytes
            )
            continue
        payload = [
            {
                "id": block.id,
                "kind": block.kind,
                "level": block.level,
                "text": inline_text(block.source),
            }
            for block in page.blocks
        ]
        if not payload:
            response = StructureResponse()
        else:
            user = "次のblock構造を補正してください。\n" + json.dumps(
                payload, ensure_ascii=False
            )
            image_path = output_dir / f"page-{page.number:04d}.png"
            try:
                image = _bound_image(
                    pdf.render_page(source_pdf, page.number, image_path)
                )
            except (OSError, ValueError):
                image = None
            try:
                if image is not None:
                    # Note 1: Vision may repair layout that text alone cannot infer.
                    try:
                        response = _structure_request(
                            settings,
                            settings.structure_model or "",
                            StructureResponse,
                            rules,
                            user,
                            reasoning=STRUCTURE_REASONING_EFFORT,
                            schema_mode=STRUCTURE_SCHEMA_MODE,
                            thinking=STRUCTURE_THINKING_POLICY,
                            image=image,
                        )
                    except LLMError:
                        # Note 2: A complete text response may replace a failed or
                        # truncated vision response, never the partial response.
                        image = None
                if image is None:
                    try:
                        response = _structure_request(
                            settings,
                            settings.structure_model or "",
                            StructureResponse,
                            rules,
                            user,
                            reasoning=STRUCTURE_REASONING_EFFORT,
                            schema_mode=STRUCTURE_SCHEMA_MODE,
                            thinking=STRUCTURE_THINKING_POLICY,
                        )
                    except LLMError as error:
                        if not _is_text_output_truncated(error):
                            raise
                        # A local provider may spend the JSON-schema budget on
                        # generation. Prompt-mode format instructions are a
                        # bounded, sequential recovery path; never retry the
                        # same exhausted request.
                        response = _structure_request(
                            settings,
                            settings.structure_model or "",
                            StructureResponse,
                            rules,
                            user,
                            reasoning=STRUCTURE_REASONING_EFFORT,
                            schema_mode="prompt",
                            thinking=STRUCTURE_THINKING_POLICY,
                        )
            except LLMError as error:
                raise StructurePageError(
                    page.number, f"page/{page.number}", error
                ) from None
            finally:
                image_path.unlink(missing_ok=True)
        audit = _apply(page, response)
        page_bytes, audit_bytes = _save_page_checkpoint(
            progress_dir / f"page-{page.number:04d}", key, page, audit
        )
        atomic_write_bytes(output_dir / f"page-{page.number:04d}.json", page_bytes)
        atomic_write_bytes(output_dir / f"audit-{page.number:04d}.json", audit_bytes)
    return result


class StructureTask(BaseTask):
    """Execute STRUCTURE while sharing elapsed-time measurement only."""

    name = "STRUCTURE"

    def run(
        self,
        document: Document,
        source_pdf: Path,
        rules: str,
        settings: Settings,
        output_dir: Path,
    ) -> Document:
        """独自のページ再開記録を利用し、構造補正が正常終了したらTask成果物を公開する。"""

        with self.measure():
            progress_dir = output_dir.parent / "structure-pages"
            if progress_dir.is_symlink() or progress_dir.is_junction():
                msg = "linked STRUCTURE progress directory is not allowed"
                raise ValueError(msg)
            with atomic_directory(output_dir) as temporary:
                result = _run_into(
                    document,
                    source_pdf,
                    rules,
                    settings,
                    temporary,
                    progress_dir,
                )
                atomic_write_json(
                    temporary / "document.json", result.model_dump(mode="json")
                )
                return result


def run(
    document: Document,
    source_pdf: Path,
    rules: str,
    settings: Settings,
    output_dir: Path,
) -> Document:
    """Existing function delegates to the typed StructureTask operation."""

    return StructureTask().run(document, source_pdf, rules, settings, output_dir)

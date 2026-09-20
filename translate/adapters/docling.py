"""Docling Serveの非同期変換interface。"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from pathlib import Path

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class DoclingClient:
    """Docling jobのsubmit、poll、downloadを隠蔽する。"""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        ocr_preset: str = "tesseract",
        ocr_lang: str = "eng",
        force_ocr: bool = False,
        retry_attempts: int = 3,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 30.0,
        timeout_seconds: float = 300.0,
        deadline_seconds: float = 21_600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key} if api_key else {}
        self.ocr_preset = ocr_preset
        self.ocr_lang = ocr_lang
        self.force_ocr = force_ocr
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.timeout_seconds = timeout_seconds
        self.deadline_seconds = deadline_seconds

    def _request(
        self, method: str, url: str, deadline: float, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(1, self.retry_attempts + 1):
            try:
                stream = kwargs.get("files", {}).get("files", (None, None))[1]
                if hasattr(stream, "seek"):
                    stream.seek(0)
                response = getattr(httpx, method)(
                    url, timeout=self.timeout_seconds, **kwargs
                )
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                status = (
                    error.response.status_code
                    if isinstance(error, httpx.HTTPStatusError)
                    else None
                )
                retryable = (
                    status in {408, 429}
                    or (status is not None and status >= 500)
                    or status is None
                )
                if (
                    not retryable
                    or attempt >= self.retry_attempts
                    or time.monotonic() >= deadline
                ):
                    raise
                delay = min(
                    self.retry_base_seconds * (2 ** (attempt - 1)),
                    self.retry_max_seconds,
                )
                time.sleep(
                    random.uniform(  # noqa: S311
                        0, min(delay, max(0.0, deadline - time.monotonic()))
                    )
                )
            else:
                return response
        msg = "Docling request exhausted without response"
        raise RuntimeError(msg)

    def convert(
        self, source: Path, poll_interval: float = 1.0
    ) -> tuple[bytes, dict[str, Any]]:
        """文書を送信し、完了したZIPとjob情報を返す。"""

        suffix = source.suffix.casefold()
        if suffix not in CONTENT_TYPES:
            msg = f"unsupported Docling document: {source}"
            raise ValueError(msg)
        deadline = time.monotonic() + self.deadline_seconds
        with source.open("rb") as stream:
            # Note 1: These are Docling Serve multipart fields, not local options.
            # Keeping the payload explicit makes accuracy changes reviewable in one place.
            data = {
                # Request the lossless structured representation consumed by LOAD.
                "to_formats": "json",
                # Standard is required for OCR and enrichment; simple text is insufficient.
                "pipeline": "standard",
                # OCR is also applied to image regions in otherwise digital PDFs.
                "do_ocr": "true",
                # False preserves an existing text layer; set true only for a broken layer.
                "force_ocr": str(self.force_ocr).lower(),
                # Tesseract gives a local, reproducible OCR engine selection.
                "ocr_preset": self.ocr_preset,
                # Tesseract trained-data language name; default is English (`eng`).
                "ocr_lang": [self.ocr_lang],
                # Docling's native parser retains coordinates used by POSITION.
                "pdf_backend": "docling_parse",
                # Detect rows, columns, spans, and header cells instead of plain text.
                "do_table_structure": "true",
                # Accurate mode is slower but translation depends on reliable cell order.
                "table_mode": "accurate",
                # Match recognized text back to table cells to avoid duplicate fragments.
                "table_cell_matching": "true",
                # Infer PDF heading levels before STRUCTURE performs visual correction.
                "do_pdf_heading_hierarchy": "true",
                # Preserve code semantics so NORMALIZE does not clean literal content.
                "do_code_enrichment": "true",
                # Preserve formulas as formulas rather than prose fragments.
                "do_formula_enrichment": "true",
                # Export figures referenced by the JSON document.
                "include_images": "true",
                # Full page renders are produced on demand by pypdfium2 for the VLM.
                "include_page_images": "false",
                # A 2x source image balances caption detail and archive size.
                "images_scale": "2.0",
                # Store asset paths in JSON instead of embedding large base64 values.
                "image_export_mode": "referenced",
                # UNPACK expects one archive containing JSON and referenced assets.
                "target_type": "zip",
                # Partial Docling output must not silently enter MERGE.
                "abort_on_error": "true",
            }
            response = self._request(
                "post",
                f"{self.base_url}/v1/convert/file/async",
                deadline,
                headers=self.headers,
                files={"files": (source.name, stream, CONTENT_TYPES[suffix])},
                data=data,
            )
        submitted = response.json()
        task_id = submitted.get("task_id") or submitted.get("id")
        if not task_id:
            msg = "Docling response has no task_id"
            raise RuntimeError(msg)
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            status_response = self._request(
                "get",
                f"{self.base_url}/v1/status/poll/{task_id}",
                deadline,
                headers=self.headers,
            )
            payload = status_response.json()
            status = str(
                payload.get("task_status") or payload.get("status", "")
            ).casefold()
            if status in {"success", "succeeded", "completed"}:
                result = self._request(
                    "get",
                    f"{self.base_url}/v1/result/{task_id}",
                    deadline,
                    headers=self.headers,
                )
                return result.content, {
                    "task_id": task_id,
                    "status": status,
                    "attempts": attempts,
                }
            if status in {"failure", "failed", "error"}:
                msg = f"Docling task failed: {task_id}"
                raise RuntimeError(msg)
            time.sleep(poll_interval)
        msg = f"Docling task timed out: {task_id}"
        raise TimeoutError(msg)

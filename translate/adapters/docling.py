"""Docling Serveの非同期変換interface。"""

import logging
import random
import time
from pathlib import Path
from typing import Any

import httpx

from translate.common.config import Config

logger = logging.getLogger(__name__)
# Docling再起動を待てる上限(秒)。短い再試行を使い切った後もこの間は待機する。
OUTAGE_TOLERANCE_SECONDS = 1800.0
OUTAGE_RETRY_INTERVAL_SECONDS = 30.0


class DoclingClient:
    """Docling jobの送信、poll、downloadと有限再試行を隠蔽する。"""

    def __init__(self, config: Config) -> None:
        """検証済み設定を保持し、接続はconvertまで遅延する。

        Args:
            config (Config): 接続先、上限値および処理Optionを保持する設定。

        Raises:
            ValueError: `Docling server URL is required`と判定した場合。
        """

        if config.docling_server_url is None:
            raise ValueError("Docling server URL is required")
        self.config = config
        self.base_url = config.docling_server_url.rstrip("/")
        self.headers = (
            {"X-Api-Key": config.docling_api_key} if config.docling_api_key else {}
        )

    def convert(
        self, source: Path, poll_interval: float = 1.0
    ) -> tuple[bytes, str, int]:
        """文書を送信し、完了したZIP、job ID、poll回数を返す。

        Args:
            source (Path): 変換または検証対象の入力Source。
            poll_interval (float): Docling Job状態の確認間隔秒数。

        Returns:
            tuple[bytes, str, int]: 変換済みZIP、Job IDおよびPolling回数のTuple。

        Raises:
            RuntimeError: `Docling submit response must be an object`、`Docling response has no
                task_id`、`Docling status response must be an object`、`f'Docling task did not
                complete: {task_id}'`のいずれかと判定した場合。
            TimeoutError: `f'Docling task timed out: {task_id}'`と判定した場合。
        """

        deadline = time.monotonic() + self.config.external_task_deadline_seconds
        logger.info("Docling started file=%s", source.name)
        with source.open("rb") as stream:
            response = self._request_through_outage(
                "POST",
                f"{self.base_url}/v1/convert/file/async",
                deadline,
                files={"files": (source.name, stream, "application/pdf")},
                data=self._request_data(),
            )
        submitted = response.json()
        if not isinstance(submitted, dict):
            raise RuntimeError("Docling submit response must be an object")
        task_id = submitted.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("Docling response has no task_id")
        logger.debug("Docling request submitted")
        polls = 0
        while time.monotonic() < deadline:
            polls += 1
            status_response = self._request_through_outage(
                "GET",
                f"{self.base_url}/v1/status/poll/{task_id}",
                deadline,
            )
            payload = status_response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Docling status response must be an object")
            # Docling Serveの状態はsuccess、pending、started、failureだけである。
            status = str(payload.get("task_status", ""))
            logger.debug(
                "Docling poll=%d status=%s",
                polls,
                status if status in {"success", "failure"} else "pending",
            )
            if status == "success":
                result = self._request_through_outage(
                    "GET",
                    f"{self.base_url}/v1/result/{task_id}",
                    deadline,
                )
                logger.info(
                    "Docling completed file=%s polls=%d bytes=%d",
                    source.name,
                    polls,
                    len(result.content),
                )
                return result.content, task_id, polls
            if status == "failure":
                logger.warning("Docling failed status=%s polls=%d", status, polls)
                raise RuntimeError(f"Docling task did not complete: {task_id}")
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        logger.warning("Docling failed type=TimeoutError polls=%d", polls)
        raise TimeoutError(f"Docling task timed out: {task_id}")

    def _request_through_outage(
        self,
        method: str,
        url: str,
        deadline: float,
        **kwargs: Any,
    ) -> httpx.Response:
        """接続断と5xxの間は待機し、サーバー側のjobを手放さず要求を続ける。

        Args:
            method (str): Docling APIへ送信するHTTP Method。
            url (str): Request送信先URL。
            deadline (float): Pollingを終了するMonotonic Clock上の期限。
            **kwargs (Any): HTTP Clientへ渡す追加Request引数。

        Returns:
            httpx.Response: 成功したHTTP応答。

        Raises:
            httpx.HTTPError: 待機上限を超えた通信失敗、または再試行できないHTTP応答。
            TimeoutError: `Docling task deadline exceeded`と判定した場合。
        """

        limit = min(deadline, time.monotonic() + OUTAGE_TOLERANCE_SECONDS)
        while True:
            try:
                return self._request(method, url, deadline, **kwargs)
            except httpx.HTTPStatusError as error:
                if error.response.status_code < 500 or time.monotonic() >= limit:
                    raise
            except httpx.TransportError:
                if time.monotonic() >= limit:
                    raise
            logger.warning("Waiting for Docling recovery method=%s", method)
            time.sleep(
                min(OUTAGE_RETRY_INTERVAL_SECONDS, max(0.0, limit - time.monotonic()))
            )

    def _request(
        self,
        method: str,
        url: str,
        deadline: float,
        **kwargs: Any,
    ) -> httpx.Response:
        """streamを巻き戻し、仕様で再試行可能なHTTP失敗だけを再送する。

        Args:
            method (str): Docling APIへ送信するHTTP Method。
            url (str): Request送信先URL。
            deadline (float): Pollingを終了するMonotonic Clock上の期限。
            **kwargs (Any): HTTP Clientへ渡す追加Request引数。

        Returns:
            httpx.Response: streamを巻き戻し、仕様で再試行可能なHTTP失敗だけを再送する。

        Raises:
            httpx.HTTPError: HTTP Retryを使い切り、最後の通信Errorを再送出する場合。
            TimeoutError: `Docling task deadline exceeded`と判定した場合。
        """

        last_error: Exception | None = None
        for attempt in range(1, self.config.http_retry_attempts + 1):
            logger.debug("Docling HTTP request method=%s attempt=%d", method, attempt)
            stream = kwargs.get("files", {}).get("files", (None, None))[1]
            if hasattr(stream, "seek"):
                stream.seek(0)
            try:
                response = httpx.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=self.config.http_request_timeout_seconds,
                    **kwargs,
                )
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                status = (
                    error.response.status_code
                    if isinstance(error, httpx.HTTPStatusError)
                    else None
                )
                retryable = status is None or status in {408, 429} or status >= 500
                if not retryable or attempt >= self.config.http_retry_attempts:
                    logger.warning(
                        "Docling HTTP failed method=%s attempt=%d status=%s",
                        method,
                        attempt,
                        status,
                    )
                    raise
                delay = min(2 ** (attempt - 1), max(0.0, deadline - time.monotonic()))
                logger.warning(
                    "Retrying Docling HTTP request method=%s attempt=%d status=%s",
                    method,
                    attempt,
                    status,
                )
                if delay <= 0:
                    break
                time.sleep(random.uniform(0, delay))  # noqa: S311
            else:
                return response
        if last_error is not None:
            raise last_error
        raise TimeoutError("Docling task deadline exceeded")

    def _request_data(self) -> dict[str, str | list[str]]:
        """Docling変換品質を固定するmultipart fieldを返す。

        Returns:
            dict[str, str | list[str]]: Docling変換品質を固定するmultipart fieldを返す。
        """

        return {
            "to_formats": "json",
            "pipeline": "standard",
            "do_ocr": "true",
            "force_ocr": str(self.config.docling_force_ocr).lower(),
            "ocr_preset": self.config.docling_ocr_preset,
            "ocr_lang": [self.config.docling_ocr_lang],
            "pdf_backend": "docling_parse",
            "do_table_structure": "true",
            "table_mode": "accurate",
            "table_cell_matching": "true",
            "do_pdf_heading_hierarchy": "true",
            "do_code_enrichment": "true",
            "do_formula_enrichment": "true",
            "include_images": "true",
            "include_page_images": "false",
            "images_scale": "2.0",
            "image_export_mode": "referenced",
            "target_type": "zip",
            "abort_on_error": "true",
        }

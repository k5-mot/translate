"""Streamlit UI runtime module."""

from __future__ import annotations

import multiprocessing
import os
import subprocess
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from pathlib import Path
from threading import Lock

import streamlit as st

from translate.adapters.artifact_store import (
    ProcessingInUseError,
)
from translate.adapters.embedding import EmbeddingError
from translate.adapters.llm import LLMError
from translate.common.config import ConfigError, load_config
from translate.common.logger import configure_logging
from translate.pipeline import InputError
from translate.pipeline.register import RegisterPipeline
from translate.pipeline.review import ReviewPipeline
from translate.pipeline.translate import TranslatePipeline
from translate.pipeline.upgrade import UpgradePipeline

from .types import ProcessingKind


class WorkerRegistry:
    """単一workerから処理ごとの停止可能な子processを管理する。"""

    def __init__(self) -> None:
        """ローカルLLMを並列呼出ししない単一workerを作る。"""

        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ui")
        self._futures: dict[str, Future[object]] = {}
        self._processes: dict[str, BaseProcess] = {}
        self._stopping: set[str] = set()
        self._lock = Lock()

    def submit(self, processing_id: str, operation: Callable[[], object]) -> bool:
        """同じ処理IDが未完了でない場合だけworkerへ登録する。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。
            operation (Callable[[], object]): 子processで実行する処理。

        Returns:
            bool: 同じ処理IDが未完了でない場合だけworkerへ登録する。
        """

        with self._lock:
            existing = self._futures.get(processing_id)
            if existing is not None and not existing.done():
                return False
            self._stopping.discard(processing_id)
            self._futures[processing_id] = self._executor.submit(
                self._run, processing_id, operation
            )
            return True

    def _run(self, processing_id: str, operation: Callable[[], object]) -> None:
        """子processの完了を待ち、UIへ安全な失敗理由を返す。"""

        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        try:
            with self._lock:
                if processing_id in self._stopping:
                    return
                process = context.Process(target=_run_worker, args=(operation, sender))
                process.start()
                self._processes[processing_id] = process
            sender.close()
            process.join()
            with self._lock:
                self._processes.pop(processing_id, None)
                stopped = processing_id in self._stopping
            if stopped:
                return
            if receiver.poll():
                name, message = receiver.recv()
                if name:
                    raise WorkerError(f"{name}: {message}" if message else name)
            if process.exitcode != 0:
                raise WorkerError(
                    f"workerが終了しました (exit code {process.exitcode})"
                )
        finally:
            sender.close()
            receiver.close()

    def stop(self, processing_id: str) -> bool:
        """対象の待機Futureまたは実行中の子processを停止する。"""

        with self._lock:
            future = self._futures.get(processing_id)
            if future is None or future.done():
                return False
            if future.cancel():
                self._stopping.add(processing_id)
                return True
            process = self._processes.get(processing_id)
            if process is None:
                self._stopping.add(processing_id)
                return True
            if not process.is_alive():
                return False
            self._stopping.add(processing_id)
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
        else:
            process.terminate()
        stopped = wait([process.sentinel], timeout=5)
        if not stopped:
            process.kill()
            stopped = wait([process.sentinel], timeout=5)
        return bool(stopped)

    def future(self, processing_id: str) -> Future[object] | None:
        """処理IDに対応するFutureをthread-safeに取得する。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。

        Returns:
            Future[object] | None: 処理IDに対応するFutureをthread-safeに取得する。
        """

        with self._lock:
            return self._futures.get(processing_id)

    def active(self, processing_id: str) -> bool:
        """処理IDのFutureが待機中または実行中かを返す。

        Args:
            processing_id (str): 新規処理またはResume対象の処理ID。

        Returns:
            bool: 処理IDのFutureが待機中または実行中かを返す。
        """

        future = self.future(processing_id)
        return future is not None and not future.done()


class WorkerError(RuntimeError):
    """子processから返された利用者向けの失敗。"""


@st.cache_resource
def worker_registry() -> WorkerRegistry:
    """Streamlitの再読込み間で共有するworker登録表を返す。

    Returns:
        WorkerRegistry: Streamlitの再読込み間で共有するworker登録表を返す。
    """

    return WorkerRegistry()


@dataclass(frozen=True, slots=True)
class PipelineJob:
    """操作・入力Path・処理IDを保持し、子processで最新設定を読んで実行する。"""

    kind: ProcessingKind
    paths: tuple[Path, ...]
    processing_id: str
    source_id: str | None = None
    resuming: bool = False

    def __call__(self) -> object:
        """新規実行または再開を、対応するPipelineへ渡す。

        Returns:
            操作に対応する成果物情報。

        Raises:
            InputError: 操作の種類またはPipelineの入力・再開条件が不正な場合。
            ValueError: 操作に必要な入力Pathの数が一致しない場合。
            Exception: 設定検証やPipelineの実行に失敗した場合。
        """
        config = load_config()
        options = {
            "resume_id" if self.resuming else "processing_id": self.processing_id
        }
        if self.kind == "translate":
            (source,) = self.paths
            return TranslatePipeline(config).run(source, **options)
        if self.kind == "review":
            source, translation = self.paths
            return ReviewPipeline(config).run(source, translation, **options)
        if self.kind == "upgrade":
            source_v1, source_v2, translation_v1 = self.paths
            return UpgradePipeline(config).run(
                source_v1, source_v2, translation_v1, **options
            )
        if self.kind == "register":
            return RegisterPipeline(config).run(
                list(self.paths), source_id=self.source_id, **options
            )
        raise InputError("Unknown processing kind")


def _render_future_error(future: Future[object]) -> None:
    """完了済みFutureの例外を回収し、利用者向けに表示する。

    Args:
        future (Future[object]): 状態または例外を表示するBackground Future。
    """

    try:
        future.result()
    except (LLMError, EmbeddingError) as error:
        st.error(f"{type(error).__name__}: {error}")
    except (ConfigError, InputError, ProcessingInUseError, WorkerError) as error:
        st.error(str(error))
    except Exception as error:  # noqa: BLE001 - 予期外失敗は型名だけを表示する。
        st.error(f"処理に失敗しました: {type(error).__name__}")


def _run_worker(operation: Callable[[], object], sender: Connection) -> None:
    """子processでPipelineを実行し、許可した例外だけ本文を返す。"""

    try:
        configure_logging(load_config().log_level)
        operation()
    except (
        LLMError,
        EmbeddingError,
        ConfigError,
        InputError,
        ProcessingInUseError,
    ) as error:
        sender.send((type(error).__name__, str(error)))
    except Exception as error:  # noqa: BLE001 - 予期外失敗は型名だけ親processへ返す。
        sender.send((type(error).__name__, ""))
    else:
        # Windowsではpeerの切断だけでもpollがTrueとなるため、成功も明示する。
        sender.send(("", ""))
    finally:
        sender.close()

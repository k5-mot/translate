#!/usr/bin/env python3
"""PDF翻訳・比較Review・参照登録・DOCX変換のCLI。"""

from __future__ import annotations

import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer

from translate_v1.common.lifecycle import (
    PreparedRun,
    PublicRunError,
    ResumeRejectedError,
    candidates_for,
    execute_public_run,
    export_run,
    prepare_run,
    run_size,
)
from translate_v1.common.progress import ProgressEvent
from translate_v1.common.runs import InvalidRunIdError, Operation, RunRepository
from translate_v1.common.settings import Backend, Settings, load_settings
from translate_v1.common.workspace import atomic_write_bytes

app = typer.Typer(no_args_is_help=True, help="英語PDFを日本語化するユーティリティ")


def _progress(event: ProgressEvent) -> None:
    """Workflowから受けた進捗値とTask名を、再計算せず端末へ表示する。"""

    typer.echo(f"[{event.current}/{event.total}] {event.task}: {event.message}")


def _is_interactive() -> bool:
    """標準入出力がともに端末のときだけ、確認質問を許可する。"""

    return sys.stdin.isatty() and sys.stdout.isatty()


def _candidate_resume(  # noqa: C901, PLR0912, PLR0913, PLR0917
    repository: RunRepository,
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend,
    source_id: str | None = None,
) -> str | None:
    """対話時のみ同一入力の候補を示し、互換Runの明示確認が得られた場合だけIDを返す。"""

    if not _is_interactive():
        return None
    candidates = candidates_for(
        repository, operation, inputs, settings, backend, source_id
    )
    if not candidates:
        return None
    typer.echo("同じ入力の既存Run:")
    compatible = []
    for candidate in candidates:
        state = "互換" if candidate.compatibility.compatible else "非互換"
        typer.echo(
            f"  {candidate.record.run_id} {candidate.record.status} {state} "
            f"updated={candidate.record.updated_at.isoformat()}"
        )
        for reason in candidate.compatibility.reasons:
            typer.echo(f"    {reason}")
        if candidate.compatibility.compatible:
            compatible.append(candidate.record.run_id)
    if not compatible:
        return None
    selected = compatible[0]
    if len(compatible) > 1:
        selected = typer.prompt("再開するrun ID", default=selected)
        if selected not in compatible:
            message = "表示された互換run IDを指定してください"
            raise typer.BadParameter(message)
    if typer.confirm(f"Run {selected} を再開しますか?", default=False):
        return selected
    return None


def _prepare(  # noqa: PLR0913, PLR0917
    operation: Operation,
    inputs: dict[str, Path],
    settings: Settings,
    backend: Backend,
    resume: str | None,
    source_id: str | None = None,
) -> tuple[RunRepository, PreparedRun]:
    """明示Resumeまたは対話選択を共通準備処理へ渡し、拒否理由をCLI引数エラーへ変換する。"""

    repository = RunRepository(settings.runs_dir)
    selected = resume or _candidate_resume(
        repository, operation, inputs, settings, backend, source_id
    )
    try:
        prepared = prepare_run(
            repository,
            operation,
            inputs,
            settings,
            backend,
            selected,
            source_id,
        )
    except (ResumeRejectedError, InvalidRunIdError) as error:
        raise typer.BadParameter(str(error), param_hint="--resume") from None
    typer.echo(
        f"run_id={prepared.record.run_id} "
        f"mode={'resume' if prepared.resumed else 'new'}"
    )
    return repository, prepared


@app.command()
def translate(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
    backend: Annotated[Backend, typer.Option()] = "llm",
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """英語PDFを日本語DOCXへ変換する。"""

    settings = load_settings("translate", backend)
    repository, prepared = _prepare(
        "translate", {"source": source}, settings, backend, resume
    )
    try:
        record, _ = execute_public_run(
            repository, prepared, settings, backend, _progress
        )
    except PublicRunError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    for path in export_run(repository, record.run_id, output_dir):
        typer.echo(path)


@app.command()
def review(
    source_en: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    translation_ja: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """任意の英日PDFを比較してMarkdown reportを作る。"""

    settings = load_settings("review")
    repository, prepared = _prepare(
        "review",
        {"source_en": source_en, "translation_ja": translation_ja},
        settings,
        "llm",
        resume,
    )
    try:
        record, outputs = execute_public_run(
            repository, prepared, settings, callback=_progress
        )
    except PublicRunError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    atomic_write_bytes(output, outputs[0].read_bytes())
    typer.echo(f"run_id={record.run_id} exported={output}")


@app.command()
def register(
    paths: Annotated[list[Path], typer.Argument(exists=True)],
    resume: Annotated[str | None, typer.Option("--resume")] = None,
    source_id: Annotated[str | None, typer.Option("--source-id")] = None,
) -> None:
    """参照文書をQdrantへ登録する。"""

    settings = load_settings("register")
    inputs = {f"reference-{index:04d}": path for index, path in enumerate(paths, 1)}
    repository, prepared = _prepare(
        "register", inputs, settings, "llm", resume, source_id
    )
    try:
        record, outputs = execute_public_run(repository, prepared, settings)
    except PublicRunError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"run_id={record.run_id} result={outputs[0]}")


@app.command()
def convert(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    resume: Annotated[str | None, typer.Option("--resume")] = None,
    reference_doc: Annotated[
        Path | None, typer.Option("--reference-doc", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """MarkdownをPandocでDOCXへ変換する。"""

    settings = load_settings("convert")
    inputs = {"source": source}
    if reference_doc is not None:
        inputs["reference_doc"] = reference_doc
    repository, prepared = _prepare("convert", inputs, settings, "llm", resume)
    try:
        record, outputs = execute_public_run(repository, prepared, settings)
    except PublicRunError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None
    atomic_write_bytes(output, outputs[0].read_bytes())
    typer.echo(f"run_id={record.run_id} exported={output}")


@app.command("runs")
def list_runs() -> None:
    """共通RepositoryのRunを更新日時の新しい順に表示する。"""

    settings = load_settings("convert")
    repository = RunRepository(settings.runs_dir)
    scan = repository.list_runs()
    for warning in scan.warnings:
        typer.echo(f"warning: {warning}", err=True)
    for record in scan.records:
        names = ",".join(item.name for item in record.inputs)
        size = run_size(repository, record.run_id)
        typer.echo(
            f"{record.run_id}\t{record.status}\t{record.operation}\t"
            f"{names}\tlast={record.last_task or '-'}\t"
            f"updated={record.updated_at.isoformat()}\tsize={size}"
        )


@app.command("export")
def export_command(
    run_id: Annotated[str, typer.Argument()],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")],
) -> None:
    """完了Runの成果物を外部directoryへcopyする。"""

    repository = RunRepository(load_settings("convert").runs_dir)
    try:
        paths = export_run(repository, run_id, output_dir)
    except InvalidRunIdError as error:
        raise typer.BadParameter(str(error), param_hint="run_id") from None
    for path in paths:
        typer.echo(path)


@app.command("delete-run")
def delete_run(
    run_id: Annotated[str, typer.Argument()],
    confirm: Annotated[bool, typer.Option("--confirm")] = False,  # noqa: FBT002
) -> None:
    """停止済みRunをpath確認後に明示削除する。"""

    repository = RunRepository(load_settings("convert").runs_dir)
    try:
        path = repository.paths(run_id).root
    except InvalidRunIdError as error:
        raise typer.BadParameter(str(error), param_hint="run_id") from None
    typer.echo(f"delete target: {path}")
    approved = confirm
    if not approved and _is_interactive():
        approved = typer.confirm(f"Run {run_id} を削除しますか?", default=False)
    if not approved:
        message = "削除には対話確認または --confirm が必要です"
        raise typer.BadParameter(message, param_hint="--confirm")
    repository.delete(run_id)
    typer.echo(f"deleted: {run_id}")


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        app()
    finally:
        end = time.perf_counter()
        # 計測表示のstream障害で本体の例外・終了通知を置き換えない。
        with suppress(OSError, ValueError):
            print(f"[TIME] TOTAL: {end - start:.3f} s")  # noqa: T201

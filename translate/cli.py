"""Translate、Review、Register、Upgradeを公開するTyper CLI。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from translate.common.config import ConfigError, load_config
from translate.pipeline import InputError
from translate.pipeline.register import register_paths
from translate.pipeline.review import review_pdfs
from translate.pipeline.translate import translate_pdf
from translate.pipeline.upgrade import upgrade_pdfs

app = typer.Typer(
    name="translate-ja",
    help="英語文書の日本語翻訳、比較レビュー、参考資料登録、版更新を行います。",
    no_args_is_help=True,
)


@app.command("upgrade")
def upgrade_command(
    source_v1: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    source_v2: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    translation_v1: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    backend: Annotated[str, typer.Option("--backend")] = "llm",
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """英文二版と日本語旧版から日本語新版DOCXを生成する。"""

    try:
        outcome = upgrade_pdfs(
            source_v1,
            source_v2,
            translation_v1,
            load_config(),
            backend=backend,
            resume_id=resume,
        )
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (ConfigError, InputError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except Exception as error:
        typer.echo(f"Upgrade処理に失敗しました: {type(error).__name__}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"upgrade_id: {outcome.upgrade_id}")
    typer.echo(f"docx: {outcome.docx}")


@app.command("translate")
def translate_command(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    backend: Annotated[str, typer.Option("--backend")] = "llm",
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """英語PDFを日本語MarkdownおよびDOCXへ変換する。"""

    try:
        outcome = translate_pdf(
            source,
            load_config(),
            backend=backend,
            resume_id=resume,
        )
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (ConfigError, InputError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except Exception as error:
        typer.echo(f"翻訳処理に失敗しました: {type(error).__name__}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"translation_id: {outcome.translation_id}")
    typer.echo(f"markdown: {outcome.markdown}")
    typer.echo(f"docx: {outcome.docx}")


@app.command("review")
def review_command(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    translation: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """独立した英語原文PDFと日本語訳文PDFを比較する。"""

    try:
        outcome = review_pdfs(source, translation, load_config(), resume_id=resume)
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (ConfigError, InputError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except Exception as error:
        typer.echo(f"レビュー処理に失敗しました: {type(error).__name__}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"review_id: {outcome.review_id}")
    typer.echo(f"report: {outcome.report}")


@app.command("register")
def register_command(
    paths: Annotated[list[Path], typer.Argument(exists=True)],
    source_id: Annotated[str | None, typer.Option("--source-id")] = None,
    resume: Annotated[str | None, typer.Option("--resume")] = None,
) -> None:
    """参照資料をEmbeddingしてQdrantへ登録する。"""

    try:
        outcome = register_paths(
            paths,
            load_config(),
            source_id=source_id,
            resume_id=resume,
        )
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    except (ConfigError, InputError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except Exception as error:
        typer.echo(f"登録処理に失敗しました: {type(error).__name__}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"registration_id: {outcome.registration_id}")
    typer.echo(f"record: {outcome.record}")


def main() -> None:
    """console scriptとmodule実行の共通CLI境界を起動する。"""

    app()

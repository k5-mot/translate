# 📘 Translate JA

Translate JAは、英語PDFの日本語DOCX化、独立した英日PDFの比較Review、参照文書のQdrant登録、MarkdownからDOCXへの変換を提供するPython applicationです。CLIとStreamlitは同じRun Repositoryを使用し、中断したWorkflowを相互にResumeできます。

## 🚀 セットアップ

Python 3.12以降と`uv`を用意し、依存関係とbrowser test用runtimeを導入します。

```powershell
# 開発用Dependencyを含めて同期する。
uv sync --dev

# 環境変数の雛形を作成する。
Copy-Item .env.sample .env
```

`.env`へ利用する外部Serviceの接続情報を設定してください。Runの保存先は`TRANSLATE_RUNS_DIR`で変更でき、未設定時はRepository直下の`runs/`です。

## 🖥️ 公開操作

製品として直接実行を保証するentry pointは`cli.py`と`main.py`です。

```powershell
# 英語PDFを日本語DOCXへ変換する。
uv run python cli.py translate input.pdf --output-dir exported

# 独立した英日PDFを比較する。
uv run python cli.py review source-en.pdf translation-ja.pdf --output review.md

# 対応形式の参照文書またはdirectoryを登録元ID付きでQdrantへ登録する。
uv run python cli.py register references --source-id product-manuals

# Markdownを指定の参照DOCXでDOCXへ変換する（省略時は同梱template）。
uv run python cli.py convert document.md --output document.docx --reference-doc style.docx

# Streamlit UIを起動する。
uv run streamlit run main.py

# Runを一覧表示し、完了成果物を外部へexportする。
uv run python cli.py runs
uv run python cli.py export <run-id> --output-dir exported

# 停止済みRunの表示pathを確認して削除する。
uv run python cli.py delete-run <run-id> --confirm
```

CLIでRunを明示的に再開するときは`--resume <run-id>`を指定します。指定がなければ新規Runを作成しますが、対話端末で同一入力の互換Runが見つかった場合だけ確認を表示します。非対話環境では確認せず新規Runを作成します。

Runは`<run-id>/inputs/`、`<run-id>/outputs/`、`<run-id>/.workspace/`およびroot直下の`<run-id>/run.json`で構成されます。Workflow固有metadataは`.workspace/workflow.json`です。自動削除は行いません。Run削除はCLIまたはStreamlitの確認付き操作で行い、明示的にexportした成果物は削除対象外です。

## 🧪 品質確認

```powershell
# Lint、format、型およびtestを順に検証する。
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

同じGateはPython 3.12のWindows／Ubuntu CIで実行し、Pandocも各Jobで明示導入します。

## 🧭 設計資料

- 用語とContext: [CONTEXT.md](CONTEXT.md)
- 実装規則: [CODING_RULES.md](CODING_RULES.md)
- 文書規則: [DOCUMENTATION_RULES.md](DOCUMENTATION_RULES.md)
- Contribution手順: [CONTRIBUTING.md](CONTRIBUTING.md)
- 実装Task: [TODO.md](TODO.md)
- Run移行・運用・廃止手順: [docs/operations.md](docs/operations.md)

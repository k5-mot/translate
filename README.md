# 📘 Translate JA

Translate JAは、英語PDFを日本語のPandoc MarkdownとDOCXへ変換するPython
applicationです。独立した英日PDFの比較Reviewと、参照資料のQdrant登録も
提供します。生成LLMを使うTaskはSTRUCTURE、TRANSLATE、REVIEWだけです。

## 🚀 セットアップ

Python 3.12以降、`uv`、Pandocを用意します。Qdrantを使わない翻訳だけなら、
Qdrant clientは不要です。

```powershell
# 基本Dependencyを同期する。
uv sync

# Qdrantの検索またはRegisterを使う場合だけ追加する。
uv sync --extra qdrant

# 開発用Dependencyを同期する。
uv sync --dev

# 環境変数の雛形を作成する。
Copy-Item .env.sample .env
```

`.env`には、単一のOpenAI互換endpoint、Task別model、Docling Serveなど、
利用する外部serviceの接続情報を設定してください。process環境変数は`.env`より
優先されます。Qdrant関連設定を一式省略すると、TranslateとReviewのRAG検索は
無効になります。

## ⌨️ CLI

公開commandはTranslate、Review、Registerの3つです。

```powershell
# 英語PDFを日本語MarkdownとDOCXへ変換する。
uv run translate-ja translate inputs/sample.pdf

# LibreTranslateを本文翻訳に使う。
uv run translate-ja translate inputs/sample.pdf --backend libretranslate

# 独立した英語原文PDFと日本語訳文PDFを比較する。
uv run translate-ja review inputs/source.pdf inputs/translation.pdf

# 参照資料をQdrantへ登録する。
uv run translate-ja register references --source-id product-manuals

# 同じ入力と設定で中断済み処理を再開する。
uv run translate-ja translate inputs/sample.pdf --resume <uuidv7>
```

`python -m translate`も同じCLIを起動します。Resumeでは入力pathを再指定し、
内容のhashまたは処理へ影響する設定が変わっている場合は拒否します。同じ処理IDを
複数processから同時操作することもできません。

成果物は`outputs/<file-basename>/<uuidv7>/`へ保存します。Translateは
`translation.json`、Reviewは`review.json`、Registerは`registration.json`を
最上位の処理記録として持ちます。LLM Taskの診断は同じ階層の
`task-structure.json`、`task-translate.json`、`task-review.json`へ保存します。

## 🖥️ UIモック

初期実装のStreamlit画面はPipelineへ接続しないモックです。

```powershell
# UI用Dependencyを追加して画面モックを起動する。
uv sync --extra ui
uv run streamlit run main.py
```

## 🧪 品質確認

```powershell
# Format、Lint、型、Testを順に検証する。
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

`translate_v1`は参照用に保持しますが、新しい成果物やResume状態との互換性は
ありません。

## 🧭 設計資料

- 確定仕様: [SPEC.md](SPEC.md)
- 用語とContext: [CONTEXT.md](CONTEXT.md)
- 実装規則: [CODING_RULES.md](CODING_RULES.md)
- 文書規則: [DOCUMENTATION_RULES.md](DOCUMENTATION_RULES.md)
- Contribution手順: [CONTRIBUTING.md](CONTRIBUTING.md)
- 今後の候補: [TODO.md](TODO.md)

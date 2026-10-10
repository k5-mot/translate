# 📘 Translate JA

Translate JAは、英語PDFを日本語のPandoc MarkdownとDOCXへ変換するPython
applicationです。独立した英日PDFの比較Review、参照資料のQdrant登録、英文二版と
日本語旧版から日本語新版を作るUpgradeも提供します。生成LLMを使うTaskは
STRUCTURE、TRANSLATE、REVIEWだけです。

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

`.env`には、OpenAI互換endpoint、Task別model、Docling Serveなど、
利用する外部serviceの接続情報を設定してください。process環境変数は`.env`より
優先されます。Qdrant関連設定を一式省略すると、TranslateとReviewのRAG検索は
無効になります。

## ⌨️ CLI

公開commandはTranslate、Review、Register、Upgradeの4つです。

```powershell
# 英語PDFを日本語MarkdownとDOCXへ変換する。
uv run translate-ja translate inputs/sample.pdf

# LibreTranslateを本文翻訳に使う。
uv run translate-ja translate inputs/sample.pdf --backend libretranslate

# 独立した英語原文PDFと日本語訳文PDFを比較する。
uv run translate-ja review inputs/source.pdf inputs/translation.pdf

# 参照資料をQdrantへ登録する。
uv run translate-ja register references --source-id product-manuals

# 英文v1、英文v2、日本語v1から日本語v2 DOCXを生成する。
uv run translate-ja upgrade inputs/source-v1.pdf inputs/source-v2.pdf inputs/translation-v1.pdf

# 同じ入力と設定で中断済み処理を再開する。
uv run translate-ja translate inputs/sample.pdf --resume <uuidv7>
```

`python -m translate`も同じCLIを起動します。Resumeでは入力pathを再指定し、
内容のhashまたは処理へ影響する設定が変わっている場合は拒否します。同じ処理IDを
複数processから同時操作することもできません。

成果物は`outputs/<file-basename>/<uuidv7>/`へ保存します。Translateは
`translation.json`、Reviewは`review.json`、Registerは`registration.json`、Upgradeは
`upgrade.json`を
最上位の処理記録として持ちます。LLM Taskの診断は同じ階層の
`task-structure.json`、`task-translate.json`、`task-review.json`へ保存します。

## 🖥️ Streamlit UI

Streamlit UIからTranslate、Review、Register、UpgradeのPipelineを実行し、
処理履歴、TaskとLLM Callの進捗、現在処理中の対象text、Resumeおよび成果物を
確認できます。初回表示はライトテーマです。

```powershell
# UI用Dependencyを追加してlocalhostで起動する。
uv sync --extra ui
uv run streamlit run main.py --server.address localhost
```

Dockerで起動する場合は `.env` を用意し、次を実行します。
ホスト上のLLMやDoclingへ接続するURLには、必要に応じて
`host.docker.internal` を使用してください。

```powershell
# Streamlit用imageをbuildし、port 8501で起動する。
docker compose up --build
```

## 🧪 品質確認

```powershell
# Format、Lint、型、Testを順に検証する。
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

### 🤖 自動受入検証とCodex修正

CLI出力、Git状態、入力PDFのhash、処理記録、Task診断およびLLM Call状態の収集は
受入検証へ統合されています。各工程の診断ZIPは`.diagnostics/`へ保存されます。

軽量PDFのCLI検証とStreamlit UIのE2E検証は、次のcommandで実行できます。
既定では`sample.pdf`、`sample3.pdf`、`sample2.pdf`を対象にし、CLI検証後にUI契約を検証します。
`-IncludeLarge`を指定した場合は、軽量3件のCLI・UI検証が完了してから`sample1.pdf`へ進みます。
CLIではRegister、Translate、WordによるDOCXからPDFへの変換、Review、Upgradeを順番に実行します。

```powershell
# 軽量PDF 3件を検証する。Codexによる自動修正は行わない。
.\scripts\acceptance.ps1

# 失敗時にCodexを1回だけ呼び出し、品質検査後に再検証する。
.\scripts\acceptance.ps1 `
  -AutoRemediate `
  -MaxRepairAttempts 1

# 軽量PDF 3件の成功後、sample1.pdfも追加する。
.\scripts\acceptance.ps1 `
  -IncludeLarge `
  -AutoRemediate `
  -MaxRepairAttempts 1
```

`-Mode cli`は実PDFのCLI検証だけ、`-Mode ui`は`tests/e2e/test_ui.py`のmock pipelineを使ったUI契約検証だけを実行します。
Codex修正は`main`以外の作業ブランチでのみ行い、commit、merge、pushは実行しません。
既存の未コミット変更は診断Bundleへ記録し、修正対象と分離して保持します。
修正結果は`.diagnostics/`のBundleに保存されます。

### 🧪 実PDFの連続検証

`scripts/real_acceptance.ps1`は`sample3 → sample2 → sample5 → sample4`の順に、
各PDFを実際のStreamlit画面とCLIで`register → translate → review → upgrade`します。
各工程はUI、CLIの順です。`sample2`は依頼時の`ssample2`に対応する実ファイル名です。
画面は`127.0.0.1:8502`を使い、未起動なら自動起動します。
翻訳DOCXはMicrosoft WordでPDFに変換してReviewとUpgradeへ渡します。

```powershell
# 実ファイル、ブラウザー、Wordの検証を開始する。
.\scripts\real_acceptance.ps1
```

進行状況は`.tmp/real_acceptance_state.json`、直近のコマンド出力は
`.tmp/real_acceptance_command.log`に保存します。失敗時は
`.tmp/real_acceptance_failure.json`を作成してCodex CLIで修正・コミットし、
品質検査後に検証スクリプトをバックグラウンドで再起動します。
同じ工程で4回目の失敗になった場合は自動修正を停止します。
全件成功後、PR #5のCIを確認してマージコミットで`main`へ統合・pushします。

## 🧭 設計資料

- 確定仕様: [SPEC.md](SPEC.md)
- Streamlit UI仕様: [SPEC_v2.md](SPEC_v2.md)
- 用語とContext: [CONTEXT.md](CONTEXT.md)
- 実装規則: [CODING_RULES.md](CODING_RULES.md)
- 文書規則: [DOCUMENTATION_RULES.md](DOCUMENTATION_RULES.md)
- Contribution手順: [CONTRIBUTING.md](CONTRIBUTING.md)
- 今後の候補: [TODO.md](TODO.md)

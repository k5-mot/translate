# 📘 Translate JA

英語PDFの翻訳、英日PDFのReview、参照資料の登録、英文改訂のUpgradeを行うStreamlitアプリケーションです。仕様は[SPEC.md](docs/SPEC.md)を参照してください。

## 🚀 セットアップと起動

Python 3.12以降、uv、Pandoc、Docling ServeとOpenAI互換LLM endpointを用意します。RegisterにはEmbedding endpointとQdrantも必要です。

```powershell
# UIとQdrantを含む依存関係を同期し、環境変数の雛形をコピーする。
uv sync --extra ui --extra qdrant --dev
Copy-Item .env.sample .env

# .envへ接続先とモデルを設定した後、ローカルで起動する。
uv run streamlit run main.py --server.address localhost
```

`.env`ではTask別model、Docling接続先、必要に応じてEmbeddingとQdrantの接続情報を設定します。環境変数は`.env`より優先されます。Qdrant関連設定を省略したTranslate・Review・UpgradeではRAG検索を無効化します。

```powershell
# DockerでUIをbuildし、port 8501で起動する。
docker compose up --build
```

Dockerからホスト上のサービスへ接続する場合は、必要に応じて`host.docker.internal`を使います。

## 🖥️ 操作と成果物

| 操作 | 入力 | 成果物 |
|---|---|---|
| Translate | 英語PDF | 日本語Markdown・DOCX |
| Review | 英語原文PDF・日本語訳文PDF | 修正対象箇所・指摘・修正提案の一覧とJSON |
| Register | 単一・複数PDF、またはPDFを含むディレクトリ | Qdrantへの登録結果 |
| Upgrade | 英文旧版・新版PDF・日本語旧版PDF | 追加・変更・削除・移動した箇所と修正提案の一覧・JSON |

ReviewとUpgradeのAgentは、途中結果から調査対象と操作を選び、必要な文脈の取得や再確認を繰り返します。提案は一覧表示までとし、入力文書への適用やDOCXの生成は行いません。

成果物と入力PDFは`outputs/<file-basename>/<uuidv7>/`にまとめます。タスク成果物は`tasks/<番号>-<task名>/`、状態ファイルは`state-translation.json`などの名前で、ログは`translation.log`、`review.log`、`registration.log`または`upgrade.log`として処理ディレクトリ直下に保存します。

処理履歴から進捗確認、成果物のdownload、中断した処理のResumeができます。アップロードしたPDFを保存するため再アップロードは不要です。Resumeは入力ファイルの同一性を検証し、設定・規則・用語集の変更は再開拒否の理由にしません。同じ処理IDの同時実行はロックで防ぎます。履歴の削除は右クリックメニュー、または履歴にフォーカスしてShift+F10から行い、確認後に実行します。

## 🧪 品質確認

```powershell
# Lint、Format、型検査、Testを実行する。
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

### 🌐 実PDFの受入検証

実装をコミットしてから、`inputs/sample.pdf`、`sample2.pdf`、`sample3.pdf`、`sample4.pdf`、`sample5.pdf`の順に検証します。各PDFについてPlaywrightで実際のUIからRegister → Translate → Review → Upgradeを開始し、完了と成果物表示を確認します。TranslateのDOCXはWindowsのMicrosoft WordでPDFへ変換し、ReviewとUpgradeへ渡します。

Upgradeの新版入力には、元PDFの最終ページを削除した検証用PDFを`.tmp/versions/`へ生成します。入力の変更内容は同じ場所のJSONへ記録します。

```powershell
# Playwrightのブラウザーを準備し、実サービスとMicrosoft Wordで検証する。
uv run playwright install chromium
.\scripts\real_acceptance.ps1
```

未起動の場合は検証用UIを`127.0.0.1:8502`で起動します。実行ごとの状態・コマンド出力・画面キャプチャは`.tmp/acceptance/<実行ID>/`へ保存します。失敗時は停止します。コードを修正して品質検査とコミットを行った後、同じコマンドでsample.pdfのRegisterから全件を新しい処理IDで検証し直します。

## 🧭 設計・開発資料

- [仕様書](docs/SPEC.md)
- [コーディング規約](docs/CODING_RULES.md)
- [文書規約](docs/DOCUMENTATION_RULES.md)
- [Contribution手順](docs/CONTRIBUTING.md)

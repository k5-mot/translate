# 🖥️ Streamlit UI・Upgrade現行実装仕様 v2

本書は、現行Sourceを基準に、[`SPEC.md`](SPEC.md)で将来対応としたStreamlit UIと実Pipelineの
接続、および英文v1、英文v2、日本語v1から日本語v2を生成するUpgradeの実装済み動作を定める。
既存の文書変換、翻訳、Review、Register、成果物、Resumeおよび外部接続の共通契約は
[`SPEC.md`](SPEC.md)を参照し、本書はUI境界とUpgradeに必要な拡張だけを記録する。

- 本書の本文は、未実装の構想ではなく `main.py`、`translate/ui.py`、`translate/pipeline/upgrade.py`
  および関連Model・Taskの現行動作を表す。
- 本書と現行Sourceに差異が見つかった場合は、現行Sourceの動作を優先して本書を同期する。
- 現行実装に存在しない候補は「将来候補」だけに記載し、完了条件へ含めない。
- 以後の変更で実装と本書の動作が変わる場合は、同じ変更で本書も更新する。

## 🎯 目的

Streamlit UIは、次の操作をbrowserから実行できるようにする。

- 英語PDFを日本語MarkdownおよびDOCXへ変換する。
- 独立した英語原文PDFと日本語訳文PDFを比較Reviewする。
- 参照資料をQdrantへRegisterする。
- 英文v1 PDF、英文v2 PDFおよび日本語v1 PDFを対応付け、日本語v2 DOCXを生成する。
- Task単位とLLM Call単位の進捗を表示する。
- 中断または失敗した処理を、既存のResume契約に従って再開する。
- 成功した処理の成果物と処理記録を表示・downloadする。

対応言語は既存仕様どおり `en` から `ja` のみとする。

## 🚫 スコープ外

初期のStreamlit UIでは、次を実装しない。

- 複数LLM endpointの切替、振り分けおよびfailover
- 設定値やAPI keyをbrowserから編集する画面
- ユーザー認証、権限管理、複数tenant管理および外部公開用の防御
- SQLite、外部queue、外部schedulerまたは別のcheckpoint store
- UI独自のTask実行系、成果物SchemaまたはResume判定
- 実行中のHTTP要求をUIから強制終了する機能
- `translate_v1` の処理記録または成果物の表示・Resume
- Langfuseによる観測および性能最適化
- 日本語v1 PDFのpage layout、fontおよび組版を日本語v2 DOCXへ完全再現すること

browserのtabを閉じる操作は中断要求として扱わない。進行中の処理はStreamlit serverが
稼働している限り継続する。serverやprocessが停止した場合は、保存済みArtifactから
Resumeする。

## 🏗️ 構成

UIは既存Pipelineの薄いadapterとして実装する。Taskや外部adapterを直接呼び出しては
ならない。

```text
browser
  -> Streamlit UI
    -> background worker
      -> translate.pipeline
        -> outputs/<file-basename>/<uuidv7>/

Streamlit UI
  <- processing recordとLLM Call Artifactを1秒間隔で再読込み
```

UIの実行中は、既存の `translation.json`、`review.json`、`registration.json`、
現行実装の `upgrade.json`、
Task状態およびLLM Call Artifactを進捗の正本とする。Streamlitの `session_state`や
background workerの `Future`は正本としない。

### 🗂️ Source配置

現行実装の主要な追加・変更Sourceは次のとおりとする。test fixtureや既存Pipelineとの
接続に伴う小規模な変更は省略する。

```text
Dockerfile                      # StreamlitとPandocを含むcontainer image
docker-compose.yml              # .env、portおよび永続directoryの接続
main.py                         # Streamlit用entry point
pyproject.toml                  # UI用optional dependencyと実行設定
.streamlit/
└── config.toml                 # ライトテーマの既定値
translate/
├── artifact_store.py           # Windowsを含む原子的path置換
├── cli.py                      # Upgrade subcommand
├── ui.py                       # 画面、入力保存、worker、進捗読込み
├── assets/
│   └── translate-logo.svg      # AppBarへ表示するapplication logo
├── models/
│   ├── artifacts.py            # DIFF、REUSEのTaskName
│   └── upgrade.py              # UpgradeRecord、UpgradePlan
├── pipeline/
│   └── upgrade.py              # Upgrade Pipeline
└── tasks/
    ├── review/
    │   └── diff.py             # 英文v1と英文v2の決定的差分
    └── translation/
        └── reuse.py            # 日本語v1の決定的再利用
tests/
├── unit/                       # UIの表示値とArtifact解決
├── e2e/                        # CLI processとPlaywright browser操作
└── regression/                 # Pipeline、Resumeおよび既存機能との統合契約
```

- rootの `main.py` は `translate.ui.main` を呼び出すだけとする。
- `translate/ui.py` はStreamlit固有の表示と、UIからPipelineへの接続を所有する。
- UIのために `views`、`controllers`、`services`などの追加packageを設けない。
- `translate/pipeline/` はStreamlitをimportしてはならない。
- 実装の増大により `ui.py` の分割が必要になった場合だけ、別の変更で再設計する。

### 📦 依存関係

- UI用optional dependencyは既存の `streamlit>=1.64.0` だけとする。
- Register用optional dependencyは `qdrant-client>=1.16.0,<2` とし、`all` extraはUI用と
  Register用の両方を導入する。
- background workerは標準Libraryの `concurrent.futures.ThreadPoolExecutor` を使用する。
- UI実装のためにprocess manager、queue、databaseまたはfilesystem watcherを追加しない。
- 新しい永続化データモデルが必要になった場合はPydanticの `BaseModel` を使用する。
  初期UIでは既存のArtifactモデルで足りるため、UI専用のJSON Schemaは追加しない。

## 🚀 起動契約

UIは次の手順で起動する。

```powershell
# UI用Dependencyを同期し、localhostでStreamlitを起動する。
uv sync --extra ui
uv run streamlit run main.py --server.address localhost
```

- UIは現在の作業directoryの `.env` とprocess環境変数を既存 `load_config()` で読み込む。
- `outputs`と `.translate-ui` は現在の作業directory直下を使用する。
- 初期構成はlocalhostでの単一Streamlit server processを前提とする。
- localhost以外へbindする場合のTLS、認証、reverse proxyおよびaccess制御は運用側の責務とする。
- 設定値とsecretはUIへ表示しない。UIは `.env` を書き換えない。

CLIの現行終了契約は次のとおりとする。

| 終了code | 条件 |
|---|---|
| `0` | Pipeline成功。処理IDと成果物pathを標準出力へ表示する |
| `1` | 予期しない例外。処理種類と例外型を標準errorへ表示する |
| `2` | `ConfigError` または `InputError`。検証messageを標準errorへ表示する |
| `130` | `KeyboardInterrupt` |

### 🐳 Docker起動

- `Dockerfile` の基盤imageは `ghcr.io/astral-sh/uv:python3.12-trixie` とする。
- imageは `uv sync --frozen --all-extras --no-dev` でUIとRegisterを含む実行依存を固定する。
- DOCX公開に必要なPandocをDebian packageから導入する。
- containerはStreamlitを `0.0.0.0:8501` で起動する。
- container起動時はheadless modeを有効にし、Streamlitの利用統計送信を無効にする。
- `docker-compose.yml` は `.env` を環境変数として渡す。imageへ `.env` を複製しない。
- `outputs` と `.translate-ui` はホストdirectoryをbind mountし、container再作成後も保持する。
- ホスト上の外部serviceへは `host.docker.internal` で接続できる構成とする。
- healthcheckは `/_stcore/health` をcontainer内から確認する。

## 🧭 画面構成

画面は次の5領域で構成する。

| 領域 | 責務 |
|---|---|
| Translate | 英語PDFの翻訳と公開 |
| Review | 英語原文PDFと日本語訳文PDFの比較Review |
| Register | 参照資料のQdrant登録 |
| Upgrade | 英文v1、英文v2および日本語v1から日本語v2を生成 |
| 処理履歴 | 状態、進捗、Resumeおよび成果物の表示 |

Translate、Review、UpgradeおよびRegisterは、この順序で `st.tabs` に表示する。処理履歴は各tabから共通で
参照できる領域とし、処理IDをURL query parameterに保持する。browserを更新しても、
同じ処理IDの表示を復元する。query parameter名は `processing` とする。

- application名 `Translate` は `st.logo` でAppBar左側へ表示し、本文の独立した大見出しにはしない。
- Session IDは入力領域のCollapse labelへ含めず、`Translate` とDeploy buttonと同じAppBarの
  縦位置へ独立して表示する。新規処理では `新規セッション` と表示する。現行実装では
  `st.html` の固定配置要素をこの表示だけに使用し、document由来の値はHTML escapeする。
- 処理履歴は左sidebarへ折り畳まず、新しい順のbuttonとして縦に並べる。選択中の処理は
  buttonの状態でも識別できるようにする。
- 本文の入力領域は上からPipeline tab、file upload、各種option、開始buttonの順とする。
- 入力領域全体は折り畳み可能とし、新規処理では展開、処理開始後または履歴選択後は
  既定で閉じる。Collapse labelは `入力と設定` とする。
- 処理開始後は、折り畳み可能な進捗領域へ、ProgressBar、進捗詳細、二列・三列の
  読取専用TextAreaの順に表示する。ProgressBarには完了Task数・総Task数、現在または
  直近のTask名およびTask状態をtextで併記する。進捗詳細は既定で閉じたCollapseとし、
  最上位JSONの更新時刻とSTRUCTURE、TRANSLATE、REVIEWのLLM Call進捗内訳だけを表示する。
  進捗領域全体は既定で展開する。

全操作で次を必須とする。

- 入力widgetの変更だけで処理を開始せず、明示的な開始buttonで確定する。
- 処理開始buttonは必須入力が揃うまでdisabledとする。
- 同じbrowser sessionからの連打で同じ処理IDを二重登録しない。
- 状態は色だけで表さず、必ずtextで併記する。
- widgetには可視labelを付け、キーボード操作を妨げる独自HTMLを使用しない。

### 🎨 表示テーマ

- `.streamlit/config.toml` の `[theme]` に `base = "light"` を設定し、初回表示は
  OSおよびbrowserの配色設定に依存せずライトモードとする。
- 同fileの `[browser]` に `gatherUsageStats = false` を設定し、local起動でも
  Streamlitの利用統計を送信しない。
- 利用者がStreamlitのSettingsから選択したテーマは、そのbrowser sessionでは既定値を
  上書きしてよい。
- application独自のテーマ切替widgetおよび独自CSSによる配色上書きは設けない。
- 状態、エラーおよび進捗はライトモードでも色だけに依存せず判別できる必要がある。

### 🌐 Translate

| 項目 | 仕様 |
|---|---|
| 英語PDF | `.pdf` の単一fileを必須とする |
| 翻訳backend | `llm` または `libretranslate`。既定値は `llm` |
| 開始操作 | `translate_pdf()` をbackground workerへ登録する |
| 成功時 | MarkdownとDOCXのdownloadを表示する |

- UIはsource languageとtarget languageの選択欄を設けない。
- Markdown previewを表示する場合は `unsafe_allow_html=False` とする。
- Markdown previewは、publisherが独立した一行として生成する
  `![caption](relative-path){Pandoc attributes}` 形式を画像要素として認識する。
- 相対画像pathはURL decodeした後、Markdown fileのdirectory内に解決できる既存fileだけを
  `st.image`で表示する。directory外参照または欠落fileは画像を表示せず、警告を表示する。
- schemeまたはhostを持つ画像URL、および行中に埋め込まれた画像記法は専用のpath解決を行わず、
  `unsafe_allow_html=False` の `st.markdown`へ渡す。Preview処理はMarkdownのdownload本文を
  変更しない。
- Resume時のbackendは `translation.json` に保存された値に固定し、変更を許可しない。

### 🔎 Review

| 項目 | 仕様 |
|---|---|
| 英語原文PDF | `.pdf` の単一fileを必須とする |
| 日本語訳文PDF | `.pdf` の単一fileを必須とする |
| 開始操作 | `review_pdfs()` をbackground workerへ登録する |
| 成功時 | `review.md` のpreviewとdownloadを表示する |

Review画面はFIXを実行せず、REPORTに含まれる指摘と修正候補を表示する。

- ALIGN完了後は、同じ `ReviewTarget` の英語原文と現在の日本語訳を、二つの読取専用
  TextAreaへ横並びで表示する。

### 📚 Register

| 項目 | 仕様 |
|---|---|
| 参照資料 | `.pdf`、`.docx`、`.pptx`、`.md`、`.markdown`、`.txt` の1件以上 |
| `source_id` | 複数fileでは必須、単一fileでは任意 |
| 開始操作 | `register_paths()` をbackground workerへ登録する |
| 成功時 | collection、Embedding model、各fileの状態、Point数と合計を表示する |

- browserからはfile uploadだけを受け付け、directory uploadは提供しない。directory指定はCLIで行う。
- 一度にuploadできるfileは100件までとする。
- 同じbasenameを持つ複数fileは論理pathが衝突するため、処理開始前に拒否する。
- `source_id` は[`SPEC.md`](SPEC.md)のRegister契約と同じ検証を使用し、UI独自の置換を行わない。

### 🆙 Upgrade

| 項目 | 仕様 |
|---|---|
| 英文v1 | `.pdf` の単一fileを必須とする |
| 英文v2 | `.pdf` の単一fileを必須とする |
| 日本語v1 | `.pdf` の単一fileを必須とする |
| 翻訳backend | `llm` または `libretranslate`。既定値は `llm` |
| 開始操作 | `upgrade_pdfs()` をbackground workerへ登録する |
| 成功時 | 日本語v2の `document.ja.docx` をdownload対象として表示する |

- 3fileは列または明確なlabelで区別し、入替えを防ぐ。
- 日本語v2の構造、読み順、画像および表は英文v2を正本とする。
- 日本語v1は既存訳の再利用と、変更箇所を翻訳する際の文脈にだけ使用する。
- 日本語v1 PDFの組版をDOCXへ複製せず、既存publisherで新しいDOCXを生成する。
- Resume時のbackendは `upgrade.json` に保存された値に固定し、変更を許可しない。
- DIFF完了後は、同じ `VersionChange` に対応する英語v1、日本語v1および英語v2を、
  三つの読取専用TextAreaへ横並びで表示する。

## 📥 Upload入力の保存

`UploadedFile` はPipelineへ直接渡さず、処理開始前に次の作業directoryへ保存する。

```text
.translate-ui/<uuidv7>/
├── translate/
│   └── <original-basename>.pdf
├── review/
│   ├── source/<original-basename>.pdf
│   └── translation/<original-basename>.pdf
├── register/
│   ├── 0001/<original-basename>
│   └── 0002/<original-basename>
└── upgrade/
    ├── source-v1/<original-basename>.pdf
    ├── source-v2/<original-basename>.pdf
    └── translation-v1/<original-basename>.pdf
```

- directory名のUUIDv7は対応する `translation_id`、`review_id`、`registration_id` または
  `upgrade_id` と同じ値とする。
- `.translate-ui/` はGit管理対象外とする。
- upload元のbasenameは成果物最上位directory名と `logical_path` のために保持する。
- basenameが空、`.`、`..`、path separatorまたは制御文字を含む場合は拒否する。
- fileの拡張子は大文字と小文字を区別せず検査する。MIME typeだけを信頼しない。
- 保存は一時fileへ書き込んだ後、同一filesystem内で原子的に確定する。Windowsの
  `WinError 5` による一時的なpath置換失敗は、50 msから始まる指数backoffで再試行し、
  初回を含む5回で確定できなければ失敗とする。
- Streamlitの `server.maxUploadSize` を1file当たりの上限とし、application独自の別のsize設定を追加しない。
- 保存した入力はResumeのために自動削除しない。初期UIは削除画面を提供しない。

## ⚙️ Pipeline接続契約

UIは保存先をPipeline起動前に決定し、即時に処理IDを表示できる必要がある。
そのため、次の4関数がkeyword-onlyの `processing_id: str | None = None` を受け取る。

- `translate.pipeline.translate.translate_pdf()`
- `translate.pipeline.review.review_pdfs()`
- `translate.pipeline.register.register_paths()`
- `translate.pipeline.upgrade.upgrade_pdfs()`

処理IDの決定は次の契約に従う。

| `processing_id` | `resume_id` | 動作 |
|---|---|---|
| `None` | `None` | Pipelineが新しいUUIDv7を生成する |
| UUIDv7 | `None` | 指定IDで新規処理を開始する |
| `None` | UUIDv7 | 指定IDの既存処理をResumeする |
| UUIDv7 | UUIDv7 | 入力エラーとして拒否する |

- `processing_id`と `resume_id` は正規のUUIDv7だけを受け付ける。
- `processing_id`で決定する処理directoryに最上位記録が既に存在する場合は、上書きせず拒否する。
- Resumeに `processing_id` を代用してはならない。Resumeは引き続き `resume_id` を使用する。
- CLIは `processing_id` を入力するoptionを公開せず、従来の引数契約を維持する。
- Translate、ReviewおよびRegisterの `outputs`配置、最上位JSON、fingerprint、Resume判定
  および排他lockの契約を変更しない。Upgradeも同じ原則へ従う。

## ♻️ Upgrade契約

UpgradeはTranslate、ReviewおよびRegisterと同じ階層の公開commandとする。

```text
translate-ja upgrade <source-v1.pdf> <source-v2.pdf> <translation-v1.pdf> [--backend llm|libretranslate] [--resume <upgrade-id>]
```

- `source-v1.pdf` と `source-v2.pdf` は英語、`translation-v1.pdf` は日本語に固定する。
- `--backend` の既定値は `llm` とし、追加または再翻訳が必要なtextだけに適用する。
- 成功時はUpgrade IDと日本語v2 DOCXのpathを表示する。
- UIとCLIは同じ `upgrade_pdfs()` を呼び出し、別のUpgrade処理系を持たない。

### 🔀 Pipeline

```text
英文v1:   SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD ─┬→ ALIGN
日本語v1: SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD ─┘

英文v2:   SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD → STRUCTURE
英文v1 LOAD ─┐
英文v2 LOAD ─┴→ DIFF

英文v2 STRUCTURE + ALIGN + DIFF → REUSE
→ 未再利用textだけTRANSLATEまたはTRANSLATE-LITE
→ CHECK → 追加・変更・再翻訳対象だけREVIEW
→ 修正候補あり: FIX
→ 修正候補なし: FIX省略
→ 最終CHECK
→ 空訳あり: 停止
→ 空訳なし: LINT
→ valid: COVER → MARKDOWN → DOCX
→ invalid: 停止
```

- ALIGNは英文v1と日本語v1を既存の決定的規則で対応付ける。
- DIFFとREUSEはLLMを使用しない。LLMを使用するTaskは既存どおりSTRUCTURE、TRANSLATE、
  REVIEWだけとする。
- `TaskName` は `DIFF` と `REUSE` を持つ。`UPGRADE` というTaskは設けず、Upgradeは
  Pipeline名および公開command名として使用する。
- STRUCTUREは最終成果物の構造となる英文v2だけに実行する。
- REVIEWはUpgrade中に翻訳または再翻訳した対象だけに実行し、再利用した未変更訳を
  LLMへ再送しない。CHECK、最終CHECKおよびLINTは文書全体を対象とする。
- REUSE後に翻訳対象が0件ならTRANSLATEまたはTRANSLATE-LITEを `skipped` とし、REVIEWも
  `skipped` とする。CHECK以降の決定的Taskは省略しない。
- COVERは英文v2 PDFから生成し、画像および表を含む公開用assetも英文v2を正本とする。

### 🔍 DIFF

DIFFは英文v1と英文v2のTextUnitを次の順に決定的に対応付ける。

1. textをNFKCで正規化し、前後空白を除去して連続空白を一つのspaceへ変換する。
2. 同じroleと正規化textの組が両文書に一度だけ現れる場合は、読み順に関係なく対応を
   確定する。同じ位置なら `unchanged`、位置が変わった場合は `moved` とする。
3. 残った要素へ既存ALIGNと同じ一意anchor、読み順およびrole列の規則を適用する。
4. 手順3の1対1対応で正規化textが同じなら `unchanged`、異なる場合は `modified` とする。
5. 英文v1側だけに残る要素は `deleted`、英文v2側だけに残る要素は `added` とする。

DIFFはEmbedding、文字列類似度、LLM fallback、confidence score、1対多および多対1の推測を
使用しない。誤った対応より `deleted` と `added` の組として新規翻訳することを優先する。

### 🔁 REUSE

REUSEは `unchanged` または `moved` の英文v2 TextUnitについて、次をすべて満たす場合だけ
日本語v1を再利用する。

- DIFFで英文v1と英文v2が1対1に対応している。
- ALIGNで対応する英文v1と日本語v1が1対1に対応している。
- 日本語v1の対象textが空でない。
- 英文v2と日本語v1で翻訳対象Spanの件数と `kind` が読み順に一致する。

再利用時は日本語v1の各Spanのsource textを、対応する英文v2 Spanの `translated` へ読み順で
設定する。ID、marks、link、構造、画像および表は英文v2側を保持する。条件を一つでも
満たさない場合は推測して移植せず、英文v2の該当TextUnitを翻訳対象へ残す。

- `modified` は英文v2を全文翻訳する。LLM backendで対応する英文v1と日本語v1がある場合は、
  旧英日ペアを翻訳文脈としてTRANSLATEのpromptへ追加する。TRANSLATE-LITEへは追加しない。
- `added` および再利用できなかった `unchanged` または `moved` は英文v2だけから翻訳する。
- `deleted` は英文v2 Documentへ含めない。
- 旧英日ペアは参考情報であり、TRANSLATE応答の対象ID、Schemaおよび適用規則を変更しない。
- 採用した旧英日ペアのIDとtext hashをLLM Call fingerprintへ含める。

### 🧱 データモデル

`UpgradeRecord` は `upgrade.json` のroot modelとし、次のfieldを持つ。

| Field | Type |
|---|---|
| `schema_version` | `Literal[1]` |
| `upgrade_id` | `str` |
| `status` | `ProcessingStatus` |
| `source_v1` | `InputFile` |
| `source_v2` | `InputFile` |
| `translation_v1` | `InputFile` |
| `source_language` | `Literal["en"]` |
| `target_language` | `Literal["ja"]` |
| `backend` | `Literal["llm", "libretranslate"]` |
| `tasks` | `list[TaskState]` |
| `llm_progress` | `list[LLMProgress]` |
| `outputs` | `list[ArtifactFile]` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |
| `error` | `ProcessingError \| None` |

`InputFile.role` はそれぞれ `source_v1`、`source_v2`、`translation_v1` とする。
`UpgradePlan` は `changes: list[VersionChange]` を持ち、`VersionChange` は次のfieldを持つ。

| Field | Type |
|---|---|
| `id` | `str` |
| `kind` | `Literal["unchanged", "moved", "modified", "added", "deleted"]` |
| `source_v1_ids` | `list[str]` |
| `source_v2_ids` | `list[str]` |
| `translation_v1_ids` | `list[str]` |
| `action` | `Literal["reuse", "translate", "delete"]` |
| `method` | `Literal["unique_text", "unique_anchor", "ordered_role", "unmatched"]` |

`ReuseReport` は `schema_version: Literal[1]`、再利用できたTextUnit IDを保持する
`reused_unit_ids: list[str]`、翻訳対象として残したTextUnit IDを保持する
`translation_target_ids: list[str]` を持ち、`upgrade/reuse/report.json` に保存する。

すべてのモデルはPydanticの `BaseModel` を継承し、`ConfigDict(extra="ignore")` を使用する。

### 📁 成果物

英文v2の `Path.stem` を最上位名に使い、UUIDv7を `upgrade_id` とする。

```text
outputs/<source-v2-basename>/<upgrade-id>/
├── upgrade.json
├── task-structure.json
├── task-translate.json      # LLMのTRANSLATEを開始した場合だけ
├── task-review.json         # REVIEWを開始した場合だけ
├── converter/
│   ├── source-v1/{split,docling,unpack,merge}/
│   ├── source-v2/{split,docling,unpack,merge}/
│   └── translation-v1/{split,docling,unpack,merge}/
├── preprocess/
│   ├── source-v1/{position,normalize,load}/
│   ├── source-v2/{position,normalize,load,structure}/
│   └── translation-v1/{position,normalize,load}/
├── upgrade/
│   ├── align/result.json
│   ├── diff/plan.json
│   └── reuse/{document.json,report.json}
├── translation/
│   └── translate/ または translate-lite/
├── review/{check,review,fix}/
└── publisher/{lint,cover,markdown,docx}/
```

利用者向け最終成果物は `publisher/docx/document.ja.docx` とする。MARKDOWNはDOCX生成に必要な
中間Artifactとして保存するが、`UpgradeRecord.outputs` にはDOCXだけを記録する。

### ⏯️ Resume

- Resumeでは3入力のrole、logical path、sizeおよびSHA-256をすべて照合する。
- いずれかの入力内容またはbackendが保存済み記録と異なる場合はResumeを拒否し、新しい
  Upgrade IDを要求する。
- DIFFとREUSEのfingerprintにはそれぞれのalgorithm schema versionを含める。algorithm
  schema、model、rulesまたはpublisher設定が変わった場合は、対応するTask以降を既存の
  fingerprint規則に従って再処理する。
- UIからResumeする場合は保存済み3fileを使用し、CLIから開始した処理など保存済み入力が
  ない場合は3fileすべての再uploadを要求する。
- 同じUpgrade IDの同時操作を `ProcessingLock` で拒否する。
- 旧Schema、`translate_v1` 成果物および別のTranslation IDのArtifactを再利用しない。

## 🧵 background worker

- UIは `ThreadPoolExecutor(max_workers=1)` を1つだけ保持する。
- workerと処理IDごとの `Future` の対応は `st.cache_resource` でStreamlitの再読込みを跨いで保持する。
- 複数browser sessionから共有されるworker登録表の読書きは標準Libraryの `threading.Lock` で保護する。
- UIから開始されたTranslate、Review、RegisterおよびUpgradeは単一worker上で順番に処理する。
- 待機中の `Future` は「待機中」と表示する。この状態はUIの一時状態であり、Artifactへ保存しない。
- 同じ処理IDの `Future` が未完了の場合は再登録しない。
- UI worker以外のCLIとの衝突は既存 `ProcessingLock` で拒否する。
- worker内で `load_config()` を呼び出し、処理開始ごとに現在の環境設定を確定する。
- Streamlit server再起動で `Future` を失っても、Artifactを失わない。利用者は処理履歴からResumeする。
- `Future.result()` は `Future.done()` の確認後だけ呼び出し、Streamlitの表示threadを待機させない。

単一workerは、ローカルLLMへの同時要求をUIが不用意に増やさないための初期制限とする。
CLIと外部serviceの同時実行能力まで制限するものではない。

## 📊 進捗表示

進捗領域は `st.fragment(run_every="1s")` で更新する。最上位JSONがまだ存在しない間は、
`Future`の状態から「待機中」または「準備中」を表示する。

最上位JSONの保存後は、次を表示する。

| 表示 | 正本 |
|---|---|
| 処理ID | `translation_id`、`review_id`、`registration_id` または `upgrade_id` |
| 処理状態 | 最上位JSONの `status` |
| 現在のTask | `status="processing"` の `TaskState` |
| 完了Task | `succeeded` または `skipped` のTask数 |
| LLM進捗 | 実行中はCall Artifactの完了数と観測数、Task完了後は `LLMProgress` の `completed_calls / planned_calls` |
| LLM再利用 | Task完了後の `LLMProgress.reused_calls` |
| LLM失敗 | 実行中はCall Artifact、Task完了後は `LLMProgress.failed_calls` |
| Register進捗 | 最上位JSONの `status` を使用した0または1の固定Task表示 |
| 更新時刻 | 最上位JSONの `updated_at` |

- LLM Task実行中は該当Taskの `calls/*/call.json` を直接集計し、完了、観測済みおよび失敗Call数を表示する。
  Call分割によって観測数が増える場合があるが、実行中の予定総数は推測しない。
- `succeeded`、`partial` および子Callへ分割済みの `split` を、実行中表示の完了Callとして数える。
- Task完了後は最上位記録の `LLMProgress` を表示し、この時点で予定Call数と再利用Call数を表示する。
- 予定Call数が0またはまだ確定していない間は、虚偽の百分率を表示せず、件数と状態だけを表示する。
- 読み込めない個別Call Artifactはそのpollの集計から除外する。検証できない最上位JSONは
  正常状態として表示せず、sidebarに「処理記録を読み込めません」とpathを表示する。
- 自動更新は `succeeded`、`failed` または `cancelled` の終端状態で停止する。

### 📈 Task ProgressBar

現行UIはTask列全体をProgressBarとして表現する。ただし、表示するのは
経過時間や処理量の推定値ではなく、既存Artifactから確認できた「完了stage数 / 全stage数」
とする。Streamlit標準の `st.progress` を使用し、独自CSS、追加Dependencyおよび新しい
進捗保存Modelは導入しない。

処理種類ごとの表示stageは次の固定順とする。`TRANSLATE` と `TRANSLATE-LITE` は保存済み
backendに対応する一方だけを表示する。

| 処理種類 | ProgressBarのstage |
|---|---|
| Translate | SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD → STRUCTURE → TRANSLATEまたはTRANSLATE-LITE → CHECK（初回）→ REVIEW → FIX → CHECK（最終）→ LINT → COVER → MARKDOWN → DOCX |
| Review | SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD → ALIGN → CHECK → REVIEW → REPORT |
| Upgrade | SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD → STRUCTURE → ALIGN → DIFF → REUSE → TRANSLATEまたはTRANSLATE-LITE → CHECK（初回）→ REVIEW → FIX → CHECK（最終）→ LINT → COVER → MARKDOWN → DOCX |
| Register | REGISTER |

- `succeeded` または `skipped` のstageを完了として数える。現在の `processing` stageは
  ProgressBarのtextへ `現在: DOCLING` のように表示するが、完了数へは含めない。
- 失敗または中断時は最後に確認できた値を保持し、Barと併せて `failed` または
  `cancelled` をtext表示する。色だけで状態を表現しない。
- CHECKの初回と最終は同じ `TaskName.CHECK` を使用するため、`findings.json` と
  `final-findings.json` の検証済みArtifactをそれぞれのstageの正本とする。
- 条件分岐で実行不要となったTRANSLATE、REVIEWまたはFIXは、既存どおり `skipped` の
  `TaskState`を保存して一つの完了stageとして扱う。
- 処理開始直後で最上位記録がない場合はProgressBarを0として「準備中」を表示する。
  正常終了時だけ100%とする。
- 各stageの重みは一律1とする。DOCLINGの通信待ちとFIXのような短い処理で所要時間が
  異なっても、時間比率らしく見せるための推定weightは導入しない。
- DOCLINGはTask directoryを完了時に原子的に公開するため、既存Artifactだけでは
  `3 / 10 parts`のようなTask内部進捗を正確に表示できない。初期実装はDOCLING stageを
  実行中として表示するだけとし、part単位の追加進捗Artifactは設けない。
- TRANSLATEなどのLLM Task内部は、既存のCall件数表示をProgressBarの下へ併記する。
  `planned_calls`は分割によって増えるため、初期実装ではLLM Call比率を別の百分率Barに
  変換しない。
- Registerは `TaskState`を持たないため、最上位JSONの状態から `REGISTER`という一つの
  表示用Taskを組み立てる。`succeeded`の場合だけ `1 / 1 Task`、それ以外は `0 / 1 Task` とし、
  Task名と最上位JSONの状態をProgressBarのtextへ表示する。

現行UIはこの方式により、PipelineやArtifact Schemaを変更せず進捗を表示する。Task内の
厳密な処理量、残り時間およびDOCLINGのpart単位進捗は、Pipeline側に途中状態の追加保存が
必要になるため表示しない。

### 🔬 進捗詳細

進捗詳細は既定で閉じたCollapseとし、`st.fragment(run_every="1s")` で進捗領域とともに
更新する。表示項目は次に限定する。

- 最上位JSONの `updated_at` を使用した更新時刻
- STRUCTURE、TRANSLATEおよびREVIEWのTask別LLM Call進捗内訳
- Task完了後の内訳では完了・予定・再利用・失敗Call数
- 実行中の内訳では完了・観測済み・失敗Call数

Task名とTask状態はProgressBarへ表示する。固定action、現在対象の本文、Upgrade差分集計、
成果物、エラーおよびResume操作は進捗詳細へ表示しない。LLMのsystem prompt、生のrequest
bodyおよび内部推論も表示しない。

### ↔️ 処理前・処理後の比較表示

TRANSLATE、REVIEWおよびFIXのtext変化は、Streamlit標準の `st.columns(2)` と読取専用の
`st.text_area`を使用し、左右に並べて表示する。TextArea内の部分装飾は行わず、その下の
`差分を表示` Collapseへ標準Library `difflib` のunified diffを `st.code(language="diff")`で
表示する。追加Dependency、HTMLおよび独自Editorは導入しない。

| Task | 左側 | 右側 |
|---|---|---|
| TRANSLATE | `翻訳前（英語）`: 成功Callの `target_ids` に対応するsource text | `翻訳後（日本語）`: 同じ成功Callの検証済み `TranslationResponse` |
| REVIEW | `修正前`: 対象の現在の日本語訳 | `修正候補`: 同じ成功Callの検証済みRevision edit。候補がない場合は「修正候補なし」 |
| FIX | `修正前`: FIX入力Documentの日本語訳 | `修正後`: `outcomes.json`で `applied`となった対象のFIX出力Document |

- 二つのTextAreaは必ず同じCallまたは同じFIX対象IDから組み立てる。現在処理中の対象と
  直前Callの結果を左右へ混在させてはならない。
- LLM応答はstreamingされないため、確定済みCallが一件もない状態でCallが実行中の場合だけ、
  現在の対象textと「処理中（確定結果なし）」を表示する。CallのresponseについてSchemaと
  SHA-256を検証できた次のpollで左右を更新する。
- 検証済みCallが一件以上ある場合は、別のCallが開始した後も、左右のTextAreaへ直近に確定した
  同一Callの処理前・処理後を表示する。実行中Callの未確定responseへ切り替えない。
- `processing`または `failed` のresponse、生のLLM応答および未適用Revisionを「修正後」として
  表示しない。SchemaとSHA-256を検証できる `partial` は確定済み項目だけを表示対象とする。
  REVIEWの右側は明示的に「修正候補」と表示する。
- FIXでは `RevisionOutcome.status="applied"` の対象が一件以上ある場合だけ処理前・処理後を
  表示する。同じFIX結果の `rejected` は、件数付きの `拒否された修正候補` Collapseへ、
  1候補を1つのlist項目として保存順にすべて表示する。各項目はRevision IDと拒否理由を
  別行のinline codeとして表示する。UIでRevisionを再適用または再計算しない。
- STRUCTUREはtext修正ではないため二つのTextAreaの対象外とする。決定的Taskにも処理前後textが
  存在しない場合は表示しない。
- 左右それぞれ先頭3件、1件240文字までとし、同じ順序、対象IDおよび省略表示を使用する。
  複数件は一つの読取専用TextArea内で対象ID付きの区切りを入れる。
- TextAreaには可視labelを付け、`disabled=True`として編集可能に見せない。文書由来textは
  MarkdownまたはHTMLとして評価しない。
- 対応する入力Document、Call Artifact、response、FIX outcomeまたは出力Documentのいずれかを
  検証できない場合は比較表示だけを省略し、Task状態とProgressBarの表示は継続する。

現行UIはこの比較表示も既存Artifactだけから組み立てる。ただし、生成中tokenを右側へ逐次表示すること、
確定前の予測結果を表示すること、および文字単位diff表示は対象外とする。

### 📑 Review・Upgradeの原文比較表示

処理前・処理後の比較とは別に、ReviewとUpgradeでは翻訳の根拠となる文書を同じ対応単位で
横並び表示する。この領域は共通の処理履歴で選択した処理が同じ種類の場合だけ、共通の
進捗領域へ配置する。処理履歴と処理IDの選択状態は既存どおり共通とする。

#### 🔎 Reviewの二列表示

Reviewは `st.columns(2)` 内へ二つの読取専用 `st.text_area`を配置する。

| 左側 | 右側 |
|---|---|
| `英語原文` | `日本語訳` |

- 正本は `review/align/alignment.json` の検証済み `AlignmentResult.targets` とする。
- 左右は必ず同じ `ReviewTarget.id` の `source` と `translation`を表示する。
- REVIEW Call実行中は、Call Artifactの `target_ids` に対応するReviewTargetを表示する。
  実行中Callがなく成功Callがある場合は直近の成功Call、Callがまだ一件もない場合は
  `AlignmentResult.targets` の先頭3件をpreviewとして表示する。
- ALIGN完了前は対応関係を推測せず、「ALIGN完了後に表示」とする。UIからALIGNを再実行しない。
- LLMが生成したFindingとRevisionはこの二列へ混ぜず、既存の直近結果および
  「修正前 / 修正候補」の比較領域へ表示する。

#### 🆙 Upgradeの三列表示

Upgradeは `st.columns(3)` 内へ三つの読取専用 `st.text_area`を次の順序で配置する。

| 左側 | 中央 | 右側 |
|---|---|---|
| `英語v1` | `日本語v1` | `英語v2` |

- 正本は `upgrade/diff/plan.json` の検証済み `UpgradePlan.changes` と、
  `preprocess/{source-v1,source-v2,translation-v1}/load/document.json` とする。
- 三列は必ず同じ `VersionChange.id` の `source_v1_ids`、`translation_v1_ids` および
  `source_v2_ids`から解決する。別のVersionChangeのtextを同じ行へ混在させない。
- `unchanged`、`moved`および`modified`は対応する三つのtextを表示する。
- `added` は英語v1と日本語v1を「該当なし」、`deleted` は英語v2を「該当なし」とする。
- 日本語v1を安全に1対1対応できなかった場合は、中央を「対応訳なし」とする。UIで類似textを
  探索したり、独自に対応付けたりしない。
- TRANSLATEまたはREVIEW Call実行中は、CallのSpan IDまたはTextUnit IDを英語v2の
  TextUnitへ解決し、対応するVersionChangeを表示する。
- DIFF完了前は三列の対応を推測せず、「DIFF完了後に表示」とする。REUSEの実行中など
  item単位の現在位置をArtifactから判定できない場合は、計画の先頭3件をpreviewとして
  表示し、現在処理中であるとは表記しない。
- 生成された日本語v2はこの三列へ混ぜず、TRANSLATEまたはFIXの検証済み結果として、
  既存の処理前・処理後比較領域へ表示する。
- 三列の下に `差分を表示` Collapseを設け、英語v1と英語v2の行単位unified diffを表示する。

#### 🧭 共通表示規則

- Reviewは左右、Upgradeは三列で同じ件数と順序を維持する。各列は先頭3件、1件240文字まで
  とし、対象ID付きの同じ区切り位置を使用する。
- TextAreaは可視labelと `disabled=True`を設定し、文書由来textをMarkdownまたはHTMLとして
  評価しない。
- 空文字列とArtifact読込失敗を区別する。検証済みの空textは「空」、対象自体が存在しない
  場合は「該当なし」、Artifactを検証できない場合は比較領域全体を一時的に非表示とする。
- 比較領域の生成では既存Artifactだけを読み、追加のLLM Call、Embedding、文字列類似度、
  Pipeline Taskおよび保存用Artifactを追加しない。
- 三列表示は画面幅を必要とするが、初期実装では別のresponsive layoutや独自CSSを追加しない。
  Streamlit標準のcolumn表示に従う。

## 🕒 処理履歴

処理履歴はdatabaseを使わず、次のpatternに合致する最上位JSONを起動時と更新時に
列挙する。

```text
outputs/*/*/translation.json
outputs/*/*/review.json
outputs/*/*/registration.json
outputs/*/*/upgrade.json
```

- 履歴は `updated_at` の新しい順に最大100件まで表示する。
- 履歴は左sidebarへ折り畳まず、選択可能なitemとして縦に並べる。
- 履歴の列挙は一度のStreamlit評価につき一回とし、Task directory全体を再帰的に読み込まない。
- 各履歴buttonは種類、代表入力、状態および処理IDを、この順序で `|` 区切りに表示する。
  Translateは英語PDF、Reviewは日本語訳文PDF、Upgradeは英文v2を代表入力とする。Registerは
  `source_id`があればその値、なければ先頭入力のlogical pathを使用する。
- 不正なJSONまたは非対応 `schema_version` は履歴から隠さず、「読込不可」とpathを表示する。
- CLIから開始した処理も同じArtifact契約であるため、履歴と成果物の表示対象とする。
- `translate_v1`、`runs`、またはその他の旧directoryは列挙対象としない。

## ⏯️ Resume

Resume buttonは `failed`、`cancelled`、または現在のUI worker登録表に未完了の
`Future` がない `processing` に表示する。`processing` が実際に稼働中かどうかをUIが
推測して正本化してはならない。同時操作は `ProcessingLock` が最終的に判定する。

- UIから開始した処理は `.translate-ui/<processing-id>/` の保存済み入力を再使用する。
- CLIから開始した処理など、対応する保存済み入力がない場合は同じ入力fileの再uploadを要求する。
- CLIでdirectoryを指定したRegisterは、論理pathをbrowser uploadで再現できないためUIから
  Resumeせず、CLIからResumeするよう案内する。
- Resume開始前にfile件数、roleおよびSHA-256を比較し、不一致ならPipelineを呼び出さず拒否する。
- TranslateおよびUpgradeのbackend、Registerの `source_id`、入力roleとlogical pathの順序は
  保存済み記録に合わせる。
- Resume buttonの確定時は「完了済みTaskおよびLLM Callを再利用し、未完了箇所から再開する」ことを明示する。
- `succeeded` の処理にResume buttonを表示しない。
- Resumeが拒否された場合も既存成果物を変更しない。

## 📤 成果物表示とdownload

- Translate、ReviewおよびUpgradeは、`succeeded` の最上位JSONの `outputs` に記録された
  Artifactだけを公開する。
- Artifactの `relative_path`は処理directoryを基準に解決し、directory外を参照するpathを拒否する。
- download前にfileの存在、sizeとSHA-256を `ArtifactFile` と比較する。
- 検証に失敗したArtifactはdownload buttonを表示せず、「成果物が欠落または変更されている」と表示する。
- TranslateはMarkdownとDOCX、Reviewは `review.md`、Registerは `registration.json`、
  Upgradeは日本語v2 DOCXをdownload対象とする。
- Registerの `registration.json` は成果物を指すroot recordそのものであり、自己参照する
  `ArtifactFile` を持たない。`RegistrationRecord` としてSchema検証でき、かつ状態が
  `succeeded` の場合に、読み込んだ同じbyte列をdownload対象とする。
- previewおよびdownload buttonは `進捗と処理内容` Collapseの外側へ表示する。
- TranslateのMarkdownとDOCXのdownload buttonは横並びにする。
- 現行実装はMarkdownとDOCXの各buttonを `st.columns(2)` の固定二列へ配置する。
- browser上のpreviewは利便性のための表示であり、downloadされるbyte列を変換しない。
- UIから成果物、処理directoryまたは入力fileを削除しない。

## ⚠️ 入力検証とエラー表示

エラー表示は次の境界に従う。本書は新しいlog安全化、秘匿化またはredaction機構を
追加しない。

| 種類 | UI表示 |
|---|---|
| 必須入力の欠落 | 対象欄の近くに不足内容を表示 |
| 未対応拡張子・file名・件数 | Pipelineを呼び出さず理由を表示 |
| `ConfigError` | 設定エラーのmessageを表示 |
| `InputError` | 入力またはResume拒否のmessageを表示 |
| 排他lock失敗 | 同じ処理IDが操作中であることを表示 |
| 既存 `ProcessingError` | `message`、`cause_type`および `retryable` を表示 |
| 予期しない例外 | 処理種類と例外型を表示し、tracebackは画面に表示しない |

- UI側の入力検証は利便性のためであり、Pipeline側の検証を省略しない。
- 失敗したbackground workerの例外は `Future.result()` で回収し、未観測の例外として放置しない。
- エラー表示後も履歴、既存成果物およびResume操作を利用可能に保つ。

## 🔒 同時操作と整合性

- UI workerは全体で一度に1処理だけを実行する。
- UI、CLIまたは別processから同じ処理IDを同時に操作することを禁止する。
- 排他の正本は `outputs/<file-basename>/<uuidv7>/.lock` と既存 `ProcessingLock` とする。
- `session_state`、buttonのdisabled状態またはworker登録表だけで排他を保証してはならない。
- UIからの新規処理は、入力保存が完了してからworkerへ登録する。
- 中途まで保存されたupload fileをPipelineへ渡さない。

## 🧪 検証契約

現行実装は次を自動testで検証する。外部LLM、Docling、LibreTranslateおよびQdrantへの実通信を
UI testの必須条件としない。

現行の品質Gateは次のcommandで実行する。

```powershell
# 静的検査、format検査、型検査、全自動testを順に実行する。
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Playwrightを初めて実行する環境では、E2E testの前にChromiumを導入する。

```powershell
# Playwright E2E testが使用するChromium binaryを導入する。
uv run playwright install chromium
```

### 🧩 Unit test

- upload先pathとfile名検証
- 複数Register fileのbasename衝突
- 処理IDのUUIDv7検証と `processing_id` / `resume_id` の相互排他
- 新規 `processing_id` による既存記録の上書き拒否
- 履歴の並び順、100件上限および非対応Schemaの表示
- Artifactのpath、sizeおよびSHA-256検証
- 同じ処理IDのworker二重登録防止
- LLM Callの `target_ids` から同一Callの処理前・処理後を解決できること
- TextAreaのpreviewが先頭3件および各240文字で省略されること
- 処理種類ごとの固定stage列からProgressBarの分母と完了数を決定できること
- CHECK（初回）とCHECK（最終）を対応する検証済みArtifactから区別できること
- Task失敗時にProgressBarが100%にならず、失敗状態をtextでも表示できること
- 左右の処理前・処理後が同じCallまたはFIX対象IDから解決されること
- unified diffが変更前後のlabel、削除行および追加行を区別すること
- publisher生成のPandoc画像記法について、URL decodeした相対画像をMarkdown directory内だけから
  解決し、欠落file、directory外参照および外部URLをローカルfileとして扱わないこと
- 未完了またはhash不一致のresponseが右側TextAreaへ表示されないこと
- TRANSLATEの一部応答がSchema・hash検証済みの `partial` 状態であれば、後続Callの
  実行中も右側TextAreaへ直近の確定結果として表示し続けること
- Reviewの英語原文と日本語訳が同じ `ReviewTarget.id` から解決されること
- Upgradeの英語v1、日本語v1および英語v2が同じ `VersionChange.id` から解決されること
- Upgradeのadded、deletedおよび対応訳なしが規定のplaceholderで同じ列数を維持すること
- 未知の対象IDまたは不正な途中Artifactで進捗領域全体を失敗させないこと
- DIFFが一意な同文の移動、1対1の変更、追加および削除を決定的に分類すること
- 重複textまたは曖昧な対応を推測せず、削除と追加として扱うこと
- REUSEが1対1対応、非空textおよびSpan互換性をすべて満たす場合だけ既存訳を移植すること
- TRANSLATEがREUSE済みSpanを対象外とし、REVIEWが今回翻訳した対象だけを受け取ること
- `UpgradeRecord` が3入力を異なるroleで保持し、Resume時にすべてのhashを照合すること

### 🎨 Streamlit test

`streamlit.testing.v1.AppTest` を使用し、少なくとも次を検証する。

- Translate、Review、Upgrade、Registerの順にtabと処理履歴が表示される。
- `Translate` とSession IDがDeploy buttonと同じAppBarの縦位置へ表示され、処理履歴が
  左sidebarへ折り畳まず縦に並ぶ。
- 新規処理では入力領域が展開され、処理開始後または履歴選択後は入力領域が閉じ、
  進捗領域が展開される。
- 進捗領域がTask数・Task名・Task状態を含むProgressBar、LLM Call進捗内訳と更新時刻だけを
  含む進捗詳細Collapse、二列・三列の読取専用TextAreaの順で表示される。
- Upgradeは英文v1、英文v2および日本語v1の3fileが揃うまで開始できない。
- 必須入力がない状態で処理を開始できない。
- 有効な入力を確定すると対応Pipelineが1回だけworkerへ登録される。
- 処理記録の状態とLLM進捗が表示される。
- LLM CallのTask別内訳が表示され、確定済みCallがある場合は後続Callの処理中も
  直近の確定結果を表示し続ける。
- Translate、ReviewおよびUpgradeでTask ProgressBarと現在stageが表示される。
- TRANSLATE、REVIEWまたはFIXの検証済み処理前・処理後が二つのTextAreaへ横並びで表示される。
- 処理前後とUpgradeの英語v1・英語v2に行単位の差分Collapseが表示される。
- 適用済みRevisionを持つFIX比較では、拒否された候補が件数付きCollapseへ保存順の
  1候補1list項目で表示され、Revision IDと拒否理由を区別できる。
- 確定済みCallが一件もない実行中Callに限り、処理後へ「処理中（確定結果なし）」と表示する。
- Reviewで英語原文と日本語訳の二つのTextAreaが横並びで表示される。
- Upgradeで英語v1、日本語v1および英語v2の三つのTextAreaが指定順で横並び表示される。
- ReviewとUpgradeの各列が異なる対応単位のtextを混在させない。
- system prompt、生のrequest bodyおよび内部推論が表示されない。
- `.streamlit/config.toml` を使用した初回表示の既定テーマがライトである。
- 失敗・中断済み処理でResume確認が表示される。
- 検証済み成果物だけにdownload buttonが表示される。
- 成果物previewとdownload buttonが `進捗と処理内容` Collapseの外側へ表示される。
- MarkdownとDOCXのdownload buttonが横並びになり、Markdown previewの相対画像が表示される。
- 設定エラーと予期しない例外で画面全体が崩れない。

### 🌐 E2E test

- Unit testは `tests/unit/`、公開境界のE2E testは `tests/e2e/`、既存機能と統合契約の
  Regression testは `tests/regression/` へ配置する。
- CLIは実processでTyper applicationを起動し、Translate、Review、UpgradeおよびRegisterの
  subcommandについて、引数解析、終了codeおよび出力を検証する。
- UIは実Streamlit serverを起動し、PlaywrightのChromiumからTranslate、Review、Upgradeおよび
  Registerのfile upload、開始buttonおよび成功表示を検証する。
- 外部LLM、Docling、LibreTranslateおよびQdrantはE2E testの対象境界より外側とし、test driverで
  置き換える。CLIとUIの公開processおよび操作経路は置き換えない。

### 🔗 Integration test

- 事前生成したUUIDv7が成果物directoryと最上位JSONへ保存される。
- 完了済みTaskとLLM Callを持つ処理をUIからResumeしても、有効なCallを再実行しない。
- UIとCLIが同じ処理IDを同時操作した場合、後から開始した側が拒否される。
- browser更新後もquery parameterの処理IDから状態を復元できる。
- Upgradeが未変更訳を再利用し、追加・変更箇所だけを翻訳して日本語v2 DOCXを生成する。
- Upgradeの入力またはbackendを変更したResumeが拒否され、既存成果物を変更しない。

## ✅ 完了条件

現行実装の完了条件は次のとおりとする。

1. 4つの入力画面から対応Pipelineを開始できる。
2. UI操作中もStreamlit画面が固まらず、処理進捗を更新できる。
3. Task状態をProgressBarとして表示し、更新時刻、LLM Call進捗および直近の検証済み結果を既存Artifactから表示できる。
4. 初回表示の既定テーマがライトである。
5. 失敗または中断したUI処理を保存済み入力でResumeできる。
6. CLIで作成した新Schemaの処理を履歴と成果物の表示対象にできる。
7. 同じ処理IDの同時操作と、新規IDによる既存処理の上書きを防止できる。
8. Upgradeが英文v2を構造の正本とし、再利用可能な日本語v1を保持しながら日本語v2 DOCXを生成できる。
9. Upgradeが追加、変更および再利用不能なtextだけを翻訳し、削除済みtextを出力しない。
10. 成功し、hash検証に通過したMarkdown、DOCXおよびReview reportをdownloadできる。また、
    Schema検証済みの成功したRegister記録をdownloadできる。
11. 基本DependencyだけのCLI利用にStreamlitのimportを必要としない。
12. 既存test、Ruff、formatterおよびtyの品質確認に通過する。
13. TRANSLATE、REVIEWおよびFIXの処理前・処理後を、同一対象の検証済みArtifactから二つの読取専用TextAreaへ表示できる。
14. Reviewは同じReviewTargetの英語原文と日本語訳を二列で、Upgradeは同じVersionChangeの英語v1、日本語v1および英語v2を三列で表示できる。

## 🚧 将来候補

次は初期Streamlit UIの実装対象に含めず、必要性を確認してから別仕様で検討する。

- 実行中の外部要求への協調的な中断通知
- 保存済みupload fileの一覧・容量表示・明示的な削除
- ユーザー認証と外部公開向けの運用構成
- Langfuseによる観測
- worker数、batch、cacheおよび処理履歴列挙の性能最適化

## 🔖 参考文献

- [Streamlit `config.toml` API reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)
- [Streamlit `st.fragment` API reference](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)
- [Streamlit `st.status` API reference](https://docs.streamlit.io/develop/api-reference/status/st.status)
- [Streamlit `st.progress` API reference](https://docs.streamlit.io/develop/api-reference/status/st.progress)
- [Streamlit `st.markdown` API reference](https://docs.streamlit.io/develop/api-reference/text/st.markdown)
- [Streamlit App testing](https://docs.streamlit.io/develop/concepts/app-testing)

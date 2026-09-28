# 🖥️ Streamlit UI・Upgrade仕様 v2

本書は、[`SPEC.md`](SPEC.md)で将来対応としたStreamlit UIと実Pipelineの接続、および
英文v1、英文v2、日本語v1から日本語v2を生成するUpgradeを定める。既存の文書変換、翻訳、
Review、Register、成果物、Resumeおよび外部接続の契約は[`SPEC.md`](SPEC.md)を正本とし、
本書はUI境界とUpgradeに必要な拡張だけを定義する。

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
本書で追加する `upgrade.json`、
Task状態およびLLM Call Artifactを進捗の正本とする。Streamlitの `session_state`や
background workerの `Future`は正本としない。

### 🗂️ Source配置

追加・変更するSourceは次の範囲に限定する。

```text
main.py                         # Streamlit用entry point
.streamlit/
└── config.toml                 # ライトテーマの既定値
translate/
├── cli.py                      # Upgrade subcommand
├── ui.py                       # 画面、入力保存、worker、進捗読込み
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
```

- rootの `main.py` は `translate.ui.main` を呼び出すだけとする。
- `translate/ui.py` はStreamlit固有の表示と、UIからPipelineへの接続を所有する。
- UIのために `views`、`controllers`、`services`などの追加packageを設けない。
- `translate/pipeline/` はStreamlitをimportしてはならない。
- 実装の増大により `ui.py` の分割が必要になった場合だけ、別の変更で再設計する。

### 📦 依存関係

- UI用optional dependencyは既存の `streamlit>=1.64.0` だけとする。
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

### 🐳 Docker起動

- `Dockerfile` の基盤imageは `ghcr.io/astral-sh/uv:python3.12-trixie` とする。
- imageは `uv sync --frozen --all-extras --no-dev` でUIとRegisterを含む実行依存を固定する。
- DOCX公開に必要なPandocをDebian packageから導入する。
- containerはStreamlitを `0.0.0.0:8501` で起動する。
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

Translate、Review、RegisterおよびUpgradeは `st.tabs`で表示する。処理履歴は各tabから共通で
参照できる領域とし、処理IDをURL query parameterに保持する。browserを更新しても、
同じ処理IDの表示を復元する。

全操作で次を必須とする。

- 入力widgetの変更だけで処理を開始せず、明示的な開始buttonで確定する。
- 処理開始buttonは必須入力が揃うまでdisabledとする。
- 同じbrowser sessionからの連打で同じ処理IDを二重登録しない。
- 状態は色だけで表さず、必ずtextで併記する。
- widgetには可視labelを付け、キーボード操作を妨げる独自HTMLを使用しない。

### 🎨 表示テーマ

- `.streamlit/config.toml` の `[theme]` に `base = "light"` を設定し、初回表示は
  OSおよびbrowserの配色設定に依存せずライトモードとする。
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
- Resume時のbackendは `translation.json` に保存された値に固定し、変更を許可しない。

### 🔎 Review

| 項目 | 仕様 |
|---|---|
| 英語原文PDF | `.pdf` の単一fileを必須とする |
| 日本語訳文PDF | `.pdf` の単一fileを必須とする |
| 開始操作 | `review_pdfs()` をbackground workerへ登録する |
| 成功時 | `review.md` のpreviewとdownloadを表示する |

Review画面はFIXを実行せず、REPORTに含まれる指摘と修正候補を表示する。

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
- 保存は一時fileへ書き込んだ後、同一filesystem内で原子的に確定する。
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
- `TaskName` へ `DIFF` と `REUSE` を追加する。`UPGRADE` というTaskは設けず、Upgradeは
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
| LLM進捗 | 実行中はCall Artifactの観測数、Task完了後は `LLMProgress` の `completed_calls / planned_calls` |
| LLM再利用 | `LLMProgress.reused_calls` |
| LLM失敗 | `LLMProgress.failed_calls` |
| Register進捗 | `RegistrationResult.sources` の件数と入力件数 |
| Upgrade進捗 | `UpgradePlan.changes` のkind別件数、再利用件数および翻訳対象件数 |
| 更新時刻 | 最上位JSONの `updated_at` |

- `planned_calls` はLLMによる分割で増えるため、進捗率が一時的に下がることを許容する。
- LLM Task実行中は該当Taskの `calls/*/call.json` を直接集計し、完了、実行中および失敗Call数を表示する。
- 予定Call数が0またはまだ確定していない間は、虚偽の百分率を表示せず、件数と状態だけを表示する。
- JSONが原子的に置換される瞬間の読込み失敗は、前回の有効な表示を維持して次回pollで再読込みする。
- 検証できないJSONを正常状態として表示してはならない。連続して検証に失敗する場合は「処理記録を読み込めない」と表示する。
- 自動更新は `succeeded`、`failed` または `cancelled` の終端状態で停止する。

### 🔬 リアルタイム処理内容

進捗領域には集約値に加えて「現在の処理内容」を常時表示する。この表示も既存の
`st.fragment(run_every="1s")` で更新し、表示専用のworker、外部要求および進捗Artifactを
追加しない。

| Task | 現在の処理表示 | 直近結果表示 |
|---|---|---|
| SPLIT、DOCLING、UNPACK、MERGE | 分割、変換、展開または結合しているfile、partおよびpage | 確定済みArtifactの件数 |
| POSITION、NORMALIZE、LOAD | 座標補正、正規化または読込みという固定actionと、判明しているpageおよびBlock件数 | 確定済みreportの要約 |
| STRUCTURE | 現在のCallが対象とするsource text、page番号および「見出し・caption・Block種別を解析中」 | 直近の成功Callで適用した構造patchの要約 |
| TRANSLATE | 現在のCallが対象とする英語source textと「日本語へ翻訳中」 | 直近の成功Callで確定した日本語訳 |
| REVIEW | 現在のCallが対象とする英語原文と日本語訳、および「品質と修正候補を確認中」 | 直近の成功Callで確定したFindingとRevisionの要約 |
| ALIGN、DIFF、REUSE | 対応付け、版間差分判定または既存訳再利用という固定actionと対象件数 | kind別件数、再利用件数および翻訳対象件数 |
| CHECK、FIX、COVER、MARKDOWN、DOCX、LINT、REPORT | Task固有の固定actionと対象件数 | 確定済みArtifactの要約 |
| Register | 現在のsource logical pathと、変換、chunk化、EmbeddingまたはQdrant登録のうちArtifactから確定できるaction | 完了source数、Point数および失敗source |

STRUCTURE、TRANSLATEおよびREVIEWでは、`status="processing"` の
`calls/*/call.json` にある `target_ids` をTask入力DocumentまたはReviewTargetへ解決し、
現在の対象textを表示する。複数の処理中Callが存在する場合は `started_at` が最も新しいCallを
現在のCallとし、ほかのCallは件数だけを表示する。処理中Callがまだ作成されていない場合は
Task名と準備中であることだけを表示する。

- 現在の対象textは先頭3件を表示し、1件につき240文字を超える部分を省略する。残件数と
  省略の有無を明示する。
- source、translationおよび結果は列または明確なlabelで区別し、文書由来のtextを
  HTMLまたはMarkdownとして評価しない。
- 直近結果は `status="succeeded"` のCall Artifactと検証済みresponseだけから表示する。
  未完了response、推測した結果および検証前の応答は表示しない。
- LLM要求はstreamingを使用しないため、生成中tokenを逐次表示しない。現在のCallが完了する
  までは現在の対象textと直前に確定した結果を表示する。
- system prompt、rules全文、JSON Schema、API key、HTTP header、生のrequest bodyおよび
  modelの内部推論は表示しない。「どう加工しているか」はTask名、固定action、対象textおよび
  検証済み結果で説明する。
- 対象IDを解決できない、または途中Artifactを検証できない場合は該当previewを非表示にし、
  処理全体を失敗扱いにしない。状態とCall件数の表示は継続する。
- preview生成のためにTask directory全体を再帰走査しない。現在のCall、直近の成功Callおよび
  対応するTask入力Artifactだけを読み込む。

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
- 履歴の列挙は一度のStreamlit評価につき一回とし、Task directory全体を再帰的に読み込まない。
- 表示項目は種類、入力logical path、処理ID、状態、作成時刻、更新時刻とする。Upgradeは
  3入力のroleとlogical pathを区別して表示する。
- 不正なJSONまたは非対応 `schema_version` は履歴から隠さず、「読込不可」とpathを表示する。
- CLIから開始した処理も同じArtifact契約であるため、履歴と成果物の表示対象とする。
- `translate_v1`、`runs`、またはその他の旧directoryは列挙対象としない。

## ⏯️ Resume

Resume buttonは `failed`、`cancelled`、または現在のUI worker登録表に未完了の
`Future` がない `processing` に表示する。`processing` が実際に稼働中かどうかをUIが
推測して正本化してはならない。同時操作は `ProcessingLock` が最終的に判定する。

- UIから開始した処理は `.translate-ui/<processing-id>/` の保存済み入力を再使用する。
- CLIから開始した処理など、対応する保存済み入力がない場合は同じ入力fileの再uploadを要求する。
- Resume開始前にfile件数、roleおよびSHA-256を比較し、不一致ならPipelineを呼び出さず拒否する。
- TranslateおよびUpgradeのbackend、Registerの `source_id`、入力roleとlogical pathの順序は
  保存済み記録に合わせる。
- Resume buttonの確定時は「完了済みTaskおよびLLM Callを再利用し、未完了箇所から再開する」ことを明示する。
- `succeeded` の処理にResume buttonを表示しない。
- Resumeが拒否された場合も既存成果物を変更しない。

## 📤 成果物表示とdownload

- `succeeded` の最上位JSONに記録されたArtifactだけを公開する。
- Artifactの `relative_path`は処理directoryを基準に解決し、directory外を参照するpathを拒否する。
- download前にfileの存在、sizeとSHA-256を `ArtifactFile` と比較する。
- 検証に失敗したArtifactはdownload buttonを表示せず、「成果物が欠落または変更されている」と表示する。
- TranslateはMarkdownとDOCX、Reviewは `review.md`、Registerは `registration.json`、
  Upgradeは日本語v2 DOCXをdownload対象とする。
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

実装時は次を自動testで検証する。外部LLM、Docling、LibreTranslateおよびQdrantへの実通信を
UI testの必須条件としない。

### 🧩 Unit test

- upload先pathとfile名検証
- 複数Register fileのbasename衝突
- 処理IDのUUIDv7検証と `processing_id` / `resume_id` の相互排他
- 新規 `processing_id` による既存記録の上書き拒否
- 履歴の並び順、100件上限および非対応Schemaの表示
- Artifactのpath、sizeおよびSHA-256検証
- 同じ処理IDのworker二重登録防止
- LLM Callの `target_ids` からTask別previewを解決できること
- previewが3件および各240文字で省略され、残件数を表示できること
- 未知の対象IDまたは不正な途中Artifactで進捗領域全体を失敗させないこと
- DIFFが一意な同文の移動、1対1の変更、追加および削除を決定的に分類すること
- 重複textまたは曖昧な対応を推測せず、削除と追加として扱うこと
- REUSEが1対1対応、非空textおよびSpan互換性をすべて満たす場合だけ既存訳を移植すること
- TRANSLATEがREUSE済みSpanを対象外とし、REVIEWが今回翻訳した対象だけを受け取ること
- `UpgradeRecord` が3入力を異なるroleで保持し、Resume時にすべてのhashを照合すること

### 🎨 Streamlit test

`streamlit.testing.v1.AppTest` を使用し、少なくとも次を検証する。

- Translate、Review、Register、Upgradeと処理履歴が表示される。
- Upgradeは英文v1、英文v2および日本語v1の3fileが揃うまで開始できない。
- 必須入力がない状態で処理を開始できない。
- 有効な入力を確定すると対応Pipelineが1回だけworkerへ登録される。
- 処理記録の状態とLLM進捗が表示される。
- 処理中LLM Callの固定actionと対象textが表示され、成功後に直近結果へ切り替わる。
- system prompt、生のrequest bodyおよび内部推論が表示されない。
- `.streamlit/config.toml` を使用した初回表示の既定テーマがライトである。
- 失敗・中断済み処理でResume確認が表示される。
- 検証済み成果物だけにdownload buttonが表示される。
- 設定エラーと予期しない例外で画面全体が崩れない。

### 🔗 Integration test

- 事前生成したUUIDv7が成果物directoryと最上位JSONへ保存される。
- 完了済みTaskとLLM Callを持つ処理をUIからResumeしても、有効なCallを再実行しない。
- UIとCLIが同じ処理IDを同時操作した場合、後から開始した側が拒否される。
- browser更新後もquery parameterの処理IDから状態を復元できる。
- Upgradeが未変更訳を再利用し、追加・変更箇所だけを翻訳して日本語v2 DOCXを生成する。
- Upgradeの入力またはbackendを変更したResumeが拒否され、既存成果物を変更しない。

## ✅ 完了条件

本書の実装は、次をすべて満たした時点で完了とする。

1. 4つの入力画面から対応Pipelineを開始できる。
2. UI操作中もStreamlit画面が固まらず、処理進捗を更新できる。
3. Task状態、LLM Call進捗、現在の固定action、対象textおよび直近の検証済み結果を既存Artifactから表示できる。
4. 初回表示の既定テーマがライトである。
5. 失敗または中断したUI処理を保存済み入力でResumeできる。
6. CLIで作成した新Schemaの処理を履歴と成果物の表示対象にできる。
7. 同じ処理IDの同時操作と、新規IDによる既存処理の上書きを防止できる。
8. Upgradeが英文v2を構造の正本とし、再利用可能な日本語v1を保持しながら日本語v2 DOCXを生成できる。
9. Upgradeが追加、変更および再利用不能なtextだけを翻訳し、削除済みtextを出力しない。
10. 成功し、hash検証に通過したMarkdown、DOCX、Review reportまたはRegister記録をdownloadできる。
11. 基本DependencyだけのCLI利用にStreamlitのimportを必要としない。
12. 既存test、Ruff、formatterおよびtyの品質確認に通過する。

## 🚧 将来候補

次は初期Streamlit UIの実装対象に含めず、必要性を確認してから別仕様で検討する。

- 実行中の外部要求への協調的な中断通知
- 保存済みupload fileの一覧・容量表示・明示的な削除
- ユーザー認証と外部公開向けの運用構成
- Langfuseによる観測
- worker数、batch、cacheおよび処理履歴列挙の性能最適化

## 🔖 参考文献

- [Streamlit `config.toml` API reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)

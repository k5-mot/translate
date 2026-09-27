# 🖥️ Streamlit UI仕様 v2

本書は、[`SPEC.md`](SPEC.md)で将来対応としたStreamlit UIと実Pipelineの接続仕様を定める。
文書変換、翻訳、Review、Register、成果物、Resumeおよび外部接続の契約は
[`SPEC.md`](SPEC.md)を正本とする。本書はUI境界と、UIから既存Pipelineを呼び出すための
最小限の拡張だけを定義する。

## 🎯 目的

Streamlit UIは、次の操作をbrowserから実行できるようにする。

- 英語PDFを日本語MarkdownおよびDOCXへ変換する。
- 独立した英語原文PDFと日本語訳文PDFを比較Reviewする。
- 参照資料をQdrantへRegisterする。
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
Task状態およびLLM Call Artifactを進捗の正本とする。Streamlitの `session_state`や
background workerの `Future`は正本としない。

### 🗂️ Source配置

追加・変更するSourceは次の2fileに限定する。

```text
main.py             # Streamlit用entry point
translate/
└── ui.py         # 画面、入力保存、worker、進捗読込み
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

## 🧭 画面構成

画面は次の4領域で構成する。

| 領域 | 責務 |
|---|---|
| Translate | 英語PDFの翻訳と公開 |
| Review | 英語原文PDFと日本語訳文PDFの比較Review |
| Register | 参照資料のQdrant登録 |
| 処理履歴 | 状態、進捗、Resumeおよび成果物の表示 |

Translate、ReviewおよびRegisterは `st.tabs`で表示する。処理履歴は各tabから共通で
参照できる領域とし、処理IDをURL query parameterに保持する。browserを更新しても、
同じ処理IDの表示を復元する。

全操作で次を必須とする。

- 入力は `st.form` 内で確定し、widget変更だけで処理を開始しない。
- 処理開始buttonは必須入力が揃うまでdisabledとする。
- 同じbrowser sessionからの連打で同じ処理IDを二重登録しない。
- 状態は色だけで表さず、必ずtextで併記する。
- widgetには可視labelを付け、キーボード操作を妨げる独自HTMLを使用しない。

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

## 📥 Upload入力の保存

`UploadedFile` はPipelineへ直接渡さず、処理開始前に次の作業directoryへ保存する。

```text
.translate-ui/<uuidv7>/
├── translate/
│   └── <original-basename>.pdf
├── review/
│   ├── source/<original-basename>.pdf
│   └── translation/<original-basename>.pdf
└── register/
    ├── 0001/<original-basename>
    └── 0002/<original-basename>
```

- directory名のUUIDv7は対応する `translation_id`、`review_id` または `registration_id` と同じ値とする。
- `.translate-ui/` はGit管理対象外とする。
- upload元のbasenameは成果物最上位directory名と `logical_path` のために保持する。
- basenameが空、`.`、`..`、path separatorまたは制御文字を含む場合は拒否する。
- fileの拡張子は大文字と小文字を区別せず検査する。MIME typeだけを信頼しない。
- 保存は一時fileへ書き込んだ後、同一filesystem内で原子的に確定する。
- Streamlitの `server.maxUploadSize` を1file当たりの上限とし、application独自の別のsize設定を追加しない。
- 保存した入力はResumeのために自動削除しない。初期UIは削除画面を提供しない。

## ⚙️ Pipeline接続契約

UIは保存先をPipeline起動前に決定し、即時に処理IDを表示できる必要がある。
そのため、次の3関数にkeyword-onlyの `processing_id: str | None = None` を追加する。

- `translate.pipeline.translate.translate_pdf()`
- `translate.pipeline.review.review_pdfs()`
- `translate.pipeline.register.register_paths()`

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
- `outputs`配置、最上位JSON、fingerprint、Resume判定および排他lockの契約を変更しない。

## 🧵 background worker

- UIは `ThreadPoolExecutor(max_workers=1)` を1つだけ保持する。
- workerと処理IDごとの `Future` の対応は `st.cache_resource` でStreamlitの再読込みを跨いで保持する。
- 複数browser sessionから共有されるworker登録表の読書きは標準Libraryの `threading.Lock` で保護する。
- UIから開始されたTranslate、ReviewおよびRegisterは単一worker上で順番に処理する。
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
| 処理ID | `translation_id`、`review_id` または `registration_id` |
| 処理状態 | 最上位JSONの `status` |
| 現在のTask | `status="processing"` の `TaskState` |
| 完了Task | `succeeded` または `skipped` のTask数 |
| LLM進捗 | `LLMProgress` の `completed_calls / planned_calls` |
| LLM再利用 | `LLMProgress.reused_calls` |
| LLM失敗 | `LLMProgress.failed_calls` |
| Register進捗 | `RegistrationResult.sources` の件数と入力件数 |
| 更新時刻 | 最上位JSONの `updated_at` |

- `planned_calls` はLLMによる分割で増えるため、進捗率が一時的に下がることを許容する。
- 予定Call数が0またはまだ確定していない間は、虚偽の百分率を表示せず、件数と状態だけを表示する。
- JSONが原子的に置換される瞬間の読込み失敗は、前回の有効な表示を維持して次回pollで再読込みする。
- 検証できないJSONを正常状態として表示してはならない。連続して検証に失敗する場合は「処理記録を読み込めない」と表示する。
- 自動更新は `succeeded`、`failed` または `cancelled` の終端状態で停止する。

## 🕒 処理履歴

処理履歴はdatabaseを使わず、次のpatternに合致する最上位JSONを起動時と更新時に
列挙する。

```text
outputs/*/*/translation.json
outputs/*/*/review.json
outputs/*/*/registration.json
```

- 履歴は `updated_at` の新しい順に最大100件まで表示する。
- 履歴の列挙は一度のStreamlit評価につき一回とし、Task directory全体を再帰的に読み込まない。
- 表示項目は種類、入力logical path、処理ID、状態、作成時刻、更新時刻とする。
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
- Translateのbackend、Registerの `source_id`、入力logical pathの順序は保存済み記録に合わせる。
- Resume buttonの確定時は「完了済みTaskおよびLLM Callを再利用し、未完了箇所から再開する」ことを明示する。
- `succeeded` の処理にResume buttonを表示しない。
- Resumeが拒否された場合も既存成果物を変更しない。

## 📤 成果物表示とdownload

- `succeeded` の最上位JSONに記録されたArtifactだけを公開する。
- Artifactの `relative_path`は処理directoryを基準に解決し、directory外を参照するpathを拒否する。
- download前にfileの存在、sizeとSHA-256を `ArtifactFile` と比較する。
- 検証に失敗したArtifactはdownload buttonを表示せず、「成果物が欠落または変更されている」と表示する。
- TranslateはMarkdownとDOCX、Reviewは `review.md`、Registerは `registration.json` をdownload対象とする。
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

### 🎨 Streamlit test

`streamlit.testing.v1.AppTest` を使用し、少なくとも次を検証する。

- Translate、Review、Registerと処理履歴が表示される。
- 必須入力がない状態で処理を開始できない。
- 有効な入力を確定すると対応Pipelineが1回だけworkerへ登録される。
- 処理記録の状態とLLM進捗が表示される。
- 失敗・中断済み処理でResume確認が表示される。
- 検証済み成果物だけにdownload buttonが表示される。
- 設定エラーと予期しない例外で画面全体が崩れない。

### 🔗 Integration test

- 事前生成したUUIDv7が成果物directoryと最上位JSONへ保存される。
- 完了済みTaskとLLM Callを持つ処理をUIからResumeしても、有効なCallを再実行しない。
- UIとCLIが同じ処理IDを同時操作した場合、後から開始した側が拒否される。
- browser更新後もquery parameterの処理IDから状態を復元できる。

## ✅ 完了条件

Streamlit UIの実装は、次をすべて満たした時点で完了とする。

1. 3つの入力画面から対応Pipelineを開始できる。
2. UI操作中もStreamlit画面が固まらず、処理進捗を更新できる。
3. Task状態とSTRUCTURE、TRANSLATE、REVIEWのLLM Call進捗を既存Artifactから表示できる。
4. 失敗または中断したUI処理を保存済み入力でResumeできる。
5. CLIで作成した新Schemaの処理を履歴と成果物の表示対象にできる。
6. 同じ処理IDの同時操作と、新規IDによる既存処理の上書きを防止できる。
7. 成功し、hash検証に通過したMarkdown、DOCX、Review reportまたはRegister記録をdownloadできる。
8. 基本DependencyだけのCLI利用にStreamlitのimportを必要としない。
9. 既存test、Ruff、formatterおよびtyの品質確認に通過する。

## 🚧 将来候補

次は初期Streamlit UIの実装対象に含めず、必要性を確認してから別仕様で検討する。

- 実行中の外部要求への協調的な中断通知
- 保存済みupload fileの一覧・容量表示・明示的な削除
- ユーザー認証と外部公開向けの運用構成
- Langfuseによる観測
- worker数、batch、cacheおよび処理履歴列挙の性能最適化

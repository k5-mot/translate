# 📘 translate 仕様書

本書は、`translate_v1` を元に再構成する `translate` の確定済み仕様を定める。

## 🎯 設計方針

- `translate` は `translate_v1` の主要な利用目的を維持しつつ、Taskの配置と内部データモデルを再構成する。
- Taskの再分類は、それ自体を振る舞いの変更としてはならない。
- 文書は翻訳工程ごとに別のモデルへ変換せず、共通の `Document` を更新する。
- 翻訳本文、構造情報、Review結果および公開用表現は、それぞれの責務を混在させてはならない。
- MarkdownやPandoc固有の構文を `Document` へ保存してはならない。

## 🌐 対応言語

- Translateの原文言語は英語 `en`、翻訳先言語は日本語 `ja` に固定する。
- Reviewは英語原文と日本語訳文の組だけを対象とする。
- TRANSLATE-LITEも `en` から `ja` への翻訳だけを要求する。
- 言語の自動判定、CLIによる言語指定および他言語へのfallbackは行わない。
- `Document.metadata` には `source_language="en"` と `target_language="ja"` を記録する。

## 🗂️ Task構成

Taskは次のpackageへ分類する。

```text
translate/tasks/
├── converter/
│   ├── split.py
│   ├── docling.py
│   ├── unpack.py
│   └── merge.py
├── preprocess/
│   ├── position.py
│   ├── normalize.py
│   ├── load.py
│   └── structure.py
├── translation/
│   ├── translate.py
│   └── translate_lite.py
├── review/
│   ├── align.py
│   ├── check.py
│   ├── review.py
│   └── fix.py
└── publisher/
    ├── lint.py
    ├── cover.py
    ├── markdown.py
    ├── docx.py
    └── report.py
```

### 🧩 converter

| Task | 責務 |
|---|---|
| SPLIT | 入力文書をDoclingで処理可能な単位へ分割する |
| DOCLING | 分割した文書をDoclingで構造化する |
| UNPACK | Docling成果からJSONと画像assetを取り出す |
| MERGE | 分割されたJSONとassetを一つの成果へ統合する |

### 🧹 preprocess

| Task | 責務 |
|---|---|
| POSITION | 文書要素の座標と読み順を整理する |
| NORMALIZE | Docling固有の差異を後続処理向けに正規化する |
| LOAD | 正規化結果を共通の `Document` へ変換する |
| STRUCTURE | LLMを使い、見出し、リスト、Captionなどの意味構造を補正する |

### 🌐 translation

| Task | 責務 |
|---|---|
| TRANSLATE | LLMを使って `TextUnit` を翻訳する |
| TRANSLATE-LITE | LLMを使わない翻訳backendで `TextUnit` を翻訳する |

### 🔎 review

| Task | 責務 |
|---|---|
| ALIGN | Review対象の原文と訳文を決定的に対応付ける |
| CHECK | 空訳と極端な長さの差のみを決定的に検査する |
| REVIEW | LLMを使い、問題の指摘と修正候補を作成する |
| FIX | REVIEWが作成した有効な修正候補を決定的に文書へ反映する |

`VERIFY` Taskは設けない。REVIEW後のLLM再検証も行わない。

### 📦 publisher

| Task | 責務 |
|---|---|
| LINT | 最終 `Document` とassetが公開可能な構造か決定的に検査する |
| COVER | 入力文書から表紙用assetを作成する |
| MARKDOWN | `Document` をPandoc Markdownへ変換する |
| DOCX | Pandoc Markdownを最終DOCXとして公開する |
| REPORT | Review結果を利用者向けMarkdownとして公開する |

`VALIDATE` Taskは設けない。従来の公開可能性検査はLINTが引き継ぐ。

Markdownへの変換処理は `convert_*` と命名する。DOCXへの変換・公開処理は `publish` と命名する。`render_*` は使用しない。

`TaskName` は、ここで定義したTask名を大文字で列挙したenumとする。TRANSLATE-LITEの値は `TRANSLATE_LITE` とする。

## 🏗️ Sourceディレクトリ構成

Task以外を含む初期実装のSource構成は次のとおりとする。

```text
main.py
translate/
├── __init__.py
├── __main__.py
├── cli.py
├── artifact_store.py
├── common/
│   ├── __init__.py
│   ├── config.py
│   └── logger.py
├── models/
│   ├── __init__.py
│   ├── document.py
│   ├── review.py
│   └── artifacts.py
├── pipeline/
│   ├── __init__.py
│   ├── translate.py
│   ├── review.py
│   └── register.py
├── adapters/
│   ├── __init__.py
│   ├── docling.py
│   ├── embedding.py
│   ├── libretranslate.py
│   ├── llm.py
│   ├── pandoc.py
│   ├── pdf.py
│   └── qdrant.py
├── tasks/
│   ├── __init__.py
│   ├── converter/
│   │   ├── __init__.py
│   │   ├── split.py
│   │   ├── docling.py
│   │   ├── unpack.py
│   │   └── merge.py
│   ├── preprocess/
│   │   ├── __init__.py
│   │   ├── position.py
│   │   ├── normalize.py
│   │   ├── load.py
│   │   └── structure.py
│   ├── translation/
│   │   ├── __init__.py
│   │   ├── translate.py
│   │   └── translate_lite.py
│   ├── review/
│   │   ├── __init__.py
│   │   ├── align.py
│   │   ├── check.py
│   │   ├── review.py
│   │   └── fix.py
│   └── publisher/
│       ├── __init__.py
│       ├── lint.py
│       ├── cover.py
│       ├── markdown.py
│       ├── docx.py
│       └── report.py
└── templates/
    ├── glossary.csv
    ├── review-rules.md
    ├── structure-rules.md
    ├── template-style.md
    ├── template.docx
    └── translation-rules.md
```

各packageとmoduleの責務は次のとおりとする。

| 配置 | 責務 |
|---|---|
| rootの `main.py` | Pipelineへ接続しないStreamlitのモック画面を提供する |
| `cli.py` | CLI引数を検査し、Pipelineを呼び出して終了コードと成果物pathを表示する |
| `artifact_store.py` | `outputs` のpath生成、排他lock、fingerprint、Task成果物およびLLM Call進捗の原子的な保存と再読込みを隠蔽する |
| `common/config.py` | 環境変数を読み取り、Pydantic設定モデルとして検証する |
| `common/logger.py` | 標準Libraryのloggingが出力するlevel名へ色を付ける |
| `models/document.py` | `Document`、`Page`、`Block`、`TextUnit`、`TextSpan`、画像および表モデルを定義する |
| `models/review.py` | `ReviewTarget`、`Finding`、`Revision`、`TextEdit`および修正結果を定義する |
| `models/artifacts.py` | 最上位JSON、Task状態、ManifestおよびTask固有Resultを定義する |
| `pipeline/` | Taskの順序、分岐、停止およびResumeを調整する |
| `adapters/` | Docling、生成LLM、Embedding、LibreTranslate、Pandoc、PDFおよびQdrantとの外部接続を隠蔽する |
| `tasks/` | 文書処理の各Taskを実装する |
| `templates/` | 規則、既定用語集およびDOCX公開用templateを保持する |

`common` は設定とloggingだけに限定する。`core`、`utils` のように責務が曖昧なpackageは設けない。Task間で共有するためだけの `BaseTask` も設けない。例外は所有するmoduleに定義し、単独の `errors.py` へ集約しない。

`artifact_store.py` は、保存形式を呼出元へ露出させず、Artifactの原子的な保存、検証済みArtifactの読込み、fingerprint照合および排他lockを提供する永続化moduleとする。`models/artifacts.py` は保存するPydanticモデルの定義だけを持ち、file I/Oを行わない。

`common/config.py` は `.env` とprocess環境変数を読み、検証済みの設定モデルを返す。外部clientの生成、Artifactの読書きおよびPipelineの選択は行わない。

`common/logger.py` は標準Libraryの `logging` が出力するlevel名へANSI色を付けることだけを責務とする。色は `DEBUG` をcyan、`INFO` をgreen、`WARNING` をyellow、`ERROR` をred、`CRITICAL` をbold redとする。出力先がTTYでない場合は色を付けない。level選択、出力先、message形式、metadata、filter、file出力および環境変数は標準Libraryまたは呼出元に任せ、`common/logger.py` では設定しない。

rootの `main.py` はTranslate、ReviewおよびRegisterの入力欄、固定された進捗例、成果物path例を表示するだけのStreamlitモックとする。Pipeline、外部endpoint、Artifact保存およびResumeは呼び出さない。実処理との接続はTODOとする。

## ⌨️ CLI契約

CLI commandは次の3つに限定する。

| Command | 形式 | 責務 |
|---|---|---|
| Translate | `translate-ja translate <source.pdf> [--backend llm\|libretranslate] [--resume <translation-id>]` | 英語PDFを日本語MarkdownおよびDOCXへ変換する |
| Review | `translate-ja review <source.pdf> <translation.pdf> [--resume <review-id>]` | 独立した英語原文と日本語訳文を比較する |
| Register | `translate-ja register <path>... [--source-id <source-id>] [--resume <registration-id>]` | RAG参照資料をQdrantへ登録する |

- `--backend` の既定値は `llm` とする。
- `publish` commandは設けない。公開処理はTranslate Pipelineの一部とする。
- Resumeでも入力pathの指定を必須とし、保存済みの入力情報だけから処理を開始してはならない。
- `.env` は現在の作業directoryから読み、`outputs` も現在の作業directory直下に作成する。同名の値がある場合はprocess環境変数を `.env` より優先する。
- 初期実装ではpackage同梱の規則、用語集およびtemplateだけを使用し、CLIから差替えるoptionは設けない。
- 成功時は終了code `0`、処理失敗は `1`、入力または設定の不備は `2`、利用者による中断は `130` とする。
- CLIは処理IDと最終成果物のpathを表示する。
- packageのconsole scriptは `translate-ja = "translate.cli:app"` とし、`python -m translate` も同じCLIを起動する。rootにCLI用の `cli.py` は置かない。

## 📁 成果物ディレクトリ

成果物のトップディレクトリは `outputs` とする。入力fileの最終suffixを除いた `Path.stem` ごとに分け、その配下で1回の処理をUUIDv7によって識別する。たとえば `manual.en.pdf` の最上位名は `manual.en` とする。ディレクトリ入力では `Path.name` を使用する。

```text
outputs/<file-basename>/<uuidv7>/
```

存在するTaskのディレクトリだけを作成し、未実行Taskの空ディレクトリは作成しない。

### 🌐 Translate成果物

入力fileの `Path.stem` を使い、UUIDv7は `translation_id` とする。TRANSLATEとTRANSLATE-LITEは選択された一方のディレクトリだけを作成する。

```text
outputs/<source-basename>/<uuidv7>/
├── translation.json
├── task-structure.json
├── task-translate.json      # LLM backendの場合だけ
├── task-review.json
├── converter/
│   ├── split/
│   ├── docling/
│   ├── unpack/
│   └── merge/
├── preprocess/
│   ├── position/
│   ├── normalize/
│   ├── load/
│   └── structure/
├── translation/
│   └── translate/ または translate-lite/
├── review/
│   ├── check/
│   ├── review/
│   └── fix/
└── publisher/
    ├── lint/
    ├── cover/
    ├── markdown/
    └── docx/
```

### 🔎 Review成果物

評価対象の翻訳済みfileの `Path.stem` を使い、UUIDv7は `review_id` とする。原文と訳文の各分岐は `source` と `translation` で識別する。ReviewではFIXを実行しない。

```text
outputs/<translation-basename>/<uuidv7>/
├── review.json
├── task-review.json
├── converter/
│   ├── source/
│   │   ├── split/
│   │   ├── docling/
│   │   ├── unpack/
│   │   └── merge/
│   └── translation/
│       ├── split/
│       ├── docling/
│       ├── unpack/
│       └── merge/
├── preprocess/
│   ├── source/
│   │   ├── position/
│   │   ├── normalize/
│   │   └── load/
│   └── translation/
│       ├── position/
│       ├── normalize/
│       └── load/
├── review/
│   ├── align/
│   ├── check/
│   └── review/
└── publisher/
    └── report/
        └── review.md
```

### 📚 Register成果物

単一fileではその `Path.stem`、単一ディレクトリではその `Path.name` を使い、UUIDv7は `registration_id` とする。複数の独立したpathをまとめて登録する場合は、`source_id` を最上位の名前として必須にする。

```text
outputs/<file-or-directory-basename>/<uuidv7>/
└── registration.json

outputs/<source-id>/<uuidv7>/
└── registration.json
```

`registration.json` は登録対象、内容のhash、登録件数、登録先および状態を保持する。登録対象の実体はQdrantへ保存し、成果物側に複製しない。

`source_id` は空でない単一のpath要素に限定する。`.`、`..`、path separator、制御文字、Windowsの予約名を含む値、および末尾がspaceまたは `.` の値は拒否し、置換や自動修正を行わない。予約名の判定は大文字と小文字を区別せず、拡張子の有無にかかわらず `CON`、`PRN`、`AUX`、`NUL`、`COM1` から `COM9`、`LPT1` から `LPT9` を対象とする。

## 🔄 Task入出力契約

- 各Taskは自身の専用ディレクトリ以外へ書き込んではならない。
- LLMを使用しないTaskの成果物は一時ディレクトリへ生成し、成功時にディレクトリ単位で公開する。
- STRUCTURE、TRANSLATEおよびREVIEWは、成功したLLM CallをTask完了前でも専用の `calls/` へ原子的に公開する。
- LLMを使用するTaskの最終 `document.json`、`review.json` およびchunk集約結果は、全Call成功後に一時pathから原子的に公開する。Task失敗時に未完成の最終結果を公開してはならない。
- 単一成果を返すTaskのために汎用の `TaskResult` を設けてはならない。
- 複数成果の対応付けが必要なTaskだけがManifestモデルを使用する。
- Taskの状態とfingerprintは、最上位の `translation.json` または `review.json` へ記録する。
- JSONおよびMarkdown成果物はUTF-8、改行code LFで保存する。

| Task | 入力 | 戻り値 | 主な成果物 |
|---|---|---|---|
| SPLIT | 入力PDF | `SplitManifest` | `manifest.json`, `parts/*.pdf` |
| DOCLING | `SplitManifest` | `DoclingManifest` | `manifest.json`, `part-*/result.zip`, `part-*/job.json` |
| UNPACK | `DoclingManifest` | `UnpackManifest` | `manifest.json`, `part-*/document.json`, `part-*/assets/` |
| MERGE | `UnpackManifest`, 入力PDF | Docling Schema JSONのPath | `document.json`, `assets/` |
| POSITION | Docling Schema JSON | Path | `document.json`, `report.json` |
| NORMALIZE | 位置補正済みJSON | Path | `document.json`, `report.json` |
| LOAD | 正規化済みJSON | `Document` | `document.json` |
| STRUCTURE | `Document`, 原本PDF, 規則 | `Document` | `document.json`, `pages/page-*.json`, `calls/*/` |
| TRANSLATE | `Document`, 規則, 用語集 | `Document` | `document.json`, `chunks/*.json`, `calls/*/` |
| TRANSLATE-LITE | `Document`, backend設定 | `Document` | `document.json` |
| ALIGN | 原文と訳文の `Document` | `AlignmentResult` | `alignment.json` |
| CHECK | `list[ReviewTarget]` | `CheckResult` | `findings.json`, `final-findings.json` |
| REVIEW | Review対象、CHECK結果、規則、用語集 | `ReviewResult` | `review.json`, `chunks/*.json`, `calls/*/` |
| FIX | `Document`, `ReviewResult` | `FixResult` | `document.json`, `outcomes.json` |
| LINT | `Document`, 原本asset | `LintResult` | `report.json` |
| COVER | 入力PDF | `CoverResult` | `cover.png`, `manifest.json` |
| MARKDOWN | `Document`, `CoverResult`, asset | MarkdownのPath | `document.ja.md`, `assets/` |
| DOCX | Markdown, template | DOCXのPath | `document.ja.docx` |
| REPORT | ALIGN、CHECK、REVIEWの結果 | ReportのPath | `review.md` |

MERGEの `assets/` を原本assetの正本とする。後続Taskはこれを変更せず、MARKDOWNだけが公開用の `assets/` へ複製する。

Registerは中間Taskディレクトリを作成せず、Qdrantへの登録結果を `RegistrationResult` として `registration.json` へ保存する。

## 🗃️ Artifactモデル

永続化するArtifact管理モデルは `pydantic.BaseModel` を継承し、`ConfigDict(extra="ignore")` を使用する。各管理JSONのroot modelは `schema_version` を保持し、日時はUTCのtimezone-aware `datetime` とする。

Task別のLLM応答モデルも `ConfigDict(extra="ignore")` で検証する。応答Schemaのversionとfile hashは対応する `call.json` が保持するため、`response.json` 自体に `schema_version` を追加しない。未知fieldは検証後のmodelへ保持せず、再保存、fingerprintおよび処理判断に使用しない。必須field、型、Schema version、参照整合性およびpath安全性の検査は省略しない。

初期実装の永続化Schema versionはすべて `1` とし、各root modelの型は `schema_version: Literal[1]` とする。LLM応答SchemaもTaskごとにversion `1` から開始する。永続化SchemaとLLM応答Schemaは独立してversionを更新し、片方の変更を理由にもう片方のversionを変更してはならない。

### 📎 共通モデル

`InputFile` は処理対象として受理した一つのfileを表す。

| Field | Type | 責務 |
|---|---|---|
| `role` | `str` | `source`、`translation`、`reference`などの入力用途 |
| `logical_path` | `str` | 入力内での相対path |
| `sha256` | `str` | 入力内容のhash |
| `size_bytes` | `int` | file size |

絶対pathは保存しない。Resume時は指定された入力を再走査し、`role`、`logical_path` および `sha256` を比較する。

`ArtifactFile` は処理ディレクトリ内の一つの成果物を表す。

| Field | Type |
|---|---|
| `relative_path` | `str` |
| `sha256` | `str` |
| `size_bytes` | `int` |

`relative_path` は処理ディレクトリ基準のPOSIX形式とし、絶対pathおよび `..` を禁止する。

`ProcessingError` は処理失敗を表す。

| Field | Type |
|---|---|
| `code` | `str` |
| `message` | `str` |
| `cause_type` | `str \| None` |
| `retryable` | `bool` |

`TaskState` は開始済みTaskだけを記録する。未着手Taskの `TaskState` は作成しない。

| Field | Type |
|---|---|
| `task` | `TaskName` |
| `status` | `Literal["processing", "succeeded", "failed", "cancelled", "skipped"]` |
| `fingerprint` | `str` |
| `started_at` | `datetime` |
| `completed_at` | `datetime \| None` |
| `artifacts` | `list[ArtifactFile]` |
| `error` | `ProcessingError \| None` |

`LLMProgress` はLLMを使用するTaskごとの集約進捗を表す。

| Field | Type |
|---|---|
| `task` | `Literal["STRUCTURE", "TRANSLATE", "REVIEW"]` |
| `planned_calls` | `int` |
| `completed_calls` | `int` |
| `reused_calls` | `int` |
| `failed_calls` | `int` |
| `updated_at` | `datetime` |

`LLMTaskDiagnostics` はLLM応答のSchema検証には成功したものの、適用しなかった項目をTask単位で記録する。

| Field | Type |
|---|---|
| `schema_version` | `Literal[1]` |
| `task` | `Literal["STRUCTURE", "TRANSLATE", "REVIEW"]` |
| `diagnostics` | `list[str]` |
| `updated_at` | `datetime` |

診断文字列には `call_id`、理由code、および存在する場合だけ対象IDを含める。通信失敗とTask全体の失敗は `ProcessingError`、FIXによる拒否は `RevisionOutcome` に記録し、この一覧へ重複して記録しない。

### 📋 最上位モデル

処理全体の `status` は `processing`、`succeeded`、`failed` または `cancelled` とする。

`TranslationRecord` は `translation.json` のroot modelとし、次のfieldを持つ。

- `schema_version: Literal[1]`
- `translation_id: str`
- `status: ProcessingStatus`
- `source: InputFile`
- `source_language: Literal["en"]`
- `target_language: Literal["ja"]`
- `backend: Literal["llm", "libretranslate"]`
- `tasks: list[TaskState]`
- `llm_progress: list[LLMProgress]`
- `outputs: list[ArtifactFile]`
- `created_at: datetime`
- `updated_at: datetime`
- `error: ProcessingError | None`

`ReviewRecord` は `review.json` のroot modelとし、次のfieldを持つ。

- `schema_version: Literal[1]`
- `review_id: str`
- `status: ProcessingStatus`
- `source: InputFile`
- `translation: InputFile`
- `tasks: list[TaskState]`
- `llm_progress: list[LLMProgress]`
- `outputs: list[ArtifactFile]`
- `created_at: datetime`
- `updated_at: datetime`
- `error: ProcessingError | None`

`RegistrationRecord` は `registration.json` のroot modelとし、次のfieldを持つ。

- `schema_version: Literal[1]`
- `registration_id: str`
- `status: ProcessingStatus`
- `source_id: str | None`
- `inputs: list[InputFile]`
- `fingerprint: str`
- `collection: str`
- `embedding_model: str`
- `result: RegistrationResult | None`
- `created_at: datetime`
- `updated_at: datetime`
- `error: ProcessingError | None`

RegisterのResumeでも指定された入力を再走査し、`inputs` の内容と順序を照合する。`fingerprint` には、`source_id`、順序付き入力、抽出設定、PDF分割設定、OCR設定、`chunk_schema`、Embedding modelおよびQdrant collectionを含める。入力とfingerprintの両方が一致する場合だけ、同じ `registration_id` による冪等な登録確認または未完了処理を継続する。不一致の場合はResumeを拒否し、新しいRegistration IDを要求する。

### 📦 ManifestとResult

| Model | Field |
|---|---|
| `SplitPart` | `number`, `page_start`, `page_end`, `file: ArtifactFile` |
| `SplitManifest` | `schema_version`, `source_sha256`, `total_pages`, `parts: list[SplitPart]` |
| `DoclingPart` | `number`, `job_id`, `archive: ArtifactFile`, `poll_attempts` |
| `DoclingManifest` | `schema_version`, `parts: list[DoclingPart]` |
| `UnpackedPart` | `number`, `document: ArtifactFile`, `assets: list[ArtifactFile]` |
| `UnpackManifest` | `schema_version`, `parts: list[UnpackedPart]` |
| `TransformReport` | `schema_version`, `task`, `input_sha256`, `output_sha256`, `diagnostics: list[str]` |
| `AlignmentResult` | `schema_version`, `groups: list[AlignmentGroup]`, `targets: list[ReviewTarget]` |
| `CheckResult` | `schema_version`, `findings: list[Finding]` |
| `ReviewResult` | `schema_version`, `findings: list[Finding]`, `revisions: list[Revision]` |
| `RevisionOutcome` | `revision_id`, `status: Literal["applied", "rejected"]`, `reason_code` |
| `FixResult` | `schema_version: Literal[1]`, `document: Document`, `outcomes: list[RevisionOutcome]` |
| `LintDiagnostic` | `code: str`, `path: str`, `message: str` |
| `LintResult` | `schema_version: Literal[1]`, `valid: bool`, `document_sha256: str`, `diagnostics: list[LintDiagnostic]` |
| `CoverResult` | `schema_version: Literal[1]`, `image: ArtifactFile`, `width: int`, `height: int`, `excluded_page_numbers: list[int]` |
| `RegistrationSourceResult` | `logical_path`, `sha256`, `revision`, `point_count`, `status: Literal["registered", "unchanged"]` |
| `RegistrationResult` | `collection`, `embedding_model`, `sources: list[RegistrationSourceResult]`, `total_points` |

単一成果を包む汎用 `TaskResult`、共通Manifest基底classおよび共通Result基底classは作成しない。

## 🔀 Pipeline

### 🌐 Translate

```text
SPLIT → DOCLING → UNPACK → MERGE
→ POSITION → NORMALIZE → LOAD → STRUCTURE
→ TRANSLATE または TRANSLATE-LITE
→ CHECK → REVIEW
→ 修正候補あり: FIX
→ 修正候補なし: FIX省略
→ 最終CHECK
→ 空訳あり: 停止
→ 空訳なし: LINT
→ valid: COVER → MARKDOWN → DOCX
→ invalid: 停止
```

- REVIEWはCHECK結果が空でも実行する。
- CHECKはReviewの参考情報とし、後続Taskを停止させない。
- `ReviewResult.revisions` が空の場合はFIXを省略する。
- REVIEWが失敗した場合はpublisherへ進まない。
- FIXはRevision単位で原子的に適用する。Revision内の一つでもEditが不正な場合、そのRevision全体を適用しない。
- 一つのRevisionの失敗は、他の有効なRevisionの適用を妨げない。
- FIX後またはFIX省略後に、同じ決定的規則で最終CHECKを実行して `final-findings.json` を保存する。残存する `empty_translation` はPipeline全体を `empty_translation` として失敗させ、LINT以降を開始しない。`extreme_short` と `extreme_long` だけでは公開を停止しない。
- LINTはDocumentを変更せず、翻訳品質も判定しない。
- LINT自体の検査が完了した場合、`valid=false` でもLINTのTask状態と `report.json` は成功として保存する。Pipeline全体は `lint_failed` として失敗させ、COVER以降を開始しない。

### 🔎 Review

```text
原文:   SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD
訳文:   SPLIT → DOCLING → UNPACK → MERGE → POSITION → NORMALIZE → LOAD
                                                          ↓
                                                        ALIGN
                                                          ↓
                                                        CHECK
                                                          ↓
                                                        REVIEW
                                                          ↓
                                                        REPORT
```

ALIGNはLLMを使用しない。決定的に対応を確定できない要素は、`source_only` または `translation_only` として残す。ReviewではFIXを実行しない。

REPORTは `review.md` に次のsectionを順番に出力する。

1. severityとcategory別の件数
2. 読み順のAlignment Groupと未対応要素
3. CHECKおよびREVIEWのFinding
4. REVIEWの修正候補について、対象ID、現在訳および提案訳

Findingと修正候補がない場合も、該当sectionへ「なし」と明記する。raw promptおよびraw LLM応答はREPORTへ含めない。

### 🧹 LINTとCOVER

LINTは最終DocumentとMERGEの原本assetを対象に、次を決定的に検査する。

- Page、Block、TextUnit、TextSpan、ImageおよびTableCellのIDがDocument内で一意である。
- Page番号とBlockの読み順が矛盾しない。
- Blockの `kind` に必要なfieldが存在する。
- asset pathが相対pathであり、`..` を含まず、MERGEの原本assetとして存在する。
- TableCellのrowとcolumnが0以上、rowspanとcolspanが1以上であり、cell領域が重複しない。
- Document内の参照IDが存在し、参照先の種類が正しい。

LINTは空訳、翻訳の正確性、文体および長さを検査せず、CHECKまたはREVIEWの責務を重複してはならない。すべての診断を `LintDiagnostic` として収集し、0件なら `valid=true`、1件以上なら `valid=false` とする。

COVERは原本PDFの1ページ目を `pypdfium2` で150 DPIのPNGへ変換し、画像の完全性を検査する。MARKDOWNはこの画像を幅100%の表紙として先頭へ挿入し、`CoverResult.excluded_page_numbers=[1]` に従ってDocumentの1ページ目を本文から除外する。1ページだけのPDFでは表紙だけを公開する。

### 📚 Register

```text
入力展開 → テキスト抽出 → 分割 → Embedding → Qdrant登録 → 登録確認
```

同じ文書hashと同じ設定による再登録は冗等とする。

### ⏯️ 再開

- SQLiteや別のcheckpoint storeは使用しない。
- Task成果物と最上位JSONを再開情報の正本とする。
- STRUCTURE、TRANSLATEおよびREVIEWでは、検証済みのLLM Call Artifactも再開情報の正本とする。
- fingerprintには入力成果物のhash、関連設定、規則、モデル名およびSchema versionを含める。
- fingerprintが変わったTaskとその後続Taskを再処理する。
- LLM Call Artifactを除き、成功前の一時ディレクトリは再利用しない。
- 同じ `translation_id`、`review_id` または `registration_id` に対する同時操作を禁止する。処理ディレクトリ直下の `.lock` を `portalocker` で排他的に取得できない場合は、処理を開始しない。
- Resume時に入力fileのhash、件数またはroleが最上位JSONと一致しない場合はResumeを拒否する。変更された入力を同じ処理IDへ取り込んではならない。
- 最上位JSONの `schema_version` が現在のSchemaと一致しない場合はResumeを拒否し、新しい処理IDを使用する。
- TaskまたはLLM Call ArtifactのSchema versionが現在のSchemaと一致しない場合、そのArtifactを再利用せず、該当Task以降を再処理する。
- 利用者による中断時は最上位modelと実行中Taskの `status` を `cancelled` にして排他lockを解放する。既に原子的に公開されたTask ArtifactとLLM Call Artifactは保持し、Resumeでは中断したTaskまたは未完了Callから再開する。
- `translate_v1` の成果物、処理状態およびcheckpointを読込み、変換または再利用してはならない。

## 🆔 ID生成

- 処理全体の `translation_id`、`review_id` および `registration_id` にはUUIDv7を使用する。
- 文書内部のIDはLOADで一度だけ生成する。
- 文書内部のIDにはDoclingのsource reference、ページ番号および読み順を使用する。
- translatedまたはrevisedの文字列をID生成に使用してはならない。
- STRUCTURE、TRANSLATE、REVIEWおよびFIXは既存IDを変更してはならない。
- Captionへ移動した `TextUnit` も元のIDを維持する。
- 同じ入力、同じConverter設定および同じSchema versionでは同じIDを生成する。
- 入力文書またはConverterのSchema versionが変わった場合、ID互換性は保証しない。

file hashはfileのraw byte列に対するSHA-256とする。構造化された値のhashとfingerprintは、PydanticのJSON modeで値を直列化し、keyをUnicode code point順にsortし、余分な空白を除き、Unicodeをescapeせず、UTC日時をISO 8601表記にしたUTF-8 JSONに対するSHA-256とする。pathはPOSIX形式へ正規化してから直列化する。

Review関連のIDは次の規則で生成する。

| 対象 | ID |
|---|---|
| `AlignmentGroup` | 読み順に `alignment-000001` から連番 |
| Translateの `ReviewTarget` | `translate/<TextUnit.id>` |
| 比較Reviewの `ReviewTarget` | `review/<AlignmentGroup.id>` |
| CHECKの `Finding` | `check/<ReviewTarget.id>/<category>` |
| REVIEWの `Finding` | `review/<call_id>/finding-<応答内4桁連番>` |
| REVIEWの `Revision` | `review/<call_id>/revision-<応答内4桁連番>` |

LLMの `call_id` はTask名、順序付き対象IDおよび分割系譜をcanonical JSONとしてhash化し、`call-<sha256>` とする。Qdrant Point IDは `uuid.uuid5(uuid.NAMESPACE_URL, source_key + "\0" + revision + "\0" + str(chunk_index))` とする。

```text
Block:      p0001-b0007
TextUnit:   p0001-b0007/content
TextSpan:   p0001-b0007/content/span-0001
TableCell:  p0001-b0012/cell-r0002-c0003
Image:      p0001-b0012/cell-r0002-c0003/image-0001
```

## 🔌 外部接続契約

### 🧠 生成LLM

生成LLMは単一のOpenAI互換endpointを使用し、`httpx` で `POST /chat/completions` を直接呼び出す。

必要な環境変数は次のとおりとする。

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`: 任意。空の場合はAuthorization headerを送信しない
- `OPENAI_STRUCTURE_MODEL`
- `OPENAI_TRANSLATION_MODEL`
- `OPENAI_REVIEW_MODEL`

`OPENAI_API_KEY` が設定されている場合は `Authorization: Bearer <key>` を送信する。要求は `temperature=0`、streamingなし、tool callなしとする。provider固有parameter、FIXまたはVERIFY用model、endpoint切替およびfallbackは使用しない。

transport error、timeout、HTTP 408、HTTP 429およびHTTP 5xxだけを再試行する。その他のHTTP 4xxは即時失敗とする。

### 🧮 Embedding

Embeddingは生成LLMと同じ `OPENAI_BASE_URL` の `POST /embeddings` を `httpx` で呼び出し、`OPENAI_EMBEDDING_MODEL` を使用する。

- 1batchは16件に固定する。
- 応答vectorの件数、次元および全要素が有限値であることを検査する。
- 同じ登録処理内でvector次元が変わった場合は失敗とする。
- `OPENAI_EMBEDDING_MODEL` が未設定の場合、TranslateとReviewではRAGを無効化する。
- RegisterではEmbedding modelを必須とする。

### 📄 Docling Serve

必要な環境変数は次のとおりとする。

- `DOCLING_SERVER_URL`
- `DOCLING_API_KEY`: 任意
- `DOCLING_OCR_PRESET`
- `DOCLING_OCR_LANG`
- `DOCLING_FORCE_OCR`

`DOCLING_API_KEY` が設定されている場合は `X-Api-Key` headerとして送信する。

Docling Adapterは次のinterfaceを使用する。

- `POST /v1/convert/file/async`
- `GET /v1/status/poll/{task_id}`
- `GET /v1/result/{task_id}`

TranslateとReviewではPDFだけを入力する。成功時はZIPを取得し、ZIP内のDocling Schema JSONがちょうど1件であることを検査する。参照画像はbase64ではなくfileとして取得する。partial resultは失敗とし、別Converterへfallbackしない。

UNPACKは展開前にZIPの全entryを検査する。絶対path、drive文字を持つpath、`..` path要素、symlink、同名entry、およびWindows上で大文字と小文字だけが異なるentryを含むZIPは失敗とし、一部だけを展開してはならない。展開先を正規化した絶対pathがpartの専用ディレクトリ内にあることも確認する。

各partのassetは、MERGE時に `assets/part-0001/...` のようなpart番号付きnamespaceへ移す。MERGEはpart順にページ番号とDoclingのcollection indexを文書全体の連番へ写像し、JSON内の参照、画像URIおよびasset pathを同じ写像で更新する。参照先が存在しない場合、または写像後にID、index、URIもしくはasset pathが衝突する場合はMERGEを失敗させる。

SPLITは `PDF_SPLIT_PAGES` pageごとに分割し、既定値を10とする。DOCLINGは次のrequest設定を固定して使用する。

| 設定 | 値 |
|---|---|
| `to_formats` | `json` |
| `pipeline` | `standard` |
| `do_ocr` | `true` |
| `force_ocr` | `DOCLING_FORCE_OCR`。既定値は `false` |
| `ocr_preset` | `DOCLING_OCR_PRESET`。既定値は `tesseract` |
| `ocr_lang` | `DOCLING_OCR_LANG` の1要素配列。既定値は `eng` |
| `pdf_backend` | `docling_parse` |
| `do_table_structure` | `true` |
| `table_mode` | `accurate` |
| `table_cell_matching` | `true` |
| `do_pdf_heading_hierarchy` | `true` |
| `do_code_enrichment` | `true` |
| `do_formula_enrichment` | `true` |
| `include_images` | `true` |
| `include_page_images` | `false` |
| `images_scale` | `2.0` |
| `image_export_mode` | `referenced` |
| `target_type` | `zip` |
| `abort_on_error` | `true` |

STRUCTUREへ渡すpage画像はDocling成果へ含めず、原本PDFを `pypdfium2` で144 DPIのPNGへ変換する。画像fileのSHA-256をSTRUCTUREのTask fingerprintとLLM Call fingerprintへ含める。

### 🌐 LibreTranslate

TRANSLATE-LITEでは `LIBRETRANSLATE_URL` と任意の `LIBRETRANSLATE_API_KEY` を使用し、`POST /translate` を呼び出す。

- `source` は `en` とする。
- `target` は `ja` とする。
- `format` は `text` とする。
- `q` には文字列配列を渡す。
- `LIBRETRANSLATE_API_KEY` が設定されている場合はrequest JSONの `api_key` として渡す。
- 応答件数が入力件数と異なる場合は失敗とする。
- LibreTranslate失敗時に生成LLMへfallbackしない。

### 📝 Pandoc

Pandoc executableは `PATH` から検索し、Python packageとして追加しない。version番号ではなく、起動前に次の機能を検査する。

- `--list-of-figures`
- `--list-of-tables`
- `docx+native_numbering`
- `--reference-doc`

変換失敗時は途中のDOCXを公開しない。MARKDOWN成果物は保持し、ResumeではDOCXだけを再生成する。

DOCX公開時のPandoc optionは次に固定する。

| Option | 値 |
|---|---|
| `--from` | `markdown-smart` |
| `--to` | `docx+native_numbering` |
| `--standalone` | 有効 |
| `--reference-doc` | package同梱の `templates/template.docx` |
| `--resource-path` | 生成したMarkdownの親directory |
| `--toc` | 有効 |
| `--toc-depth` | `6` |
| `--list-of-figures` | 有効 |
| `--list-of-tables` | 有効 |

### 📚 Qdrant

Qdrantは公式の `qdrant-client` を直接使用し、次の環境変数を受け取る。

- `QDRANT_URI`
- `QDRANT_API_KEY`: 任意
- `QDRANT_COLLECTION`

Qdrantが未設定の場合、TranslateとReviewではRAGを無効化する。一部の設定だけが存在する場合は設定エラーとする。RegisterではQdrantの全設定とEmbedding modelを必須とする。optional dependencyである `qdrant-client` が必要な操作で未導入の場合も設定エラーとする。

collectionが存在しない場合は、最初のEmbedding vectorの次元とCosine距離で作成する。既存collectionのvector次元または距離関数が現在の設定と異なる場合は失敗とし、collectionを変更しない。Point IDは `source_key`、`revision` および `chunk_index` からUUIDv5で決定的に生成する。新revisionの全Pointを書込み、取得確認が完了してから旧revisionを削除する。同一revisionのPointがすべて存在する場合は書込みを省略する。

各Pointのpayloadは少なくとも次のfieldを保持する。

- `source_key`
- `revision`
- `chunk_index`
- `logical_path`
- `content`
- `content_sha256`
- `chunk_schema`
- `embedding_model`

RAG検索は上位5件に固定し、score閾値は設けない。生成LLMの入力上限へ収まらない場合は順位の低い結果から除外する。実際に採用した検索結果のPoint IDと `content_sha256` をLLM Call fingerprintへ含める。

RAGはTRANSLATEとREVIEWだけで使用し、STRUCTUREでは使用しない。各LLM Callが対象とする英語原文を対象ID順にLFで連結し、Embeddingした値を検索queryとする。英語原文が空の場合は検索しない。検索結果はscore降順でpromptへ追加し、同scoreではPoint ID順とする。

Qdrantが設定済みで検索または登録に失敗した場合、障害を無視してRAGなしで継続してはならない。

### 📂 Register入力

Registerは `.pdf`、`.docx`、`.pptx`、`.md`、`.markdown` および `.txt` を受理する。

`.md`、`.markdown` および `.txt` はUTF-8として読み、改行codeをLFへ正規化する。不正なUTF-8は置換せず入力エラーとする。

`.pdf` は `PDF_SPLIT_PAGES` pageごとに分割してDoclingへ送り、既定値を10とする。`.docx` と `.pptx` は分割せずfile全体をDoclingへ送る。Docling成果の本文だけを登録用テキストとして抽出する。

単一fileの `logical_path` はbasenameとする。ディレクトリ入力では `<rootのbasename>/<rootからの相対path>`、複数入力でも各入力に同じ規則を適用する。logical pathはPOSIX形式へ正規化し、Unicode code point順で昇順に並べる。異なる入力が同じ `logical_path` になる場合は入力エラーとし、自動改名しない。

ディレクトリ入力は再帰的に列挙し、symlinkを追跡しない。指定入力の内側に解決済みの成果物rootが存在する場合、そのdirectoryと配下を列挙対象から除外する。単一fileとして未対応形式が指定された場合はエラーとする。ディレクトリ内の未対応形式は無視し、対応fileが1件も存在しない場合はエラーとする。

抽出したテキストは改行をLFへ正規化し、空行で区切られた段落を優先して最大1,000 Unicode code pointのchunkへ分割する。隣接chunkは最大100 code pointを重複させる。単一段落が上限を超える場合だけ文字位置で分割する。分割規則の識別子は `registration-v1` とする。

`source_key` は、`source_id` が指定された場合は `<source_id>/<logical_path>`、指定されない場合は `logical_path` そのものとする。`revision` は入力内容のSHA-256、抽出設定、`chunk_schema` およびEmbedding model名から生成する。

### ⏱️ 外部処理の制限

生成LLM以外のHTTP接続および外部processには次の環境変数を使用する。安全上限を超える値または正でない値は設定エラーとし、黙って丸めない。

| 環境変数 | 既定値 | 安全上限 | 対象 |
|---|---:|---:|---|
| `HTTP_RETRY_ATTEMPTS` | 3 | 3 | 初回を含むHTTP送信の総試行回数 |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | 300 | 1,800 | 1回のHTTP要求およびPandoc processのtimeout |
| `EXTERNAL_TASK_DEADLINE_SECONDS` | 21,600 | 21,600 | Doclingの送信・poll・取得およびPandocを含む1 Task全体 |

- transport error、timeout、HTTP 408、HTTP 429およびHTTP 5xxだけを再試行する。
- その他のHTTP 4xx、応答Schema不正および成果物不正は同じ開始内で再試行しない。
- 再試行には安全上限内の指数backoffを使用する。
- DoclingのpollingはTask deadlineを超えて継続してはならない。
- 利用者が明示的にResumeした場合は、未完了または失敗した外部Taskへ新しいdeadlineと試行枠を与える。

## 📦 依存関係

新実装はTask成果物で処理状態を管理し、SQLiteおよびLangGraphを使用しない。LLMは `httpx` でOpenAI互換endpointを呼び出し、Pydanticで応答を検査する。Embeddingも `httpx` で呼び出し、Qdrantは公式clientを直接使用する。

新実装への移行完了後、次の直接依存を削除する。

- `langgraph`
- `langgraph-checkpoint-sqlite`
- `langchain`
- `langchain-core`
- `langchain-openai`
- `langchain-qdrant`
- `langchain-text-splitters`
- `langsmith`
- `typing-extensions`

基本依存には `httpx`、`pydantic`、`pillow`、`pypdfium2`、`portalocker`、`python-dotenv`、`typer` および `uuid-utils` を残す。`qdrant-client` はRAGおよびRegisterを利用する場合のoptional dependencyとする。Streamlitはrootの `main.py` を表示する `ui` optional dependencyとし、Langfuseは初期実装のdependencyへ含めない。

optional dependencyを利用する機能は必要になった時点で遅延importし、未導入のoptional dependencyが通常のTranslateを停止させてはならない。

環境変数は `os.environ` から読み取り、Pydanticの設定モデルで検証する。環境変数の読取りだけを目的として `pydantic-settings` を追加してはならない。

## 🧠 LLM利用

LLMを使用するTaskは次の3つに限定する。

- STRUCTURE
- TRANSLATE
- REVIEW

CHECK、FIXおよびpublisherの各TaskはLLMを使用してはならない。

### 📥 共通契約

- LLM応答はJSON objectとし、Pydantic応答モデルで検証する。
- provider-nativeなstructured outputは必須としない。
- LLM応答モデルは `ConfigDict(extra="ignore")` とする。
- 必須項目の欠落は検証エラーとする。
- 応答項目の順序は要求しない。
- 不明なIDは適用せず診断情報へ記録する。
- 重複IDは該当項目だけを不正とする。
- LLMへ文書全体の再出力を要求せず、変更または翻訳結果だけを返させる。
- すべてのPydanticモデルは未知fieldを無視するが、定義済みfieldとTask固有の整合条件は検査する。

### 📚 用語集

用語集はUTF-8のCSVとし、先頭のUTF-8 BOMは許容する。headerは次の8列をこの順序で持ち、列の追加、省略および重複を許可しない。

```text
english-short,english-long,japanese-short,japanese-long,kind,description,note,reference
```

- `english-short` と `japanese-short`、`english-long` と `japanese-long` はそれぞれ対とし、一方だけが空の行を拒否する。
- 各行はshortまたはlongの少なくとも一方の英日対を持たなければならない。
- `english-short` と `english-long` の空でない値は、全行・両列を通じて大文字と小文字を区別せず一意とする。
- LLM Callごとに、そのCallの英語原文へ大文字と小文字を区別せず出現する英語表記を一つ以上持つ行だけを渡す。
- 採用した行はCSVの記載順を保持し、長さ、列種別または一致位置によって並べ替えない。
- CHECKは用語集を参照せず、用語の一致または不一致を検査しない。

### 📏 実行制限

ローカルLLMのメモリ消費、待ち時間および出力不安定化を抑えるため、次の安全境界を設ける。

| 項目 | 安全境界 |
|---|---:|
| Model context | 30,208 tokens |
| 1要求の入力 | 8,192 tokens |
| 1要求の出力 | 4,096 tokens |
| 画像予約 | 2,048 tokens |
| safety reserve | 1,024以上、4,096 tokens以下 |
| 1chunkのBlock | 64件 |
| 1chunkの `TextUnit` | 64件 |
| 1chunkの `ReviewTarget` | 32件 |
| 1回のPipeline開始における同一LLM Callの総試行回数 | 3回（初回を含む） |
| 出力超過時の分割深度 | 6 |
| 1要求のtimeout | 1,800秒 |
| 1Taskのdeadline | 21,600秒 |

タスク別の既定値はハード上限以下とし、次の値を使用する。

| Task | 入力上限 | 出力上限 |
|---|---:|---:|
| STRUCTURE | 6,144 tokens | 2,048 tokens |
| TRANSLATE | 8,192 tokens | 4,096 tokens |
| REVIEW | 8,192 tokens | 4,096 tokens |

上限は次の環境変数で指定する。未指定時は既定値を使用する。環境変数は安全上限を引き上げるものではなく、安全上限以下へ調整するための設定とする。安全上限を超える値、正でない値、および矛盾するtoken budgetは起動時の設定エラーとし、黙って丸めない。

| 環境変数 | 既定値 | 安全上限 | 対象 |
|---|---:|---:|---|
| `LLM_CONTEXT_TOKENS` | 30,208 | 30,208 | Model context |
| `LLM_IMAGE_TOKENS` | 2,048 | 2,048 | 画像予約 |
| `LLM_SAFETY_TOKENS` | 1,024 | 4,096 | safety reserve |
| `STRUCTURE_INPUT_TOKENS` | 6,144 | 8,192 | STRUCTURE入力 |
| `STRUCTURE_OUTPUT_TOKENS` | 2,048 | 4,096 | STRUCTURE出力 |
| `STRUCTURE_MAX_BLOCKS` | 64 | 64 | 1chunkのBlock数 |
| `TRANSLATE_INPUT_TOKENS` | 8,192 | 8,192 | TRANSLATE入力 |
| `TRANSLATE_OUTPUT_TOKENS` | 4,096 | 4,096 | TRANSLATE出力 |
| `TRANSLATE_MAX_UNITS` | 64 | 64 | 1chunkの `TextUnit` 数 |
| `REVIEW_INPUT_TOKENS` | 8,192 | 8,192 | REVIEW入力 |
| `REVIEW_OUTPUT_TOKENS` | 4,096 | 4,096 | REVIEW出力 |
| `REVIEW_MAX_TARGETS` | 32 | 32 | 1chunkの `ReviewTarget` 数 |
| `LLM_RETRY_ATTEMPTS` | 3 | 3 | 1回のPipeline開始における同一LLM Callの総試行回数 |
| `LLM_SPLIT_MAX_DEPTH` | 6 | 6 | 出力超過時の分割深度 |
| `LLM_REQUEST_TIMEOUT_SECONDS` | 1,800 | 1,800 | 1要求のtimeout |
| `LLM_TASK_DEADLINE_SECONDS` | 21,600 | 21,600 | 1Taskのdeadline |

`LLM_SAFETY_TOKENS` は1,024以上とする。各Taskについて `入力上限 + 出力上限 + 画像予約 + safety reserve <= Model context` を満たさなければならない。画像を含まない要求では画像予約を計算から除外してよい。

有効な上限は、環境変数、endpointが示す上限および本書の安全上限の最小値とする。入力上限にはルール、Schema、用語集、文書本文およびメッセージ形式をすべて含める。ローカルendpointのTokenizerを利用できない場合は、UTF-8 byte数をtoken数の保守的な上限として使用し、追加のTokenizer依存を導入しない。再試行回数は失敗理由ごとに加算せず、1回のPipeline開始における一つのLLM Callについて全理由を合算して最大3回とする。利用者が明示的にResumeした場合、未完了または失敗したCallには新しい試行枠を与えるが、`attempts` は累計値として保持する。

### 🧾 Structured output

`structured_output` はローカルLLM endpoint間の互換性差を吸収するため、次の3方式から環境変数 `LLM_STRUCTURED_OUTPUT_MODE` で明示的に選択する。

| 値 | 動作 |
|---|---|
| `json_object` | 既定。endpointへJSON objectの生成を要求し、compact contractをpromptに含める |
| `json_schema` | endpointのnative JSON Schema機能を使用する |
| `prompt` | response formatを指定せず、promptだけでJSON objectを要求する |

endpointの機能推測による方式の自動切替は行わない。選択した方式をendpointが受理しない場合は設定エラーとして扱う。いずれの方式でも、受信したJSONは最終的に `json.loads` とPydantic応答モデルで検証する。

structured outputには次の環境変数と安全上限を設ける。

| 環境変数 | 既定値 | 安全上限 | 対象 |
|---|---:|---:|---|
| `LLM_SCHEMA_MAX_BYTES` | 8,192 | 16,384 | promptまたはnative schemaへ渡す契約 |
| `LLM_SCHEMA_MAX_DEPTH` | 4 | 6 | JSON Schemaの入れ子深度 |
| `LLM_RESPONSE_MAX_BYTES` | 262,144 | 1,048,576 | parse前の応答本文 |
| `REVIEW_MAX_FINDINGS` | 32 | 32 | 1応答のFinding数 |
| `REVIEW_MAX_REVISIONS` | 32 | 32 | 1応答のRevision数 |
| `REVIEW_MAX_EDITS_PER_REVISION` | 16 | 16 | 1RevisionのEdit数 |

STRUCTUREのpatch数は入力Block数以下、TRANSLATEのtranslation数は入力 `TextSpan` 数以下とし、上記のchunk上限も超えてはならない。件数超過は応答全体ではなく、上限を超えた項目を不正として診断情報へ記録する。

native JSON Schemaへ渡すSchemaはLLM応答専用の浅いSchemaとし、内部の `Document` Schemaを渡してはならない。また、Pydanticの `model_json_schema()` を無加工でendpointへ渡さず、次の制約を満たす縮約Schemaを生成する。

- rootはobjectとする。
- 再帰参照および任意keyのdictを使用しない。
- `oneOf`、`anyOf` および `allOf` を使用しない。
- 型はobject、array、string、integer、numberおよびbooleanに限定する。
- `null` をSchemaへ含めず、省略可能な値はfield自体を省略する。
- arrayにはTask別の最大件数を設定する。

`json_object` と `prompt` では完全なJSON Schemaをpromptへ埋め込まず、field名、型、必須性、件数上限および最小例だけを含むcompact contractを使用する。`prompt` 方式に限り、応答全体を囲む1組の `json` code fenceを除去してよい。JSON5化、正規表現による修復、欠落値の捏造は行わない。parseまたはPydantic検証に失敗した場合は検証エラーを示して1回だけ再試行し、この再試行も `LLM_RETRY_ATTEMPTS` に含める。

LLM応答モデルはTaskごとに `StructureResponse`、`TranslationResponse` および `ReviewResponse` を定義する。これらは永続化モデルから分離し、必要な差分だけを表す。

生成LLMには単一のOpenAI互換endpointだけを使用する。複数endpointの切替、振り分け、failoverおよびendpoint別設定はスコープ外とする。

### 💾 LLM Call進捗とResume

STRUCTURE、TRANSLATEおよびREVIEWは、Task単位に加えてLLM Call単位で進捗を永続化する。LLM Callは固定された対象ID群に対する一つの論理的な要求とし、同じ要求の通信再試行およびSchema再試行は別のLLM Callとして数えない。

LLM Call Artifactは各Taskの次の場所へ保存する。

```text
<task-directory>/calls/<call-id>/
├── call.json
└── response.json
```

`response.json` はPydantic検証に成功した応答だけを保存する。raw応答、prompt、API keyおよび認証headerは保存しない。

LLM診断情報はCallディレクトリへ保存せず、処理ディレクトリ直下でTask単位に集約する。STRUCTUREは `task-structure.json`、TRANSLATEは `task-translate.json`、REVIEWは `task-review.json` を使用する。TRANSLATE-LITEでは `task-translate.json` を作成しない。各fileは `LLMTaskDiagnostics` として原子的に更新し、診断が0件でもLLM Taskが開始された場合は空の一覧を保存する。これらは説明用Artifactであり、Resume判定の正本には使用しない。

`call.json` は `LLMCallArtifact` として次のfieldを保持する。

| Field | Type | 責務 |
|---|---|---|
| `schema_version` | `int` | LLM Call Artifact形式 |
| `response_schema_version` | `int` | Task別LLM応答Schemaのversion。初期値は `1` |
| `call_id` | `str` | Task内で決定的な識別子 |
| `task` | `Literal["STRUCTURE", "TRANSLATE", "REVIEW"]` | LLMを使用したTask |
| `status` | `LLMCallStatus` | Callの状態 |
| `fingerprint` | `str` | Call入力と設定のhash |
| `target_ids` | `list[str]` | このCallが処理する順序付き対象ID |
| `attempts` | `int` | 同じCall内の送信試行数 |
| `child_call_ids` | `list[str]` | 分割または欠落再送で生じた子Call |
| `response_sha256` | `str \| None` | 検証済み `response.json` のhash |
| `input_tokens` | `int \| None` | endpointが返した入力token数 |
| `output_tokens` | `int \| None` | endpointが返した出力token数 |
| `started_at` | `datetime` | 最初の送信開始時刻 |
| `updated_at` | `datetime` | 最後の状態更新時刻 |
| `error` | `ProcessingError \| None` | 本文を含まない失敗情報 |

`LLMCallStatus` は次の値に限定する。

| Status | 意味 | Resume時の動作 |
|---|---|---|
| `processing` | 送信開始済みで結果未確定 | このCallだけを再送する |
| `succeeded` | 応答の検証と保存が完了 | `response.json` を再利用する |
| `partial` | 有効な一部応答を保存し、欠落対象を子Callへ移した | 保存済み応答と子Callを再利用する |
| `split` | 親要求を再送せず、対象を子Callへ分割した | 子Callだけを処理する |
| `failed` | 再試行を使い切った | このCallから再開する |

`call_id` はTask名、順序付き `target_ids` および分割系譜から決定的に生成する。fingerprintには少なくとも次を含める。

- Task名とLLM Call Schema version
- 順序付き対象IDと対象内容のhash
- system指示、規則、用語集およびRAG文脈のhash
- STRUCTUREで使用するpage画像のhash
- model名、structured output方式およびtoken上限
- LLM応答Schemaのversion

Resumeでは `call_id`、fingerprint、`response_sha256` およびPydantic検証がすべて一致するCallだけを再利用する。一つでも一致しないCallはそのCallだけを再実行し、同じTask内の有効なCallを再実行してはならない。

出力超過で分割する場合は、親Callを `split` として子Call IDを先に原子的に保存してから子Callを送信する。Resume時に親Callを再送してはならない。TRANSLATEでIDが欠落した場合、または訳文が空の場合は、有効な応答を `partial` として保存し、該当IDだけの子Callを作成する。

各Taskの進捗は最上位JSONの `LLMProgress` にも集約し、`planned_calls`、`completed_calls`、`reused_calls`、`failed_calls` および `updated_at` を保持する。分割によって `planned_calls` が増えることを許容する。Call Artifactを進捗の正本とし、集約値に不整合がある場合はCall Artifactから再計算する。

Task完了時は保存済みCallを対象ID順に適用して最終結果を作る。Callの完了順で結果順序を変えてはならない。停止時に生成中だったCallの推論途中からの再開は行わず、そのCallだけを再送する。完了済みCallを再送しないことをResumeの保証範囲とする。

### 🧩 STRUCTURE

- 基本単位は1ページとする。
- 変更が必要なBlockの `StructurePatch` だけを返す。
- Block本文の再出力を要求しない。
- 入力上限を超えるページは連続するBlock単位で分割する。

`StructureResponse` は `patches: list[StructurePatch]` を持ち、`StructurePatch` は次のfieldを持つ。

| Field | Type |
|---|---|
| `block_id` | `str` |
| `kind` | `BlockKind \| None` |
| `level` | `int \| None` |
| `alert_kind` | `AlertKind \| None` |
| `caption_source_id` | `str \| None` |

`level`、`alert_kind` および `caption_source_id` は該当する変更がない場合に省略できる。Pydantic検証後、既存Blockと整合するpatchだけを適用する。

### 🌐 TRANSLATE

- 応答は `span_id` と翻訳後の `text` だけを含む。
- `code` と `line_break` はLLMへ送信しない。
- 応答に存在しないIDと、`text.strip()` が空になるIDを未完了対象として扱い、有効な応答を `partial` として保存して対象IDだけを1回再送する。
- 部分再送後も空の翻訳はDocumentへ保持し、CHECK、REVIEWおよびFIXの対象とする。同じIDだけを無制限に再送してはならない。
- 通常は `TextUnit` を分断しない。単一の `TextUnit` が入力上限を超える場合だけ一時的な断片へ分割し、応答後に再結合する。

`TranslationResponse` は `translations: list[TranslationItem]` を持ち、`TranslationItem` は `span_id: str` と `text: str` を持つ。

### 🔎 REVIEW

- 応答は `findings` と `revisions` を含む。
- Findingだけがあり、Revisionがない結果を許容する。
- Revisionは同じchunk内の `TextSpan.id` だけを対象とする。
- CHECK結果は参考情報として渡し、同じ指摘の再出力を強制しない。
- LLM応答にはFinding IDおよびRevision IDを含めない。Pydantic検証後、applicationが `call_id` と応答内の順序から決定的なIDを付与する。

### 🔁 再試行

1. 接続失敗、timeoutおよびrate limitは、安全上限内の指数backoffで再試行する。
2. Schema不正は検証エラーを渡して1回だけ再試行する。
3. 出力超過は同じ要求を繰り返さず、対象を半分に分割する。
4. TRANSLATEの欠落IDと空訳IDは対象分だけ1回再送する。
5. 最小単位でも成功しない場合はそのTaskを失敗とする。
6. 成功したLLM CallはArtifactとして直ちに保存し、Task完了前に停止しても再開時に再利用する。
7. LLMによる追加の検証処理は行わない。

## 📝 Markdown方言

- MARKDOWNはPandoc Markdownを基盤とする。
- Pandocが解釈可能なGFM互換記法は使用してよい。
- 完全なGFM準拠は保証しない。
- Pandoc属性、grid tableおよびRaw OpenXMLなど、DOCX公開に必要なPandoc拡張は使用してよい。
- GFM用とPandoc用の別々の変換処理は設けない。

## 🧱 データモデル

永続化するデータモデルはすべて `pydantic.BaseModel` を継承し、LLM応答モデルを含めて `ConfigDict(extra="ignore")` を使用する。

### 📄 Document構造

```text
Document
└── pages: list[Page]
    └── blocks: list[Block]
        ├── content: TextUnit | None
        ├── caption: TextUnit | None
        ├── image: Image | None
        └── cells: list[TableCell]
```

`Document` は全工程で共有する。STRUCTURE、TRANSLATE、FIXなどの工程ごとに別のDocument型を作成してはならない。

### 🔤 TextSpan

`TextSpan` は、書式と参照先を共有する最小の翻訳単位とする。

| Field | Type | 責務 |
|---|---|---|
| `id` | `str` | 文書内で安定した識別子 |
| `kind` | `Literal["text", "code", "link", "line_break"]` | Inlineの種類 |
| `source` | `str` | 原文 |
| `translated` | `str \| None` | 初回翻訳 |
| `revised` | `str \| None` | FIXが反映した修正訳 |
| `marks` | `list[TextMark]` | 太字、斜体などの装飾 |
| `href` | `str \| None` | linkの参照先 |

`TextMark` は `strong`、`emphasis`、`strikethrough`、`underline`、`subscript` または `superscript` のenumとする。

最終出力で採用する文字列は、`revised`、`translated`、`source` の優先順で決定する。`None` は未設定を表し、空文字列と区別する。

### 📝 TextUnit

| Field | Type | 責務 |
|---|---|---|
| `id` | `str` | FindingおよびRevisionが参照する安定ID |
| `spans` | `list[TextSpan]` | 書式付きの文字列 |

`TextUnit` は本文、Captionおよび表セル内容に共通して使用する。

### 🖼️ Image

| Field | Type | 責務 |
|---|---|---|
| `id` | `str` | 文書内で安定した識別子 |
| `asset_path` | `str` | 文書assetの相対path |
| `alt_text` | `str` | 代替テキスト |
| `width_pt` | `float \| None` | PDF上の幅 |
| `height_pt` | `float \| None` | PDF上の高さ |
| `caption` | `TextUnit \| None` | 画像のCaption |

### 📊 TableCell

| Field | Type |
|---|---|
| `id` | `str` |
| `row` | `int` |
| `column` | `int` |
| `rowspan` | `int` |
| `colspan` | `int` |
| `header` | `bool` |
| `content` | `TextUnit` |
| `images` | `list[Image]` |

### 🧱 Block

`Block` は種類ごとのサブクラスに分割せず、次の項目を持つ単一の `BaseModel` とする。

`BlockKind` は `paragraph`、`heading`、`blockquote`、`list_item`、`alert`、`code`、`formula`、`figure`、`table`、`footnote` または `horizontal_rule` のenumとする。`AlertKind` は `note`、`tip`、`important`、`warning` または `caution` のenumとする。

| Field | Type |
|---|---|
| `id` | `str` |
| `order` | `int` |
| `kind` | `BlockKind` |
| `bbox` | `tuple[float, float, float, float] \| None` |
| `content` | `TextUnit \| None` |
| `caption` | `TextUnit \| None` |
| `image` | `Image \| None` |
| `cells` | `list[TableCell]` |
| `level` | `int \| None` |
| `ordered` | `bool` |
| `checked` | `bool \| None` |
| `language` | `str \| None` |
| `alert_kind` | `AlertKind \| None` |

Block種類ごとの主な使用項目は次のとおりとする。

| `kind` | 使用項目 |
|---|---|
| `paragraph`, `blockquote`, `footnote` | `content` |
| `heading` | `content`, `level` |
| `list_item` | `content`, `level`, `ordered`, `checked` |
| `alert` | `content`, `alert_kind` |
| `code` | `content`, `language` |
| `formula` | `content` |
| `figure` | `image` |
| `table` | `caption`, `cells` |
| `horizontal_rule` | 追加項目なし |

LOAD直後の不完全な構造を扱えるよう、必要のない項目までBlock生成時に厳格に拘束してはならない。各Taskは自身が必要とする条件のみを入口で検査する。

### 📃 PageとDocument

| Model | Field | Type |
|---|---|---|
| `Page` | `number` | `int` |
| `Page` | `width` | `float \| None` |
| `Page` | `height` | `float \| None` |
| `Page` | `blocks` | `list[Block]` |
| `Document` | `schema_version` | `Literal[1]` |
| `Document` | `pages` | `list[Page]` |
| `Document` | `metadata` | `dict[str, JsonValue]` |

## 🔗 ALIGNとCHECK

### 🔗 ALIGN

ALIGNは独立した英語原文と日本語訳文を保守的に1対1対応させる。Translate Pipelineでは同じ `Document` 内のIDから `ReviewTarget` を直接作成し、ALIGNを実行しない。

比較ReviewのALIGNは次の手順で処理する。

1. 原文と訳文から本文、見出し、Captionおよび表セルを読み順で列挙する。
2. 空文字列だけの要素を除外する。
3. 要素のroleを `body`、`heading`、`caption` または `table_cell` に分類する。
4. URL、見出し先頭の節番号および図表番号から、両文書に一度だけ現れる同一anchorを抽出する。
5. 読み順が逆転しないanchorだけを確定する。
6. anchor間の要素数とrole列が一致する場合だけ、読み順で1対1対応させる。
7. 一意に確定できない要素を `source_only` または `translation_only` として残す。

`AlignmentGroup` は次のfieldを持つ。

| Field | Type |
|---|---|
| `id` | `str` |
| `source_ids` | `list[str]` |
| `translation_ids` | `list[str]` |
| `kind` | `Literal["matched", "source_only", "translation_only"]` |
| `method` | `Literal["unique_anchor", "ordered_role", "unmatched"]` |

初期実装ではLLM fallback、Embedding類似度、翻訳文間の文字列類似度、1対多または多対1の推測、およびconfidence scoreを使用しない。誤った対応より未対応を優先する。

anchor抽出ではPython標準Libraryの正規表現と `unicodedata.normalize("NFKC", text)` だけを使用する。URLは末尾の句読点を除いた文字列、heading先頭の `2.1` などは `section:2.1`、`Figure 3`、`Fig. 3` および `図3` は `figure:3`、`Table 4` および `表4` は `table:4` へ正規化する。一般的な数値、本文途中の節番号およびこれらに該当しない語句はanchorとして扱わない。

`source_only` と `translation_only` はREPORTへ出力するが、CHECKの長さ比較対象およびREVIEWへ渡す `ReviewTarget` には含めない。

### ✅ CHECK

CHECKは比較前に文字列の前後空白を除去し、連続する空白を一つのspaceへ正規化する。長さはPythonの `len()` によるUnicode code point数とする。

| 条件 | `Finding.category` | severity |
|---|---|---|
| 原文が空でなく、訳文が空 | `empty_translation` | `error` |
| 原文が80文字以上、訳文が原文の15%未満 | `extreme_short` | `warning` |
| 訳文が100文字以上、訳文が原文の5倍超 | `extreme_long` | `warning` |

- 空訳では `extreme_short` を重複生成しない。
- 原文が空の場合は長さを比較しない。
- 一つの `ReviewTarget` につき長さに関するFindingは最大1件とする。
- 閾値は固定値とし、初期実装では環境変数化しない。
- 同文判定、未翻訳推測、用語集照合、URLまたはfile名の保持確認、文法、正確性および流暢性は検査しない。

CHECKの対象外とした品質判断はREVIEWの責務とする。

## 🛠️ Reviewと修正

Review結果は `Document` へ直接混在させず、別の `BaseModel` として扱う。

### 🎯 ReviewTarget

CHECKとREVIEWは、Translateと独立した比較Reviewの両方から作成できる `ReviewTarget` を共通入力とする。

| Field | Type | 責務 |
|---|---|---|
| `id` | `str` | Review対象の決定的な識別子 |
| `source` | `str` | 英語原文 |
| `translation` | `str` | 日本語訳文 |
| `target_ids` | `list[str]` | 対応する訳文側の `TextUnit.id` |
| `spans` | `list[TextSpan]` | 修正候補が参照できる訳文側のSpan |

### 🔎 Finding

`Finding` は問題の指摘を表し、対象の `TextUnit.id` を参照する。指摘と修正候補は分離する。

| Field | Type |
|---|---|
| `id` | `str` |
| `origin` | `Literal["check", "review"]` |
| `category` | `str` |
| `severity` | `Literal["info", "warning", "error"]` |
| `target_ids` | `list[str]` |
| `message` | `str` |

### 🛠️ Revision

| Model | Field | 責務 |
|---|---|---|
| `Revision` | `id` | applicationが付与する決定的な識別子 |
| `Revision` | `target_id` | 対象の `TextUnit.id` |
| `Revision` | `edits` | `list[TextEdit]` |
| `TextEdit` | `span_id` | 対象の `TextSpan.id` |
| `TextEdit` | `text` | `revised` へ設定する修正訳 |

`ReviewResult` は `findings` と `revisions` を保持する。FIXはRevisionのID参照、重複、対象の種類などを決定的に検査し、有効な `TextEdit.text` を `TextSpan.revised` へ設定する。

`FixResult` は更新した `Document` と `RevisionOutcome` の一覧を保持する。適用できない候補は本文の状態として保存せず、`RevisionOutcome` に理由とともに記録する。

`ReviewResponse` は `findings: list[ReviewFinding]` と `revisions: list[ReviewRevision]` を持つ。LLM応答用の各modelは次のfieldだけを持ち、IDと `origin` は含めない。

| Model | Field |
|---|---|
| `ReviewFinding` | `category: str`, `severity: Literal["info", "warning", "error"]`, `target_ids: list[str]`, `message: str` |
| `ReviewRevision` | `target_id: str`, `edits: list[ReviewTextEdit]` |
| `ReviewTextEdit` | `span_id: str`, `text: str` |

`ReviewFinding`、`ReviewRevision` および `ReviewTextEdit` はLLM応答専用modelとし、いずれも `ConfigDict(extra="ignore")` を使用する。永続化用の `TextEdit` を `ReviewResponse` の検証へ流用してはならない。

Pydanticで形状を検証できたFindingとRevisionは `ReviewResult` に保持する。未知のFinding対象IDも削除せずREPORTへ渡し、診断情報へ記録する。ただし、未知のIDをDocument変更へ使用してはならない。applicationは `origin="review"` と決定的なIDを付与し、Callの対象ID順、各応答内の出現順で `ReviewResult` を集約する。CHECKが生成するFindingには `origin="check"` を設定する。

FIXは `ReviewResult.revisions` の順序でRevisionを処理し、次の規則を決定的に適用する。

- 未知の `target_id` はRevision全体を `unknown_target` で拒否する。
- 未知の `span_id`、または対象 `TextUnit` に属さない `span_id` はRevision全体を `unknown_span` で拒否する。
- 同じRevision内で同じ `span_id` が複数回現れる場合はRevision全体を `duplicate_edit` で拒否する。
- `text.strip()` が空になるEditを含む場合はRevision全体を `empty_text` で拒否する。
- 先に適用したRevisionと同じ `span_id` を変更するEditを一つでも含む場合は、後のRevision全体を `conflicting_edit` で拒否する。先に適用したRevisionを巻き戻さない。
- すべてのEditが有効なRevisionだけを原子的に適用し、`TextEdit.text` を対応する `TextSpan.revised` へそのまま設定する。

FIXは候補の意味を再評価せず、LLMを呼び出さない。比較ReviewではFIXを実行しないため、RevisionはREPORT上の提案としてだけ表示する。

## 🔁 `translate_v1` との互換性

新実装は次の利用目的を維持する。

- 英語PDFから、文書構造を保った日本語MarkdownおよびDOCXを生成する。
- 独立した英語原文と日本語訳文からReview reportを生成する。
- 対応文書をEmbeddingし、Qdrantへ登録する。

一方、JSON Schema、ID、成果物path、Task数、Finding数、MarkdownおよびDOCXのbyte列、内部例外、Resume形式の一致は保証しない。`translate_v1` の成果物、処理状態およびcheckpointを新実装へ移行する互換layerも設けない。

## 🚧 TODO

初期実装の完了後に、必要性と測定結果を確認して次を検討する。

- StreamlitモックUIと実Pipelineの接続
- Langfuseによる観測
- 並列化、cache調整およびbatch調整を含む性能最適化

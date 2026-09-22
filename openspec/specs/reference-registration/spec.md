<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

# reference-registration Specification

## Purpose

参照文書を検索・翻訳・比較処理から一貫して利用できるよう、Qdrantへの登録、再登録、失敗診断および再開可能性を定義する。大規模な文書と外部Service障害に対しても、登録済みdataの完全性と秘密情報の保護を維持する。

## Requirements

### Requirement: 大規模PDFを有界な処理単位で登録する
Systemは、PDFを設定済みpage上限以下の順序付きpartとして抽出し、source hashを入力sizeに比例するmemoryへ全量保持せず計算し、ChunkのEmbedding、書込みおよび確認を有限件数のbatchで実行しなければならない（MUST）。同じ入力、登録元IDおよび分割設定からは同じChunk順序とPoint IDを生成し、すべての新revisionを確認した後だけ旧revisionを削除しなければならない（MUST）。Q-PERFおよびQ-REL（ISO/IEC 25010）として、1回のDocling入力を`PDF_SPLIT_PAGES`以下にし、Qdrant batchを設計上の固定上限以下に保ち、65 MB・358 pageの固定受入PDFを設定済みTask deadline内に登録完了させなければならない（MUST）。

#### Scenario: 大規模PDFを新規登録する
- **WHEN** 利用者がpage数の多いPDFを公開CLIまたはStreamlitから登録する
- **THEN** Systemはpage上限以下のpartを元page順に処理し、全Chunkの登録確認後に成功件数を返す

#### Scenario: 大規模PDFの登録途中で外部Serviceが失敗する
- **WHEN** Docling、EmbeddingまたはQdrantの有限retryが回復せず、partまたはbatchの処理が完了しない
- **THEN** Systemは登録成功を報告せず、旧revisionを保持し、同じrun IDから再実行可能なfailed Runを保存する

#### Scenario: 同じ大規模PDFを再登録する
- **WHEN** 同じ登録元ID、入力内容および分割設定のPDFを再登録する
- **THEN** Systemは決定的なPoint IDを再利用し、確認済みChunkの重複と旧revisionの残存を0件にする

### Requirement: 登録失敗を安全なstage情報で診断できる
Systemは、登録失敗時に`REGISTER` Task、失敗stageおよび下位例外型を`failure.json`、Run logならびに公開Errorへ保持しなければならない（MUST）。stageは収集、hash、分割、抽出、書込み、確認およびrevision置換を区別しなければならない（MUST）。Credential、文書本文、raw外部応答、外部job IDおよび画像binaryを診断情報へ含めてはならない（MUST NOT）。Q-USEおよびQ-SEC（ISO/IEC 25010）として、stage別障害注入Testで原因stage不明と秘密漏えいを0件にしなければならない（MUST）。

#### Scenario: Docling抽出が失敗する
- **WHEN** PDF partのDocling抽出が有限retry後も失敗する
- **THEN** Systemは`REGISTER`、抽出stageおよび安全な下位例外型を記録し、raw応答と外部job IDを記録しない

#### Scenario: Qdrant登録確認が失敗する
- **WHEN** 書込み済みPointの確認が有限retry後も完了しない
- **THEN** Systemは確認stageと安全な下位例外型を記録し、登録成功件数を報告せず旧revisionを削除しない

#### Scenario: Revision置換が失敗する
- **WHEN** 新revision確認後の旧revision削除が有限retry後も失敗する
- **THEN** Systemはrevision置換stageと安全な下位例外型を記録し、登録操作全体を失敗として返す

### Requirement: 対応文書を登録できる
Systemは、PDF、DOCX、PPTX、MarkdownおよびTextのFileまたはDirectoryを受け取り、文書を抽出・分割・Embeddingして指定Collectionへ登録しなければならない（SHALL）。未対応形式は黙って登録してはならない（MUST NOT）。

#### Scenario: 複数形式を登録する
- **WHEN** 利用者が対応形式のFileとDirectoryを指定する
- **THEN** Systemは対象文書を収集し、検索可能なChunk件数を返す

#### Scenario: 未対応形式だけが指定される
- **WHEN** 利用者が未対応形式だけを指定する
- **THEN** Systemは登録対象がないことを示す入力Errorを返す

### Requirement: 登録単位を置換できる
Systemは、同一の登録元revisionを再登録した場合、旧Chunkを残したまま重複追加せず、新revisionへ置換しなければならない（SHALL）。登録確認が完了する前に成功を報告してはならない（MUST NOT）。

#### Scenario: 更新文書を再登録する
- **WHEN** 既に登録済みの文書を新しい内容で登録する
- **THEN** Systemは旧revisionのChunkを新revisionで置換し、重複しない登録件数を返す

### Requirement: 登録障害を失敗として返す
Systemは、抽出、Embedding、Collection作成、書込みまたは登録確認に失敗した場合、有限retry後に登録操作を失敗させなければならない（MUST）。部分登録を完全な成功として報告してはならない（MUST NOT）。

#### Scenario: Qdrantへの書込みが回復しない
- **WHEN** Qdrant書込みが有限retry後も失敗する
- **THEN** Systemは秘密情報を含まないErrorを返し、登録成功件数を報告しない

### Requirement: 検索結果を追跡できる
Systemは、翻訳またはReviewで使用した検索結果を、Collection名、検索日時、引用元および取得内容とともにRun Artifactへ保存しなければならない（SHALL）。Qdrantの可変状態をRunのResume拒否判定に使用してはならない（MUST NOT）。

#### Scenario: Qdrant変更後にRunをResumeする
- **WHEN** 完了済みTaskの後にQdrant内容が変更され、同じRunをResumeする
- **THEN** Systemは完了済みArtifactを再利用し、未完了Taskだけが現在のQdrantを検索し、利用した検索結果を保存する

### Requirement: 参照登録の品質を検証できる
Q-REL（ISO/IEC 25010 信頼性）として、Systemは登録の再試行、revision置換および部分失敗の自動Testを実行可能にし、重複Chunkと誤った成功報告を0件にしなければならない（MUST）。

#### Scenario: 登録信頼性Testを実行する
- **WHEN** 保守者が一時障害、再登録および恒久障害のTestを実行する
- **THEN** Systemは一時障害を有限回で回復し、再登録を置換し、恒久障害を失敗として報告する

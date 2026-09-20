<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Purpose

利用者が対応形式の参照文書をQdrantへ登録し、翻訳およびReviewが根拠付き検索結果を利用できるようにするとともに、登録失敗を明示的に検出できるようにする。

## ADDED Requirements

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


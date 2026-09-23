## MODIFIED Requirements

### Requirement: PDFを日本語DOCXへ変換できる

Systemは、STRUCTUREのLLM接続Errorに遭遇した場合、同じpage要求を最大1回だけ逐次再送しなければならない（MUST）。再送が成功した場合は完全な応答をcheckpointし、失敗した場合は既存の安全なStructurePageErrorとして停止しなければならない（MUST）。

#### Scenario: STRUCTURE接続断から回復する
- **WHEN** 初回要求が接続Errorとなり、再送が完全な構造応答を返す
- **THEN** Systemはpageを保存し次の未完了pageへ進む

#### Scenario: 接続retryが枯渇する
- **WHEN** 初回と最大1回の再送が接続Errorとなる
- **THEN** Systemは安全な診断とResume可能Failureだけを保持し、raw responseを公開しない

#### Scenario: PDF翻訳に成功する
- **WHEN** 利用者が読取り可能な英語PDFと有効な設定を指定する
- **THEN** SystemはRunの公開成果物として検証済み日本語DOCXを生成する

#### Scenario: 読取り不能なPDFを拒否する
- **WHEN** 利用者が空、暗号化済み、破損または読取り不能なPDFを指定する
- **THEN** Systemは入力Errorを示し、DOCXを公開しない

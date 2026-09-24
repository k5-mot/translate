<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 任意の英日PDFを比較できる
Systemは、互いに独立した読取り可能な英語PDFと日本語PDFを受け取り、両入力を変更せずに比較Reviewを実行しなければならない（SHALL）。Review入力が分割された場合も、全chunkのFindingを重複なく統合してからreportを公開しなければならない（MUST）。

#### Scenario: 独立した英日PDFを比較する
- **WHEN** 利用者が改ページや段落構成の異なる英語PDFと日本語PDFを指定する
- **THEN** Systemは両入力を変更せず、公開Review reportと診断用Artifactを生成する

#### Scenario: 一方のPDFが無効である
- **WHEN** いずれかのPDFが空、暗号化済み、破損または読取り不能である
- **THEN** Systemは対象入力を特定したErrorで停止し、Review reportを公開しない

#### Scenario: Review chunkが完了する
- **WHEN** 利用者が入力PDFと対応する翻訳PDFを指定し、全Review chunkが完了する
- **THEN** Systemは対応関係、欠落、追加、誤訳および保護対象のFindingを含むMarkdown reportを公開する

#### Scenario: Review chunkが失敗する
- **WHEN** 比較Reviewの最小chunkが有限retry後も失敗する
- **THEN** Systemは部分reportを公開せず、失敗Taskと対象を記録したResume可能なRunを保持する

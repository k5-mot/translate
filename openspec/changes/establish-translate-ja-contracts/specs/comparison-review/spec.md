<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Purpose

利用者が独立して作成された英語PDFと日本語PDFを比較し、入力文書を変更せず、多対多の対応関係と問題根拠を含むReview reportを取得できるようにする。

## ADDED Requirements

### Requirement: 任意の英日PDFを比較できる
Systemは、互いに独立した読取り可能な英語PDFと日本語PDFを受け取り、両入力を変更せずに比較Reviewを実行しなければならない（SHALL）。

#### Scenario: 独立した英日PDFを比較する
- **WHEN** 利用者が改ページや段落構成の異なる英語PDFと日本語PDFを指定する
- **THEN** Systemは両入力を変更せず、公開Review reportと診断用Artifactを生成する

#### Scenario: 一方のPDFが無効である
- **WHEN** いずれかのPDFが空、暗号化済み、破損または読取り不能である
- **THEN** Systemは対象入力を特定したErrorで停止し、Review reportを公開しない

### Requirement: 文書要素を多対多で対応付ける
Systemは、見出し、番号、URL、固有名詞、順序および前後関係を用いて、1対1、1対多および多対1の対応を表現しなければならない（SHALL）。未対応要素は原文側または訳文側の未対応として保持し、全対象IDを重複なく一度だけ扱わなければならない（MUST）。

#### Scenario: 一段落が複数段落に翻訳されている
- **WHEN** 一つの英語段落が複数の日本語段落に分割されている
- **THEN** Systemは1対多の対応Groupを生成する

#### Scenario: 対応する要素が存在しない
- **WHEN** 原文または訳文の要素に対応先が存在しない
- **THEN** Systemは対象を欠落候補としてreportへ明示する

### Requirement: 問題と根拠をReportする
Systemは、決定的検査と意味ReviewのFindingを、重大度、種別、対象、根拠および修正方針とともに公開Review reportへ記載しなければならない（SHALL）。比較Workflowは入力文書または訳文を修正してはならない（MUST NOT）。

#### Scenario: Findingを集計する
- **WHEN** 対応Groupに数値欠落、誤訳または不自然な日本語が検出される
- **THEN** SystemはFindingと根拠を重大度・種別別に集計してreportへ出力する

#### Scenario: Findingがない
- **WHEN** すべての対応Groupが検査とReviewに合格する
- **THEN** SystemはFindingが0件であることを明示したreportを生成する

### Requirement: 比較処理をTask単位で再開できる
Systemは、英語側と日本語側の解析Taskを独立して追跡し、両文書の解析完了後に対応付けを開始しなければならない（SHALL）。失敗後のResumeでは、成功済みTaskを再実行せず、失敗したTaskから再開しなければならない（MUST）。

#### Scenario: 日本語側解析の途中で失敗する
- **WHEN** 英語側解析が完了し、日本語側のTaskが失敗したRunをResumeする
- **THEN** Systemは英語側の完了済みArtifactを再利用し、日本語側の失敗Taskから処理を再開する

### Requirement: 比較Reviewの機能品質を検証できる
Q-FUNC（ISO/IEC 25010 機能適合性）として、Systemは1対1、1対多、多対1、原文側未対応および訳文側未対応のfixtureを自動検証し、各IDの重複・欠落件数を0件にしなければならない（MUST）。

#### Scenario: 対応fixtureを検証する
- **WHEN** 保守者が既知の対応関係を持つ比較fixtureを実行する
- **THEN** Systemは期待した全Groupを生成し、重複IDと未分類IDを0件にする


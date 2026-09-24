<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 翻訳結果を検査してから公開する
Systemは、決定的検査と意味Reviewを行い、指摘がある翻訳単位だけに修正候補を生成し、検証に合格した候補だけを採用しなければならない（SHALL）。修正または検証が失敗した単位は修正前訳へ戻し、警告として記録しなければならない（MUST）。ReviewのLLM出力が上限に達した場合、Systemは入力pairsを決定的に分割してFindingを統合し、全chunkの検証完了前にReview Artifactを公開してはならない（MUST NOT）。

#### Scenario: 修正候補を採用する
- **WHEN** 修正候補が指摘を解消し、新しい欠落、追加または誤訳を生じない
- **THEN** Systemは候補を最終採用訳として使用する

#### Scenario: 修正または検証に失敗する
- **WHEN** 修正生成または検証が対象単位で失敗する
- **THEN** Systemは修正前訳を保持し、対象IDと理由を警告へ記録して残りの文書処理を継続する

#### Scenario: Review出力が枯渇する
- **WHEN** ReviewのLLM応答が`finish_reason=length`で終了する
- **THEN** Systemは有限retry後にpairsを決定的に分割し、全chunkのFindingをページへ統合してからReview Artifactをatomic公開する

#### Scenario: Review分割後も失敗する
- **WHEN** 最小Review chunkでも規定回数のretryに失敗する
- **THEN** SystemはREVIEWを停止し、未完了Artifactを公開せず、同じRunをResume可能な状態と安全なFailure Evidenceを保持する

### Requirement: PDFを日本語DOCXへ変換できる
Systemは、読取り可能な英語PDFを受け取り、日本語DOCXと診断用Artifactを生成しなければならない（SHALL）。空、暗号化済み、破損または読取り不能なPDFは入力Errorとして拒否しなければならない（MUST）。Reviewが未完了の場合は検証済み成果物を公開してはならない（MUST NOT）。

#### Scenario: PDF翻訳に成功する
- **WHEN** 利用者が読取り可能な英語PDFと有効な設定を指定する
- **THEN** SystemはRunの公開成果物として検証済み日本語DOCXを生成する

#### Scenario: 読取り不能なPDFを拒否する
- **WHEN** 利用者が空、暗号化済み、破損または読取り不能なPDFを指定する
- **THEN** Systemは入力Errorを示し、DOCXを公開しない


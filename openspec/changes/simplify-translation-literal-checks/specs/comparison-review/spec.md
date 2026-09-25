<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 問題と根拠をReportする
Systemは、決定的検査と意味ReviewのFindingを、重大度、種別、対象、根拠および修正方針とともに公開Review reportへ記載しなければならない（SHALL）。比較Workflowは入力文書または訳文を修正してはならない（MUST NOT）。共通の決定的検査は、固有名詞・略語・一般識別子の表記差だけでは保護文字列欠落とせず、明確なURL・ファイル名の変更をwarningとして記録しなければならない（MUST）。このwarningだけを理由にReviewを停止してはならない（MUST NOT）。意味Reviewによる根拠のある誤訳の指摘は妨げない。

#### Scenario: Findingを集計する
- **WHEN** 対応Groupに数値欠落、誤訳または不自然な日本語が検出される
- **THEN** SystemはFindingと根拠を重大度・種別別に集計してreportへ出力する

#### Scenario: Findingがない
- **WHEN** すべての対応Groupが検査とReviewに合格する
- **THEN** SystemはFindingが0件であることを明示したreportを生成する

#### Scenario: URLまたはファイル名の変更を警告としてReportする
- **WHEN** 対応する原文と訳文で明確なURLまたはファイル名の変更を決定的検査が検出する
- **THEN** Systemは対象・根拠をwarningとしてreportへ保持し、入力文書を変更せずに処理を継続する

#### Scenario: 略語の表記差を欠落と誤認しない
- **WHEN** U.S.と米国を含む対応Groupを決定的検査する
- **THEN** Systemはその表記差だけによる保護文字列欠落Findingを作らない

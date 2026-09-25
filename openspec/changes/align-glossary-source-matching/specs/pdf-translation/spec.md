<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 用語集の原語の適用範囲を一貫させる
Systemは、用語選択と翻訳結果の決定的検査で、原語の大小文字と連続空白を正規化し、英数字で始まるまたは終わる用語の該当端を別の単語や識別子の内部へ一致させてはならない（MUST NOT）。適用対象となる原語の指定訳がない場合は既存の用語集Findingを保持しなければならない（MUST）。本文・Caption・表セルおよび両翻訳Backendで同じ判定を行わなければならない（MUST）。Q-FUNC/Q-RELとして、以下の合成Scenarioを全成功させ、専用の意味判定要求を追加せず、他の品質検査を弱めてはならない（MUST NOT）。

#### Scenario: 別の単語の一部に誤一致しない
- **WHEN** 原文にCapitalがあり、用語集にAPIの指定訳があるが、独立したAPIはない
- **THEN** SystemはAPIの指定訳欠落を指摘せず、Capital自体の翻訳は他の既存検査の対象として維持する

#### Scenario: 実際の用語の指定訳欠落を検出する
- **WHEN** 原文にAPI、apiまたは括弧付きの(API)があり、訳文に指定訳がない
- **THEN** Systemは対象IDと原語の根拠を持つ用語集Findingを生成する

#### Scenario: 複数語の空白の違いを扱う
- **WHEN** 用語集の原語の単語間空白が本文で改行や連続空白になっている
- **THEN** Systemは同じ原語として適用し、指定訳の有無を検査する

#### Scenario: 指定訳を既に使用している
- **WHEN** 適用対象の原語とその指定訳が原文と訳文にある
- **THEN** Systemはその用語の指定訳欠落を指摘しない

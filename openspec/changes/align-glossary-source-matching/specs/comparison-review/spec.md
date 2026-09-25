<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 比較時の用語集検査で単語内の誤一致を避ける
Systemは、比較対象の本文・Caption・表セルについて、翻訳時と同じ原語の大小文字・連続空白・単語境界の判定を用いなければならない（MUST）。原語が別の単語や識別子の内部にあるだけで指定訳欠落を作ってはならない（MUST NOT）。実際の原語の指定訳欠落は対象と根拠付きでreportへ保持し、入力PDFを変更してはならない（MUST NOT）。Q-FUNC/Q-USEとして、以下の合成Scenarioで誤一致0件、真の指定訳欠落のreport保持率100%を満たさなければならない（MUST）。

#### Scenario: CapitalをAPIと誤認しない
- **WHEN** 対応する原文にCapitalがあり、独立したAPIはなく、用語集にAPIがある
- **THEN** SystemはAPIの指定訳欠落を決定的検査のreportへ追加しない

#### Scenario: 原語の正規化と指定訳欠落を扱う
- **WHEN** 原語が大小文字や単語間空白の違いを含んで実際に存在し、対応訳文に指定訳がない
- **THEN** Systemは用語集Findingの対象・根拠をreportへ保持し、両入力を変更しない

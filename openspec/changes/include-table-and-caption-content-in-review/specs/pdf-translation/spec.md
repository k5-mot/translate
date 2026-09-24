<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 翻訳結果を検査してから公開する
Systemは、決定的検査と意味Reviewを行い、指摘がある翻訳単位だけに修正候補を生成し、検証に合格した候補だけを採用しなければならない（SHALL）。修正または検証が失敗した単位は修正前訳へ戻し、警告として記録しなければならない（MUST）。検査と候補検証は本文、Captionおよび各Table cellを対象とし、対象を識別できるIDを保持しなければならない（MUST）。空になった訳を原文で補って欠落を隠してはならない（MUST NOT）。Q-FUNCとして、本文・Caption・cellのfixtureで対象漏れと重複を0件とし、別cellに同じ数値が残る場合でも対象cellの数値欠落を検出しなければならない（MUST）。

#### Scenario: 修正候補を採用する
- **WHEN** 修正候補が指摘を解消し、新しい欠落、追加または誤訳を生じない
- **THEN** Systemは候補を最終採用訳として使用する

#### Scenario: 修正または検証に失敗する
- **WHEN** 修正生成または検証が対象単位で失敗する
- **THEN** Systemは修正前訳を保持し、対象IDと理由を警告へ記録して残りの文書処理を継続する

#### Scenario: セル内の数値が欠落する
- **WHEN** 一つのTable cellで数値が欠落し、別cellには同じ数値が残っている
- **THEN** Systemは対象cellの欠落を検出し、対象ID付きFindingをReviewへ渡す

#### Scenario: Captionまたはcellの訳が空になる
- **WHEN** 原文があるCaptionまたはcellの訳が空になる
- **THEN** Systemは空訳を原文で置き換えず、欠落を検査・意味Reviewへ渡す

#### Scenario: Captionまたはcellの修正候補を検証する
- **WHEN** Captionまたはcellの修正候補が生成される
- **THEN** Systemはその原文・初回訳・候補を検証し、不合格の場合は初回訳へ戻す

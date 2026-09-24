<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## MODIFIED Requirements

### Requirement: 文書要素を多対多で対応付ける
Systemは、見出し、番号、URL、固有名詞、順序および前後関係を用いて、1対1、1対多および多対1の対応を表現しなければならない（SHALL）。未対応要素は原文側または訳文側の未対応として保持し、全対象IDを重複なく一度だけ扱わなければならない（MUST）。本文がないTableまたはFigureであっても、文字を持つcellおよびCaptionを対象から除外せず、対応Groupから決定的検査と意味Reviewへ内容を引き渡さなければならない（MUST）。

#### Scenario: 一段落が複数段落に翻訳されている
- **WHEN** 一つの英語段落が複数の日本語段落に分割されている
- **THEN** Systemは1対多の対応Groupを生成する

#### Scenario: 対応する要素が存在しない
- **WHEN** 原文または訳文の要素に対応先が存在しない
- **THEN** Systemは対象を欠落候補としてreportへ明示する

#### Scenario: 表またはCaptionだけの文書を比較する
- **WHEN** 比較文書が本文段落を持たずTable cellまたはCaptionだけに文字を持つ
- **THEN** Systemは対象のIDと内容を対応付け、対象0件として検査を省略しない

#### Scenario: 表セルが片側だけに存在する
- **WHEN** 原文側または訳文側に対応先のない文字を持つcellがある
- **THEN** Systemはそのcellを未対応として保持し、欠落または追加の候補をreportへ渡す

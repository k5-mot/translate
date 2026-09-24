<!-- markdownlint-disable MD041 -->

## Context

proposal.mdのWhyを参照。既存CODING_RULESは最小実装とPackage再利用を要求するが、全関数の説明範囲とcheckpointの正本は明示していない。監査の具体例は[追加監査](../restore-docx-tables-and-indexes/coding-rules-audit.md)にある。

## Goals / Non-Goals

規約の解釈を、関数説明、依存機能の契約比較、再開状態の正本に絞って明確化する。既存コードの全是正、未承認directory配置、旧Run移行の決定は本Changeでは行わない。

## Decisions

1. 関数の説明はPythonではdocstringを基本とするが、利用者要求の「コメント」を勝手に一律docstring必須へ狭めず、定義に対応する説明コメントも認める。特殊method・入れ子・Testを除外しない。lambdaは周囲の説明と可読性で点検し、説明のためだけのwrapperを増やさない。
2. 機能名の一致だけで置換を決めない。導入済みversionのAPIと、入出力・例外・retry単位・永続化・副作用を比較する。同等なら再利用し、契約差があるなら差の根拠を記録する。新しい汎用adapter/frameworkを増やさない。
3. Task順序・分岐・再開位置・完了履歴をGraph側の正本へ一元化する。表示はそこから導出する。Task内部のpage/chunk再開も独立記録で再実装しない。外部副作用の冪等性確認、入力互換性判定、Artifact入出力はこの規則と区別する。
4. commonのlogger/settings以外の既存追加を追認しない。新設moduleは利用元と既存実装/依存で足りない理由を説明し、今回の規約整備を配置承認に流用しない。

## Quality Attribute Design

Q-MNT: 対象範囲と確認手順を明記し、規則を他文書へ重複追加しない。Q-REL: 再開正本を増やさず、既存違反の修正には障害/Resume Testを必須とする。文書検査・既存documentation Testと要求対応表で検証する。

## Lifecycle, Migration and Operations

製品の起動方法、データ、依存を変更しない。既存監査は未解決として維持する。正式verifyの実行条件はtranslation→Word PDF化→reviewとし、製品codeが変わらない文書変更でも勝手に省略しない。

## Risks / Trade-offs

- [Risk] コメントが存在するだけで適合とする → 目的、制約、副作用の説明を実装と照合する。
- [Risk] Packageへ機械的置換してretry範囲や失敗時の保存契約が変わる → 契約差と回帰Testを要求する。
- [Risk] 規約整備を全違反の解消と取り違える → 本Changeの完了と監査是正の完了を区別する。

## Migration Plan

既存規則を補足・更新し、重複した規範文を作らない。文書差分は通常のrevertで戻せるが、利用者が明示した禁止事項を実装から免除するものではない。

## Why

全件監査で`ty check`が23 diagnosticsを報告した。STRUCTUREの引数転送が具体型を失い、診断Evidenceのgenerator/失敗記録/許可値の型が実際の契約と不一致なため、既存の振る舞いを保持して型検査を回復する。

## What Changes

- STRUCTUREの逐次再送境界で、既存adapterと同じ具体的な引数型・応答型を保持する。
- Evidenceのcontextmanager戻り型、FailureRecord入力、検証済みLiteral値の返却型を修正する。
- 引数転送、逐次再送回数、counterのcontext復元、失敗診断の安全な値を回帰検証する。
- 型ignoreやAnyで検査を迂回せず、既存の未commit機能差分をこの変更のcommitへ混ぜない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。振る舞いを変えない内部型契約の修復であり、`skip_specs: true`とする。新Capabilityや検査を通すためだけのRequirementは追加しない。

## Impact

`translate/tasks/structure.py`、`translate/common/terminal_evidence.py`と関連Test。依存追加、Run保存形式、モデル設定、retry方針、commonの配置、Taskのclass化は変更しない。ARCH-001/ARCH-002と結合表方針は利用者の判断待ちを維持する。

## Stakeholders and Lifecycle Impact

保守者が型検査を利用できるようにする。取得・供給は新規依存/サービスがないため変更なし。移行・運用は既存Runをそのまま使用し、廃止対象の公開APIや成果物はない。ロールバックは当該コード差分のrevertで可能。

## Quality Considerations

- Q-MNT: 全体ty diagnosticsを23から0へ。全体`uv run ty check`で測定。
- Q-FUNC/Q-REL: 引数/返却値/例外/逐次再送回数をTestで固定し、型変更が実行意味を変えないことを確認。
- Q-SEC: 許可値以外を診断に通さず、本文を保存しない既存Testを維持。
- 性能・互換性: 追加外部callや依存、並列処理なし。公開操作/保存形式を不変にする。
- 操作性・柔軟性・安全性: UI・deployment・危険操作に変更なし。実LLMを用いた品質受入、DOCX目視、排他競合修正は本Changeの型修正で解決した扱いにしない。

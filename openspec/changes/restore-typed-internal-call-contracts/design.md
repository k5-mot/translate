## Context

proposal.mdのWhyを参照。現在のSTRUCTURE再送関数はadapter呼出をobject可変引数で包み、型を失っている。Evidenceの呼出元はPublicRunErrorのfailure（FailureRecord）を渡しており、PublicRunError自体を渡す製品経路はない。

## Goals / Non-Goals

**Goals:** 型宣言を実際の入力・出力へ対応させ、既存の呼出回数と診断安全性を維持する。

**Non-Goals:** common移動、Task基底class、再送条件変更、Run排他、表修正、未commitのcontext-exceeded機能の取込み。これらの未解決事項を閉じない。

## Decisions

1. STRUCTUREはSettings/model/StructureResponse型/system/userとkeyword-onlyのreasoning/schema_mode/thinking/imageを明示する。同じcallを一度だけ再送するため、標準functools.partialで型付きadapter呼出を束縛する。汎用object引数やAnyへ戻さない。新wrapper classは不要。
2. bind_call_countsはIterator[Mapping[str, int]]をyieldするcontextmanagerとして宣言する。counterの値やcontext復元は変更しない。
3. evidence_from_failureの入力を既存FailureRecord型にする。importはTYPE_CHECKING内に置き、新しいruntime循環を作らない。docstringも実際の呼出契約へ合わせる。
4. phase/stageは既存Literalの許可値照合を維持し、その検証が成功した分岐だけtyping.castで具体型を返す。検証なしのcast/ignoreは採用しない。
5. grill-with-docsの判断木では、型検査を通すこと・逐次実行・既存振る舞い維持は利用者の既定要求で確定済み。新たな製品仕様・配置・継承の判断は行わない。用語の変更がないためCONTEXT.md/ADRは追加しない。

## Quality Attribute Design

Q-MNTは全体tyと対象Ruff/format、Q-FUNC/Q-RELは引数転送・成功/接続断/再送失敗の回帰Test、Q-SECは許可値/未知値とcounter復元のTestで検証する。モデル呼出はfakeに置換し逐次で行う。

## Lifecycle, Migration and Operations

保存形式と公開entry pointは不変。既存Runの書換えやLLM再実行は不要。型修正だけをstageし、既存の未commitのFailureKind差分を保持する。検証失敗は失敗として記録する。

## Risks / Trade-offs

- [Risk] 型修正が実際の呼出引数を変える → 全引数と同一返却object、再送回数を検査。
- [Risk] Literal castが値の安全性を隠す → membership成功後だけcastし、未知値はNoneを維持。
- [Risk] 全体suiteの既存detached flake → 初回失敗を記録し、再実行成功だけで既知問題を解決済みにしない。

## Migration Plan

Test追加、型修正、対象/全体検査、verifyを順に行う。問題時はこのChangeの差分だけrevertする。型修正に伴うデータ移行はない。

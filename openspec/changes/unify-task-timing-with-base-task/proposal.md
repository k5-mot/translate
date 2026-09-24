<!-- markdownlint-disable MD013 MD041 -->

## Why

ARCH-002で指摘された20 Taskの計測重複と、成果物公開前に計測を終える不統一を解消する。利用者が承認した関数入口とBaseTask/各Taskクラスの併用を実装し、固有処理の型とLangGraphの実行管理を維持する。

## What Changes

- Taskごとの既存run関数と型付き引数を維持し、同じModule内の具体Taskクラスへ委譲する。
- tasks/base.pyのBaseTaskで経過時間の計測だけを共通化し、各Taskクラスから利用する。
- 計測対象をTaskの公開境界全体へ揃え、成功・失敗時とも計測できるようにする。経過時間は完了状態ではない。
- 継承、引数転送、計測回数、失敗伝播、atomic公開境界を自動Testする。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。Task内部のRefactorであり、入力・成果物・再開・障害処理の公開契約は変更しない。skip_specsを指定する。Task計測の製品要求はclarify-code-documentation-and-reuse-rulesのrun-lifecycle deltaで追跡し、重複Requirementを作らない。

## Impact

translate/tasksの20 Module、追加するbase.py、tests/test_timing_contract.py。新Package、入力DTO、Registry、汎用実行Frameworkは追加しない。Workflow、checkpoint、Modelの逐次実行は維持する。既存のTask内Page/Chunk再開機構の是正やcommon移管は、この計測共通化で解決済みにしない。

## Stakeholders and Lifecycle Impact

保守者は各Taskの固有処理と共通計測を区別でき、運用者のCLI/UI操作は変わらない。取得・供給は新依存なし、移行は既存関数入口により呼出元とデータ変更なし。廃止対象は20か所の手書き計測コードのみで、既存成果物を削除しない。

## Quality Considerations

Q-MNT: 20/20 TaskがBaseTaskを継承し、20/20関数入口が具体型を維持して委譲する。Q-REL: 各呼出し1回の計測、元例外の伝播、Task公開完了後の計測終了をTestする。Q-COMP: 既存回帰Testと型検査が合格する。性能の新目標、UI機能、安全性の新機能は対象外。Q-SEC: 新たな本文・Credential出力を追加せず、時間と固定Task名だけを通知する。正式verifyでは利用者指定の実translation→Word PDF→reviewを順に実施する。

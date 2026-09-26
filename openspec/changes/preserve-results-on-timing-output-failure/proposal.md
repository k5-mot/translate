<!-- markdownlint-disable MD013 MD041 -->

## Why

[TASK-TIMING-001](../unify-task-timing-with-base-task/verification.md)では、TaskとCLI/UIのfinally内の計測表示が失敗すると、成功結果または元例外を置き換えることを確認した。利用者が承認した「表示だけを諦め、本体結果を維持する」方針を明文化し、保存障害との区別を実装する。

## What Changes

- Taskと公開入口のTIME出力の同期的なstream障害で、本体の成功・失敗を変更しない。
- 通常の出力形式・出力先は維持する。表示失敗時の再出力や新たな保存先は追加しない。
- 成果物・Checkpoint保存失敗は抑制せず、計測情報を完了状態や再開位置に使用しない。
- BrokenPipe、閉じたstream、通常I/O障害を注入し、戻り値・元例外・公開入口の終了状態を検証する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: 計測表示障害と本処理結果を分離する要件を追加する。既存の計測可能性要件とは別の障害境界であり、skip_specsは指定しない。

## Impact

translate/tasks/base.py、cli.py、main.py、既存tests/test_timing_contract.py。新しいModule、依存、設定、再開状態は追加しない。既存loggerへの出力先変更、一般のCLI出力エラー処理、翻訳品質修正は含めない。

## Stakeholders and Lifecycle Impact

運用者は計測表示の故障で本体が失敗扱いになることを避けられる。保守者は計測表示と必須保存を区別する。取得・供給は既存依存だけで変更なし、移行はデータ形式・既存Run変更なし、廃止は例外を上書きする計測出力経路のみでデータ削除なし。

## Quality Considerations

Q-REL/Q-FUNC: 成功・失敗と3出力境界を障害注入で検査し、結果の置換を0件にする。Q-COMP/Q-MNT: 関数/class入口と既存形式を保ち、新しい共通層を0件にする。Q-SEC: 失敗本文・Credentialを計測表示へ追加しない。操作性は新UIを追加せず、性能効率は再試行・外部通信を追加しないことで維持する。可搬性は標準Pythonで検査する。安全性の新たな制御対象はなく、本処理と保存の例外を抑制しないことを検証する。正式verifyではreasoning OFFの実translation→Word PDF→reviewと利用者の目視結果を別々に記録する。

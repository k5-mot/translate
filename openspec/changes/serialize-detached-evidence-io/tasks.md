## 1. 排他と安全な読取り

- [ ] 1.1 読取りが無排他であることを決定的Testで再現し、portalockerによる単一lock下のread/writeへ修正する。取得回数、有限待機、例外時解放をTestする。
- [ ] 1.2 heartbeatを同じEvidenceStore経由へ変更し、未使用helperを削除する。不正JSON/schemaを成功にしないことと、古いrunning通知からterminalを保護することをTestする。

## 2. 統合検証と移行確認

- [ ] 2.1 モデルを呼ばない実親子processで高頻度のEvidence/heartbeat I/Oを反復検証し、完了結果とexit 0を保持することを確認する。
- [ ] 2.2 対象Ruff/format、全体ty/pytest、OpenSpec strictを実行してverification.mdへ記録する。旧schema/Run/未commit差分を保持し、監査の該当項目だけ更新する。

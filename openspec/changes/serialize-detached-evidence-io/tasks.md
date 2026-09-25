## 1. 排他と安全な読取り

- [x] 1.1 読取りが無排他であることを決定的Testで再現し、portalockerによる単一lock下のread/writeへ修正する。取得回数、有限待機、例外時解放をTestする。
- [x] 1.2 heartbeatを同じEvidenceStore経由へ変更し、未使用helperを削除する。不正JSON/schemaを成功にしないことと、古いrunning通知からterminalを保護することをTestする。
- [x] 1.3 constructorのパス解決とreadの存在確認を既存排他内へ含め、実heartbeat読取り経路でlock境界を決定的Testする。未作成EvidenceのTestを所有temp領域へ限定し、正規化・temp root外判定・解決失敗時のlock解放を維持する。

## 2. 統合検証と移行確認

- [ ] 2.1 モデルを呼ばない実親子processで高頻度のEvidence/heartbeat I/Oを反復検証し、完了結果とexit 0を保持することを確認する。
- [ ] 2.2 対象Ruff/format、全体ty/pytest、OpenSpec strictを実行してverification.mdへ記録する。旧schema/Run/未commit差分を保持し、監査の該当項目だけ更新する。

# Verification: serialize-detached-evidence-io

## 中間判定（2026-09-25）

**検証失敗・未完了。archive不可。** 利用者の設計確認への回答を優先するため、製品修正は途中状態で保持する。

- 修正前の追加Testで無排他read、不正JSON処理漏れ、既存library非利用の3件を再現（3 failed/2 passed）。
- 修正後の対象Testは25 passed。Ruff/format/全体tyとOpenSpec strictは成功。
- 高頻度I/O・終端回収・公開convertの3 Testを10回反復し、command exit 0を確認。
- ただし全体pytestは**286 passed / 1 failed / 1 skipped**。高頻度I/O Testの親watchdogがEvidenceStore.write → atomic_write_json → Path.replaceでWinError 5を再現した。読書きを同じlockへ寄せただけでは十分と証明できない。
- この実行では全体suiteと反復Testは別temp pathで同時に動いていた。外部LLM/Embeddingはどちらも呼ばない。異なるtemp pathなので同一ファイルの競合とは断定できず、負荷条件の影響も含め追加切分けが必要。
- parent/child以外のhandle、lock前のpath存在確認/解決などは原因候補であり、未確定。任意のPermissionErrorを無視して通す修正は行っていない。
- 反復commandのhandleは終了（exit 0）。対象python processが残っていないことも確認。中断を理由にRunを再起動していない。
- Tasks 1.1/1.2の機能Testは成功したが、統合・全体品質の2.1/2.2は未完了のまま。型修復済みChangeと他の既存未commit差分は保持する。

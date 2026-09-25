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

## 再検証（2026-09-25 10:21 JST）

Using change: `serialize-detached-evidence-io`。OpenSpec rootは当Repository、schemaはmysdd、skip_specs=true。proposal/design/tasksと現在の実装を照合した。製品Code、Test、既存Run、設定は変更していない。

### 対象と実装対応

- `terminal_evidence.py:28`は既存portalockerへ10秒の取得期限を委譲する。`EvidenceStore.write/read`は同じFile別lockを使用し、取得済みwriteからは`_read_locked`を呼んで再入取得を避ける。
- `_read_locked`はJSON/schema不正をNoneへ変換する一方、PermissionErrorを成功・欠落へ変換しない。古いrunning更新からterminalを保護する判定も同じlock内にある。
- `_read_heartbeat`とchildのheartbeat保存はEvidenceStoreへ委譲する。旧OS別lockと未使用helperは除去済みだが、これらの実装差分は未commitのままである。
- 既存の決定的Testは読書き時のlock深さ・取得回数、有限取得設定、不正JSON/schema、例外時解放、旧版保持、終端保護、権限障害の伝播を検査している。実親子Testと組み合わせて確認した。

### 実行結果

- 実行前にCIMで対象CLI/診断child/pytestの既存processがないことを確認した。
- `uv run pytest tests/test_terminal_evidence.py -q`: **25 passed、6.56秒**。
- 高頻度Evidence/heartbeat I/O、stdoutなし終端回収、公開convertへの委譲の3 Testを、別々のpytest起動で**20回逐次反復、60/60成功**。session 38204はexit 0。各高頻度Testはchildが100回両JSONを更新し、親は1ms間隔で監視する。exit 0、completed、100/100、保存終端の再読取りを確認した。LLM/Embeddingは呼ばない。
- 反復終了後に全体Testを実行し、負荷条件を混在させなかった。`uv run pytest -q`: **656 passed / 1 skipped、42.21秒**、session 40722はexit 0。PYTHONUTF8などの追加環境指定は行っていない。
- 対象2 filesのRuff check/format、全体ty、OpenSpec strictは成功。既存configの未知operation `verify`警告は今回の対象外で、変更していない。
- 検証対象はHEAD `5946b6e`に既存未commit差分を含むworktreeであり、commit単独の検証ではない。terminal_evidence.pyのSHA-256は`881339c47e68857e782f21b4d7c2e2609c65ab4e6458584c3a5e6c1cd565b6f8`、同Testは`a9f297005d194123513e13b8ced47792a64f5849728b91300346ae3d516e1e2f`。無関係なFailureKind拡張を含む既存差分を今回のcommitへ取り込まない。

### Verification Report

| Dimension | 判定 |
| --- | --- |
| Completeness | tasksは2/4。2.1の反復・2.2の品質commandについて新しい成功証拠を取得したが、既知競合の最終受入は未完了 |
| Correctness | 排他境界・安全な失敗・終端保持のTestは成功。過去の修正後WinError 5は今回非再現であり、原因除去は未証明 |
| Coherence | 既存library利用、有限待機、二重lock回避、新依存なし。公開仕様のDeltaはないためScenario照合はproposal/designと既存Testを対象とした |

**CRITICAL:** 過去に同じ排他修正後の全体Testで起きたPath.replaceのWinError 5について、原因とそれを防ぐ回帰証拠が未確定。今回の反復成功で過去失敗を取り消さない。Tasks 2.1/2.2の最終判定とarchiveは保留する。次は失敗時の操作・対象File・handle所有を観測して切り分ける。`EvidenceStore.__init__`のpath.resolveとreadの存在確認はlock外だが、それらが原因だとはまだ断定しない。任意のPermissionErrorを無視する修正は認めない。

**WARNING:** 実translation→Microsoft Word PDF→Comparison Reviewは未実施。最新OFF翻訳が保護記号欠落で停止している別問題を本Testで代替しない。今回の変更は検証記録だけで、common配置・再開の二重管理・利用者判断待ちも解決済みにしない。

**最終判定: 自動検査は成功、Changeの正式verifyは未合格。archive/main merge/push不可。** 元の監査指摘には本節を参照し、既存の未完了Checkboxは維持する。

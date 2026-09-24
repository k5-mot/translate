<!-- markdownlint-disable MD013 MD041 -->

# 実装時検証: protect-active-run-from-rejected-execution

## 判定

2026-09-25、4/5 Task完了。実装・自動検証は成功したが、新Codeでの実translation→Word PDF→review・利用者目視・正式verifyが未完了のためarchive不可。RUN-001全体の最終解決は保留する。

## Completeness

execute_runの既存OutputLockを最外周へ移し、最新metadata読込み、開始保存、log設定、Task通知、成功/失敗保存、log解除を保持範囲へ入れた。workspace.pyの既存portalocker取得失敗をOutputInUseErrorへ分類し、公開境界では所有者の古いfailure.jsonを誤採用せず、一時的な拒否情報だけを返す。新しいModule、保存状態、lock実装、Dependencyは追加していない。

## Correctness

tests/test_execution_exclusion.pyで実portalockerを使用した。外部Serviceは呼んでいない。

| 条件 | 証拠 |
| --- | --- |
| translate/review/register/convert、旧failureなし/あり | 8条件。修正前は全条件でmetadata/failureのbyte比較失敗、修正後は成功 |
| 拒否時の副作用 | metadata/log/checkpoint/output/failureがbyte単位で不変、log設定と製品操作の呼出0件 |
| 公開拒否 | 旧failureを転用せずOutputInUseError、今回の操作を表示し、内部pathを非出力 |
| 成功/失敗の全保存境界 | 4操作×2条件。状態保存、failure公開/削除、log設定/解除で実lockの再取得を拒否 |
| 終端保存中の別呼出 | 成功/失敗保存直前の公開再入を拒否し、所有者の結果はそれぞれcompleted/failed |
| 最新metadata | PreparedRun取得後に追加されたwarningを保持し、Task通知を保存 |
| 解放後Resume | 実prepare_runで互換性検証、同一IDのResumeを受理し成功保存 |

- 追加17 Test: passed（2.29秒）。
- 全体pytest: 383 passed、1 skipped（26.77秒）。skipは成功と数えない。
- 対象3 Python filesのRuff checkとFormat check、全体ty: 成功。
- OpenSpec strict validation、git diff --check: 成功。
- 初回Test fixtureはWindowsのlockfileまで読もうとしてPermissionErrorになった。これは製品再現とは数えず、排他file以外の保存対象をbyte比較するよう修正した後、製品不具合の8失敗を確認した。
- 全体Testは既存未commit差分を含むworktreeで実施。本Changeのstageへcontext-exceeded等の別差分を含めない。

## Coherence

導入済みportalockerをそのまま使用し、拒否側の新しいretry・queue・Task完了台帳は作らない。既存RuntimeErrorのsubclassで呼出互換性を維持する。Testの複数spyは同一所有者の副作用順を検証するためであり、製品の新しい抽象層ではない。

## 未完了事項

- CRITICAL: Task 2.2。新Codeの実translation→Word PDF→review、利用者目視と正式verify。
- 実翻訳session 40709は修正前Codeを読込んだProcessとして継続中。2026-09-25 02:37 JSTまでにpage-0010-chunk-0001の検索Artifact更新を確認。これを本修正の証明には流用しない。
- Run削除がlock確認後に解放してからrmtreeする競合は別途是正する。今回削除操作は変更していない。
- 通常実行失敗の公開wrapperによるfailure再読込み、common責務移管、LangGraph以外の二重状態は引き続き整理対象。今回の局所的な保存境界修正を現行Architectureの承認とはしない。

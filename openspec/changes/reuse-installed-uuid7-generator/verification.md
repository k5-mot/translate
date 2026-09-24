<!-- markdownlint-disable MD013 MD041 -->

## Apply時の検証（2026-09-25）

4/5 tasks完了。正式verify・archiveは実translation→Word PDF→review待ち。

| 観点 | 証拠・判定 |
| --- | --- |
| 導入済みAPI再利用 | Run作成元でuuid_utils.compat.uuid7を直接使用し、identifiers.pyと独自bit生成を廃止 |
| 依存 | offline lock更新前後の全117 Packageのname/version集合が完全一致。差分はrootの明示依存2行のみ |
| UUID契約 | 標準UUID型、version7、RFC variant、canonical表現、明示時刻のmillisecond保持、同時刻2,000件の衝突0を確認 |
| Run作成時刻 | 実際のrepository.createの前後時刻内にUUID時刻があることを確認。許容幅は追加していない |
| 残存 | translate/testsのcommon.identifiers importと独自def uuid7は0件 |
| データ | 既存Runの移動/変換/削除なし。廃止した生成器ソースはGit履歴で復元可能 |

## 検査と失敗履歴

- 置換直後の関連39 Testは成功したが、最初の全体suiteは336 passed / 1 failed / 1 skipped。失敗はUUID時刻の範囲Test。
- 無引数uuid7ではPython取得時刻より1ms先になる現象を単独生成10batchでも再現した。Package内部とPython時計の差の発生機序までは断定しない。
- installed 0.17.1のAPI、同versionの公式source、実行結果を確認し、Run作成元で取得したUnix時刻をtimestamp/nanosへ渡す設計へ修正。独自bit操作は復活させず、Testの時間許容幅も広げていない。
- 修正後の全体`uv run pytest -q`: **337 passed, 1 skipped（26.58秒）**。
- repository suiteの独立Processでの5回反復: 終了コードすべて0。
- 対象3fileのRuff lint/format、全体`uv run ty check`、git diff --check、OpenSpec strict: 合格。
- Testは既存の未commit修正を含むworktreeで実行。terminal-evidenceの既存I/O修正は本Changeへ混入させず、import差分だけをstageする。

## 未完了

- CRITICAL: task 2.2。実行中のclass化/UUID置換前Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`は、新生成器のE2E証拠ではない。新実装の実translation→Word PDF→reviewが必要。
- commonの残りの整理、二重Resume、Package再利用の他候補、全関数説明、診断I/O等の既存指摘は解決扱いにしない。

## References

- [uuid-utils 0.17.1生成API](https://github.com/aminalaee/uuid-utils/blob/0.17.1/src/lib.rs)

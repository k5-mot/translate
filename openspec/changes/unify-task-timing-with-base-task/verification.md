<!-- markdownlint-disable MD013 MD041 -->

## Apply時の検証（2026-09-25）

正式verifyは未完了。4/6 tasks完了。実translation→Word PDF→reviewと利用者の目視確認が残るためarchive不可。

| 観点 | 証拠・判定 |
| --- | --- |
| 具体Taskと関数入口 | 20 ModuleすべてにBaseTask継承class、元signatureのrun関数を実装。40caseで明示引数/既定値、戻り値identityと型signatureの一致を確認 |
| 共通計測 | base.pyのmeasureに集約。成功・失敗それぞれ1回の固定形式出力と元例外identityを確認。例外本文は時間出力に含めない |
| 公開境界 | MERGE/STRUCTURE/MARKDOWNの3caseで、開始時未公開・終了時公開済みであることを実atomic_directoryで確認 |
| 再開状態の追加なし | BaseTaskはcontextlib/time/型のみを参照し、Workflow/Artifact/checkpoint/進捗管理への依存を持たない。Task名以外のinstance状態を追加していない |
| 既存データと操作 | 関数入口を維持し、入力copy、保存layout、成果物形式、公開操作を変更していない |

## 自動検査

- `uv run pytest -q tests/test_timing_contract.py`: 47 passed。
- `uv run ruff check translate/tasks tests/test_timing_contract.py`: 合格。
- `uv run ruff format --check translate/tasks tests/test_timing_contract.py`: 23 files合格。
- `uv run ty check`: 合格。
- `uv run pytest -q`: 337 passed, 1 skipped（27.65秒）。ローカルモデルの追加要求は行っていない。
- OpenSpec strict validation、git diff --check、git diff --cached --check: 合格。
- 全体suiteは既存の未commit修正を含むworktreeで実行した。REVIEWの既存のcontext/latency修正は本Changeのcommitへ混入させず、class化/計測だけをstageする。

## 残課題

- CRITICAL: 2.2。class化前から実行中のsample3翻訳Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`を、class化後の実行証拠に流用しない。完了後に新実装の実translation→Word PDF→reviewを逐次実行する必要がある。
- CRITICAL: 2.3。利用者によるWord/PDF目視は未完了。
- [既存監査](../restore-docx-tables-and-indexes/verification.md)のcommon配置、独立Page/Chunk再開、全関数説明、導入済みAPI重複、表セル検証、Run排他は未解決。本Changeで相殺しない。
- 診断I/Oの間欠失敗も、今回の全体suite成功のみでは解決と扱わない。

## 判定

承認済みの関数/class併用を実装し、計測の回帰検証は成功。正式verify・archive・main merge/pushは未実施。

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

## Verify再確認（2026-09-26）

先行節はApply時点の記録として保持する。今回はCode/Ruleを変更せず、完了済み実検証のArtifact、metadata、履歴と現行実装を読取り確認した。別の新規翻訳Runが稼働中のため追加の実Model要求は行っていない。

| 観点 | 現在の判定 |
| --- | --- |
| Completeness | 5/6 tasks。2.2の実行順・成果物証拠を確認し完了へ更新。2.3の利用者目視は未完了 |
| Correctness | delta specなし（skip_specs）。20 concrete Task/関数入口、計測1か所、公開後計測の既存47 Testを確認。標準出力故障時の元例外保持には不足あり |
| Coherence | BaseTaskは計測のみで、保存・進捗・再開状態を追加しない。通常時の関数/class併用は設計どおり。例外保持の設計との差は下記WARNING |

### Task 2.2の実成果物証拠

- class化commit 1497910は2026-09-25 02:09:30 JST。後続455808bはbase.pyの説明変更のみで計測処理は同一。前回実検証はこれらより後であり、class化前のRunを流用していない。
- 翻訳Run 01a0d8b6-c2ab-7c92-bed9-58403a8410b3は2026-09-25 13:17:31.195268〜13:56:57.912623 UTC、completed/DOCX。生成DOCXは3,656,615 bytes、SHA-256 78aeb3c5e50f8785e4a9b5dca1f64776355f9a96470ed090b357263764ca4d7d。
- DOCXをMicrosoft WordでPDF出力した操作の詳細は[共通実検証記録](../simplify-translation-literal-checks/verification.md)を参照。今回PDFそのものからCreator/Producer=Microsoft Word 2024、作成時刻2026-09-25 23:00:14 JST、28ページを再確認。SHA-256は57a19cc835e8cb637f9ac027b3b6f27458a1f21c191c213ade4f1950309ac21a。翻訳完了後、比較開始前の出力である。
- 比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2は2026-09-25 14:03:03.534312〜14:25:51.765485 UTC、completed/REPORT。Run内のtranslation_ja入力コピーをhashし上記Word PDFと一致、source_enは原本sample3のSHA-256 5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34fと一致した。
- 公開review.mdは194,084 bytes、SHA-256 0f7ca98be7ee70ea00736f8dee8f3f1f10b3eb0a27ff90e65b879e391830eb19。三つの実操作の順序と保持された成果物を確認した。ALIGN誤対応・表表示・旧診断counter不整合を解消した証拠ではない。

### CRITICAL: Task 2.3の目視受入未完了

Word/PDFは利用者へ提示済みだが、目視結果の返答を未取得。common整理・LangGraphの独立再開状態の是正など他Changeの未解決事項も相殺しない。利用者確認と残る指摘の解消後に再verifyする。archive/merge/pushは不可。

### WARNING: TASK-TIMING-001 計測出力障害が元例外を置き換える

`translate/tasks/base.py:28`のfinally内printがBrokenPipeErrorを出すと、TaskがValueErrorで失敗していても伝播する例外はBrokenPipeErrorになる。外部通信なしの合成試験で、成功TaskでもBrokenPipeErrorへ変わること、失敗Taskでは元例外が__context__に残るだけで同一例外として伝播しないことを確認した。既存tests/test_timing_contract.pyの成功/失敗Testは「出力可能な環境」に限定され、この経路を含まない。

design.mdの「元例外を伝播する」との差であり、コメントの訂正だけでは解決しない。推奨対応は、計測の通知失敗で本処理結果/元例外を置き換えない最小の境界と、出力失敗を注入する回帰Testを別の修正計画で定義すること。今回Codeを変更せず、実行中のSTRUCTURE待機の原因とも同一視しない。

### 検査範囲と最終判定

最新の全体品質Gateは[計数修正の記録](../reuse-canonical-detached-child-module/verification.md)の732 passed / 1 skipped、Ruff/format/ty成功を参照する。本ターンではその全suiteを再実行したとはしない。今回のOpenSpec strictはvalid、git diff --check成功。Code/Test/設計照合、完了済み実ArtifactとWord metadataの再確認、出力故障の合成再現を実施した。

CRITICAL 1件、WARNING 1件のため正式検証は未合格。Task 2.2の完了を、当該Changeまたは翻訳品質全体の合格に読み替えない。

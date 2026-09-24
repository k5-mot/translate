# Verification: restore-typed-internal-call-contracts

## Apply evidence — 2026-09-25

- STRUCTUREの具体型付き署名と標準partialへの転送を実装。接続断時のみ最大一回再送する条件、例外object、返却objectを維持。
- Evidenceのgenerator戻り型、FailureRecord引数型、許可値照合後のLiteral型を修正。runtime import、保存schema、依存は追加していない。
- 新規Testは9件（STRUCTUREの4条件、counter復元1件、Literalの4条件）。関連Testは最終29 passed。
- 全体`uv run ty check`: **All checks passed**（監査時23 diagnosticsから0）。対象4ファイルのRuff lint/format、追跡Python全体のRuff lintも成功。
- 全体format: 271 files already formatted。全体pytest: **278 passed, 1 skipped / 25.71秒**、process exit 0確認。
- `ruff check .`は既存の未追跡`tests/manual_detached_historical_gate.py:64`のprint 1件で失敗。非commitの手動probeであり、このChangeでは勝手に削除/commitしない。全体作業環境の残課題として元監査に保持。
- 初回の関連Testでは28 passed/1 failed。`test_detached_watchdog_collects_completion_without_stdout`が`EvidenceStore.read → load_json → Path.read_text`でPermissionErrorになった。再実行では29 passed。初回失敗を隠さず、型修正で競合が解消されたとはしない。
- 検査は既存未commit差分を含むworktreeで実行。stageではterminal_evidenceの既存FailureKind拡張hunkを除外し、残差分が元のcontext-exceeded追加だけであることを確認。LLM/Review/Lifecycleの既存差分、.agents、PDF/DOCX、outputs、手動probeはこのcommitに含めない。
- モデル要求・既存Run変更・Word/PDF生成は行っていない。common配置、BaseTask採否、表構造、表の検査対象、Run排他、診断runner競合、利用者目視確認は未解決のまま。

## Verify

2026-09-25、実装commit `3ea187d`を対象に正式verifyを実施。**本Changeの型修復は検証成功。** Repository全体の受入成功や、親監査の全指摘解消を意味しない。

| 観点 | 証拠・判定 |
| --- | --- |
| Completeness | 4/4 tasks完了。型修復のみでskip_specsが妥当、新Requirementなし |
| Correctness | structure.pyの具体型/partial転送/接続断のみ1回再送、terminal_evidence.pyのIterator/FailureRecord/許可値検証後castを実装差分と照合。新規9件＋FailureRecordを使用する既存1件を再実行し10 passed |
| Coherence | 標準libraryのみ、runtime import循環追加なし、既存保存schema不変。既存FailureKind拡張はcommit外で保持 |
| Quality | 全体tyをverifyで再実行し0 diagnostics。OpenSpec strict validate成功。Ruff/formatと全体278 passed/1 skippedは同一実装の直前Apply証拠 |

型修復に対するCRITICAL/WARNINGは0件。既存のEvidence読取り競合と手動probeのLintは上記および親監査に未解決で記録済みであり、解決済みに移していない。型Change単体はarchive可能。main統合の品質ゲートは残課題の解消とPR/CI確認後に判定する。

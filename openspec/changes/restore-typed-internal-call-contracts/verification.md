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

正式verify未実施。ApplyのTest成功だけをarchive可の判定にしない。

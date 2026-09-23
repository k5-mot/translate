<!-- markdownlint-disable MD041 -->

## 1. Adapter and STRUCTURE fallback

- [x] 1.1 `translate/tasks/structure.py`へText `output-truncated`専用のprompt-mode fallbackを最大1回・逐次で実装し、通常のVision→Text fallback、最後の`StructurePageError`およびatomic cleanupを維持することをfocused testで確認する（Q-FUNC／Q-REL）。
- [x] 1.2 fallback成功時に完全なPydantic responseだけが`_apply`、page JSON、auditおよびcheckpointへ進み、partial response・raw本文・原文・画像binaryが公開されないことを`tests/test_structure_diagnostics.py`で確認する（Q-SEC／Q-COMP）。
- [x] 1.3 fallbackでも枯渇した場合に最終stage、`output-truncated`、`finish_reason=length`、token usageだけを保存し、既存のResume可能Failure契約を維持することをFailure/Lifecycle testで確認する。

## 2. Regression and lifecycle evidence

- [ ] 2.1 focused STRUCTURE／LLM／Lifecycle testとRuff、format、tyを実行し、同時Model requestが1件以下であることと既存契約の回帰0件を記録する。
- [ ] 2.2 `npx --yes --offline --package=@fission-ai/openspec@1.13.1 openspec validate recover-structure-output-budget --strict`を実行し、proposal・spec・design・tasksの整合を確認する。
- [ ] 2.3 実PDF detached Gateを同じRun IDで再実行し、STRUCTUREからTRANSLATEへ進むか、安全な終端Failureとstage／cause／token usageを`openspec/changes/recover-structure-output-budget/verification.md`へ記録する。source SQLite hash不変、temp cleanup、秘密・本文非出力を確認する。
- [ ] 2.4 Gateが成功した場合、同じRun IDを明示Resumeし、完了済みTaskを再実行せず未完了Taskから再開できること、成果物とsource SQLiteが不変であることを記録する。失敗した場合はResumeせず、次のChangeが必要な根拠を記録する（ISO/IEC/IEEE 12207運用・保守）。

## 3. Completion and archive

- [ ] 3.1 全pytestと関連静的検査を再実行し、実証Evidenceとともにtasksを全完了へ更新する。
- [ ] 3.2 変更差分をレビューし、`.agents`、ユーザー所有の未依頼変更、raw PDF、credentialおよび一時probeをcommit対象外にしたことを確認する（Q-SEC）。
- [ ] 3.3 全受入条件が満たされた後にのみChangeをarchiveし、Main SpecへDeltaが同期されたことをstrict validationで確認する。

<!-- markdownlint-disable MD041 -->

## 1. TRANSLATE fallback

- [x] 1.1 `translate/tasks/translate.py`へ`text-output`の`output-truncated`専用fallbackを最大1回・逐次で実装し、`reasoning="none"`および`thinking="disabled"`を指定して同じchunkを再送する
- [x] 1.2 fallback結果を既存のID一致・protected fragment検証へ通し、完全応答だけをmappingへ適用し、部分訳・raw response・原文を保存しないことをunit testで確認する
- [x] 1.3 fallback枯渇時にstage、cause、`output-truncated`、finish reasonおよびtoken usageだけを保持し、atomic cleanupとResume可能Failureを回帰testで確認する

## 2. Regression and lifecycle evidence

- [x] 2.1 TRANSLATE/LLM/Failure focused test、全pytest、Ruff、formatおよびty baselineを実行し、同時Model requestが1件以下であることを記録する（pytest 242 passed, 1 skipped、tyは既存terminal_evidence.pyの5件baseline）
- [x] 2.2 `npx --yes --offline --package=@fission-ai/openspec@1.13.1 openspec validate recover-translate-output-budget --strict`を実行する
- [ ] 2.3 構造fallback後に失敗した同じRun IDをdetached GateでResumeし、TRANSLATEが代替要求後に進行または安全に停止すること、source SQLite hash不変、temp cleanup、秘密・本文非出力を証跡化する
- [ ] 2.4 Gateが進行または完了した場合、同じRun IDを明示Resumeし、完了済みTask/chunkを再実行せず未完了単位から継続できることを記録する。再度失敗した場合は次のChangeの根拠を記録する

## 3. Completion and archive

- [ ] 3.1 全受入testと静的検査を再実行し、`verification.md`へ実証結果を記録する
- [ ] 3.2 差分をレビューし、`.agents`、AGENTS.md/config.yamlのユーザー変更、raw PDF、credentialおよび一時probeをcommit対象外にする
- [ ] 3.3 全受入条件を満たした後にのみarchiveし、Main SpecへのDelta同期とstrict validationを確認する

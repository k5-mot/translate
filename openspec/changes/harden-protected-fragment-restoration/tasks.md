<!-- markdownlint-disable MD041 -->

## 1. Placeholder復元契約

- [x] 1.1 分割翻訳のplaceholderをcanonical tokenへ正規化する処理を実装し、大小文字・区切り文字・空白の許容表記と未知tokenをunit testで検証する
- [x] 1.2 tokenの一対一対応を検査して原文fragmentを復元し、重複・合流・欠落を`ProtectedFragmentMissing`へ分類するunit testを追加する
- [x] 1.3 復元処理を既存のID検証・retryループへ接続し、保護値を無条件追記せず有限回で停止することをテストする
- [x] 1.4 CONTENT-PROTECTED-001を是正し、対応表が空の通常・分割Chunkでも未知markerを拒否する。正常な応答の表記を維持し、有限retry・公開拒否・既存Artifact保持を回帰Testで確認する

## 2. 診断安全性とRun連携

- [x] 2.1 復元失敗のFailureRecord/Evidenceがtask、page、target ID、stage、cause typeだけを保持し、URL・Path・生LLM応答を含まないことをテストする（Q-SEC）
- [x] 2.2 復元不能時にTRANSLATEが成果物を公開せず、Runが同じ入力とcheckpointを保持したResume可能な失敗状態になることを既存Lifecycleテストで確認する（Q-REL/Q-REC、12207運用・保守）

## 3. 実サンプル受入検証

- [ ] 3.1 `inputs/sample3.pdf`を使用してregister/translate/reviewをシーケンシャルに実行し、保護対象を含む少ページRunの証跡を保存する
- [ ] 3.2 成功時にMarkdown/DOCXの表紙重複、保護値欠落、artifact公開条件を検査し、失敗時は同じRunをResumeして終端状態を確認する（Q-FUNC/Q-COMP）
- [ ] 3.3 source hash不変、一時領域cleanup、証跡の機密値非包含を確認し、OpenSpec verification記録を作成する

## 4. 品質ゲートと完了

- [x] 4.1 `uv run pytest -q`、Ruff、format、strict type validationを実行し、結果をChangeのEvidenceへ記録する（Q-MNT）
- [x] 4.2 `openspec validate harden-protected-fragment-restoration --strict`を実行し、全ArtifactとSpec Deltaが検証済みであることを確認する
- [ ] 4.3 実サンプル受入、品質・Security・Lifecycle判定を反映してTasksを完了し、Changeをarchiveする（12207移行・廃止）

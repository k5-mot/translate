<!-- markdownlint-disable MD041 -->

## 1. 全chunk保護実装

- [ ] 1.1 通常chunkでも保護fragmentをplaceholder化してpromptへ渡し、通常・split双方の成功応答をunit testで確認する（Q-FUNC/Q-COMP）
- [ ] 1.2 通常chunkの復元失敗を既存retryへ接続し、欠落・未知・重複tokenが成果物公開前に`ProtectedFragmentMissing`になることをテストする
- [ ] 1.3 placeholder追加によるchunk budget境界を確認し、LLM/Embeddingを並列化せず既存split経路へ委譲する

## 2. FailureとResumeの検証

- [ ] 2.1 通常chunk失敗のFailure Evidenceがtask、page、target ID、stage、cause typeだけを含み、原文保護値・prompt・生応答を含まないことを確認する（Q-SEC）
- [ ] 2.2 失敗時にatomic成果物を公開せず、同一translate Runを明示Resumeできること、source hashが不変であることを既存Lifecycleテストで確認する（Q-REL/Q-REC）

## 3. sample3実Run受入

- [ ] 3.1 `inputs/sample3.pdf`でregisterを完了し、登録済み参照を利用したtranslateをシーケンシャルに実行する。Run ID、fingerprint、TIMEおよび終端証跡を保存する
- [ ] 3.2 translate成功時は生成PDF/Markdown/DOCXの保護値と表紙重複を検査し、reviewを同じ入力成果物に対して実行する。失敗時は同じtranslate RunをResumeする
- [ ] 3.3 source hash、Qdrant登録結果、artifact cleanup、Failure Evidence秘匿性を確認し、verification.mdへ記録する

## 4. 品質ゲートとarchive

- [ ] 4.1 `uv run pytest -q`、Ruff、format、strict type validationを実行し結果をEvidenceへ記録する（Q-MNT）
- [ ] 4.2 `openspec validate protect-all-translation-chunks --strict`を実行し、Spec Deltaと全Artifactを確認する
- [ ] 4.3 受入判定とLifecycle/Security判定をTasksへ反映し、ChangeをarchiveしてMain Spec同期を確認する（12207移行・保守・廃止）


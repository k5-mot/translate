<!-- markdownlint-disable MD041 -->

## 1. Specification and implementation

- [x] 1.1 Proposal、designおよび`pdf-translation` Deltaでsplit sub-chunkのprotected fragment契約を定義する
- [x] 1.2 split fallback promptのplaceholder化と応答復元を逐次実装し、既存ID/protected検証へ接続する
- [x] 1.3 復元成功、placeholder欠落、有限retry、raw本文非出力をunit testで確認する

## 2. Regression and lifecycle evidence

- [ ] 2.1 focused test、全pytest、Ruff、format、ty baselineおよびstrict validationを実行する
- [ ] 2.2 同じRun IDをdetached Gateで再開し、split後のprotected fragment維持、source hash不変、temp cleanup、秘密・本文非出力を証跡化する
- [ ] 2.3 Gateが進行または完了した場合、同じRun IDの明示Resumeを記録する

## 3. Completion and archive

- [ ] 3.1 `verification.md`へ実証結果を記録する
- [ ] 3.2 `.agents`、AGENTS.md/config.yaml、raw PDF、credentialおよびprobeをcommit対象外にして差分レビューする
- [ ] 3.3 全受入条件を満たした後にのみarchiveし、Main Spec同期とstrict validationを確認する

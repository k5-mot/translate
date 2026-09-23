<!-- markdownlint-disable MD041 -->

## 1. Specification and implementation

- [x] 1.1 Proposal、designおよび`pdf-translation` Deltaを作成し、有限sub-chunk fallback、逐次実行、診断redaction、Resume境界を定義する
- [x] 1.2 `translate/tasks/translate.py`へ出力枯渇時の決定的二分割を最大2段階で実装し、通常要求とfallbackを含めて同時Model requestを発生させない
- [x] 1.3 分割成功時の完全ID/protected fragment検証、分割枯渇時の安全なFailure、部分訳非公開をunit testで確認する

## 2. Regression and lifecycle evidence

- [ ] 2.1 focused test、全pytest、Ruff、formatおよびty baselineを実行し、strict validationを通す
- [ ] 2.2 構造fallback後に失敗した同じRun IDをdetached Gateで再開し、TRANSLATEがsub-chunk分割後に進行または安全に停止すること、source SQLite hash不変、temp cleanup、秘密・本文非出力を証跡化する
- [ ] 2.3 Gateが進行または完了した場合、同じRun IDを明示Resumeし、完了済みTask/chunkを再実行せず未完了単位から継続できることを記録する

## 3. Completion and archive

- [ ] 3.1 `verification.md`へ実証結果と残存ty baselineを記録する
- [ ] 3.2 差分をレビューし、`.agents`、AGENTS.md/config.yamlのユーザー変更、raw PDF、credentialおよび一時probeをcommit対象外にする
- [ ] 3.3 全受入条件を満たした後にのみarchiveし、Main SpecへのDelta同期とstrict validationを確認する

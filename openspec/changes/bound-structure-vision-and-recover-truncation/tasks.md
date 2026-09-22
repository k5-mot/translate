<!-- markdownlint-disable MD013 MD041 -->

## 1. Failing Contract Tests

- [x] 1.1 STRUCTURE画像の1,000,000-pixel上限、縦横比、page全域、上限内無変更およびCOVER非影響を失敗Testへ追加し、Q-FUNC／Q-PERFの境界を確認する
- [x] 1.2 visionの`output-truncated`後にtext-onlyを一度だけ開始し、完全なschema応答だけを採用する成功／両失敗Testを追加する。Adapterの同条件retry 0件、最終Failure、逐次呼出しをQ-REL／Q-SECとして確認する
- [x] 1.3 page checkpointの中断・Resume、入力／設定不一致、破損、旧Runにprogressなし、Task全体のAtomic公開境界を失敗Testへ追加し、Q-COMP／Q-RELの再推論0件と公開途中Artifact 0件を確認する

## 2. STRUCTURE Implementation

- [x] 2.1 STRUCTUREのvision入力だけを既存Dependencyで1,000,000 pixels以下へ縮小し、1.1のTestと実画像寸法でcropping 0件を確認する
- [x] 2.2 vision出力枯渇を同一requestへretryせず既存text-only経路へ有限・逐次で渡し、1.2のTestで成功時Failureなし／両失敗時安全なFailureを確認する
- [x] 2.3 Run内に検証可能な非公開page checkpointを原子的に確定し、同じ入力・互換設定のResumeで再利用する。1.3のTestで破損時再処理、旧Run互換およびTask全体のatomic publishを確認する
- [x] 2.4 先行する`align-llm-token-budget-and-truncation-diagnostics`の保留中Spec deltaと設計を、STRUCTUREで完全な代替応答を得た場合だけ継続する契約に整合させ、両Changeのstrict validationとSpec diffで矛盾0件を確認する

## 3. Quality and Security Gate

- [x] 3.1 `ruff check`、`ruff format --check`、`ty check`、focused pytest、全pytestおよび`openspec validate bound-structure-vision-and-recover-truncation --strict`を成功させ、Dependency差分0件とModel／Embedding逐次性を確認する（Q-MAIN／Q-PORT、保守）
- [x] 3.2 Test、Failure、Run log、checkpoint metadataおよびChange EvidenceをCredential、endpoint、prompt、文書本文、reasoning、raw response、画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）

## 4. Real Run and Handoff

- [ ] 4.1 Model context 30,208、parallel 1、他request 0件、Run fingerprint一致、旧Artifact hash／mtimeを確認し、page 3相当の有界vision→text回復probeが完全なschema応答を返すことを記録する（Q-FUNC／Q-PERF、運用）
- [x] 4.2 条件が揃った場合だけ900秒request timeoutで既存Run `01a0c97c-f5cf-7031-b808-4ad545133925`をCLIから明示Resumeし、page checkpoint、Run Failure、STRUCTURE公開境界および逐次呼出しを観測する。中断・再失敗時はRunを保持し、同じRunの互換checkpointだけを再利用する（Q-REL／Q-COMP、移行・廃止）
- [ ] 4.3 STRUCTURE以降の完了、既完了Artifact不変、最終成果物および外部exportを実測し、残存制約を`resolve-structure-model-invocation-typeerror`、`align-llm-token-budget-and-truncation-diagnostics`および受入Changeへ引き渡す。Word-to-PDF変換と目視比較は利用者作業として未完了なら明記する（Q-USE、Support）

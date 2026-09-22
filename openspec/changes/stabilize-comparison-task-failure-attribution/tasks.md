<!-- markdownlint-disable MD013 MD041 -->

## 1. Deterministic Reproduction

- [x] 1.1 全pytestで失敗し単独では成功する比較Reviewの読取り不能`translation_ja` caseを、先行Testまたは共有状態を二分して最小の順序依存Testへ縮約し、失敗event列、最終Taskおよび`target_id`だけを安全なEvidenceへ記録する（Q-FUNC／Q-REL、Support）
- [x] 1.2 縮約結果をTask status context、LangGraph branch、checkpoint、Run metadataおよびTest fixture cleanupと照合し、失敗event欠落または上書きの一つの原因を特定する。特定できなければ推測修正をせず停止する（Q-MAIN／Q-SEC）

## 2. Failure Attribution Correction

- [x] 2.1 原因を再現する失敗Testを先に追加し、確認した境界だけを最小修正して`SOURCE-SPLIT`／`source_en`と`TARGET-SPLIT`／`translation_ja`の帰属を一致させる（Q-FUNC／Q-USE）
- [x] 2.2 下位Errorの具体的な`target_id`優先、欠落時の比較input role、最初のfailed event、外側fallback、旧Failure読取りおよびCredential／本文redactionをUnit／Integration Testで確認する（Q-COMP／Q-SEC）
- [x] 2.3 source成功後target失敗のResumeでsource Artifactを再利用し、失敗Taskから再開して公開Review reportの部分版を残さないことを確認する（Q-REL、運用・移行）

## 3. Quality and Archive Gate

- [x] 3.1 `ruff check`、`ruff format --check`、`ty check`、focused／順序依存／全pytestおよびOpenSpec strict validationを成功させ、新規Dependency 0件、Model／Embedding並列処理0件を確認する（Q-MAIN／Q-PERF／Q-PORT）
- [x] 3.2 Test出力、Failure、Run logおよびEvidenceをCredential、endpoint、文書本文、raw response、traceback、reasoningおよび画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）
- [ ] 3.3 現行Gate結果を`verification.md`へ記録して本Changeをverify／archiveし、`resolve-translate-contract-verification-gaps`を再verifyしてCRITICAL 0件の場合だけarchiveする（Q-REL、保守・廃止）

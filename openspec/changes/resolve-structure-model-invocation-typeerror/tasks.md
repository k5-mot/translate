<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline

- [ ] 1.1 新Run `01a0c97c-f5cf-7031-b808-4ad545133925`のFailure、fingerprint、入力SHA-256、SPLIT〜LOADのfile count／aggregate hash／latest mtimeおよびcheckpoint数を読取り専用で記録し、旧Runと外部exportに変更がないことを確認する（Q-COMP／Q-REL、移行・廃止）
- [ ] 1.2 LM StudioのModel識別子、管理上のcontext、推論processの実`--ctx-size`、同時処理中のrequest有無、および既存Settingsのrequest timeout／Task deadlineを本文・endpointなしで確認し、安全なprobe条件を記録する（Q-PERF／Q-SEC、運用）

## 2. Sequential Root-Cause Diagnosis

- [ ] 2.1 保存済みpage 3 payloadに対して既存`structured()`のtext-only経路を900秒timeoutで一回だけ実行し、stage、allowlist済み例外chain型／origin、status有無、attempt数、finish reason、数値usage、wall timeおよびschema適合だけを記録して、成功済み直接probeとの差を判定する（Q-FUNC／Q-SEC）
- [ ] 2.2 2.1が成功した場合に限り、同じpage 3のvision経路を単発・逐次で実行し、同じ安全な項目とfallbackへ進むべきError分類を記録する。2.1が失敗した場合はvision requestを増やさず、その失敗で原因分類に進む（Q-PERF／Q-REL）
- [ ] 2.3 2.1／2.2の結果を既存Adapter、STRUCTUREおよびMock Testと照合し、製品request／SDK応答処理／fallback／local runtimeのどこに原因があるかを`verification.md`へ安全に記録する。分類不能なら追加の推測修正をせず停止する（Q-USE／Q-MAIN、Support）

## 3. Cause-Specific Correction

- [ ] 3.1 製品原因なら再現する失敗TestをAdapterまたはSTRUCTUREへ追加してから最小修正し、そのTestと既存retry／truncation Testを通す。環境原因なら製品コードを変更せず必要なLM Studio設定処置を記録し、同条件のprobeで解消を確認する（Q-FUNC／Q-MAIN、保守）
- [ ] 3.2 vision成功、vision失敗後text成功、両方失敗の各経路で有限retry、安全なTask／page／target／stage／cause type、旧Failure読取り、Atomic Artifact、fingerprint不変をfocused Testで確認する（Q-COMP／Q-REL／Q-SEC）

## 4. Quality and Security Gate

- [ ] 4.1 `ruff check`、`ruff format --check`、`ty check`、focused pytest、全pytestおよび`openspec validate resolve-structure-model-invocation-typeerror --strict`を成功させ、Dependency差分0件と逐次Model呼出しを確認する（Q-MAIN／Q-PORT）
- [ ] 4.2 probe出力、Test、Failure、Run logおよびChange EvidenceをCredential、endpoint、prompt、文書本文、reasoning、raw response、画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）

## 5. Resume and Handoff

- [ ] 5.1 他のModel／Embedding requestがないこと、LM Studioの実効contextが必要値を満たすこと、Run fingerprintが現在設定と一致することを確認し、条件が揃わなければ同RunをResumeせず理由を記録する（Q-COMP／Q-PERF、運用）
- [ ] 5.2 条件が揃った場合に限り900秒request timeoutで同じRun IDをCLIから一度だけ明示Resumeし、成功済みTaskのhash／mtime不変、STRUCTURE以降のcheckpoint、Failure、途中Artifactおよび外部exportの有無を記録する。再失敗時はRunを保持して停止する（Q-FUNC／Q-REL、移行・廃止）
- [ ] 5.3 実結果と残存制約を`align-llm-token-budget-and-truncation-diagnostics`および`complete-sample-pdf-acceptance-verification`へ引き渡すEvidenceとしてまとめ、Word-to-PDF変換と目視受入を本Changeで完了扱いにしない（Q-USE、Support・保守）

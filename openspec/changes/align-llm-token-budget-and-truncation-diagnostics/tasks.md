<!-- markdownlint-disable MD013 MD041 -->

## 1. Contract Test

- [ ] 1.1 Settings Testへcontext 30,208、最大出力16,384、画像予約2,048、安全余白1,024、既定入力領域10,752、30,208超の上限制限および予約値不整合の明示拒否を追加し、Q-FUNC／Q-PERFの境界を失敗Testとして確認する
- [ ] 1.2 LLM Adapter Testへ空本文と途中本文の`finish_reason=length`、2種類のusage metadata形、数値allowlist、parse前停止およびinvoke 1回を追加し、Q-REL／Q-SECとしてraw metadataと本文が公開Errorへ残らないことを確認する
- [ ] 1.3 Failure contract Testへ`output-truncated`、`text-output`／`vision-output`、終了理由、token count、旧Failure読取り、formatおよびAtomic Artifactを追加し、Q-COMP／Q-USEとしてoptional fieldとredactionを確認する
- [ ] 1.4 Fingerprint／Run Testへ旧既定値との差分、`tokens.context`と`tokens.output`によるResume拒否、旧Run不変および新規UUIDv7を追加し、Q-COMP／Q-RELの誤Resume 0件を確認する

## 2. Token Budget Implementation

- [ ] 2.1 SettingsのModel上限と既定値を30,208／16,384／2,048へ更新し、共通の1,024-token安全余白とavailable-input計算を実装して、1.1のTestが成功することを確認する
- [ ] 2.2 Translationのchunk予算を共通available-input計算へ統一し、すべてのrequestがcontext内で組み立てられることと既存の逐次処理をfocused Testで確認する

## 3. Truncation Diagnostics Implementation

- [ ] 3.1 LLM応答の終了理由とinput／output／total usageをallowlist正規化する処理を追加し、本文parse前に`length`を`text-output`または`vision-output`の`output-truncated`へ変換することを1.2のTestで確認する
- [ ] 3.2 出力枯渇をnon-retryableにし、既存のtransport／HTTP／Provider互換Errorだけが有限retryされることをinvoke回数とdeadline Testで確認する
- [ ] 3.3 Task status、Workflowの失敗event、Failure recordおよび共通表示へoptional診断fieldを伝播し、旧Failure互換、Resume可能なcheckpointおよび途中Artifact 0件を1.3のTestで確認する

## 4. Automated Quality Gate

- [ ] 4.1 `ruff check`、`ruff format --check`、`ty check`およびfocused pytestを実行し、Q-MAIN／Q-PORTとして新規Dependency 0件と変更箇所の型・lint・format成功を記録する
- [ ] 4.2 全pytestと`openspec validate align-llm-token-budget-and-truncation-diagnostics --strict`を実行し、既存CLI／Streamlit／Run／Qdrant／Docling契約に回帰がないことを確認する
- [ ] 4.3 Test、logおよび作成Evidenceをcredential、endpoint、prompt、文書本文、reasoning content、raw response、画像binaryのsentinelで走査し、Q-SECの漏えい0件を記録する

## 5. Sequential Real-Model Verification

- [ ] 5.1 旧Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`の更新時刻またはdirectory hashを取得し、新設定での明示Resumeが`tokens.context`と`tokens.output`を理由に拒否され、前後で旧Runが不変であることをLifecycle Evidenceへ記録する
- [ ] 5.2 保存済みDocling documentのpage 3相当payloadを最大同時request 1で一回probeし、Q-FUNC／Q-PERFとして非空かつschema適合、`finish_reason`非`length`、context内の数値usageおよびwall timeだけを安全なEvidenceへ記録する
- [ ] 5.3 5.2成功後に同じ実PDFを新しいUUIDv7 Runとして逐次Translationし、STRUCTURE以降のcheckpoint、Artifact、Failure有無およびRun metadataを確認する。再truncation時は自動増額せずFailureを保持してTaskを未完了とする

## 6. Lifecycle and Handoff

- [ ] 6.1 新旧Run、Failure、checkpoint、入力copy、成果物および外部exportが自動削除・書換えされていないことを確認し、ISO/IEC/IEEE 12207の移行、運用、Support、保守、rollbackおよび廃止Evidenceをまとめる
- [ ] 6.2 `complete-sample-pdf-acceptance-verification`へ引き渡す新Run ID、Translation結果、残存制約および安全な診断を記録し、本ChangeがWord-to-PDF変換や目視受入を代替しないことを確認する

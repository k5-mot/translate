<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline and Diagnosis

- [x] 1.1 先行した実page 3のvision／text responseをraw本文非表示のallowlist parserで再確認し、両方が`finish_reason=length`、content 0文字、reasoning 16,381／completion 16,384 tokensであり、`ValidationError`表示がfinish判定後ではないprobe harnessの誤分類だったことをEvidenceへ記録する（Q-USE／Q-SEC、Support）
- [x] 1.2 Run `01a0c97c-f5cf-7031-b808-4ad545133925`の入力SHA-256、fingerprint、Failure、SPLIT～LOAD file count／aggregate hash／latest mtime、checkpoint、公開Artifact、outputおよび外部exportを読取り専用でbaseline化し、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを確認する（Q-COMP／Q-PERF、運用・移行）

## 2. Failing-First Contract Tests

- [x] 2.1 Adapter TestでSTRUCTURE用`disabled` policyが`reasoning_effort="none"`、`chat_template_kwargs.enable_thinking=false`およびJSON numberの`thinking_budget_tokens=0`をstrict schemaの同一requestへ送ること、provider-default policyには3 fieldを送らないことを失敗先行で固定する（Q-FUNC／Q-COMP）
- [x] 2.2 STRUCTUREのvision→text fallbackが常に逐次で同じzero-budget policyを使い、Translation／Review／FIX／VERIFY／ALIGNのrequestとreasoning policyを変更しないことをMock call順序とpayloadで確認する（Q-PERF／Q-COMP）
- [x] 2.3 probe／Adapterのfinish-first Testを追加し、AIMessageとSDK例外の`length`をcontent parse前に`output-truncated`へ分類し、`stop`だけをPydantic検証すること、Provider 400を一回で停止すること、およびraw response／reasoning／tracebackを出力しないことを確認する（Q-USE／Q-REL／Q-SEC）
- [x] 2.4 private STRUCTURE page checkpoint Testでversion 4とzero-budget policyがkeyへ含まれ、version 3以前またはbudget不一致を再利用せず、同一policyのAtomic checkpointだけを再利用すること、および公開Run fingerprintが不変であることを確認する（Q-COMP／Q-REL、移行）

## 3. Zero-Budget Implementation

- [x] 3.1 `translate/adapters/llm.py`の`disabled` thinking policyへtop-level `thinking_budget_tokens=0`を最小追加し、既存template hint、strict schema、有限retryおよび安全なSDK length正規化を維持する。公開設定、prompt special token、native API、Dependencyまたはglobal Model設定を追加しないことを差分とTestで確認する（Q-FUNC／Q-MAIN／Q-PORT、取得・供給）
- [x] 3.2 `translate/tasks/structure.py`のprivate page checkpointをversion 4へ更新してzero-budget policyをkeyへ結び付け、vision成功、vision失敗後text成功、両方失敗で部分公開0件、Atomic保存および既存Failure伝播をfocused Testで確認する（Q-REL／Q-COMP、保守・移行）

## 4. Automated Quality and Security Gate

- [x] 4.1 Adapter、STRUCTURE、checkpoint、Failure、Resume、workflowおよびAtomic公開のfocused pytestを成功させ、Model／Embedding呼出しが常に同時最大1件かつ有限attemptであることをcall記録から確認する（Q-FUNC／Q-PERF／Q-REL）
- [x] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、公開CLI／Run schema／fingerprint、Dependency lockおよびOS固有製品分岐の意図しない差分が0件であることを確認する（Q-COMP／Q-MAIN／Q-PORT）
- [x] 4.3 Test output、Failure、Run metadata、checkpointおよびChange EvidenceをCredential、endpoint、prompt、文書本文、raw response、reasoning本文、tracebackおよび画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）
- [x] 4.4 `openspec validate enforce-structure-zero-thinking-budget --strict`を成功させ、実装とtasks／designの対応、Migration、Rollback、Supportおよび廃止影響をEvidenceへ記録する（Q-MAIN、ISO/IEC/IEEE 12207）

## 5. Short Provider Contract Gate

- [x] 5.1 他のModel／Embedding requestがないこと、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを再確認し、SDK retry 0、request timeout 900秒、同時request 1の短いstrict-schema probe条件とserver log開始offsetを本文非表示で記録する（Q-PERF／Q-SEC、運用）
- [x] 5.2 短い固定入力へ一回だけSTRUCTURE text requestを送り、request logへJSON numberの`thinking_budget_tokens=0`が到達し、HTTP成功、`finish_reason=stop`、reasoning 0、完全`StructureResponse`およびPydantic適合を全て確認する。不一致なら追加Model request、page 3およびRun Resumeを行わず停止する（Q-FUNC／Q-REL）
- [x] 5.3 short probeのrequest field、finish reason、数値usage、reasoning長、schema適合、attemptおよびwall timeだけをEvidenceへ記録し、raw log line、prompt、response、reasoning、Credential、endpointおよび画像binaryが保存されていないことをscanで確認する（Q-USE／Q-SEC、Support）

## 6. Sequential Real Page 3 Gate

- [x] 6.1 short probe成功後にruntimeとRun fingerprintを再確認し、保存済みpage 3をRun外一時directoryで検証する条件を固定する。vision一回、失敗時だけtext一回、SDK retry 0、timeout 900秒、同時request 1とし、既存Run／Artifactを変更しない（Q-PERF／Q-COMP、運用）
- [x] 6.2 page 3を逐次実行し、各responseをfinish-firstで評価して`stop`、完全schema、Pydantic適合、非truncationおよび有限wall timeを全て満たすことを確認する。失敗時は追加requestとRun Resumeを行わず、RunをResume可能な状態で保持する（Q-FUNC／Q-REL）
- [x] 6.3 page 3のstage、target、finish reason、数値usage、attempt、wall timeおよびschema適合だけをEvidenceへ記録し、probe前後でRun、SPLIT～LOAD、公開Artifactおよび外部exportが不変、Qdrant writeが0件であることを確認する。Qdrant外部状態は変更を許容してfingerprint／Resume拒否へ含めず、秘密漏えい0件を確認する（Q-COMP／Q-SEC、移行・廃止）

## 7. Conditional Resume and Final Evidence

- [x] 7.1 page 3成功時だけRun fingerprint、入力SHA-256およびSPLIT～LOAD baselineの一致、LM Studioのcontext 30,208／parallel 1／queued 0／idle、外部Serviceの利用可能性を確認し、条件不一致ならResumeせず理由を記録する（Q-COMP／Q-PERF、運用）
- [x] 7.2 全条件成立時に限り公開CLIから同じRun IDを一度だけ明示Resumeし、全Model／Embedding呼出しを逐次実行する。失敗時は有限retry後にWorkflowを停止してFailureとResume状態を保持し、追加Resumeを行わない（Q-FUNC／Q-REL、運用・保守）
- [x] 7.3 Resume成功時にRun完了、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外、Atomic Artifact、既完了SPLIT～LOAD不変、外部exportおよび自動削除0件を実測し、失敗時は部分Artifact非公開と保存状態を実測する（Q-FUNC／Q-COMP／Q-REL、移行・廃止）
- [x] 7.4 最終品質、Security、Lifecycleおよび受入Evidenceをまとめ、未完のWord-to-PDF変換、目視比較およびComparison Reviewを完了扱いにせず後続Changeへ引き渡し、本Changeのverify／archive可否を実証結果だけで判定する（Q-USE／Q-SEC／Q-MAIN、Support・保守・廃止）

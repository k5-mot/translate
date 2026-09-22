<!-- markdownlint-disable MD013 MD041 -->

## 1. Provider and Run Preconditions

- [x] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のinput hash、fingerprint、Failure、SPLIT～LOAD file count／aggregate hash／latest mtime、private checkpoint、公開STRUCTUREおよび外部outputをread-onlyでbaseline化し、LM Studioが対象Gemma 4、context 30,208、parallel 1、queued 0／idleで他Model／Embedding request 0件であることを確認する（Q-COMP／Q-PERF／Q-SEC、運用・移行）
- [ ] 1.2 現行OpenAI互換endpointへ、短い入力、実`StructureResponse` strict schema、`reasoning_effort=none`および`chat_template_kwargs.enable_thinking=false`を一回だけ逐次送信し、HTTP成功、`finish_reason=stop`、reasoning 0、schema-valid、attempt 1および有限wall timeを安全なmetadataだけで記録する。失敗時は以後の実装、Model requestおよびRun Resumeを行わず停止する（Q-FUNC／Q-PERF／Q-SEC、取得／供給）

## 2. Failing-First Request and Checkpoint Contracts

- [ ] 2.1 Adapter Testを先に追加し、disabled thinking policyが`reasoning_effort="none"`とJSON booleanの`chat_template_kwargs.enable_thinking=false`をschema `response_format`と同じrequestへ一度だけ渡し、既定policyではtemplate引数を追加しないことを失敗確認する（Q-FUNC／Q-COMP／Q-MAIN）
- [ ] 2.2 STRUCTURE Testを先に追加し、vision／text両経路だけがdisabled thinking policyを使用し、vision失敗時だけtextへ逐次fallbackし、Translation／Review／FIX／VERIFY／ALIGNのrequest policyが変わらないことを失敗確認する（Q-FUNC／Q-PERF／Q-COMP）
- [ ] 2.3 Adapter Testでtemplate field拒否の400が一回で停止し、AIMessage／SDK双方の`finish_reason=length`が途中内容をparseせず既存`output-truncated`へ分類され、raw prompt／response／reasoningをErrorへ含めないことを確認する（Q-REL／Q-USE／Q-SEC）
- [ ] 2.4 page checkpoint Testを先に追加し、旧versionまたはthinking policyが異なるpageを再利用せず、同一policy／schemaだけをAtomic再利用し、公開Run fingerprintが不変であることを失敗確認する（Q-COMP／Q-REL、移行／Rollback）

## 3. Minimal Non-Thinking Implementation

- [ ] 3.1 `translate/adapters/llm.py`へ後方互換な型付きthinking policyを追加し、disabled時だけnested template optionと`reasoning_effort=none`を最終request bodyへ構成して2.1および2.3を成功させる。prompt instruction、native API、Dependencyおよび暗黙fallbackは追加しない（Q-FUNC／Q-MAIN／Q-PORT）
- [ ] 3.2 `translate/tasks/structure.py`のvision／textだけへdisabled thinking policyを指定し、他Taskのreasoning／requestと逐次fallbackを維持して2.2を成功させる（Q-FUNC／Q-PERF／Q-COMP）
- [ ] 3.3 `PAGE_CHECKPOINT_VERSION`とpage keyへthinking policyを含め、旧page miss／新page hit、Atomic publishおよび公開fingerprint不変を確認して2.4を成功させる（Q-COMP／Q-REL、移行／Rollback）

## 4. Automated Quality, Security and Lifecycle Gates

- [ ] 4.1 Adapter、STRUCTURE、checkpoint、Failure、Resume、WorkflowおよびAtomic Artifactのfocused Testを成功させ、request回数／順序、400即時停止、有限retry、truncation非採用、部分Artifact公開0件および旧Failure読取りを確認する（Q-FUNC／Q-REL／Q-COMP）
- [ ] 4.2 `ruff check .`、`ruff format --check .`、`ty check`および全pytestを成功させ、Dependency lock、公開CLI／Run schema／fingerprint、他Task requestおよびOS固有製品分岐の差分0件を確認する（Q-MAIN／Q-PORT／Q-COMP、取得／供給）
- [ ] 4.3 Test output、console、Failure、run metadata、checkpoint、logおよびChange Evidenceを走査し、Credential、endpoint、prompt、本文、reasoning本文、raw response、tracebackおよび画像binaryの漏えい0件を記録する（Q-SEC／Q-USE、Support）
- [ ] 4.4 `openspec validate enforce-structure-nonthinking-provider-contract --strict`を成功させ、正本Specに未同期deltaがなく`skip_specs: true`が実装修正の範囲と一致することを確認する（Q-MAIN、保守）

## 5. Sequential Real Page Proof

- [ ] 5.1 4章成功後にruntimeのModel、context 30,208、parallel 1、queued 0／idleおよびRun baselineを再確認し、保存済みpage 3をRun外一時directoryでvision一回、失敗時だけtext一回、retry 1、request timeout 900秒、同時request 1で実行する（Q-PERF／Q-COMP／Q-REL、運用）
- [ ] 5.2 5.1でreasoning 0、`finish_reason=stop`、完全schema、Pydantic適合および部分Artifact 0件を確認し、mode、stage、attempt、数値usage、wall timeだけをEvidenceへ記録する。条件を一つでも満たさない場合は追加Model requestとRun Resumeを行わず停止する（Q-FUNC／Q-SEC／Q-REL、Support）

## 6. Same-Run Recovery and Handoff

- [ ] 6.1 5.2成功時だけcurrent fingerprintと保存値、SPLIT～LOAD baselineおよびModel idleを再確認し、公開CLIの`--resume 01a0c97c-f5cf-7031-b808-4ad545133925`を900秒request timeoutで一度だけ実行する。Model／Embeddingを逐次処理し、再失敗時は追加ResumeせずRunを保持する（Q-REL／Q-COMP／Q-PERF、運用）
- [ ] 6.2 Resume後に全Task状態、Failure、private checkpoint、検証済みDOCX／Markdown／診断Artifact、表紙一重出力、進捗100%、Atomic publish、既完了SPLIT～LOAD hash／mtimeおよび外部export境界を検査する（Q-FUNC／Q-REL／Q-USE／Q-SEC）
- [ ] 6.3 `verification.md`へprovider probe、failing-first／回帰Test、品質Gate、Security scan、実page、Resume、Lifecycle、移行／Rollbackおよびtask対応Evidenceをまとめ、残課題0件の場合だけ`bound-structure-reasoning-and-schema-output`と`complete-sample-pdf-acceptance-verification`へ成果物を引き渡す（Q-MAIN、保守／Support／廃止）

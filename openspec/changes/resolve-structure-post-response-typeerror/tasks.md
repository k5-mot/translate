<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline

- [ ] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`の入力SHA-256、fingerprint、Failure、page checkpoint、SPLIT～LOAD file count／aggregate hash／latest mtime、公開Artifact、Run outputおよび外部exportを読取り専用で記録し、baseline取得による変更0件を確認する（Q-COMP／Q-REL、移行・廃止）
- [ ] 1.2 LM StudioのModel、context 30,208、parallel 1、queued 0／idle、Settingsのrequest timeout／Task deadline／retry回数、導入済みLangChain OpenAI／OpenAI SDK／Langfuse versionを本文・Credential・endpointなしで記録する（Q-PERF／Q-SEC、運用・取得）

## 2. Offline Differential and Failing-First Tests

- [ ] 2.1 `httpx.MockTransport`がstrict-schemaのOpenAI Chat Completions互換responseを一件返すfixtureを作り、実`ChatOpenAI.bind(...).invoke()`、finish診断およびPydantic parseをNetwork 0件で通すことをHTTP call countとschema適合で確認する（Q-FUNC／Q-MAIN）
- [ ] 2.2 観測なし、current observation、detached observationの3条件で同じresponse stackを実行し、current contextの有無、結果、call count、安全な例外型chain／originだけを比較する失敗先行Testを追加する。raw request／response／tracebackが出力されないことも確認する（Q-REL／Q-SEC、Support）
- [ ] 2.3 generation観測のcreate、update、endおよびwarning sinkへ個別にFailureを注入し、schema-validな成功値、Provider call count 1、warning一回を期待するTestと、transport／408／429／5xx／parse Errorの既存有限retryが不変なTestを追加する（Q-REL／Q-PERF）

## 3. Detached Observation Implementation

- [ ] 3.1 `translate/adapters/langfuse.py`へ内部detached modeを実装し、generationでは`start_observation()`と明示的`update()`／`end()`、workflow／Task spanでは従来の`start_as_current_observation()`を使用することをfake clientのcall順序で確認する（Q-FUNC／Q-COMP、保守）
- [ ] 3.2 `translate/adapters/llm.py`のgeneration観測をdetached modeへ切り替え、`_invoke_with_retry()`を観測Failure domainから分離する。未知の`TypeError`、Provider Errorおよびparse Errorを握りつぶさず、受領済み成功応答だけは観測終了失敗で再送しないことをfocused Testで確認する（Q-REL／Q-MAIN）
- [ ] 3.3 観測warningがaction、例外型およびTaskだけを保持し、Credential、endpoint、prompt、入力本文、raw response、reasoning本文、tracebackおよびmodule名を含まないことをsentinel Testで確認する（Q-USE／Q-SEC、Support）
- [ ] 3.4 page checkpoint version 4、zero-thinking budget、strict schema、公開Run fingerprint、Run schema、CLI、Model/context、Dependencyおよび全Model／Embedding逐次実行方針に意図しない差分が0件であることを差分と既存回帰Testで確認する（Q-COMP／Q-PORT、移行・供給）

## 4. Automated Quality and Security Gate

- [ ] 4.1 Langfuse、Adapter、STRUCTURE、Failure、Resume、workflowおよびAtomic公開のfocused pytestを成功させ、観測fault時のProvider call count 1とModel Failure時の有限attemptを記録する（Q-FUNC／Q-REL／Q-PERF）
- [ ] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、Dependency lock差分0件とOS固有製品分岐0件を確認する（Q-MAIN／Q-PORT）
- [ ] 4.3 Test output、warning、Failure、Run metadata、checkpointおよびChange Evidenceを秘密・本文・raw応答・reasoning・traceback・画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）
- [ ] 4.4 `openspec validate resolve-structure-post-response-typeerror --strict`を成功させ、実装とtasks／designの対応、Migration、Rollback、Supportおよび廃止影響をEvidenceへ記録する（Q-MAIN、ISO/IEC/IEEE 12207）

## 5. Observation-Enabled Provider Gate

- [ ] 5.1 他のModel／Embedding requestがないこと、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを再確認し、SDK retry 0、request timeout 900秒、同時request 1の短いstrict-schema probe条件を本文・endpointなしで記録する（Q-PERF／Q-SEC、運用）
- [ ] 5.2 観測有効の短い固定入力へ一回だけSTRUCTURE text requestを送り、HTTP成功、`finish_reason=stop`、reasoning 0、完全`StructureResponse`、Pydantic適合、Provider request 1件および観測終了後も成功値が保持されることを確認する。不一致なら追加request、page 3およびRun Resumeを行わず停止する（Q-FUNC／Q-REL）
- [ ] 5.3 short probeのstage、finish reason、数値usage、reasoning長、schema適合、attempt、wall timeおよび安全な観測warningだけをEvidenceへ記録し、raw値と秘密の保存0件をscanする（Q-USE／Q-SEC、Support）

## 6. Sequential Real Page 3 Gate

- [ ] 6.1 short probe成功後にruntime、Run fingerprintおよびpage 2 checkpoint v4を再確認し、保存済みpage 3をRun外一時directoryでvision一回、失敗時だけtext一回、SDK retry 0、timeout 900秒、同時request 1で検証する条件を固定する（Q-PERF／Q-COMP、運用・移行）
- [ ] 6.2 観測有効でpage 3を逐次実行し、`finish_reason=stop`、reasoning 0、完全schema、Pydantic適合、非truncation、有限wall timeおよび各response一回だけの消費を確認する。失敗時は追加requestとRun Resumeを行わず、RunをResume可能な状態で保持する（Q-FUNC／Q-REL）
- [ ] 6.3 page 3の安全な診断値だけをEvidenceへ記録し、probe前後でRun、SPLIT～LOAD、公開Artifactおよび外部exportが不変、Qdrant writeが0件、秘密漏えい0件であることを確認する。Qdrant外部状態はfingerprint／Resume拒否へ含めない（Q-COMP／Q-SEC、移行・廃止）

## 7. Conditional Resume and Handoff

- [ ] 7.1 page 3成功時だけRun fingerprint、入力SHA-256、SPLIT～LOAD baseline、LM StudioのModel／context 30,208／parallel 1／queued 0／idleおよび必要Serviceの利用可能性を確認し、条件不一致ならResumeせず理由を記録する（Q-COMP／Q-PERF、運用）
- [ ] 7.2 全条件成立時に限り公開CLIから同じRun IDを一度だけ明示Resumeし、全Model／Embedding呼出しを逐次実行する。失敗時は有限retry後にWorkflowを停止してFailureとResume状態を保持し、同じChange内で追加Resumeを行わない（Q-FUNC／Q-REL、運用・保守）
- [ ] 7.3 Resume成功時にRun完了、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外、Atomic Artifact、既完了SPLIT～LOAD不変、外部exportおよび自動削除0件を実測し、失敗時は部分Artifact非公開と保存状態を実測する（Q-FUNC／Q-COMP／Q-REL、移行・廃止）
- [ ] 7.4 最終品質、Security、Lifecycleおよび受入Evidenceをまとめ、本Changeのverify／archive可否を実証結果だけで判定する。Translation未完なら原因を次の独立Changeへ引き渡し、Word-to-PDF変換、目視比較およびComparison Reviewを完了扱いにしない（Q-USE／Q-SEC／Q-MAIN、Support・保守）

<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline

- [x] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`の入力SHA-256、fingerprint、Failure、page checkpoint、SPLIT～LOAD file count／aggregate hash／latest mtime、公開Artifact、Run outputおよび外部exportを読取り専用で記録し、baseline取得による変更0件を確認する（Q-COMP／Q-REL、移行・廃止）
- [x] 1.2 LM StudioのModel、context 30,208、parallel 1、queued 0／idle、Settingsのrequest timeout／Task deadline／retry回数、およびlock済みLangfuse／OpenTelemetry／LangChain OpenAI／OpenAI SDK versionを本文・Credential・endpointなしで記録する（Q-PERF／Q-SEC、運用・取得）

## 2. Actual Observation Boundary and Failing-First Tests

- [x] 2.1 Test用span exporterを渡した実Langfuse clientと`httpx2.MockTransport`を渡した実`ChatOpenAI`でworkflow chain→Task span→generationの三層を構成し、Network 0件、Provider call 1件、strict-schema適合、および修正前にModel handler内へcurrent spanが残ることを失敗先行Testで確認する（Q-FUNC／Q-MAIN）
- [x] 2.2 failing-first Testでexportされた三層のtrace ID／parent span ID、Model handler内のcurrent span有無、結果、call countおよび安全な例外型だけを比較し、raw request／response／traceback／CredentialがTest outputへ出ないことを確認する（Q-COMP／Q-SEC、Support）
- [x] 2.3 root／child observationのcreate、update、endおよびwarning sinkへ個別にFailureを注入するTestを追加し、成功値または元の業務Error、Provider call count 1、warning一回、および次の独立Runで親ContextVarが空になることを期待値として固定する（Q-REL／Q-USE）

## 3. Non-Current Observation Hierarchy

- [x] 3.1 `translate/adapters/langfuse.py`へ親観測object用の内部ContextVarを実装し、detached rootはclient、detached childは親objectの`start_observation()`から作成して、OpenTelemetry current contextを変更せず親子階層を維持することを実Langfuse Testで確認する（Q-FUNC／Q-COMP、保守）
- [x] 3.2 detached観測のContextVar tokenを観測終了成否にかかわらず`finally`でresetし、create／update／end失敗を既存warningへ縮退し、成功値と元Errorを保持することをfault-injection Testで確認する（Q-REL／Q-SEC、Support）
- [x] 3.3 TranslationとComparison Reviewのroot workflow／全Task観測を明示的`detached=True`へ切り替え、製品Codeの全Model呼出しでLangfuse current spanが残らず、workflow→Task→generationの階層とflushが維持されることをIntegration Testで確認する（Q-FUNC／Q-MAIN）
- [x] 3.4 transport／408／429／5xx／parse Errorの既存有限retry、未知の`TypeError`伝播、page checkpoint v4、zero-thinking budget、strict schema、Run fingerprint／schema、CLI、Model／token設定および全Model／Embedding逐次実行方針に差分がないことを回帰Testと差分で確認する（Q-REL／Q-COMP／Q-PORT、移行・供給）

## 4. Automated Quality and Security Gate

- [x] 4.1 Langfuse、Adapter、Translation／Comparison Review workflow、STRUCTURE、Failure、Resume、Atomic公開およびfingerprintのfocused pytestを成功させ、観測fault時のProvider call count 1とModel Failure時の有限attemptを記録する（Q-FUNC／Q-REL／Q-PERF）
- [x] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、Dependency lock差分0件とOS固有製品分岐0件を確認する（Q-MAIN／Q-PORT）
- [x] 4.3 Test output、warning、Failure、Run metadata、checkpoint、span exporterの検査値およびChange Evidenceを秘密・本文・raw応答・reasoning・traceback・画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）
- [x] 4.4 `openspec validate isolate-model-invocation-from-workflow-observation --strict`を成功させ、実装とtasks／designの対応、Migration、Rollback、Supportおよび廃止影響をEvidenceへ記録する（Q-MAIN、ISO/IEC/IEEE 12207）

## 5. Observation-Enabled Short Provider Gate

- [x] 5.1 他のModel／Embedding requestがないこと、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを再確認し、SDK retry 0、request timeout 900秒、同時request 1の短いstrict-schema probe条件を本文・endpointなしで固定する（Q-PERF／Q-SEC、運用）
- [x] 5.2 実workflow→Task→generationのnon-current観測階層内で短い固定入力を一回だけ処理し、HTTP成功、`finish_reason=stop`、reasoning 0、完全schema、Pydantic適合、Provider request 1件およびModel処理中のLangfuse current spanなしを確認する。不一致なら追加request、page 3およびRun Resumeを行わず停止する（Q-FUNC／Q-REL）
- [x] 5.3 short probeのstage、finish reason、数値usage、reasoning長、schema適合、attempt、wall time、trace階層成立および安全な観測warningだけをEvidenceへ記録し、raw値と秘密の保存0件をscanする（Q-USE／Q-SEC、Support）

## 6. Sequential Real Page 3 Gate

- [x] 6.1 short probe成功後にruntime、Run fingerprint、入力SHA-256およびpage 2 checkpoint v4を再確認し、保存済みpage 3をRun外一時directoryでvision一回、失敗時だけtext一回、SDK retry 0、timeout 900秒、同時request 1で検証する条件を固定する（Q-PERF／Q-COMP、運用・移行）
- [x] 6.2 non-current workflow／Task観測階層内でpage 3を逐次実行し、`finish_reason=stop`、reasoning 0、完全schema、Pydantic適合、非truncation、有限wall timeおよび各response一回だけの消費を確認する。失敗時は追加requestとRun Resumeを行わず、RunをResume可能な状態で保持する（Q-FUNC／Q-REL）
- [x] 6.3 page 3の安全な診断値だけをEvidenceへ記録し、probe前後でRun、SPLIT～LOAD、公開Artifactおよび外部exportが不変、Qdrant write 0件、秘密漏えい0件であることを確認する。Qdrant外部状態はfingerprint／Resume拒否へ含めない（Q-COMP／Q-SEC、移行・廃止）

## 7. Conditional Resume and Handoff

- [x] 7.1 page 3成功時だけRun fingerprint、入力SHA-256、SPLIT～LOAD baseline、LM StudioのModel／context 30,208／parallel 1／queued 0／idleおよび必要Serviceの利用可能性を確認し、条件不一致ならResumeせず理由を記録する（Q-COMP／Q-PERF、運用）
- [x] 7.2 全条件成立時に限り公開CLIから同じRun IDを一度だけ明示Resumeし、全Model／Embedding呼出しを逐次実行する。失敗時は有限retry後にWorkflowを停止してFailureとResume状態を保持し、同じChange内で追加Resumeを行わない（Q-FUNC／Q-REL、運用・保守）
- [x] 7.3 Resume成功時にRun完了、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外、Atomic Artifact、既完了SPLIT～LOAD不変、外部exportおよび自動削除0件を実測し、失敗時は部分Artifact非公開と保存状態を実測する（Q-FUNC／Q-COMP／Q-REL、移行・廃止）
- [x] 7.4 最終品質、Security、Lifecycleおよび受入Evidenceをまとめ、本Changeのverify／archive可否を実証結果だけで判定する。Translation未完なら原因を次の独立Changeへ引き渡し、Word-to-PDF変換、目視比較およびComparison Reviewを完了扱いにしない（Q-USE／Q-SEC／Q-MAIN、Support・保守）

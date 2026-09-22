<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現行Adapterは`reasoning_effort=none`を`extra_body`へ入れ、STRUCTUREだけがstrict JSON Schema modeを使う。実page 3ではrequest上の指定を確認できたにもかかわらずreasoningが16,381 tokens生成された。local Gemma 4の`model.yaml`はcustom field `enableThinking`をJinja変数`enable_thinking`へ割り当て、既定値をtrueとしている。llama.cppのOpenAI互換境界ではrequestの`chat_template_kwargs`がvendor互換のreasoning指定より後にmergeされるため、この変数をfalseへ直接固定する経路を検証する。

現行endpointはOpenAI互換`/v1/*`を提供する一方、同じoriginのnative `/api/v1/models`は404を返す。native chatはstrict JSON Schemaを公開契約に持たず、既存LangChain／Failure／retry境界も変わるため、このChangeでは使用しない。Model／Embeddingはlocal hardware制約により常に逐次実行する。

## Goals / Non-Goals

**Goals:** STRUCTUREのvision／text requestへModel templateのthinking無効化を明示し、reasoning 0かつ完全なschema応答だけを採用する。既存のOpenAI互換Adapter、strict schema、有限retry、安全な診断、Atomic publishおよび同じRunからのResumeを維持する。

**Non-Goals:** native LM Studio APIまたはLM Studio SDKへの移行、server起動optionやModel既定値の変更、別Model／endpoint／processの追加、Translation／Review／FIX／VERIFY／ALIGNのreasoning変更、token上限増加、並列実行、parse緩和、公開設定追加、Run fingerprint変更および受入作業の目視判定。

## Decisions

### 1. 実装前にProvider contractを短い実requestで検証する

現在のModel、strict `StructureResponse` schema、`reasoning_effort=none`および`chat_template_kwargs.enable_thinking=false`を組み合わせた短いtext requestを、retry 1、request timeout 900秒、同時request 1で一度だけ送る。受入条件はHTTP成功、`finish_reason=stop`、reasoning 0 tokens、完全schemaおよびPydantic適合の同時成立とする。prompt、responseおよびendpointは保存せず、mode、finish reason、数値usage、schema適合性、attemptとwall timeだけをEvidenceへ記録する。

Providerがfieldを拒否する、fieldを無視してreasoningを生成する、またはschemaを完成しない場合は、製品実装と追加Model requestを開始せず停止する。これにより未対応optionをMockだけで正当化しない。短いprobeの成功は実page成功の十分条件ではないため、後段のpage 3 Gateを省略しない。

### 2. template引数はSTRUCTURE専用の明示policyとしてAdapterへ渡す

共有Adapterのmodel生成境界へ後方互換なthinking policyを追加し、既定はProvider defaultとする。STRUCTUREだけがdisabledを指定し、Adapterはその場合に限り`extra_body`へ`reasoning_effort="none"`と`chat_template_kwargs={"enable_thinking": false}`を同じrequest bodyとして構成する。JSON booleanを使用し、文字列`"false"`へ変換しない。既存のschema `response_format` bindとは別のrequest optionとして保持し、どちらも一回のrequestへ共存させる。

全Taskでtemplate引数を暗黙適用する案は、reasoningを必要とするTranslation／Review等を変えるため採用しない。`/no_think`などのprompt instructionはModel template境界を保証せず、本文と診断面も増やすため採用しない。server／Modelのglobal設定変更は、同じModelを使う他Taskへ影響し、運用者の状態に依存するため採用しない。

### 3. Provider拒否とthinking残存を安全に停止させる

Mock Testでは最終request bodyのnested option、schema option、呼出し回数および他Taskの不変性を検証する。Providerがunknown fieldまたは組合せを400で拒否した場合は既存どおり恒久Errorとして一回で停止し、template optionを外したrequestへ暗黙fallbackしない。応答が`length`ならSDK／AIMessageのどちらの形でも既存`text-output`または`vision-output`の`output-truncated`へ正規化し、途中JSONをparseしない。

Providerが`finish_reason=stop`を返してもreasoning usageが正の実probeは受入れない。製品の永続Failure schemaへreasoning値を追加せず、実機GateのEvidenceだけで判断する。これによりreasoning本文やProvider raw responseをRunへ残さない。

### 4. private page checkpointをtemplate policyへ結び付ける

`PAGE_CHECKPOINT_VERSION`を更新し、既存のreasoning effort、schema mode、response schema hashに加えてthinking policyをpage keyへ含める。旧versionまたはtemplate policyが異なるpageは同じRunでも再利用せず、新policyで検証済みのpageだけをAtomicに再利用する。公開Run fingerprintは、利用者設定ではない固定実装修正のため変更しない。

### 5. 実page成功後だけ同じRunを一度Resumeする

自動Gate後、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを確認する。保存済みpage 3をRun外一時directoryで、visionを一回、失敗時だけtextを一回、逐次・retry 1・900秒timeoutで実行する。reasoning 0、`finish_reason=stop`、完全schemaおよびPydantic適合を得た場合だけ、fingerprintとSPLIT～LOAD baselineを再確認して公開CLIの同一run ID Resumeを一度実行する。

page 3またはResumeが失敗した場合は、Failure、private checkpointおよびRunを保持し、追加Resumeを行わない。成功時はDOCX／Markdown／診断Artifact、表紙、進捗、Atomic publishおよび既完了Artifact不変を確認し、受入Changeへ引き渡す。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | Jinja template引数とstrict schemaを同じrequestで固定し、Pydantic再検証後だけ採用する | short probe、payload Test、page 3、Run結果 |
| Q-PERF | 900秒上限、有限attempt、同時request 1を維持し、reasoning生成を0 tokensにする | usage、wall time、queued／parallel、call順序 |
| Q-COMP | Adapter既定と他Task request、公開fingerprint／schemaを維持しprivate page keyだけ更新する | regression Test、fingerprint diff 0件、checkpoint miss／hit |
| Q-USE | Failureは既存stage／cause／finish／usageに限定する | Failure Test、CLI表示、Evidence review |
| Q-REL | field拒否、thinking残存、truncationで暗黙fallbackせず停止する | 400／length Test、部分公開0件、追加Resume 0件 |
| Q-SEC | raw値を保存せずboolean contractとallowlist metadataだけを扱う | sentinel scan、Credential／endpoint scan |
| Q-MAIN／Q-PORT | 既存`extra_body`と導入済みDependencyだけで実装する | Ruff、Format、ty、全pytest、Dependency diff 0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。旧private STRUCTURE page checkpointはversion／policy key不一致として無視し、Run metadata、Failure、公開Artifactおよび外部exportは変換しない。
- 運用: Model／Embedding requestは常に逐次とし、probeとResume前にloaded instance、context、parallel、queueおよびfingerprintを確認する。利用者へModel global設定変更を要求しない。
- 保守／Support: Model packageのtemplate変数とrequest payloadをTestで結び付け、LM Studio／llama.cpp更新後も短いprobeと実page Gateを再利用する。Providerがfieldを廃止した場合は本Changeで別APIへ推測移行しない。
- Rollback: Code commitを通常のGit操作で戻す。Run、private checkpoint、外部exportおよびQdrant Collectionは削除しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldがないため個別廃止処理は不要である。

## Risks / Trade-offs

- [Risk] `chat_template_kwargs`がLM Studio bridgeで拒否または無視される → 実装前の短いprobeで検出し、失敗時はCodeとRunを変更せず停止する。
- [Risk] 短いprobeだけ成功し、実pageではthinkingまたはschema枯渇が再発する → 保存済みpage 3を独立Gateにし、成功前のResumeを禁止する。
- [Risk] explicit template argumentが将来のbackendで非互換になる → STRUCTUREの明示policyだけに限定し、400を即時失敗させて暗黙fallbackしない。
- [Risk] thinking無効化で構造判断品質が下がる → schema-validだけで受入れず、既存rule-based補正、audit、DOCX検査およびComparison Reviewを後続Gateとして維持する。
- [Risk] page checkpoint無効化で358ページの再処理時間が増える → correctnessを優先し、新policyで成功したpageはAtomic checkpointへ保存して以後のResumeで再利用する。

## Migration Plan

1. Runとruntimeをread-onlyでbaseline化し、短いProvider contract probeを一回だけ実行する。失敗時は停止する。
2. Failing-first TestでSTRUCTURE専用template引数、schema共存、他Task不変、拒否／truncationおよびcheckpoint keyを固定する。
3. Adapter、STRUCTURE policyおよびprivate checkpoint versionを最小修正し、focused／全品質Gateと秘密scanを成功させる。
4. idleなlocal runtimeで保存済みpage 3を逐次検証する。失敗時はRunを変更せず停止する。
5. 成功時だけ同じRunを公開CLIから一度Resumeし、成果物、Lifecycleおよび既完了Artifact保護を検査する。
6. Rollback時は製品Codeを戻し、Runと外部exportを保持する。新policy checkpointは旧Codeからkey不一致で無視される。

## References

- [LM Studio model.yaml](https://lmstudio.ai/docs/app/modelyaml)
- [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [LM Studio native chat API](https://lmstudio.ai/docs/developer/rest/chat)
- [llama.cpp OpenAI reasoning parameter mapping](https://github.com/ggml-org/llama.cpp/pull/20479)

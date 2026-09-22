<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現行Adapterは全requestへ`reasoning_effort`を渡し、STRUCTUREだけが`none`とstrict JSON Schemaを使用する。保存済み実page 3ではtemplate制御なしのvision／textが各16,381 reasoning tokensを生成して出力上限へ到達した。一方、同じProviderへ`chat_template_kwargs.enable_thinking=false`を加えた短い実requestは、245 reasoning tokensを報告しながら7.910秒、`finish_reason=stop`およびschema-validで完了した。

local Gemma 4ではSTRUCTURE、Translation、ReviewおよびFIXが同じModelを共有する。Modelのglobal既定値を変更すると高reasoningを使う他Taskへ波及するため、制御はrequest単位かつSTRUCTURE専用にする。Model／Embeddingはlocal hardware制約により常に逐次実行する。

## Goals / Non-Goals

**Goals:** STRUCTUREのvision／textへModel templateのthinking抑制を明示し、reasoning量にかかわらず、出力枯渇せず有限時間内に得た完全なstrict-schema応答だけを採用する。既存の有限retry、安全な診断、Atomic publishおよび同じRunからのResumeを維持する。

**Non-Goals:** reasoning tokensを0件にする保証、native LM Studio APIまたはSDKへの移行、server起動optionやModel既定値の変更、別Model／endpoint／processの追加、他Taskのreasoning変更、token上限増加、並列実行、parse緩和、公開設定追加、Run fingerprint変更および目視による合否判定。

## Decisions

### 1. 完全な応答を受入条件とし、reasoning量は診断値に限定する

受入条件は`finish_reason=stop`、完全な`StructureResponse`、Pydantic適合、非truncationおよび既存deadline内の完了とする。reasoning token countはProvider実装によって0にならないため、正しさのGateには使わず、実機Evidenceへ非負の数値だけを記録する。prompt、response、reasoning本文およびProvider raw objectは保存しない。

`finish_reason=length`はSDK例外またはAIMessage metadataのどちらで返っても、既存の`output-truncated`へ正規化し、途中JSONをparseしない。schema不適合は既存の有限retry対象とし、deadlineまたはattempt上限でResume可能に停止する。これによりreasoningが少ないだけの不完全応答を誤採用しない。

### 2. template制御はSTRUCTURE専用の型付きrequest policyとして渡す

共有Adapterのmodel生成境界へ、Provider既定またはthinking抑制を表す型付きpolicyを追加する。既定はProvider既定を維持し、STRUCTUREだけがthinking抑制を指定する。抑制時は`extra_body`へ既存`reasoning_effort="none"`と`chat_template_kwargs={"enable_thinking": false}`をJSON booleanで同居させ、strict schemaの`response_format` bindと同じrequestへ送る。

全Taskへ暗黙適用する案とModelのglobal設定変更は、同じModelを使う高reasoning Taskへ影響するため採用しない。`/no_think`などのprompt instructionはtemplate変数を保証せず、本文境界も増やすため採用しない。native APIへの移行は既存のstrict schema、retryおよびFailure契約を広く変えるため採用しない。

### 3. Provider拒否時にpolicyを外して再送しない

Mock Testは最終request bodyのnested option、strict schema option、呼出し回数および他Taskの不変性を検証する。Providerがunknown fieldまたは組合せを400で拒否した場合は恒久Errorとして一回で停止し、template optionを除いた暗黙fallbackを行わない。vision失敗時の既存text fallbackは一回ずつ逐次実行するが、同一stage内の並列化や無制限再送は行わない。

### 4. private page checkpointを新しい生成policyへ結び付ける

`PAGE_CHECKPOINT_VERSION`を更新し、既存のreasoning effort、schema modeおよびresponse schema hashに加えてthinking policyをpage keyへ含める。旧versionまたはpolicyが異なるpageは同じRunでも再利用せず、新policyで検証済みのpageだけをAtomicに再利用する。公開Run fingerprintは利用者設定ではない固定実装修正のため変更しない。

### 5. 既存short probeを再利用し、実page成功後だけ同じRunを一度Resumeする

先行Change `enforce-structure-nonthinking-provider-contract`のcommitted EvidenceをProviderがoptionを受理して完全schemaを返すshort probeとして再利用し、同じrequestを再送しない。自動Gate後、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを確認し、保存済みpage 3をRun外一時directoryでvision一回、失敗時だけtext一回、retry 1、request timeout 900秒で逐次実行する。

page 3が完全schemaで成功した場合だけ、fingerprintとSPLIT～LOAD baselineを再確認して公開CLIから同じrun IDを一度Resumeする。page 3またはResumeが失敗した場合はFailure、private checkpointおよびRunを保持し、追加Resumeを行わない。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | template引数とstrict schemaを同じrequestへ固定し、Pydantic再検証後だけ採用する | short probe Evidence、payload Test、page 3、Run結果 |
| Q-PERF | 900秒request timeout、既存deadline、有限attempt、同時request 1を維持する | wall time、usage、queued／parallel、call順序 |
| Q-COMP | Adapter既定、他Task request、公開fingerprint／schemaを維持しprivate page keyだけ更新する | regression Test、fingerprint差分0件、checkpoint miss／hit |
| Q-USE | Failureを既存stage／cause／finish／usageへ限定する | Failure Test、CLI表示、Evidence review |
| Q-REL | 400、length、schema不適合で暗黙fallbackせず、完全応答だけを公開する | 400／length Test、部分公開0件、追加Resume 0件 |
| Q-SEC | raw値を保存せずboolean契約とallowlist metadataだけを扱う | sentinel scan、Credential／endpoint scan |
| Q-MAIN／Q-PORT | 既存`extra_body`と導入済みDependencyだけで実装する | Ruff、Format、ty、全pytest、Dependency差分0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。旧private STRUCTURE page checkpointはversion／policy key不一致として無視し、Run metadata、Failure、公開Artifactおよび外部exportは変換しない。
- 運用: Model／Embedding requestは常に逐次とし、page probeとResume前にloaded instance、context、parallel、queueおよびfingerprintを確認する。利用者へModel global設定変更を要求しない。
- 保守／Support: Model packageのtemplate変数とrequest payloadをTestで結び付け、Provider更新後も実page Gateで非退行を確認する。reasoning usageは合否ではなく傾向診断に使う。
- Rollback: Code commitを通常のGit操作で戻す。Run、private checkpoint、外部exportおよびQdrant Collectionは削除しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldがないため個別廃止処理は不要である。

## Risks / Trade-offs

- [Risk] `chat_template_kwargs`が将来のProviderで拒否または無視される → 400は一回で停止し、実pageの完了／usage／wall timeを再検証して暗黙fallbackを禁止する。
- [Risk] short probeは成功しても実pageでschema枯渇が再発する → 保存済みpage 3を独立Gateにし、成功前のResumeを禁止する。
- [Risk] thinking抑制でも少量のreasoning tokensが残る → countをGateにせず、完全schema、stop、非truncationおよび有限時間で判定する。
- [Risk] thinking抑制で構造判断品質が下がる → schema-validだけで最終品質とせず、既存rule-based補正、audit、DOCX検査およびComparison Reviewを後続Gateとして維持する。
- [Risk] checkpoint version更新で358ページの再処理時間が増える → correctnessを優先し、新policyで成功したpageはAtomic checkpointへ保存して以後のResumeで再利用する。

## Migration Plan

1. 保存済みRunと先行short probe Evidenceをread-onlyで再確認し、追加probeを送らない。
2. Failing-first TestでSTRUCTURE専用template引数、schema共存、他Task不変、拒否／truncationおよびcheckpoint keyを固定する。
3. Adapter、STRUCTURE policyおよびprivate checkpoint versionを最小修正し、focused／全品質Gateと秘密scanを成功させる。
4. idleなlocal runtimeで保存済みpage 3を一度だけ逐次検証する。失敗時はRunを変更せず停止する。
5. 成功時だけ同じRunを公開CLIから一度Resumeし、成果物、Lifecycleおよび既完了Artifact保護を検査する。
6. Rollback時は製品Codeを戻し、Runと外部exportを保持する。新policy checkpointは旧Codeからkey不一致で無視される。

## References

- [LM Studio model.yaml](https://lmstudio.ai/docs/app/modelyaml)
- [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [llama.cpp OpenAI reasoning parameter mapping](https://github.com/ggml-org/llama.cpp/pull/20479)

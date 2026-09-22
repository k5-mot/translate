<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。先行Changeのpage 3 probeは`ValidationError`だけを報告したが、同じ2 requestのlocal server logをraw本文非表示で再解析すると、requestには`chat_template_kwargs.enable_thinking=false`が到達し、responseはvision／textとも`finish_reason=length`、content 0文字、reasoning 16,381／completion 16,384 tokensだった。原因はSDK envelopeではなく、実payloadでtemplate hintがthinking生成を抑止しなかったことである。

local Gemma 4のtemplateは`enable_thinking=false`時に空のthought channelをgeneration promptへ挿入するが、Modelは実pageでthought channelを再開した。llama.cppは起動時budgetが未指定の場合、OpenAI互換request bodyの`thinking_budget_tokens`をper-request reasoning budgetとして扱い、0を即時終了に使用する。現在の`llama-server.exe` command lineにはreasoning、reasoning effort、reasoning budgetおよびchat-template kwargsのglobal overrideがなく、STRUCTURE、Translation、ReviewおよびFIXは同じModelを共有している。

## Goals / Non-Goals

**Goals:** STRUCTUREのvision／textだけへzero thinking budgetを強制し、実pageでreasoningが出力上限を消費する経路を閉じる。finish reasonをcontent parseより先に判定し、short probe、page 3および同じRun Resumeを逐次Gateとして実証する。

**Non-Goals:** global Model設定またはserver起動optionの変更、Translation／Review／FIX／VERIFY／ALIGNのreasoning budget変更、別Model／endpoint／processの追加、native API移行、token上限増加、並列実行、schema緩和、公開設定追加、Run fingerprint変更およびraw prompt／response／reasoningの保存。

## Decisions

### 1. 先行probeをfinish-firstで再分類する

先行2 responseの正しい分類は`output-truncated`である。probeはcompletion取得後、最初に`finish_reason`と数値usageを確認し、`length`ならcontentをPydanticへ渡さず安全な出力枯渇として停止する。`stop`の場合だけcontentを`StructureResponse`へ検証する。SDKがcompletion返却前に`LengthFinishReasonError`を投げた場合も、既存のallowlist抽出と同じくfinish／input／output／totalだけを扱う。

local server logはProvider responseの確認に有用だが、raw prompt、contentおよびreasoningを含む。補助解析はrequest keyとboolean／number、finish reason、content／reasoning長、数値usageおよびPydantic errorの`loc`／`type`だけをmemory上で抽出し、raw lineをconsole、EvidenceまたはRepositoryへ出力しない。

### 2. zero budgetをSTRUCTURE専用policyの同じrequestへ追加する

Adapterの`disabled` thinking policyは、既存の`reasoning_effort="none"`と`chat_template_kwargs={"enable_thinking": false}`に加え、top-level `thinking_budget_tokens=0`を`extra_body`へ入れる。0はJSON numberであり、文字列`"0"`やbooleanへ変換しない。strict schemaの`response_format` bindと同じrequestへ一回だけ送る。

既存hintは異なるruntime世代との互換意図として残す。budgetだけをglobal server optionへ設定する案は同じModelを使う高reasoning Taskへ波及するため採用しない。promptへ特殊tokenや`/no_think`を追加する案はtemplate injection境界と本文診断面を増やすため採用しない。

### 3. short probeでlocal Provider contractを一回だけGateする

実装と自動Gate後、短い固定入力、実`StructureResponse` strict schema、3つのthinking制御fieldを一回のtext requestで送る。SDK retry 0、request timeout 900秒、同時request 1とする。受入条件はrequest logの`thinking_budget_tokens=0`、HTTP成功、`finish_reason=stop`、reasoning 0、完全schemaおよびPydantic適合である。

field拒否、request logでの欠落、reasoning残存、lengthまたはschema不適合なら追加Model request、page 3およびRun Resumeを行わず停止する。これによりlocal bridgeがunknown fieldを黙って捨てる場合も、14分規模の実page前に検出する。

### 4. private page checkpointをzero-budget policyへ結び付ける

`PAGE_CHECKPOINT_VERSION`を4へ更新し、page keyのthinking policyへzero budgetを含める。version 3以前またはbudgetが異なるpageは同じRunでも再利用せず、zero-budget policyで検証済みのpageだけをAtomicに再利用する。公開Run fingerprintは利用者設定ではない固定実装修正のため変更しない。

### 5. 実page成功後だけ同じRunを一度Resumeする

short probe成功後、runtimeが対象Model、context 30,208、parallel 1、queued 0／idleであることを再確認する。保存済みpage 3をRun外一時directoryでvision一回、失敗時だけtext一回、SDK retry 0、timeout 900秒で逐次実行する。各responseはfinish-firstで判定し、`stop`、完全schema、非truncationおよび有限wall timeを全て満たす場合だけ成功とする。

page 3成功時だけfingerprintとSPLIT～LOAD baselineを再確認し、公開CLIから同じrun IDを一度Resumeする。short probe、page 3またはResumeが失敗した場合は追加request／Resumeを行わず、Failure、private checkpointおよびRunを保持する。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | zero budget、template hint、strict schemaを同じrequestへ固定し、stop後だけPydantic検証する | payload Test、short probe、page 3、Run結果 |
| Q-PERF | timeout 900秒、SDK retry 0、既存deadline、同時request 1を維持し、reasoning 16,384-token枯渇を防ぐ | request field、usage、wall time、queued／parallel、call順序 |
| Q-COMP | Adapter既定、他Task request、公開fingerprint／schemaを維持しprivate page keyだけ更新する | regression Test、fingerprint差分0件、checkpoint miss／hit |
| Q-USE | finish-firstで`length`を正しく表示し、safe usageだけを残す | SDK／AIMessage length Test、probe Evidence |
| Q-REL | field欠落／拒否、reasoning残存、length、schema不適合で暗黙fallbackせず完全応答だけを公開する | negative Test、部分公開0件、追加Resume 0件 |
| Q-SEC | server logのraw値を出力せず固定allowlist metadataだけを抽出する | sentinel scan、Credential／endpoint scan、Evidence review |
| Q-MAIN／Q-PORT | 既存`extra_body`と導入済みDependencyだけで実装する | Ruff、Format、ty、全pytest、Dependency差分0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。旧private STRUCTURE page checkpointはversion／policy key不一致として無視し、Run metadata、Failure、公開Artifactおよび外部exportは変換しない。
- 運用: Model／Embedding requestは常に逐次とし、各実機Gate前にloaded instance、context、parallel、queueおよびfingerprintを確認する。server再起動やglobal設定変更を要求しない。
- 保守／Support: request bodyとfinish-first分類をTestで固定し、runtime更新後もshort probeでfield到達とreasoning 0を再検証する。local server logはraw表示せず、失敗時の補助Evidenceに限定する。
- Rollback: Code commitを通常のGit操作で戻す。Run、private checkpoint、外部exportおよびQdrant Collectionは削除しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldがないため個別廃止処理は不要である。

## Risks / Trade-offs

- [Risk] LM Studio bridgeが`thinking_budget_tokens`を拒否または黙って破棄する → short probeのrequest log fieldとreasoning 0を両方Gateにし、失敗時はpage 3を送らない。
- [Risk] budget 0がModelの構造判断品質を下げる → schema-validだけで最終品質とせず、既存rule-based補正、audit、DOCX検査およびComparison Reviewを後続Gateとして維持する。
- [Risk] short probe成功後も実pageでModelがthought channelを再開する → page 3を独立Gateにし、stop／schema-valid前のResumeを禁止する。
- [Risk] server log自体がraw本文を含む → Parserはallowlist値だけをmemory上で抽出し、raw lineと本文をconsole／Evidenceへ出さない。
- [Risk] checkpoint version更新で358ページの再処理時間が増える → correctnessを優先し、zero-budget policyで成功したpageをAtomic checkpointへ保存して以後のResumeで再利用する。

## Migration Plan

1. 先行page 3 responseをfinish-firstで再分類し、Runとruntimeをread-onlyでbaseline化する。
2. Failing-first Testでzero-budget request、他Task不変、finish-first診断、拒否／lengthおよびcheckpoint v4を固定する。
3. AdapterとSTRUCTURE private policyを最小修正し、focused／全品質Gateと秘密scanを成功させる。
4. short provider probeを一回だけ逐次実行し、field到達、reasoning 0、stopおよびschema-validを確認する。失敗時は停止する。
5. 成功時だけ保存済みpage 3を一度逐次検証し、さらに成功した場合だけ同じRunを公開CLIから一度Resumeする。
6. 成果物、Lifecycle、Securityおよび既完了Artifact保護を検査する。Rollback時は製品Codeを戻し、Runと外部exportを保持する。

## References

- [llama.cpp server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp per-request thinking budget discussion](https://github.com/ggml-org/llama.cpp/discussions/21445)
- [llama.cpp request schema](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/server-schema.cpp)

<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

STRUCTUREへ`reasoning_effort=none`とstrict JSON Schemaを送る短いprobeは成功したが、保存済み実page 3ではvision／textともreasoningを16,381 tokens生成して出力上限へ到達した。対象Gemma 4のlocal `model.yaml`はthinking制御をJinja変数`enable_thinking`へ結び付けているため、OpenAI互換requestでこのModel固有境界を明示し、実payloadで有効性を証明してから同じRunを再開する。

## What Changes

- 現在のOpenAI互換endpoint、Model、strict JSON Schemaおよび逐次実行を維持し、STRUCTUREのvision／text requestだけへ`chat_template_kwargs.enable_thinking=false`を明示する。既存の`reasoning_effort=none`も互換意図として保持する。
- 実装前に短いstrict-schema probeを一回だけ行い、Providerが両指定を受理し、reasoning 0、完全schemaおよび`finish_reason=stop`を返すことを確認する。無視または拒否された場合は推測実装、native API移行およびRun Resumeを行わず停止する。
- request payload、vision→text fallback、出力枯渇、permanent 400、有限retry、Pydantic再検証および秘密非出力をfailing-first Testで固定し、生成policy変更に合わせて非公開page checkpointを無効化する。
- 自動品質Gate後に保存済みpage 3をRun外で一度だけ逐次検証し、成功した場合だけUUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度Resumeする。失敗時は追加Model requestを行わずRunを保持する。
- 公開CLI、Run layout／fingerprint、成果物形式、Model、token予算、Dependency、他Taskのreasoning policy、QdrantおよびWord-to-PDF操作は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成する契約を、`run-lifecycle`はLLM障害時の有限retry、安全な停止およびResumeを既に定義している。本Changeはその不適合実装を修正するため、`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 製品Code: `translate/adapters/llm.py`のOpenAI互換request optionと`translate/tasks/structure.py`のSTRUCTURE専用policy、および非公開page checkpoint key。
- Test／Evidence: Adapter、STRUCTURE、checkpoint、Failure、Resume、全品質Gate、短いcontract probe、保存済みpage 3 probeおよび条件付きの同一Run Resume。
- 外部境界: 既存LM Studio／llama.cpp OpenAI互換endpointだけを使用する。現環境で404となるnative `/api/v1/*`、新規SDK、別Model、別processおよび並列推論は導入しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 既存Runを作り直さず、実payloadがthinkingなしで完了すると実証した後だけ明示Resumeする。運用者によるModel再設定や同時request増加を要求しない。
- 取得／供給: 現在lock済みのLangChain、OpenAI SDK、PydanticおよびLM Studio機能だけを使用し、Dependency差分を0件にする。
- 移行: 公開Run schemaとfingerprintは変更しない。生成policyが異なる旧private STRUCTURE page checkpointだけをkey不一致として無視する。
- 保守／Support: request policyをMockで固定し、実機Evidenceはmode、finish reason、schema適合性、attempt、wall timeおよび数値usageだけを保持する。prompt、本文、reasoning本文、raw response、Credential、endpointおよび画像binaryは保存しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは利用者の明示操作なしに削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 短いprobeと実page 3のvisionまたはtextでreasoning 0、`finish_reason=stop`、完全`StructureResponse`およびPydantic適合を100%満たし、成功時だけResumeする。
- Q-PERF（性能効率性）: Model／Embedding requestを同時最大1件、request timeout 900秒、既存Task deadlineと有限attempt内に保ち、16,384-tokenのreasoning枯渇を0件にする。
- Q-COMP（互換性）: 公開Run fingerprint、Run schema、CLI、他Task requestおよび既完了SPLIT～LOAD Artifactの差分を0件にする。
- Q-USE（使用性）: 失敗時は既存のTask／page／target／stage／causeと安全なfinish／usageだけで再開可否を判断できるようにする。
- Q-REL（信頼性）: Provider拒否やthinking残存時に暗黙fallbackまたは追加Resumeを行わず、部分Artifact公開を0件にする。
- Q-SEC（Security）: Test output、Run metadata、Failure、log、checkpointおよびChange EvidenceのCredential、endpoint、prompt、本文、reasoning本文、raw responseおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: failing-first Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有の製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

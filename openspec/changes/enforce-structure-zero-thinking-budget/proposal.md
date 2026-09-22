<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

STRUCTUREへ`reasoning_effort=none`と`chat_template_kwargs.enable_thinking=false`を送った実page 3の応答をlocal server logからallowlist解析した結果、vision／textともcontent 0、reasoning 16,381／completion 16,384 tokens、`finish_reason=length`だった。前回の`ValidationError`表示は空contentをfinish reasonより先に検証したprobe harnessの誤分類であり、template hintだけでは実payloadのreasoning枯渇を防げないため、Providerが実行時に強制するzero thinking budgetをSTRUCTURE requestへ追加する。

## What Changes

- STRUCTUREのvision／text requestだけへ、既存の`reasoning_effort=none`と`chat_template_kwargs.enable_thinking=false`に加えて`thinking_budget_tokens=0`をJSON numberで送る。他Taskのreasoning policyは変更しない。
- probe harnessは`finish_reason`とusageをcontent parseより先に評価し、`length`を`ValidationError`ではなく出力枯渇として記録する。local logを補助Evidenceに使う場合もrequest field、finish reason、数値usage、content／reasoning長およびschema error pathだけへ限定する。
- request payload、Providerの400拒否、SDK／AIMessage双方のlength終了、vision→text逐次fallback、private page checkpoint policyおよび秘密非出力をfailing-first Testで固定する。
- 実装後に短いstrict-schema probeを一回だけ逐次実行し、requestへbudget 0が到達し、reasoning 0、`finish_reason=stop`および完全schemaを得た場合だけ、保存済みpage 3を一度検証する。
- page 3成功時だけUUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度Resumeする。失敗時は追加Model requestを行わず、Resume可能なRunを保持する。
- 公開CLI、Run layout／fingerprint、成果物形式、Model、context／output token設定、Dependency、global Model設定、Qdrantおよび並列実行は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成する契約を、`run-lifecycle`はLLM障害時の有限retry、安全な停止およびResumeを既に定義している。本Changeは既存契約を満たすためのProvider request修正と検証harness修正であるため、`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 製品Code: `translate/adapters/llm.py`のSTRUCTURE用OpenAI互換request body、`translate/tasks/structure.py`の非公開page checkpoint key。
- Test／Evidence: Adapter、STRUCTURE、checkpoint、Failure、Resume、全品質Gate、短いbudget probe、保存済みpage 3 probeおよび条件付きの同一Run Resume。
- 外部境界: 現在のLM Studio／llama.cpp OpenAI互換endpointだけを使用する。新規SDK、native API、別Model、別process、server再起動および並列推論は導入しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 既存Runを作り直さず、zero budgetが実機で有効と確認された後だけ明示Resumeする。運用者によるModel既定値変更や同時request増加を要求しない。
- 取得／供給: 現在lock済みのLangChain、OpenAI SDK、Pydanticおよびlocal runtimeだけを使用し、Dependency差分を0件にする。
- 移行: 公開Run schemaとfingerprintは変更しない。生成policyが異なる旧private STRUCTURE page checkpointだけをkey不一致として再計算する。
- 保守／Support: request policyとfinish-first診断をMockで固定し、実機Evidenceにはboolean／numberのrequest field、finish reason、schema適合性、attempt、wall timeおよび数値usageだけを記録する。prompt、本文、response、reasoning本文、Credential、endpointおよび画像binaryは保存しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは利用者の明示操作なしに削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: short probeでbudget 0の到達、reasoning 0、`finish_reason=stop`および完全schemaを確認し、実page 3でもstop、完全`StructureResponse`、Pydantic適合および非truncationを100%満たす。
- Q-PERF（性能効率性）: Model／Embedding requestを同時最大1件、request timeout 900秒、既存Task deadlineと有限attempt内に保ち、16,384-tokenのreasoning枯渇を0件にする。
- Q-COMP（互換性）: 公開Run fingerprint、Run schema、CLI、他Task requestおよび既完了SPLIT～LOAD Artifactの差分を0件にする。
- Q-USE（使用性）: finish reasonをparseより先に分類し、失敗時はTask／page／stage／causeと安全なusageだけで再開可否を判断できるようにする。
- Q-REL（信頼性）: Provider拒否、budget無効、length終了またはschema不適合時に暗黙fallbackや追加Resumeを行わず、部分Artifact公開を0件にする。
- Q-SEC（Security）: Test output、Run metadata、Failure、log、checkpointおよびChange EvidenceのCredential、endpoint、prompt、本文、response、reasoning本文、tracebackおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: failing-first Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有の製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

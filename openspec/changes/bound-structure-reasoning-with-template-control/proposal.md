<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

STRUCTUREへ`reasoning_effort=none`と`chat_template_kwargs.enable_thinking=false`を送る短い実機probeは、reasoningを0件にはできなかったものの、245 reasoning tokensだけで`finish_reason=stop`かつ完全なstrict schemaを返した。0件という内部制約は現Providerの実態と一致しないため、受入条件を本来必要な「出力枯渇を起こさず有限時間内に完全schemaを得ること」へ修正し、保存済み実page 3と同じRunのResumeで有効性を確定する。

## What Changes

- STRUCTUREのvision／text requestだけへ、既存`reasoning_effort=none`とJSON booleanの`chat_template_kwargs.enable_thinking=false`を併用する。Translation、Review、FIX、VERIFYおよびALIGNのreasoning policyは変更しない。
- `reasoning_tokens == 0`を正しさの条件にせず、`finish_reason=stop`、完全な`StructureResponse`、Pydantic適合、非truncationおよび有限時間を受入条件とする。reasoning usageは安全な診断値として記録する。
- request契約、Providerの400拒否、length終了、vision→text逐次fallback、private page checkpoint policyおよび秘密非出力をfailing-first Testで固定する。
- 自動品質Gate後に保存済みpage 3をRun外で一度だけ逐次検証し、成功した場合だけUUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度Resumeする。失敗時は追加Model requestを行わず、Resume可能なRunを保持する。
- 公開CLI、Run layout／fingerprint、成果物形式、Model、context／output token設定、Dependency、global Model設定、Qdrantおよび並列実行は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成する契約を、`run-lifecycle`はLLM障害時の有限retry、安全な停止およびResumeを既に定義している。本Changeはその不適合実装と過剰な内部受入条件を修正するため、`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 製品Code: `translate/adapters/llm.py`のOpenAI互換request option、`translate/tasks/structure.py`のSTRUCTURE専用policyおよび非公開page checkpoint key。
- Test／Evidence: Adapter、STRUCTURE、checkpoint、Failure、Resume、全品質Gate、既存short probe evidence、保存済みpage 3 probeおよび条件付きの同一Run Resume。
- 外部境界: 既存LM Studio／llama.cpp OpenAI互換endpointだけを使用する。native API、新規SDK、別Model、別processおよび並列推論は導入しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 既存Runを作り直さず、実pageが完全schemaで完了した後だけ明示Resumeする。運用者によるModel既定値変更や同時request増加を要求しない。
- 取得／供給: 現在lock済みのLangChain、OpenAI SDK、PydanticおよびLM Studio機能だけを使用し、Dependency差分を0件にする。
- 移行: 公開Run schemaとfingerprintは変更しない。生成policyが異なる旧private STRUCTURE page checkpointだけをkey不一致として再計算する。
- 保守／Support: request policyをMockで固定し、実機Evidenceにはmode、finish reason、schema適合性、attempt、wall timeおよび数値usageだけを記録する。prompt、本文、reasoning本文、raw response、Credential、endpointおよび画像binaryは保存しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは利用者の明示操作なしに削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 実page 3のvisionまたはtextで`finish_reason=stop`、完全`StructureResponse`、Pydantic適合および非truncationを100%満たし、成功時だけResumeする。
- Q-PERF（性能効率性）: Model／Embedding requestを同時最大1件、request timeout 900秒、既存Task deadlineと有限attempt内に保ち、16,384-tokenの出力枯渇を0件にする。
- Q-COMP（互換性）: 公開Run fingerprint、Run schema、CLI、他Task requestおよび既完了SPLIT～LOAD Artifactの差分を0件にする。
- Q-USE（使用性）: 失敗時は既存のTask／page／target／stage／causeと安全なfinish／usageだけで再開可否を判断できるようにする。
- Q-REL（信頼性）: Provider拒否、length終了またはschema不適合時に暗黙fallbackや追加Resumeを行わず、部分Artifact公開を0件にする。
- Q-SEC（Security）: Test output、Run metadata、Failure、log、checkpointおよびChange EvidenceのCredential、endpoint、prompt、本文、reasoning本文、raw responseおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: failing-first Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有の製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

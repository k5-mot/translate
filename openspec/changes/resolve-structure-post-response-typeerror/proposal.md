<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

STRUCTURE page 3の公開CLI Resumeでは、local Providerが6回とも`finish_reason=stop`、reasoning 0、strict schema適合の応答を返した後に`text-invoke`の`TypeError`で停止した。一方、Langfuseを無効化した同じpage 3の直接実行は成功しているため、Provider応答後のLangChain／Langfuse観測境界を再現可能な形で切り分け、観測障害が製品処理を停止しない既存契約へ適合させる必要がある。

## What Changes

- 実NetworkやModelを使わないstrict-schema応答fixtureで、実際のLangChain/OpenAI応答処理を観測有効／無効の両条件で実行し、`TypeError`の発生境界と例外chainのoriginを安全なallowlist情報だけで確定する。
- 原因がLangfuse／OpenTelemetry観測境界にある場合、観測の開始・更新・終了・export失敗をwarningへ変換し、schema-validなLLM結果を維持する。別の境界が原因の場合は、再現結果が示した箇所だけを最小修正する。
- Provider応答を受領した後の観測失敗で同じModel requestを再送しないこと、実際のtransport／Provider／parse障害には既存の有限retryと安全な停止を維持することをfailing-first Testで固定する。
- 診断情報はstage、例外型chain、固定分類したmodule origin、status、finish reason、数値usageおよびattemptだけへ限定し、prompt、入力本文、raw response、reasoning本文、Credential、endpointおよびtracebackを保存しない。
- 自動品質Gateの後、観測有効の短いstrict-schema probeを一回、成功時だけ保存済みpage 3をvision一回（必要な場合だけtext一回）逐次検証し、さらに成功した場合だけ同じRunを公開CLIから一度Resumeする。
- STRUCTUREのzero-thinking budget、strict schema、private page checkpoint v4、公開Run fingerprint、Model／context、Dependency、Qdrant方針および全Model／Embedding処理の逐次実行を変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`run-lifecycle`はLangfuse障害を警告へ変換して本処理を継続すること、およびLLM障害時の有限retryとResume可能な停止を既に要求している。`pdf-translation`も読取り可能なPDFから検証済み日本語DOCXを生成する契約を既に定義している。本Changeはこれらの既存要求へ実装を適合させるため、`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 製品Code: `translate/adapters/llm.py`の応答処理・retry分類、および原因が実証された場合の`translate/adapters/langfuse.py`観測境界。
- Test／Evidence: LangChain/OpenAIのsynthetic completionを使うoffline differential、Adapter／Langfuse／Lifecycle回帰Test、全品質Gate、観測有効の短い実Provider probe、保存済みpage 3および条件付きResume。
- 公開API、Run schema、fingerprint、CLI option、成果物形式、Dependencyおよび外部Service構成は変更しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: UUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を保持し、自動Gateと段階的実機Gateが成功した後だけ明示Resumeする。Model／Embedding requestは常に同時最大1件とする。
- 取得／供給: 現在lock済みのLangChain OpenAI 1.6.2、OpenAI SDK 3.16.2、Langfuse 4.15.4および既存Test Dependencyだけを使用し、Dependency差分を0件にする。
- 移行: Data migration、Run schema変更およびcheckpoint version更新は行わない。page 2までのprivate checkpoint v4と既完了SPLIT～LOAD Artifactを再利用する。
- 保守／Support: offline differentialとorigin分類を回帰Testにし、観測障害と製品障害を安全な情報だけで区別できるようにする。再現結果が仮説と異なる場合は、そのEvidenceに基づき対象を狭める。
- 廃止: 新規Service、Package、永続fieldおよび公開optionを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは利用者の明示操作なしに削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 観測有効でもschema-validなProvider応答を一回で`StructureResponse`として返し、公開ResumeがSTRUCTUREの応答後境界を通過することを確認する。
- Q-REL（信頼性）: Langfuseの開始・更新・終了・export失敗をwarningへ縮退し、受領済み応答に対する重複Provider requestを0件にする。実LLM障害は有限retry後にResume可能な状態を保持する。
- Q-PERF（性能効率性）: Model／Embedding requestを同時最大1件、request timeout 900秒に保ち、offline TestではNetwork 0件、実機Gateでは定義した上限を超えるrequestを0件にする。
- Q-COMP（互換性）: 公開Run fingerprint、Run schema、page checkpoint v4、CLI、成果物形式、Model/contextおよびDependencyの意図しない差分を0件にする。
- Q-USE（使用性）: FailureからTask、page、stage、固定origin、例外型chain、finish reasonおよび安全なusageを判断でき、観測warningと製品Failureを区別できるようにする。
- Q-SEC（Security）: Test output、warning、Failure、Run metadata、checkpointおよびChange EvidenceへのCredential、endpoint、prompt、入力本文、raw response、reasoning本文、tracebackおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: failing-first Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有の製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

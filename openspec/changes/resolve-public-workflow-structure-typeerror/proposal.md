<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

保存済みpage 3は実Modelとnon-current三層観測を使う単独Taskでschema-validに成功したが、同じ入力と設定を使う公開CLI Resumeは55.778秒後にSTRUCTURE page 3の`text-invoke`／`TypeError`で停止した。単独Taskと公開Workflowの差であるLangGraph worker、SQLite checkpoint、公開Lifecycle wrapperおよび観測Context伝播を実際の呼出し境界で再現し、推測ではなく発生元に限定した修正が必要である。

## What Changes

- 実`StateGraph`、`SqliteSaver`、Translation node wrapper、実Langfuse／OpenTelemetryおよび実ChatOpenAI response stackをNetworkなしで組み合わせ、公開Resumeと同じworker／checkpoint境界を再現する失敗先行Testを追加する。
- 観測開始、Model構築／bind／invoke、response返却、parse、観測終了およびLangGraph node返却の各境界を、例外型、origin、thread／context一致、attempt、Provider call countおよび応答消費回数だけで安全に区別する。Prompt、本文、raw response、reasoning、endpointおよびtracebackは記録しない。
- 再現結果が示す一つの境界だけを最小修正し、未知の`TypeError`一般を成功扱いせず、受領済みProvider応答を観測またはcheckpoint障害で再送しない。
- TranslationとComparison Reviewの逐次実行、Langfuse fail-open、有限retry、Atomic Artifact、page checkpoint v4、fingerprint、Run schemaおよびQdrant方針を維持する。
- 自動品質Gate後、保存済みpage 3を実LangGraphのRun外一時workspaceで一回検証し、成功時だけUUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度Resumeする。失敗時は追加Resumeを行わず安全なEvidenceを次Changeへ渡す。
- 公開CLI、Model `google/gemma4:12b`、context 30,208、token予算、成果物形式、Dependencyおよび全Model／Embedding同時request最大1は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`run-lifecycle`はLLM障害時の有限retry／Resume可能停止、Langfuse障害時の警告継続および秘密非出力を既に要求し、`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成することを既に要求している。本Changeは既存契約への実装適合であり、`.openspec.yaml`の`skip_specs: true`によりdelta specを作成しない。

## Impact

- 製品Code: 再現された原因に応じて`translate/workflows/translation.py`、`translate/adapters/langfuse.py`、`translate/adapters/llm.py`または公開Lifecycleの最小境界だけを変更する。
- Test: 実LangGraph／SQLite／Langfuse／ChatOpenAIを結合したoffline Integration Test、既存retry／Failure／Resume／Atomic公開回帰Test。
- 実Run: 現在のFailure、page 2 checkpointおよびSPLIT～LOADを保持し、段階Gate成功時だけ同一Runを一度Resumeする。
- 公開API、Dependency、永続schema、fingerprint、Modelおよび外部Service構成への変更はない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 公開CLIとStreamlitが共有するRunを、成功済みTaskを再実行せずSTRUCTUREから安全に再開できる状態へ戻す。実機検証はtimeout 900秒、parallel 1、queued 0から開始する。
- 取得／供給: lock済みLangGraph、Langfuse、OpenTelemetry、LangChain OpenAI、OpenAI SDKおよびTest Dependencyだけを使用し、新規PackageとProviderを追加しない。
- 移行: Data migration、Run schema、checkpoint version、fingerprintおよび旧Failure形式を変更しない。Qdrant外部状態はResume互換性に含めない。
- 保守／Support: 公開Workflow固有境界をoffline回帰Testへ固定し、安全なstage／origin／call countで再発箇所を特定できるようにする。
- 廃止: 新規Service、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは自動削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 実LangGraph worker／SQLite Resume境界でpage 3をschema-validに処理し、公開ResumeがSTRUCTUREを通過することをoffline Test、Run外page probeおよび同一Run結果で確認する。
- Q-REL（信頼性）: Provider response一件を一度だけ消費し、観測／checkpoint障害で再送しない。回復しないLLM障害は有限retry後にFailureとResume状態を保持する。
- Q-PERF（性能効率性）: offline TestはNetwork 0件、実機GateはSDK retry 0、request timeout 900秒、同時request 1とし、attempt、Provider call countおよびwall timeを記録する。
- Q-COMP（互換性）: Run schema、fingerprint、checkpoint v4、既完了Artifactおよび公開CLIを変更せず、CLI／Streamlit共有Runを維持する。
- Q-USE（使用性）: `text-invoke`だけでは区別できない発生元を、秘密を含まない固定boundary／origin／例外型へ縮約する。
- Q-SEC（Security）: Test、log、Failure、checkpointおよびEvidenceへのCredential、endpoint、prompt、本文、raw response、reasoning本文、tracebackおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: 実Dependency stackを使う失敗先行Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

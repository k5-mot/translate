<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

`resolve-structure-post-response-typeerror`でgeneration観測をnon-current化した後も、公開CLI ResumeはProviderが6件の完全応答を返した後にSTRUCTURE page 3の`text-invoke`で`TypeError`となった。成功した直接page probeとの差として、公開Workflowのworkflow／Task観測がcurrent OpenTelemetry contextを保持しているため、実Langfuse境界を再現してModel呼出しを観測contextから完全に隔離する必要がある。

## What Changes

- 実Langfuse 4.15.4とlock済みOpenAI SDK response stackをNetworkなしで使用し、外側workflow／Task current observation内のstrict-schema Model呼出しを再現する失敗先行Testを追加する。
- 原因がcurrent observationであることを確認した場合、workflow、Taskおよびgeneration観測をnon-current lifecycleへ移し、製品側の小さいContextVarで親観測objectを受け渡してtrace階層を維持する。別原因なら再現Evidenceが示す境界だけを修正する。
- 観測の作成、親子付け、更新、終了およびflushの障害を秘密を含まないwarningへ縮退し、本来の成功値とErrorを変更しない。受領済みProvider応答を観測障害で再送しない。
- TranslationとComparison Reviewのworkflow／Task観測を同じ逐次・non-current方針へ統一し、Model／Embedding同時request数1を維持する。
- 自動品質Gate後、短い外側workflow観測付きprobe、保存済みpage 3の順に一回ずつ検証し、成功時だけUUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度Resumeする。失敗時は追加Resumeせず次Changeへ安全なEvidenceを引き渡す。
- 公開CLI、Run schema、fingerprint、checkpoint version、Model、context 30,208、token予算、成果物形式、DependencyおよびQdrant方針は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`run-lifecycle`はLangfuse障害時の警告継続とLLM障害時の有限retry／Resume可能な停止を既に要求し、`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成することを既に要求している。本Changeは既存契約への実装適合であり、`.openspec.yaml`の`skip_specs: true`によりdelta specを作成しない。

## Impact

- 製品Code: `translate/adapters/langfuse.py`のnon-current観測階層、`translate/workflows/translation.py`と`translate/workflows/comparison_review.py`のworkflow／Task観測境界。
- Test: 実Langfuse／OpenTelemetry outer contextと実ChatOpenAI response stackを組み合わせるoffline回帰Test、観測障害注入、Translation／Comparison Review／Resume／Atomic公開の既存回帰Test。
- 実Run: 既存Runとpage 2 checkpointを保持し、段階Gate成功時だけ同一Runを一度Resumeする。
- 公開API、Dependency、永続schema、fingerprintおよび外部Service構成への変更はない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: Langfuse有効時も翻訳処理を観測障害から隔離し、失敗時は現在のRun ID、Failure、checkpointおよびArtifactを保持する。実機呼出しはtimeout 900秒、同時最大1件とする。
- 取得／供給: 導入済みLangfuse 4.15.4、OpenTelemetry、LangChain OpenAI、OpenAI SDKおよびTest Dependencyだけを使用し、新規PackageとProviderを追加しない。
- 移行: Data migration、Run schema、checkpoint version、fingerprintおよび旧Failure形式を変更しない。
- 保守／Support: actual SDK stackと実観測contextの組合せを回帰Testにし、warningはaction、Taskおよび例外型だけを記録する。raw prompt、本文、response、reasoning、endpointおよびtracebackは保存しない。
- 廃止: 新規Service、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは自動削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 外側workflow／Task観測が有効でもstrict-schema応答をProvider call 1件で返し、公開ResumeがSTRUCTUREの応答後境界を通過することをoffline Test、実page probeおよびRun結果で確認する。
- Q-REL（信頼性）: 観測create／parent／update／end／flush障害をwarningへ縮退し、成功値を保持する。Provider／parse障害は既存の有限retry後にResume可能な状態で停止する。
- Q-PERF（性能効率性）: offline TestはNetwork 0件、実機Gateはrequest timeout 900秒、SDK retry 0、同時Model／Embedding request 1件で行い、request countとwall timeを記録する。
- Q-COMP（互換性）: trace階層を維持しつつ、公開CLI、Run schema／fingerprint、checkpoint v4、Model／token設定および成果物形式の差分を0件にする。
- Q-USE（使用性）: 観測warningと製品Failureを安全なaction、Task、page、stageおよび例外型で区別できるようにする。
- Q-SEC（Security）: Test output、warning、Failure、Run metadata、checkpointおよびEvidenceへのCredential、endpoint、prompt、本文、raw response、reasoning本文、tracebackおよび画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: failing-first Test、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

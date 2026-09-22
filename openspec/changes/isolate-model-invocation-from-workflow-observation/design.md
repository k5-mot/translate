<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。`observe(..., detached=True)`はgeneration自体をcurrentにしないが、`translation.run()`のworkflow chainと各LangGraph nodeのTask spanは`start_as_current_observation()`を使う。そのためModel呼出し時にも外側Task spanがOpenTelemetry current contextとして残る。直接page probeは外側spanなしで成功し、公開Resumeは全6 Provider応答が`finish_reason=stop`／strict schema適合後にclient側`TypeError`となった。

導入済みLangfuse 4.15.4では、clientの`start_observation()`はnon-current rootを作成し、返された観測objectの`start_observation()`は親spanを一時的に使用してnon-current childを作成する。製品側でOpenTelemetry tokenを直接attach／detachせずに、親子階層とModel context隔離を両立できる。

## Goals / Non-Goals

**Goals:** 実Langfuse observationと実ChatOpenAI response stackで外側current contextを検出する失敗先行Testを作る。workflow、Task、generationをnon-currentの親子階層へ移し、Model処理中のLangfuse current spanをなくす。観測障害は本処理から隔離し、段階Gate後に同一Runを一度だけResumeする。

**Non-Goals:** OpenTelemetry／Langfuseの置換またはupgrade、trace廃止、prompt／response本文のtrace追加、手動span ID生成、async／並列観測、retry増加、Model／token／schema変更、Run fingerprint／checkpoint version変更、Qdrant状態固定および受入成果物の目視判定。

## Decisions

### 1. 実Langfuse clientと実OpenAI SDK response stackでcurrent境界を固定する

Test用span exporterを渡した実`Langfuse` clientと、`httpx2.MockTransport`を渡した実`ChatOpenAI`を同時に使用する。workflow chain、Task span、detached generationの三層内でstrict-schema responseを一件処理し、Provider handler内のOpenTelemetry current span、HTTP call count、Pydantic結果およびexportされた親子IDだけを検査する。修正前は外側Task spanがcurrentであるため「Model処理中のcurrent spanなし」という期待で失敗し、修正後は三層の親子関係を保ちながらcurrent spanを無効にする。

Test専用`ContextVar[bool]`だけを使う案は実OpenTelemetry contextとLangfuse span作成を通らず、前Changeで公開Workflowとの差を残したため採用しない。実Networkを使うTestも非決定的で秘密とGPU時間を必要とするため採用しない。

### 2. 製品ContextVarでnon-current観測objectだけを伝播する

`translate/adapters/langfuse.py`に現在の親観測objectを保持する内部ContextVarを追加する。detached観測開始時は、親がなければclientの`start_observation()`、親があれば親objectの`start_observation()`を呼ぶ。作成後にContextVarへ設定し、body終了時に必ずtokenをresetしてから観測を終了する。このContextVarはtrace階層用であり、OpenTelemetry current contextを変更しない。

親子付けに`trace_context`とspan IDを手動抽出する案はSDK内部表現へ依存する。OpenTelemetryの`attach(Context())`でModel呼出しだけを一時隔離する案はtokenの順序違反やcleanup失敗面を増やす。導入済みLangfuseが公開する親object APIを使う方が小さく、version lockに対するTestも作れるため採用する。

### 3. すべての製品workflow／Task観測を明示的detachedにする

TranslationとComparison Reviewのroot workflowとTask spanを`detached=True`へ切り替える。generationは既にdetachedであり、同じ親ContextVarからTaskの子として作成する。製品Codeに残る`observe()`呼出しをすべてnon-currentへ統一することで、別WorkflowのLLM処理にも同じ障害境界を残さない。`observe()`のcurrent modeは差分Testと互換確認用に維持し、公開interfaceにはしない。

Translationだけを変える案はComparison ReviewのModel呼出しへ同じcurrent spanを残すため採用しない。`observe()`のdefaultを暗黙に変更する案もcall siteから意図が見えず、回帰Testのcurrent対照条件を失うため採用しない。

### 4. 観測の全lifecycleをfail-openにし、業務Errorを優先する

root／child create、update、endおよびflushを個別にcatchし、既存warning sinkへaction、例外型、Taskだけを一度通知する。create失敗時は親ContextVarを変更せずuntracedでbodyを実行する。bodyが失敗した場合は観測update／end失敗より元Errorを優先し、成功した場合はend失敗で成功値を変えない。ContextVar tokenは観測終了処理が失敗しても必ずresetする。

未知のModel `TypeError`を成功扱いする、retry対象から一律除外する、または例外messageを保存する案は採用しない。Provider、transport、parse Errorの既存有限retryは変更しない。

### 5. 実機検証は短いouter-observation probeから一方向に進める

自動Gate後、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを確認する。最初に実workflow／Taskのnon-current観測階層内で短いstrict-schema requestを一件送る。成功時だけ保存済みpage 3をvision一件、失敗時だけtext一件で検証し、さらに成功時だけ同じRunを公開CLIから一度Resumeする。各段階でSDK retry 0、request timeout 900秒、同時request 1とし、失敗後は追加requestを送らない。

## Quality Attribute Design

| ID | Design approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC | 実Langfuse三層観測と実ChatOpenAI stackを通し、Model中のcurrent spanなしとschema-valid結果を両立する | failing-first offline Test、short probe、page 3、Run結果 |
| Q-REL | 親ContextVarをfinallyでresetし、create／update／end／flushを業務結果から隔離する | fault injection、Provider call count 1、Error identity Test |
| Q-PERF | offline診断を先行し、実機を900秒上限・逐次一件の段階Gateにする | HTTP call count、wall time、parallel／queued状態 |
| Q-COMP | 親object APIでtrace階層を維持し、永続schemaとfingerprintを変えない | exporterのparent ID、既存Lifecycle／fingerprint Test |
| Q-USE | warningを固定action、Task、例外型へ限定する | warning sink Test、Failure／CLI表示 |
| Q-SEC | 実response stackを通してもraw値をlog／Evidenceへ保存しない | sentinel scan、差分review |
| Q-MAIN／Q-PORT | 導入済みLangfuse APIとContextVarだけを使用する | Ruff、Format、ty、全pytest、Dependency差分0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。Run、Failure、checkpoint、Artifactおよびfingerprintを変更せず、page 2 checkpointを再利用する。
- 運用: Model／Embedding requestは常に逐次とし、各実機Gate前にModel、context、parallel、queue、Run fingerprintおよび入力hashを確認する。失敗時は同一Change内で再Resumeしない。
- 保守／Support: 実Langfuse client、span exporterおよびactual SDK response stackの回帰TestでSDK更新時のcontext／parenting変化を検出する。安全な分類値を越える診断は永続化しない。
- Rollback: 製品CodeとTest commitだけを通常のGit操作で戻し、Run、checkpoint、外部exportおよびQdrant Collectionを保持する。
- 廃止: 新規Service、Package、公開optionおよび永続fieldがないため個別廃止処理はない。

## Risks / Trade-offs

- [Risk] 親観測objectのContextVarが例外後に残留する → token resetを観測endとは独立した`finally`で保証し、連続Runとnested failureをTestする。
- [Risk] non-current化でLangfuseの親子関係が失われる → 実span exporterでworkflow→Task→generationのtrace ID一致とparent span IDを検査する。
- [Risk] Langfuse SDKの親object APIが将来変わる → lock済みversionでsignatureを固定せず振る舞いをTestし、upgrade時はTest failureとして検出する。
- [Risk] outer context以外にも公開Workflow固有差分がある → short probeとpage 3成功後だけResumeし、再失敗時は推測修正や追加Resumeをせず次ChangeへEvidenceを渡す。
- [Risk] 観測create失敗後に子観測が誤った親へ付く → create失敗時はContextVarを変更せず、root／child別fault injectionで呼出し順序を確認する。

## Migration Plan

1. 実Langfuse outer current contextとactual ChatOpenAI stackを組み合わせた失敗先行Testを追加し、修正前のcurrent span残留を確認する。
2. non-current親ContextVar階層とfail-open cleanupを実装し、Translation／Comparison Reviewの全workflow／Task call siteを明示的detachedへ切り替える。
3. 親子階層、観測障害、Model retry、秘密非出力、Run互換性および全品質Gateを検証する。
4. 短いouter-observation probe、保存済みpage 3、同一Run Resumeの順に一回ずつ実行する。
5. 成功時は最終成果物とLifecycleを検査し、失敗時はRunを保持して次Changeへ引き渡す。RollbackでもRunと外部状態を削除しない。

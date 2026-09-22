<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現在の単独page probeはmain threadで`structure.run()`を直接呼び、実Model、実Langfuse三層観測および同じpage payloadを通して成功した。一方、公開Resumeは`execute_public_run()`からTranslationのcompiled `StateGraph.stream()`へ入り、`SqliteSaver`のpending STRUCTURE nodeをworker contextで再開する。この差にはnode wrapper、ContextVar copy、thread、checkpoint serialization、進捗／Failure callbackおよび観測lifecycleが含まれる。

現在のTestは、実Langfuseと実ChatOpenAIを結合するがTranslationの`_run()`を置換しており、実LangGraph nodeを通らない。また、実LangGraph Resume TestはSTRUCTUREとModelをfakeにしている。そのため両者が交差する境界の回帰Testがない。

## Goals / Non-Goals

**Goals:** 実LangGraph workerとSQLite Resumeを通るSTRUCTURE Model呼出しをofflineで決定的に再現する。Provider call前後とnode返却までを安全な分類値で区別し、再現された原因だけを修正する。実page 3と公開Runで修正を一方向に検証する。

**Non-Goals:** LangGraph／Langfuse／OpenAI SDKのupgradeまたは置換、async／並列化、Model／prompt／schema／token予算変更、retry増加、raw診断追加、Run schema／fingerprint／checkpoint v4変更、Qdrant状態固定および未完了のWord-to-PDF／目視比較／Comparison Review受入。

## Decisions

### 1. 実Translation graphのpending STRUCTURE Resumeをofflineで再現する

Test用一時workspaceへ実`SqliteSaver` checkpointを作り、STRUCTURE直前までの小さいArtifact pathだけをstateへ保存する。Translationの実`build_graph()`、node wrapper、`compiled.stream(None, config)`および`max_concurrency=1`を使用し、STRUCTUREより前のnodeを再実行しないpending Resumeを構成する。STRUCTURE内部では実`llm.structured()`、実ChatOpenAI／OpenAI SDK stack、`httpx2.MockTransport`のstrict-schema responseおよび実Langfuse span exporterを使用する。

`translation._run()`全体をfakeにする既存Testの拡張案は問題のworker／checkpoint境界を除去するため採用しない。実local Networkを使うTestは非決定的でGPU時間とCredentialを必要とするため、実機Gateに限定する。

### 2. Cause Gateは値ではなく境界と回数を比較する

Test hookまたは既存境界のmonkeypatchで、worker thread identity、ContextVarの親観測有無、OpenTelemetry current span有無、Model build／bind／invokeの到達、Provider call count、response return count、parse count、observation update／endおよびnode returnをboolean／count／固定例外型だけで記録する。Raw message、prompt、response、reasoning、endpoint、span contentおよびtracebackは保持しない。

失敗がProvider call前、Provider response後、観測終了時またはcheckpoint commit時のどこで発生するかを一意に分類できた場合だけ修正へ進む。offlineで再現不能または複数境界が同時に疑われる場合は、製品修正と実Run Resumeを行わず、Run外の実page graph probeで同じ安全な分類だけを取得する。

### 3. 修正は再現された所有境界へ限定する

- Context伝播が原因なら、worker開始時に必要な製品ContextVarだけを明示的に束縛し、OpenTelemetry current contextは作らない。
- 観測objectのthread越し利用が原因なら、親子IDを安全に引き渡し、worker内でnon-current childを作成する。観測を無効化するのではなくtrace階層をTestする。
- ChatOpenAI／OpenAI clientのthread再利用が原因なら、Model clientをrequest実行thread内で一回だけ生成し、response後に再invokeしない。
- LangGraph node return／checkpoint commitが原因なら、Model結果を完全なPydantic値へ確定して観測を閉じた後に小さいArtifact pathだけを返す。

Cause Gateに一致しない一般的な`TypeError` catch、retry対象からの除外、Langfuse全体の無効化、およびResponseを成功扱いする案は採用しない。これらは原因を隠し、正当な一時障害回復または観測契約を壊すためである。

### 4. Offline回帰はResponse一回消費とFailure identityを固定する

成功経路はProvider call 1、response return 1、parse 1、STRUCTURE ArtifactのAtomic公開、checkpoint commit 1を要求する。観測create／update／end、Provider transport、parseおよびcheckpoint commitへ個別に障害を注入し、観測障害だけがwarning継続し、それ以外は元の業務Error identityと有限attemptを保持することを確認する。次の独立RunでContextVarが空になることも確認する。

### 5. 実機検証はRun外graph probeから公開Resumeへ一方向に進める

自動Gate後、LM Studio、Run fingerprint、入力SHA-256、page 2 checkpoint v4およびSPLIT～LOAD baselineを確認する。保存済みpage 3を実Translation graphのRun外一時workspaceで、SDK retry 0、Application retry 1、timeout 900秒、同時request 1として一度処理する。成功時だけ同じRunを公開CLIから一度Resumeする。いずれかが失敗した後は追加requestまたはResumeを行わない。

## Quality Attribute Design

| ID | Design approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC | 実Graph／SQLite／node wrapper／SDK stackの交差点を通し、単独Taskでは見えない差を再現する | failing-first offline Integration Test、Run外graph probe、公開Run |
| Q-REL | 一response一消費、観測fail-open、有限retry、Atomic公開およびFailure identityを固定する | call count、fault injection、checkpoint／Artifact検査 |
| Q-PERF | offline優先、実機は900秒上限・parallel 1・一方向Gateとする | attempt、wall time、LM Studio queue状態 |
| Q-COMP | UUIDv7 Run、fingerprint、checkpoint v4、CLI／UI共有layoutを変更しない | Lifecycle／Resume／fingerprint回帰Test、実Run差分 |
| Q-USE | 境界、originおよび例外型をallowlist値へ縮約する | Failure／warning／Evidence inspection |
| Q-SEC | 本文とraw値を収集せず、Credential／endpoint sentinelを走査する | Test output、Run files、Evidence scan |
| Q-MAIN／Q-PORT | 導入済み実stackの結合Testと原因限定修正だけを追加する | Ruff、Format、ty、全pytest、Dependency差分 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。保存済みRun、Failure、checkpoint、Artifactおよびfingerprintをそのまま使用する。
- 運用: Model／Embedding requestは常に逐次実行し、実機Gate前にModel、context 30,208、parallel 1、queued 0／idleを確認する。失敗後は同一Change内で再Resumeしない。
- 保守／Support: offline Integration Testを公開Workflow境界の回帰契約とし、安全なcount／boundary以外をlogまたはEvidenceへ残さない。
- Rollback: 原因限定の製品CodeとTest commitを通常のGit操作で戻す。Run、checkpoint、外部exportおよびQdrant Collectionは保持する。
- 廃止: 新規Service、Dependency、公開optionおよび永続fieldがないため個別廃止処理はない。

## Risks / Trade-offs

- [Risk] LangGraph内部thread schedulingへTestが過度に依存する → 公開APIの`compile()`、`stream()`、`SqliteSaver`および観測された境界だけを検査し、内部class名やthread名を固定しない。
- [Risk] Offline responseではlocal runtime固有のTypeErrorを再現できない → offlineで境界を絞れない場合だけRun外graph probeへ進み、製品修正と公開Resumeは保留する。
- [Risk] Test hookが製品診断面を増やす → 原則としてmonkeypatch可能な既存関数境界を使用し、製品field追加は原因修正に不可欠な固定分類だけに限定する。
- [Risk] 観測親objectがworker間で安全でない → thread内作成案をCause Gateで選び、実span exporterでworkflow→Task→generationの親子IDを検査する。
- [Risk] 再度公開Resumeが失敗する → 一回限り制約を維持し、部分Artifact非公開とResume可能状態を実測して次Changeへ渡す。

## Migration Plan

1. 実Graph／SQLite Resumeと実SDK response stackを結合したoffline Testを追加し、修正前Failureまたは再現不能Evidenceを確定する。
2. Cause Gateが一意に示す境界だけを最小修正し、response一回消費、観測fail-open、retryおよびcheckpoint回帰を成功させる。
3. 全自動品質／Security Gate後、Run外の実page 3 graph probeを一回実行する。
4. Probe成功時だけ同一Runを一度Resumeし、成功なら最終成果物、失敗なら保存状態を検査する。
5. Rollback時はCodeとTestだけを戻し、Runおよび外部状態を削除しない。

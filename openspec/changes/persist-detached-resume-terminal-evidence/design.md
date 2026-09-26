<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。前Changeでは、正本SQLiteをtemp forkへ複製し、実ModelでSTRUCTURE 351ページを完了してTRANSLATEへ進んだ。しかし、90分規模のPTY sessionが終了したため、temp rootのcleanup前に最終結果を回収できなかった。既存`execute_run()`はRun内の`run.json`／`failure.json`へ安全な状態を保存するが、probeがtemp rootを削除すると、その状態を外側へ退避するwatchdog境界がない。

## Goals / Non-Goals

**Goals:** PTYを使わずに同じ一時Runをdetached child processで実行し、親watchdogがprocess handleとheartbeatを監視する。安全なterminal recordをtemp root外へatomicに保存し、正常終了、`PublicRunError`、外部process異常終了、timeoutおよびcleanupを区別する。終了結果を確定できた場合だけ、次の一回限り正本Resumeへ進める。

**Non-Goals:** 公開CLIの対話仕様変更、Run／checkpoint schema変更、Product Run metadataへの本文追加、Model／prompt／schema／token予算変更、parallel化、retry無制限化、PTY依存の復活、正本Runの複数Resume、Word-to-PDF／目視比較／Comparison Review受入。

## Decisions

### 1. Terminal evidenceは検証用の外部sinkへ保存する

`TerminalEvidence`を検証用の小さいJSONとして定義し、version、run ID、phase、task、current／total、status、safe stage／cause type、finish reason、数値usage、checkpoint／artifact count、heartbeat時刻、child PIDおよびexit codeだけを許可する。任意のmessage、path、exception text、prompt、本文、raw response、reasoning、Credentialおよびendpointは型レベルで受け付けない。

Evidence pathはtemp Run rootの外側に置き、`atomic_write_json()`で同一volumeの一時Fileから置換する。childはRun内のsafe Failure／metadataを読み取ってallowlist値へ縮約し、parent watchdogはprocess exitと最後のheartbeatを記録する。EvidenceをRun rootへ置く案はcleanup時に失われ、Run metadataへfieldを追加する案は永続schemaを変更するため採用しない。

### 2. Detached childとwatchdogを分離する

2026-09-26補足: `run_public_run_detached()`はwatchdogが終端結果を返した後だけrequest／heartbeat／temp rootを削除する。監視例外や`KeyboardInterrupt`で戻らない場合、childの終了を確認できないため、それらを保持して元例外を伝播する。無条件の`finally`による削除はしない。この保持だけではparentのhard crash後の再回収、PID再利用を含む所有確認や明示cleanupの安全性は満たさず、Task 2.5の残件とする。Evidence／heartbeatの保存方式は[後継Change](../overwrite-diagnostic-json-in-place/design.md)の承認済み直接上書きを適用し、本書の旧atomic方式とは区別する。

親は`subprocess.Popen`でchildを起動し、stdout／stderrを保存せず`DEVNULL`へ接続する。childは既存のtemp clone／`execute_public_run()`を一度だけ実行し、progress callbackと例外境界で外部sinkへsafe updateする。親は一定間隔でchild handleをpollし、heartbeatとcheckpoint／Artifactの数だけを更新する。handleが終了した場合はexit codeを読み、childが書いたterminal record、Run statusおよびFailureを検査してterminal statusを確定する。

watchdogが先にstaleを検出した場合は、直ちにchildを再起動せず`watchdog-timeout`をEvidenceへatomicに記録し、childの停止を待ってからcleanupする。親が落ちてもchildとEvidenceは独立して残るため、PTY session消失を実処理Failureと混同しない。`Start-Process`だけでfire-and-forgetする案はprocess handleとexit codeを失うため採用しない。

### 3. Phaseとcountは既存境界からのみ取得する

Childの進捗は既存`ProgressCallback`のtask／current／totalを使用する。Failureは`failure.json`の`task`、`page`、`stage`、`cause_type`、`failure_kind`、`finish_reason`および数値usageだけを取り込む。checkpoint／Artifact countはcleanup前にroot containmentを検査して数える。LLM／Embedding call countは既存の逐次Model境界のcount hookを検証時だけ束ね、request内容を記録しない。Qdrantはsearch／registerの結果countと失敗分類だけを記録し、collection名・URL・payloadは保存しない。

Product codeへ環境変数や永続callbackを追加する代わりに、既存のinternal function／test hookとdetached probe runnerへ束ねる。公開CLI／Streamlit interfaceとfingerprintは変更しない。

### 4. Terminal判定は一方向にする

`completed`はchild exit 0、Run status completed、最終Artifact検証、heartbeat停止およびEvidence flush成功の全条件でのみ成立する。`failed`はsafe Failureまたはnon-zero exitを伴う場合、`unexpected-exit`はFailureがなくhandleだけが終了した場合、`timeout`はwatchdog deadline到達時とする。`unknown`／staleは成功とみなさず、追加Model requestと正本Resumeを禁止する。

temp Gateがcompletedになった場合だけ、同じ正本Runを公開CLIから一度Resumeする。正本Resumeの結果も同じ外部Evidence sinkへ保存し、失敗またはEvidence欠落時はRunを保持して次Changeへ引き渡す。

## Quality Attribute Design

| ID | Design approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC | child lifecycle、TRANSLATE／Review phase、terminal判定を同じRun boundaryで収集する | detached integration Test、temp実Model Gate、正本Resume |
| Q-REL | process handle、heartbeat、atomic JSON、exit／Failure分類、一方向Gateを採用する | child crash／timeout／Failure injection、Evidence検査 |
| Q-PERF | watchdog I/Oを小さいJSONと定間隔pollへ限定し、Model／Embeddingはparallel 1のままにする | 同時request、poll wall time、Model／Qdrant count |
| Q-COMP | UUIDv7、fingerprint、Run layout、checkpoint v4およびQdrant非依存を変更しない | Resume／fingerprint／schema regression、正本hash |
| Q-USE | phase／task／current／total／safe causeをPTYに依存せず利用可能にする | terminal record、process exit、Failure表示 |
| Q-SEC | allowlist valuesだけを外部sinkへ保存し、stdout／stderr／raw dataを破棄する | sentinel scan、root containment、Evidence file scan |
| Q-MAIN／Q-PORT | Python標準`subprocess`／`json`／既存atomic writerを使用し、Windows／PowerShellで検証する | Ruff、Format、ty、pytest、Dependency／OS差分 |

## Lifecycle, Migration and Operations

- 移行: 永続Run／checkpoint schema、fingerprint、Failure互換形式および外部exportを変更しない。新Evidenceは検証専用で、運用Runへ混入させない。
- 運用: childとwatchdogを同一Runにつき一度だけ起動し、実Model／Embeddingはparallel 1、SDK retry 0、timeout 900秒で逐次処理する。terminal status確定前にcleanup・Resumeを行わない。
- 保守／Support: Evidence version、phase、safe cause、exit codeおよびheartbeatを使い、PTY切断、Qdrant障害、LLM timeoutおよびProduct Failureを区別する。
- Rollback: runner／Test／terminal schemaの変更だけを戻し、正本Run、外部exportおよびQdrant Collectionは保持する。
- 廃止: terminal Evidence、child process、lockおよびtemp cloneは全terminal経路でcleanupする。parent crash時だけEvidenceを残して次の明示cleanupへ渡す。

## Risks / Trade-offs

- [Risk] Parent watchdogがchildの長いModel requestをstaleと誤判定する → heartbeatをparent自身でも更新し、process handleがliveである間はdeadlineを超えない。staleはhandle終了または明示deadline後だけにする。
- [Risk] Childがhard crashしてFailureを保存できない → watchdogがexit code、最後のheartbeat、checkpoint／Artifact countをsafe recordへ保存し、unknownを成功扱いにしない。
- [Risk] Evidence sinkへ秘密が混入する → enum／数値／型限定のwriterと16 sentinel scanをTestし、stdout／stderrを保存しない。
- [Risk] Temp cleanupがEvidenceを先に消す → sinkをtemp root外へ作り、terminal write／fsync確認後にcleanupする。
- [Risk] detached processが重複起動する → child PID／run ID／lockをwatchdogで一意に管理し、既存handleがある場合は再起動しない。

## Migration Plan

1. Terminal evidence schema、atomic writer、safe Failure／progress mappingとdetached child／watchdog Testを追加する。
2. Synthetic crash、Qdrant／LLM／checkpoint failure、timeout、parent／child cleanupおよびsecret scanを成功させる。
3. 品質Gate後、正本historical cloneをdetached temp Runへ一度Resumeし、terminal statusとEvidenceを回収する。
4. temp Gateがcompletedの場合だけ、公開CLIから同一正本Runを一度Resumeする。
5. 成功／失敗をEvidenceへ固定し、failureなら追加Resumeせず次Changeへ引き渡す。Rollback時はCode／Testだけを戻す。

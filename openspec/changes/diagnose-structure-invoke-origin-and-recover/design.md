<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と実Run Evidenceは[proposal.md](proposal.md)および先行Changeのverificationを参照する。現行Adapterは`client.invoke()`から出た任意の`TypeError`をretryableとして扱い、最終的にstageとcause typeだけへ縮約する。この契約は秘密を保護する一方、27分後の再失敗がrequest構築、LangChain、OpenAI SDK、transportまたはlocal runtimeのどこで生じたかを区別できない。RunにはSPLIT〜LOADとpage 2の検証済みcheckpointがあり、page 3以降だけを逐次再開できる。

## Goals / Non-Goals

**Goals:** raw値を保存せず`TypeError`の所有境界を一意に分類し、再現Testを先行して原因箇所だけを修正する。既存の安全なFailure、有限retry、Atomic Artifact、page checkpoint、fingerprintおよび逐次実行を維持したまま同じRunを再開する。

**Non-Goals:** 全`TypeError`の握り潰し、schema parseの緩和、prompt／token予算の変更、別Model／Providerへの切替え、並列化、公開CLI追加、旧Run／Qdrant／外部exportの削除、およびWord-to-PDF受入作業。

## Decisions

### 1. 最初にread-only Evidenceと単発の診断probeでoriginを分類する

再失敗時刻周辺のlocal runtime logは、生の行を転記せず、process終了、HTTP status、finish reason、既知exception型およびassertion有無だけへ正規化する。それだけで所有境界を確定できない場合、保存済みpage 3 payloadと同じ有界vision→text順序をRun外の一時directoryで一度だけ実行する。diagnostic wrapperはexception chainの型とtraceback frameのmodule名をmemory内で調べ、`application`、`langchain`、`openai-sdk`、`transport`、`local-runtime`または`unknown`の固定enum、stage、attempt、status有無、数値usage、finish reason、wall timeだけを出力する。exception message、frame path、line text、prompt、本文、response、endpointおよび画像は出力・保存しない。

full Runを先に再開する案は、27分の再現コストと原因縮約を繰り返すため採用しない。製品Failureへ直ちにtracebackやmessageを追加する案は、秘密漏えいと互換性の範囲を不必要に広げるため採用しない。

### 2. 原因ごとに修正境界を固定し、再現不能なら停止する

診断probeで製品requestまたはresponse互換処理が原因と確認できた場合、同じ型・origin・stageを再現するMockを追加し、該当変換だけを修正する。LangChain／OpenAI SDK内の既知返却形が原因なら、HTTP fixtureまたはclient stubで再現し、provider固有値を公開せず既知形だけを正規化する。transport／local runtime原因なら製品コードへ推測回避を入れず、LM Studio設定またはversion処置を記録し、同じ診断probeで解消を確認する。

一般的な`TypeError`をretryableとする現行判定は、originが一時障害境界であると確認できる場合だけ維持する。request構築や決定的SDK変換の`TypeError`は即時失敗させ、既存のtransport、408、429および5xx retryは変えない。分類が`unknown`または再現しない場合は、追加の推測修正やfull Run Resumeを行わずChangeを未完了で停止する。

### 3. 診断分類はprobe Evidenceに限定し、公開Run schemaを増やさない

既存の`LLMError`、`StructurePageError`、Task statusおよびFailure recordが公開するstage／cause typeを維持する。origin分類は診断wrapperとTest assertionだけで使用し、原因解消に恒久的なfieldが必須と判明しない限りRun metadataへ追加しない。これにより`skip_specs: true`と旧Failure互換を維持する。恒久fieldが必要になった場合は、本Changeを停止して`run-lifecycle`のdelta Specを持つ別Changeへ切り出す。

### 4. 修正後の実証はtargeted probeから同一Runへ一方向に進める

Mock回帰、focused Test、全品質Gate、Security scanを通した後、context 30,208、parallel 1、queued 0／idle、推論process context、fingerprint一致を再確認する。まずpage 3相当の有界vision→text probeを同時request 1、各request timeout 900秒、既存Task deadlineで実行し、schema-validな完全応答を要求する。成功時だけ同じRun IDを公開CLIから一度Resumeする。

Resume後はpage 2 checkpoint再推論0件、SPLIT〜LOAD hash／mtime不変、page 3以降のAtomic checkpoint、Failureおよび公開成果物を確認する。再失敗時はRunを保持し追加Resumeしない。成功時は先行3 Changeと受入Changeへ成果物と残存制約を引き渡す。

## Quality Attribute Design

| ID | Design Approachとtrade-off | Verification Evidence |
|---|---|---|
| Q-FUNC | 実失敗と同じmode順序を再現し、原因別の最小修正だけを許可する | failing-first Test、page 3 probe、同一Run結果 |
| Q-REL | retryable境界をoriginで限定し、page checkpointとAtomic publishを維持する | attempt数、checkpoint再利用、途中公開0件 |
| Q-PERF | 900秒／21,600秒の有限上限と同時request 1を維持する | wall time、LM Studio queued／parallel、呼出し順 |
| Q-COMP | Run schemaとfingerprintを変えず旧Failureを読む | compatibility Test、fingerprint diff 0件 |
| Q-USE | 固定origin enumを一時Evidenceへ限定する | Support判定表、`unknown`時の停止Evidence |
| Q-SEC | raw exception／traceback／payloadをmemory外へ出さない | sentinel／Credential／endpoint scan 0件 |
| Q-MAIN／Q-PORT | 原因再現Testから最小修正しOS固有分岐を製品へ入れない | Ruff、Format、ty、全pytest、Dependency差分0件 |

## Lifecycle, Migration and Operations

Data migrationはない。運用者は単一Modelをcontext 30,208／parallel 1で維持し、診断probeとResumeを同時実行しない。Supportは固定origin、stage、cause type、attemptおよびwall timeだけを扱う。保守者は原因fixtureと最小修正を同じChangeへ残し、Dependency更新を回避する。rollbackは通常のGit revertで行い、既存Runとpage checkpointはそのまま保持する。Run、外部exportおよびQdrant Collectionの廃止は利用者の明示操作まで実施しない。

## Risks / Trade-offs

- [Risk] 単発probeで非決定的な失敗が再現しない → 成功を原因解消と誤認せず、既存Failureとruntime logだけで原因を確定できなければ`unknown`として停止する。
- [Risk] traceback module名でもProvider固有情報が漏れる → moduleは固定prefix照合後のenumだけを出力し、path、function、lineおよびmessageを破棄する。
- [Risk] 900秒requestがvisionとtextで連続し長時間化する → 各mode一回、parallel 1、既存Task deadlineに制限し、full Runはprobe成功後だけ実行する。
- [Risk] 原因修正に公開Failure fieldが必要になる → 現Changeでschemaを拡張せず、delta Specを持つ別Changeへ切り出す。
- [Risk] page 3通過後に別pageで同種障害が発生する → page checkpointで完了pageを保持し、一回のResume結果をEvidence化して追加自動Resumeを禁止する。

## Migration Plan

1. RunとLM Studioを読取り専用でbaseline化し、runtime logを安全なenumへ分類する。
2. 必要な場合だけRun外で有界vision→text診断probeを一度実行し、originを確定する。
3. failing-first Testと原因固有の最小修正を実装し、自動GateとSecurity scanを通す。
4. page 3 probeが完全成功した場合だけ同じrun IDを一度明示Resumeする。
5. 成否を先行Changeと受入Changeへ引き渡す。rollback時もRun、checkpoint、外部exportおよびQdrantを削除しない。

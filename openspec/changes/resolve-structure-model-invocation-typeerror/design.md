<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)のWhyを参照する。現在の`structured()`は`client.invoke()`内の`TypeError`を有限retryし、最終的にstageと例外型だけを持つ`LLMError`へ変換する。STRUCTUREはvision失敗後にtext-onlyへfallbackするが、両方失敗した場合は最終text ErrorだけがFailureへ渡る。保存済みRunにはSPLIT〜LOADのArtifactと9件のcheckpointがあり、STRUCTUREの途中directoryと公開出力はない。単発text probeは成功しているため、`structured()`経路、vision後のfallback経路、またはlocal runtime状態との差を切り分ける必要がある。LM Studio管理情報のcontextは30,208だが、推論processの起動引数は30,000だった。

## Goals / Non-Goals

**Goals:** 同一page／Model／Ruleの経路を逐次・有限時間で再現し、visionとtextそれぞれの安全な失敗境界を特定する。確認した原因だけを最小範囲で修正し、既存Runを明示Resumeできる状態を保つ。

**Non-Goals:** raw SDK messageや文書内容の恒久保存、未知の`TypeError`を広く握りつぶす処理、token予算／fingerprintの変更、別Modelへの切替え、同時Model request、旧Runの削除、受入Changeの目視判定。

## Decisions

### 1. 変更前にtextとvisionの境界を分けて再現する

保存済みDocling documentからpage 3 payloadを再構成し、既存`structured()`のtext-only経路を単発実行する。これは成功済みの直接`_model().invoke()` probeとの最小差分である。text-onlyが成功した場合にだけ、同じpayloadとpage画像でvision経路を単発実行する。各呼出しは900秒timeout、既存Task deadline、同時実行数1に制限する。失敗時は例外型、allowlistした例外chainの型、HTTP statusの有無、tracebackの所属を`application`／`langchain`／`openai-sdk`／`transport`／`unknown`へ正規化した分類、stage、attempt数、wall timeだけを標準出力へ出し、prompt、画像、raw response、exception messageおよびtracebackを保存・表示しない。必要な場合のみこの分類を使ってMockによる失敗Testを作る。

単に同じRunを再開して失敗を待つ案は、Doclingのcheckpointは再利用できても失敗点を分離できず、vision側の原因を再び失うため採用しない。先に診断用の永続logを広げる案も秘密漏えい面を増やすため採用しない。

### 2. 原因で修正境界を決める

製品のrequest payload、`structured()`のresponse正規化、LangChain／OpenAI互換APIの使い方、またはvision→text fallbackの制御が原因と再現できた場合、該当境界に失敗Testを追加して最小修正する。`TypeError`一般をretry対象から外す、すべての例外をfallbackさせる、parse結果を緩く採用する、といった包括変更はしない。SDK／Providerの実際の返却形に由来する場合はMock HTTP responseで再現してから互換処理を追加する。

LM StudioのModel設定、実効context、runtime異常または外部Providerだけが原因なら、利用者のRunと製品コードを変更せず、必要なlocal設定処置を記録する。特にappの30,208とbackendの30,000という差はResume前に再確認する。backendが必要なcontextを提供できない場合、fingerprintを変えて同Runを無理に再開せず作業を停止する。診断結果がこの二分岐に収まらない場合は、実装範囲を広げる前にChange artifactsを更新する。

### 3. FailureとArtifactの既存契約を固定する

製品修正時も`LLMError`のstage、cause type、truncation診断、有限retryを保持する。visionが失敗してtextが成功した場合はactive failureを残さず、両方失敗した場合はRunを停止する。旧Failure JSONの読取り、Task checkpoint、atomic directory cleanup、入力copyおよびfingerprintに対する回帰Testを必須とする。diagnostic probeのvisionとtextの両結果をEvidenceへ並べて記録し、製品の公開Failure field追加は原因解消に必須と確認できた場合だけ別途設計する。

### 4. 実Run Resumeは診断と自動Gateの後に一度だけ行う

Ruff、Format、ty、focused／全pytest、OpenSpec strict validationと秘密sentinel scanを通した後、他のModel／Embedding requestがないこと、現在設定のfingerprintがRunと一致すること、LM Studioのcontext表示と実process設定を確認する。SPLIT〜LOADのfile count、hashおよびmtimeをbaseline化し、`--resume 01a0c97c-f5cf-7031-b808-4ad545133925`を900秒request timeoutで明示実行する。再失敗時はFailureとArtifactを保持して追加の自動Resumeをしない。成功時だけ旧Artifact不変、STRUCTURE以降のcheckpoint、成果物および外部exportを確認し、元のChangeと受入Changeへ引き渡す。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | `structured()`と直接probeの差分を順に絞る。実Model呼出しが増える | mode別結果、原因再現Test、明示Resume |
| Q-PERF | 900秒上限、有限attempt、逐次Model／Embeddingを維持する | wall time、attempt数、同時request最大1 |
| Q-COMP | Run schemaとfingerprintを変えない | 旧Failure読取り、Resume互換Test |
| Q-USE | 結論は安全なstage／分類／型と運用処置で示す | Evidence review、CLI Failure Test |
| Q-REL | 完了済みArtifactを再利用し、失敗TaskはAtomicに公開する | hash／mtime、checkpoint、途中Artifact 0件 |
| Q-SEC | raw messageとtracebackはin-memory分類後に捨てる | sentinel scan、Credential／endpoint scan |
| Q-MAIN／Q-PORT | 原因に対応するMock Testだけを追加し、既存Dependencyを使う | Ruff、Format、ty、全pytest、Dependency差分0 |

## Lifecycle, Migration and Operations

移行とData migrationはない。運用者は900秒timeoutとLM Studio contextの実効値を確認してから、既存Runを明示Resumeする。Supportは保存済みFailureと安全なprobe結果から、製品不具合かlocal runtime設定かを区別する。保守者は原因に対応するTestと最小修正を同じChangeへ残し、将来のProvider差異に対する無差別retryを避ける。Rollbackはコードを通常のGit操作で戻す手順とし、Run、外部export、Qdrant Collectionは変更・削除しない。廃止は利用者の明示操作に任せる。

## Risks / Trade-offs

- [Risk] 再現probeが非決定的で原因を確定できない → mode別に一回ずつ実行し、安全な結果を記録して停止する。無制限の繰返しで「たまたま成功」を修正根拠にしない。
- [Risk] tracebackやSDK messageに本文・endpointが含まれる → 生の値を表示せず、所属enumと型のallowlistだけを出力する。
- [Risk] server context 30,000とapplication 30,208の差が実requestへ影響する → Resume前に両値を確認し、不整合を残したまま互換性を主張しない。
- [Risk] 修正がRun fingerprintへ影響する → 出力影響設定を変えずに修正できるか先に判定し、必要なら同Run ResumeをやめてChangeを更新する。
- [Risk] 長い実Runで再失敗する → 完了済みArtifactをbaseline化し、一度のResume後に安全なFailureを保全して停止する。

## Migration Plan

1. 新RunとLM Studioの現在状態を読取り専用で確認し、RunのArtifact baselineを取得する。
2. text-only、必要ならvisionの順に安全な単発probeを行い、原因を分類する。
3. 製品原因なら失敗Testと最小修正を実装し、環境原因なら設定処置を記録してコード変更を行わない。
4. 自動Gateと秘密scan後、運用条件が一致するときだけ同Runを一度Resumeする。
5. 成否をEvidenceへ記録する。Rollback時もRun／成果物を削除しない。

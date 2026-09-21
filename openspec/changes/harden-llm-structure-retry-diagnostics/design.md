<!-- markdownlint-disable MD041 -->

## Context

変更理由と範囲は[proposal.md](proposal.md)を参照する。現在のLLM Adapterは`httpx.TransportError`、408、429および5xxだけをretryし、`client.invoke()`または構造化応答解析から生じた`TypeError`を即時伝播する。STRUCTUREは各pageでvision呼出しに失敗するとtext-onlyへfallbackするが、両方が失敗した場合、Workflowへ渡る例外にpage、対象ID、呼出しmodeおよび処理段階がない。

Workflow wrapperは例外の`page`、`group`および`target_id`属性をTaskStatusEventへ転記する。一方、Failureの`stage`と`cause_type`は現在Qdrant `RegistrationError`専用である。受入RunにはSPLIT〜LOADの完全なcheckpointがあり、同じfingerprintでSTRUCTUREからResumeできる。

## Goals / Non-Goals

**Goals:**

- 外部LLM境界の一時的なinvoke／parse Errorだけを、既存設定に従って有限retryする。
- retry上限後に、STRUCTUREのpage、安定した対象ID、vision／text mode、invoke／parse stageおよび下位例外型を安全に保存・表示する。
- 既存Registration failureと旧failure JSONを壊さず、共通Lifecycleへ診断metadataを伝播する。
- 修正後に同じ受入RunをResumeし、成功済みTaskを再実行しないことを実証する。

**Non-Goals:**

- Task内部、Application Codeまたは未知の場所で生じる全`TypeError`をretry対象にしない。
- LLM prompt、Model、reasoning、vision→text fallback順序、成果物内容またはfingerprintを変更しない。
- 新しいretry package、例外Frameworkまたは汎用Adapter Layerを追加しない。
- 旧Run／failure JSONを一括変換せず、Run schema versionも変更しない。
- このChange内でTranslation成果物の内容品質、利用者PDF変換またはComparison Reviewを完了判定しない。それらは受入Changeへ戻って判定する。

## Decisions

### 1. LLM外部境界専用の安全なError型を導入する

`translate/adapters/llm.py`へ、allowlist済みstageと下位例外型だけを保持するLLM Errorを追加する。stageはimage有無から決まる`vision`／`text`と、失敗箇所の`invoke`／`parse`を組み合わせた固定値とする。Error messageにはstageとcause typeだけを含め、raw例外message、endpoint、prompt、response contentおよび画像Dataを保持・表示しない。

既存例外をそのままLifecycleへ渡す案は、今回の`TypeError`のように出所を失い、SDK messageへ秘密やraw応答が含まれる可能性があるため採用しない。汎用外部Service Error階層は、この修正で使用しないAdapterまで変更するため導入しない。

### 2. requestとparseを一回のretry attemptとして扱う

各attemptは、1件の`client.invoke()`、response contentの正規化、およびPydantic parseまでを逐次実行する。次だけをretryableとする。

- `httpx.TransportError`、408、429および5xx。
- `client.invoke()`またはresponse content正規化の外部境界で発生した`TypeError`。
- LLMが返した構造化contentを既存Pydantic parserが解釈できないErrorのうち、allowlistしたparse／validation Error。

retryable Errorは`retry_attempts`、指数backoff、`retry_max_seconds`および`task_deadline_seconds`で制限する。恒久的な4xx、Model／設定構築Error、prompt生成Error、およびAdapter外で生じた`TypeError`は即時失敗させる。retry判定を`structured()`全体へ広げる案は、画像読込みやApplication bugまで外部障害として隠すため採用しない。

### 3. vision fallbackを維持し、最終失敗だけを公開する

STRUCTUREは従来どおり、vision requestが有限retry後も失敗した場合に同じpageをtext-only requestで処理する。text-onlyが成功すればTaskを継続し、回復済みvision Errorをactive failureへ残さない。text-onlyも失敗した場合だけ、最終LLM ErrorをSTRUCTURE page Errorで包み、`page=<number>`、`target_id=page/<number>`、LLM stageおよびcause typeを公開境界へ渡す。

全block IDをfailureへ格納する案はmetadataを肥大化させ本文構造を過剰に公開するため採用しない。page単位Taskなので、安定した`page/<number>`を一つの対象IDとする。

### 4. TaskStatusEventを安全な診断metadataの伝送路にする

TaskStatusEventへoptionalな`stage`と`cause_type`を追加し、Workflowの失敗変換が例外のallowlist済み属性を転記する。Lifecycleはevent値を中央allowlistで検証してFailureRecordへ保存する。Qdrant Registrationは現在のstageとcause typeを同じEvent経路へ正規化し、既存の公開文字列とTestを維持する。

Lifecycleが任意の例外属性を無条件で保存する案は、不正な文字列やraw Errorを永続化できるため採用しない。FailureRecordのfieldはoptionalのままとし、旧JSON読取りと既存CLI／Streamlit表示を後方互換にする。

### 5. retry、診断、redactionおよびResumeを段階的に検証する

最初にAdapter Unit Testでinvoke `TypeError`とparse Errorの回復・上限、試行回数、backoff、恒久4xx即時失敗および境界外TypeError非retryを確認する。次にSTRUCTURE／Workflow Testでpage、target、stage、cause typeとAtomic directoryを確認し、Lifecycle TestでCLI、failure JSON、log、旧JSONおよび秘密非出力を確認する。

自動Testと全品質Gateが成功した後だけ、別Workflow processが0件であることを確認し、受入Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`を同じQdrant Collection、入力、backendおよび外部export先で明示Resumeする。Resume前後でSPLIT〜LOADのaggregate hash、file countおよびlatest mtimeを照合する。Runが再度失敗した場合は追加修正を推測せず、failure Evidenceを記録してApplyを停止する。

## Quality Attribute Design

| ID | Design approach | Trade-off | Verification evidence |
|---|---|---|---|
| Q-FUNC | invoke／parse境界を固定stageで分類し、有限retry後に構造化failureへ変換する | retry対象をallowlistへ限定するため、未知の新Errorは即時失敗する | Adapter retry Test、STRUCTURE failure Test |
| Q-PERF | 既存attempt、backoff、request timeout、deadlineを再利用し、試行を逐次化する | 一時障害時は最大attempt分だけ遅延する | call count、sleep、deadline、同時実行数1 |
| Q-COMP | optional fieldと旧JSON defaultを維持し、fingerprint／checkpointを変更しない | stage種類の追加を消費側が文字列表示できることに依存する | Legacy failure、CLI/UI、Resume互換Test |
| Q-USE | page、安定target、stage、cause typeをCLIへ表示する | raw messageを表示しないため詳細は型と段階に限定される | CLI failure assertion、実Run Evidence |
| Q-REL | Atomic STRUCTURE Artifactとcheckpoint再利用を維持する | STRUCTURE自体はpage 2から再実行する | failure時Artifact 0件、Resume前後hash／mtime |
| Q-SEC | safe Errorへ正規化し、allowlist metadataだけを永続化する | provider固有messageをSupportへ渡せない | sentinelを含むretry／Lifecycle Test、secret scan |
| Q-MAIN | Adapter・Task・Lifecycleの責務を分離し、focused Testへ対応付ける | 小さいError型とstage mappingが追加される | Ruff、Format、ty、pytest、Traceability |
| Q-PORT | 標準Pythonと既存Dependencyだけを使用する | Provider差異はError allowlistの保守対象になる | Windows/POSIX既存Test、Dependency差分0 |

## Lifecycle, Migration and Operations

- 移行: Failure fieldはoptionalのまま固定stageを追加する。schema versionを上げず、既存Runと旧failure JSONを読めることをTestする。
- 運用: 実Run Resumeは自動Test完了後に一度だけ行う。local Modelへ他processが接続していないことを確認し、内部graph `max_concurrency=1`を維持する。
- Support: retry attempt数、最終stage、cause type、pageおよびtargetをEvidenceへ記録する。raw SDK messageや文書内容は保存しない。
- 保守: 新しいprovider Errorをretry対象へ追加する場合は、外部境界由来で一時的である根拠とUnit Testを必須にする。
- 廃止: 対象Run、外部exportおよびQdrant Collectionは削除しない。Apply失敗時も同じRunを後続修正からResume可能に保つ。

## Risks / Trade-offs

- [Risk] Programming由来の`TypeError`を外部障害として繰り返す → `client.invoke`、content正規化およびparser境界内で捕捉したErrorだけを対象にし、Task／prompt構築Errorは即時伝播する。
- [Risk] malformed responseのretryで同じ失敗を反復する → attempt、backoffおよびdeadlineを既存設定で有限化し、上限後は安全なstage付きfailureへ停止する。
- [Risk] vision失敗後のtext fallbackで診断が曖昧になる → 最終failure stageへmodeを含め、成功したfallbackではactive failureを残さない。
- [Risk] Failure schema拡張で旧Runが読めなくなる → fieldをoptionalに保ち、旧field欠落・Registration stage・新LLM stageを同じTest Matrixで検証する。
- [Risk] 実Run Resumeが長時間化または別Errorで停止する → 成功済みArtifact baselineを先に記録し、逐次実行・有限timeout・停止時Evidenceを維持する。
- [Risk] Error contextへ本文や秘密が混入する → page番号、固定target、allowlist stage、class名以外をFailureへ渡さずsentinel scanする。

## Migration Plan

DeployおよびData migrationはない。ApplyではTestを先に追加し、LLM Adapter、STRUCTURE context、TaskStatusEvent、Lifecycleの順に最小実装を行う。focused Testと全品質Gate成功後に同じ実RunをResumeする。RollbackはCode変更を通常のGit revertで戻すことであり、Run Artifactを削除・書換えしない。実Runが完了した場合は、後続Turnで`complete-sample-pdf-acceptance-verification`へ戻り、成果物検査と残Taskを継続する。

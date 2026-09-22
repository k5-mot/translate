<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現在の`structured()`は、Langfuseの`start_as_current_observation(..., as_type="generation")`が作るcurrent OpenTelemetry contextの内側で、LangChainの`client.invoke()`、応答変換、Pydantic parseおよび全retry loopを実行する。Langfuseなしの実page 3は一回で成功した一方、公開ResumeではProviderが完全応答を返した後に`invoke`由来の`TypeError`として6回再送されたため、「Model attempt」と「観測lifecycle」のFailure domainが分離されていない。

導入済みruntimeはLangChain OpenAI 1.6.2、OpenAI SDK 3.16.2、Langfuse 4.15.4である。Langfuseにはcurrent contextをattachする`start_as_current_observation()`に加え、観測を作るがcurrent contextを変更しない`start_observation()`と明示的な`end()`がある。新しいDependencyは不要である。

## Goals / Non-Goals

**Goals:** syntheticなOpenAI互換completionでProvider応答後の境界を再現し、Model処理を観測contextから隔離する。観測障害はwarningへ縮退し、成功済み応答を再送せず、実LLM障害だけに既存の有限retryを適用する。修正を観測有効の短いprobe、実page 3、同一Run Resumeの順に逐次実証する。

**Non-Goals:** Langfuseの全廃、trace内容の拡大、OpenTelemetry／LangChain／OpenAI SDKの更新、別Model／endpointの追加、schema緩和、retry回数増加、並列実行、Run fingerprint／schema変更、page checkpoint version更新およびQdrant状態の固定。

## Decisions

### 1. 実response stackをNetworkなしで差分検証する

`httpx.MockTransport`からOpenAI Chat Completions互換のstrict-schema responseを一件返し、実`ChatOpenAI.bind(...).invoke()`と既存Pydantic parseを通すTest harnessを作る。観測なし、current observationあり、detached observationありの順に同じfixtureを実行し、HTTP call count、result、例外型chainおよび固定module originだけを比較する。

単純なMock clientだけを使う案は、今回疑われるLangChain／OpenAI応答変換とOpenTelemetry contextの相互作用を通らないため採用しない。実Providerを最初の診断に使う案も、再現ごとにlocal GPU時間を消費し、6回再送を招くため採用しない。

### 2. generation観測をcurrent contextから切り離す

`observe()`へ内部用のdetached modeを設け、generation requestでは`start_observation()`で観測を作成し、`update()`と`end()`を明示的に行う。作成時点のcurrent workflow observationはLangfuse側がparent contextとして解決できるが、LangChain／OpenAI呼出し中のcurrent OpenTelemetry contextは変更しない。Workflow／Task spanは従来どおり`start_as_current_observation()`を使う。

全観測を無効化する案は運用上必要なtraceまで失うため採用しない。LangChain callだけを観測context外へ一時退避して同じcurrent managerへ戻す案はOpenTelemetry tokenのattach／detach失敗面を増やすため、Langfuseが公開するnon-current lifecycleを選ぶ。

### 3. 観測lifecycleをModel retryの外側へ置く

一つのgeneration観測は論理LLM request全体を表し、内部のModel attemptは既存`_invoke_with_retry()`だけが管理する。観測のcreate／update／end失敗は既存warning sinkへ一度だけ通知し、Model attempt結果を変更しない。特にschema-validなresponse取得後の`end()`失敗は成功値を返し、Provider call countを増やさない。

transport Error、408、429、5xxおよび既存parse Errorのretry規則は変更しない。未知の`TypeError`を一律に成功扱いする案はprogramming errorを隠すため採用しない。offline differentialがcurrent observation以外の原因を実証した場合も、同じ「応答受領後は観測失敗で再送しない」境界を保ち、実証されたadapter箇所だけを修正する。

### 4. 診断は固定分類値だけを扱う

既存の`_exception_chain_types()`と`_exception_origin()`をTestおよび一時probeの判定へ使用し、型名は最大8件、originは固定集合へ縮約する。製品Failureへ新しいraw message、traceback、module名またはresponseを追加しない。観測warningもaction、例外型、Taskだけを保持する。

### 5. checkpointと公開fingerprintを維持する

今回の修正は観測経路だけで、STRUCTURE生成policyや成果物内容を変えないため、private page checkpointはversion 4のままとする。page 2 checkpointを再利用し、page 3以降だけを処理する。観測設定は成果物へ影響しないため公開fingerprintへ追加しない。

### 6. 実機検証を失敗時停止の逐次Gateにする

自動Gate成功後、観測有効・strict schema・SDK retry 0・timeout 900秒の短いtext requestを一回だけ送る。成功した場合だけ、保存済みpage 3をvision一回、失敗時だけtext一回で検証する。さらに成功した場合だけ同じRunを公開CLIから一度Resumeする。各Gateが失敗した時点で追加requestとResumeを止め、Runを保持する。

## Quality Attribute Design

| ID | Approachとtrade-off | Evidence |
|---|---|---|
| Q-FUNC | 実ChatOpenAI response stackとdetached generation観測を通して完全schemaを返す | offline differential、short probe、page 3、Run結果 |
| Q-REL | 観測create／update／end失敗をwarningへ縮退し、受領済み応答の再送を禁止する | fault injection、HTTP call count 1、Run Failure／checkpoint |
| Q-PERF | Networkなしの診断を先行し、実機はtimeout 900秒・同時1 requestの段階Gateにする | transport count、wall time、queued／parallel |
| Q-COMP | workflow span、Run schema／fingerprint、checkpoint v4、生成policyを維持する | regression Test、public surface／fingerprint差分0件 |
| Q-USE | 観測warningとModel Failureをaction／stage／安全な型とoriginで区別する | warning sink、Failure、sanitized Evidence |
| Q-SEC | raw本文、response、reasoning、Credential、endpoint、tracebackを保存しない | sentinel scan、差分review |
| Q-MAIN／Q-PORT | Langfuse公開APIと既存DependencyだけでFailure domainを分離する | Ruff、Format、ty、全pytest、Dependency差分0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationはない。Run、Failure、checkpointおよび公開Artifactのschemaを変更せず、既存page 2 checkpointを再利用する。
- 運用: Model／Embedding requestは常に逐次とし、各実機Gate前にModel、context 30,208、parallel 1、queued 0／idle、fingerprintを確認する。観測Serviceの不調はwarningとして運用者へ残す。
- 保守／Support: actual response stackのoffline回帰TestでLangChain、OpenAI SDKまたはLangfuse更新時の相互作用を検出する。安全なorigin分類を越える情報は一時診断にも出力しない。
- Rollback: 製品CodeとTestのcommitを通常のGit操作で戻す。Run、private checkpoint、外部exportおよびQdrant Collectionは削除しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldがないため個別廃止処理は不要である。

## Risks / Trade-offs

- [Risk] detached observationでgenerationが期待するparentへ結び付かない → fake／real Langfuse boundary Testでtrace IDとparenting可能性を確認し、本文を送らずmetadataだけを維持する。
- [Risk] synthetic completionでは実Provider固有の応答変換を再現できない → 同じSDK model、strict schema、finish reasonおよびusage envelopeを使用し、続いて一回限りのshort provider probeで補完する。
- [Risk] current observation以外にもpublic workflow固有条件がある → offline差分で原因が再現しない場合も安全なorigin Evidenceをshort probeで取得し、推測の広域修正をせず実証箇所だけを変更する。
- [Risk] warning sink自体の失敗が本処理へ波及する → 既存の二重fail-open処理を維持し、sink failureもlogger warningだけにする。
- [Risk] Resumeが長時間化する → page checkpoint v4を維持し、各Gate失敗後の追加requestを禁止して無駄なGPU処理を避ける。

## Migration Plan

1. Runとruntimeを読取り専用でbaseline化し、actual response stackのoffline differentialを失敗先行で追加する。
2. generation観測をdetached lifecycleへ変更し、観測fault、Model retry、call count、秘密非出力のfocused Testを成功させる。
3. 全品質Gateとstrict validationを成功させる。
4. 観測有効のshort provider probeを一回だけ実行し、成功時だけ実page 3を逐次検証する。
5. page 3成功時だけ同じRunを公開CLIから一度Resumeし、成果物、Lifecycle、Securityを検査する。
6. 失敗時はRunを保持して次の原因に対する別ChangeへEvidenceを引き渡す。成功時は本Changeをverify／archiveし、残る受入Changeを継続する。

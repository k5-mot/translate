<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現在の`structured()`は全用途でPydantic schemaをprompt本文へ埋め込み、`ChatOpenAI`へ`reasoning_effort`を渡した後、通常text応答を`PydanticOutputParser`で検証する。STRUCTUREはvision失敗後にtext-onlyへ逐次fallbackするが、両方とも`low` reasoningかつ非制約生成であり、page 3では各16,384 output tokensを使い切った。

ローカル実機ではGemma 4の公開reasoning optionが`off,on`、既定値が`on`である。CLIの`off`は2 tokensで正常停止した。OpenAI互換Chat Completionsは`reasoning_effort=off`を400で拒否した一方、`reasoning_effort=none`を受理してreasoning 0 tokensで停止し、`StructureResponse.model_json_schema()`をstrict `response_format`へ指定したprobeも15 completion tokensでPydantic検証に成功した。LM Studioはcontext 30,208、parallel 1で動作し、Model／Embeddingの並行利用は許容しない。

## Goals / Non-Goals

**Goals:** STRUCTUREのvision／textをthinkingなしのschema-constrained generationへ限定し、完全な`StructureResponse`だけを採用する。既存のstage診断、有限retry、vision→text fallback、Atomic publishおよび同じRunからのResumeを維持する。生成条件が異なる旧private page checkpointは決定的に無効化する。

**Non-Goals:** Translation、Review、FIX、VERIFYまたはALIGNのreasoning policy変更、出力token増加、別Model／Providerへの切替え、native `/api/v1/chat`への移行、並列化、parse緩和、公開設定／CLI追加、Run schema／fingerprint変更、既存Failure変換、Word-to-PDF処理およびQdrant状態変更。

## Decisions

### 1. 共有Adapterへ明示的なschema modeを追加し、STRUCTUREだけで有効化する

`structured()`へ後方互換な明示引数を追加し、既存のprompt-based modeと、OpenAI互換`response_format.type=json_schema`を使うschema-constrained modeを区別する。後者は`response_type.model_json_schema()`を`json_schema.schema`へ、型名を`json_schema.name`へ、`strict=true`をProvider requestへ渡す。STRUCTUREだけがこのmodeを指定し、他Taskは既存modeを維持する。

schema-constrained modeではPydanticのformat instructionをsystem promptへ重複埋込みせず、Providerが返す通常のmessage contentを既存Parserでもう一度検証する。`ChatOpenAI.with_structured_output()`ではなく`bind(response_format=...)`を選ぶ。これによりraw message自体を永続化せず、既存の`response_metadata`からfinish reasonとtoken usageを取得して`length`をparseより先に分類できる。

代替案の全Task一括schema化は、未検証のTranslation／Review挙動まで変えるため採用しない。prompt短縮だけでは出力の有限性を保証できず、出力token増加は30,208 context内の入力余地を減らすため採用しない。native APIへの移行はresponse型、認証、観測およびretry境界を広く変更するため対象外とする。

### 2. STRUCTUREのreasoning effortは固定値`none`とする

STRUCTUREのvisionとtextの両呼出しへ`reasoning="none"`を指定する。`none`は現在のOpenAI互換endpointで実測済みであり、Gemma 4のreasoningを0 tokensへ抑制した。`off`は同endpointで400となるため使用しない。Translation等の`high`およびALIGNの`low`は維持する。

Adapterのreasoning引数は許容Literalへ狭め、意図しない値をTestと型検査で検出する。Providerが`none`またはschemaを拒否した場合は400を恒久Errorとして即時停止し、既存の安全なstage／causeだけをRunへ伝播する。自動的にreasoning `on`や非制約生成へ戻してはならない。

### 3. page checkpointは生成policyとschemaへ結び付ける

`PAGE_CHECKPOINT_VERSION`を更新し、keyへreasoning effort、schema mode、およびcanonical JSONでhashした`StructureResponse` schemaを含める。これにより旧`low`／非制約生成のpage 2 checkpointを同じRunで再利用せず、変更後に生成・検証したpageだけを再利用できる。

公開Run fingerprintは変更しない。この変更は利用者設定ではなく不適合実装の固定修正であり、Run全体を拒否すると既完了SPLIT～LOADを安全に再利用できない。STRUCTURE Taskは未完了なので、private page checkpointだけを新policyで再計算し、公開Task完了は従来どおり全pageのAtomic publish後に記録する。

### 4. 実証は短いcontract probe、page 3 probe、full Resumeの順に行う

Mock Testと品質Gateの後、LM Studioのloaded model、context 30,208、parallel 1、queued 0／idleを確認する。まず秘密や本文を出力しない短いrequestで`none`、strict schema、reasoning 0およびschema-validを確認する。次に保存済みpage 3相当をRun外一時directoryでvision→必要時のみtextの順に各一回、同時request 1、request timeout 900秒、既存Task deadline内で実行する。

page 3で完全なschema応答を得た場合だけ、fingerprintと既完了Artifact baselineを確認して同じrun IDを公開CLIから一度Resumeする。probeまたはResumeが失敗した場合は追加Model requestを行わず、RunをResume可能なまま保持し、mode、stage、finish reason、数値usage、attempt、schema適合性およびwall timeだけをverificationへ記録する。

## Quality Attribute Design

| 品質ID | Design approach／Trade-off | 検証Evidence |
|---|---|---|
| Q-FUNC | STRUCTUREだけに`none`とstrict schemaを適用し、Pydantic再検証後だけ採用する | request契約Test、parse／truncation Test、page 3 probe、同一Run結果 |
| Q-PERF | reasoning 0を要求し、出力token増加と並列化を行わない。旧page checkpointの再計算costは正しさのため受容する | completion／reasoning usage、wall time、queued／parallel、再計算page数 |
| Q-COMP | Run fingerprint／schemaを維持し、private page keyだけversion化する | fingerprint diff 0件、旧page miss／新page hit、SPLIT～LOAD hash／mtime |
| Q-USE | 既存のTask／page／stage／causeと安全なfinish／usageで停止理由を示す | Failure表示Test、Evidenceのallowlist確認 |
| Q-REL | Provider拒否で暗黙fallbackせず、vision→textだけを有限・逐次で許可する | call順序／回数、400即時失敗、部分公開0件、Resume Test |
| Q-SEC | raw prompt、本文、reasoning、response、Credential、endpoint、画像を保存しない | repository／Test output／Run metadata／logの秘密scan |
| Q-MAIN／Q-PORT | Adapterのmodeを明示型にし、既存SDK機能だけを使う | Ruff、Format、ty、全pytest、Dependency diff 0件、Windows固有製品分岐0件 |

## Lifecycle, Migration and Operations

- 移行: Data migrationは行わない。同じRunの旧private STRUCTURE page checkpointはkey不一致として無視し、新policyで再作成する。公開Artifact、Failure、run metadataおよび外部exportは変換しない。
- 運用: Model／Embedding requestは常に逐次とし、Resume前にloaded instanceのcontext、parallel、queueおよびfingerprintを確認する。full Resumeはprobe成功後の一回に限定する。
- 保守／Support: Provider contractをMockで固定し、実機Evidenceはallowlistされた数値と分類値だけを保存する。LM Studio更新後もcontract probeで`none`とJSON Schemaを確認できるようにする。
- Rollback: Code commitを通常のGit操作で戻す。Run dataは削除せず、rollback後に旧page checkpointを強制利用する操作は提供しない。
- 廃止: 新規Service、Package、公開optionおよび永続fieldを追加しないため個別廃止処理は不要である。既存Run削除は利用者の明示操作だけに従う。

## Risks / Trade-offs

- [Risk] Modelが複雑な実pageで`none`時に構造判断品質を落とす → page 3 probeと既存rule-based補正、Pydantic schema、auditおよび最終Reviewで検証し、schema-validだけでは受入れない。
- [Risk] LM Studioまたは別OpenAI互換Providerが`reasoning_effort=none`／strict schemaを拒否する → 400を即時・安全に失敗させ、thinking有効やprompt-onlyへ暗黙fallbackしない。Provider差異の一般化は別Changeとする。
- [Risk] 旧page checkpoint無効化で358ページRunの再処理時間が増える → correctnessを優先して受容し、新policyで成功したpageはAtomic checkpointへ保存して以後のResumeで再利用する。
- [Risk] JSON Schemaの`$defs`、nullable fieldまたはdefaultのProvider解釈が変わる → 実際の`StructureResponse.model_json_schema()`を使うcontract probeとMock payload assertionをGateにする。
- [Risk] 既存の16,384-token診断がreasoning本文をmessage contentとして数えた可能性がある → 修正の受入れはreasoning 0、`finish_reason=stop`、完全schemaおよびPydantic検証の組合せで判定する。

## Migration Plan

1. Failing-first TestでSTRUCTUREが`none`とstrict `response_format`を要求し、他Taskのpolicyが変わらないことを固定する。
2. Adapterのschema modeとSTRUCTURE呼出しを実装し、page checkpoint version／keyを更新する。
3. Focused Test、全品質Gate、Security scanおよびOpenSpec strict validationを実行する。
4. idleなlocal runtimeで短いcontract probeとpage 3 probeを逐次実行する。失敗時はRunを変更せず停止する。
5. 成功時だけ既存Runを一度Resumeし、DOCXとdiagnostic Artifact、Lifecycle、既完了Artifact保護を検証する。
6. Rollback時は製品Codeを戻し、Runと外部exportを保持する。新policyのprivate page checkpointは旧Codeからkey不一致で無視される。

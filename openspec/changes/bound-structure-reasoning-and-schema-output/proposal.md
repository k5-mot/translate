<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFのSTRUCTURE page 3をRun外で逐次再現したところ、visionとtextの両経路が各16,384 output tokensを使い切り、`finish_reason=length`のためschema応答を完成できなかった。現在のGemma 4はreasoning既定値が`on`だが、OpenAI互換APIの`reasoning_effort=none`とJSON Schema制約を併用した短い実機probeではreasoning 0 tokensかつschema-validで停止したため、この確認済み経路へSTRUCTUREだけを限定して同じRunを回復させる。

## What Changes

- STRUCTUREのvision／text両requestだけを`reasoning_effort=none`で実行し、Translation、Review、FIXおよびALIGNの既存reasoning設定は変更しない。
- STRUCTURE応答へPydantic model由来のstrict JSON Schemaを指定し、schemaに適合する完全なJSONだけを採用する。`finish_reason=length`、parse失敗、Provider拒否およびtransport障害は既存の安全なstage／cause分類と有限retryへ渡す。
- reasoning modeとschema制約をpage checkpoint keyへ含めてversionを更新し、旧アルゴリズムで作成したprivate STRUCTURE page checkpointは再利用しない。Run fingerprint、run ID、SPLIT～LOADの公開Artifactおよび外部exportは維持する。
- Mock／focused／全品質Gateの後、保存済みpage 3 payloadでvision→textを同時request 1で実証する。成功時だけ既存Run `01a0c97c-f5cf-7031-b808-4ad545133925`を公開CLIから一度明示Resumeし、失敗時は追加Resumeせず状態を保持する。
- 新規Package、別Model、並列処理、公開CLI option、Run schemaおよびWord-to-PDF処理は追加しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。正本の`pdf-translation`は検証済み日本語DOCXの生成を、`run-lifecycle`は有限retry、安全なFailure、Atomic Artifactおよび互換RunのResumeを既に要求している。本Changeは、その契約を満たせずSTRUCTUREで停止する実装の修正であり、Spec Levelの振る舞いを変更しないため`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 対象Code: `translate/adapters/llm.py`のstructured output境界、`translate/tasks/structure.py`のreasoning指定とpage checkpoint key、および対応するAdapter／STRUCTURE／Lifecycle Test。
- 対象System: ローカルLM StudioのOpenAI互換Chat Completions、`google/gemma4:12b`、既存UUIDv7 Runとprivate page checkpoint。Docling、Qdrant、Embedding、LibreTranslateおよびLangfuseは変更しない。
- Dependency、公開API、Run layout、成果物形式、設定項目およびData migrationは追加しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 同じrun IDと入力を保持し、context 30,208、parallel 1、queued 0／idle、他Model／Embedding request 0件を確認して明示Resumeする。再失敗時はDOCXを公開せずResume可能な状態を維持する。
- 取得／供給: 現在lock済みのLangChain、OpenAI SDK、PydanticおよびLM Studio機能だけを使用し、Dependency差分を0件にする。
- 移行: 公開Run schemaとfingerprintは変更しない。STRUCTUREの生成条件が変わるためprivate page checkpoint versionを更新し、旧page結果は安全に再計算する。SPLIT～LOADの成功済みTaskは再利用する。
- Support／保守: mode、stage、finish reason、数値usage、schema適合性およびwall timeだけをEvidenceに残し、raw prompt、本文、reasoning、response、Credential、endpointおよび画像binaryを保存しない。
- 廃止: Run、入力copy、外部exportおよびQdrant Collectionは自動削除しない。rollbackは通常のGit操作とし、利用者の明示削除規則を維持する。

## Quality Considerations

- Q-FUNC（機能適合性）: visionまたはtextから完全な`StructureResponse`だけを採用し、page 3の実probeと同一Run ResumeでSTRUCTURE通過を確認する。truncated／不正schema採用は0件とする。
- Q-PERF（性能効率性）: Model／Embedding同時request最大1、各request timeout 900秒、Task deadline 21,600秒を維持し、旧page checkpoint無効化による再計算page数、usageおよびwall timeを記録する。
- Q-COMP（互換性）: run ID、fingerprint、Run schema、既存Failure、SPLIT～LOAD ArtifactおよびCLI／Streamlit共通Runの互換性を回帰Testする。旧STRUCTURE page checkpointだけを意図どおり再利用しないことを確認する。
- Q-USE（使用性）: 失敗時にTask、page、target、stage、cause type、finish reasonおよび安全なtoken usageから運用判断できることを確認する。
- Q-REL（信頼性）: reasoning無効化、schema制約、vision→text fallback、有限retryおよびAtomic publishをTestし、無制限retryと部分Artifact公開を0件にする。
- Q-SEC（Security）: Test、console、Failure、log、checkpointおよびEvidenceへのCredential、endpoint、prompt、本文、reasoning、raw response、traceback、画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: STRUCTURE固有policyを共有Adapterの明示引数で表現し、新規DependencyとOS固有の製品分岐を0件にする。Ruff、Format、ty、全pytestおよびOpenSpec strict validationを成功させる。
- Interaction capability、SafetyおよびFlexibilityは公開操作や自律Actionを増やさないため新規評価対象外とし、既存回帰Testで確認する。

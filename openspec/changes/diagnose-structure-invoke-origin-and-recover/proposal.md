<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

有界visionとpage checkpointを導入した実Translation Runでも、page 3のtext fallbackが27分後に`text-invoke`／`TypeError`で再停止した。現行Failureは安全だが下位originを区別できず、再現可能な原因と最小修正を確定できないため、同じRunを推測で繰り返さず診断境界を一段だけ深める必要がある。

## What Changes

- `text-invoke`の`TypeError`について、raw messageやtracebackを永続化せず、例外chainの型とtraceback moduleをallowlistされたorigin分類へin-memoryで正規化し、原因が製品request、LangChain／OpenAI SDK、transportまたはlocal runtimeのどこにあるかを単発・逐次probeで確定する。
- 確定した原因をMockまたは保存済みpage 3 payloadで先に再現し、該当境界だけを最小修正する。一般的な`TypeError`の無差別retry、parse緩和、別Modelへの切替えは行わない。
- vision側とtext側の各最終結果を安全な分類値、attempt数、wall time、finish reasonおよび数値usageだけで検証し、Run Failure、Atomic Artifact、page checkpoint、fingerprintおよび逐次実行契約を維持する。
- 品質・Security gateとLM Studioのcontext 30,208／parallel 1／idleを確認した後、既存Run `01a0c97c-f5cf-7031-b808-4ad545133925`を一度だけ明示Resumeする。再失敗時はRunを保持し、追加ResumeせずEvidenceを残す。
- 公開CLI option、Run layout、成果物形式、Model、token予算、DependencyおよびWord-to-PDFの利用者運用は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。正本の`pdf-translation`は読取り可能なPDFから検証済みDOCXを生成する契約を、`run-lifecycle`は有限retry、安全な原因表示、Atomic ArtifactおよびResumeを既に要求している。本Changeは未達実装の原因特定と適合修正であり、Spec Levelの振る舞いを変更しないため`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 対象Code: `translate/adapters/llm.py`、必要な場合だけ`translate/tasks/structure.py`とFailure伝播。TestはLLM Adapter、STRUCTURE、Lifecycleおよび既存Run互換性を対象とする。
- 対象System: ローカルLM Studioの`google/gemma4:12b`、保存済みRunとpage checkpoint。Qdrant、Docling、既完了Artifactおよび外部exportは変更しない。
- 新規Package、Service、公開interface、Data migrationおよび並行処理は追加しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 同じrun IDを保持し、context 30,208、parallel 1、他request 0件、900秒request timeoutで明示Resumeする。再失敗時は自動再実行しない。
- 取得／供給: 現在lock済みのLangChain、OpenAI SDK、PydanticおよびLM Studioだけを使用し、Dependency差分を0件にする。
- 移行: Run schema、fingerprint、既存Failureとpage checkpointを変換しない。診断分類が製品に残る場合もoptionalかつ旧形式を読取り可能にする。
- Support／保守: raw message、prompt、本文、reasoning、raw response、endpointおよび画像binaryを保存せず、固定originとcause typeで再現Testへ結び付ける。
- 廃止: Run、外部export、入力copyおよびQdrant Collectionは自動削除しない。rollbackは通常のGit操作とし、利用者の明示削除規則を維持する。

## Quality Considerations

- Q-FUNC（機能適合性）: page 3相当の再現Testと実RunでSTRUCTUREを通過し、最終Translation成果物または安全な再現原因を100%特定する。
- Q-REL（信頼性）: retryは既存有限上限内、同一modeの無制限再試行0件、失敗時の部分公開0件、成功済みArtifact再計算0件とする。
- Q-PERF（性能効率性）: Model／Embedding同時request最大1、各request timeout 900秒、Task deadline 21,600秒を維持し、attemptとwall timeを計測する。
- Q-COMP（互換性）: fingerprint、旧Failure JSON、既存page checkpointおよびCLI／Streamlit共通Runの互換性を自動Testする。
- Q-USE（使用性）: SupportがTask、page、target、stage、cause typeおよび固定originだけで次の処置を判断できることを検証する。
- Q-SEC（Security）: Test、console、Failure、log、checkpointおよびEvidenceのCredential、endpoint、prompt、本文、reasoning、raw response、traceback、画像binary漏えい0件をscanする。
- Q-MAIN／Q-PORT（保守性／移植性）: 原因を再現するTestを先行し、Ruff、Format、ty、全pytest、OpenSpec strict validationを成功させ、新規DependencyとOS固有の製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作や自律Actionを増やさないため新規評価対象外とし、既存回帰Testで確認する。

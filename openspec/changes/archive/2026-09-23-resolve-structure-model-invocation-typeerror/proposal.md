<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

900秒timeoutで単発のSTRUCTURE page 3テキストprobeは成功したが、新規Translation Run `01a0c97c-f5cf-7031-b808-4ad545133925`は同pageのvision失敗後、text fallbackの`text-invoke`で`TypeError`となり停止した。現行の安全なFailure記録からは発生元を特定できないため、同Runを盲目的にResumeせず、再現可能な原因を特定して最小修正を行う。

## What Changes

- 保存済みpage 3と同じSTRUCTUREのvision／text呼出しを、同時Model request 1件、request timeout 900秒、有限Task deadlineで個別に再現し、例外型、既知SDK境界、HTTP status有無、attempt数、finish reasonおよび数値token usageだけを安全なEvidenceへ記録する。raw message、prompt、文書本文、response、画像binaryおよびendpointは記録しない。
- 原因が製品のrequest構築、LangChain／OpenAI互換応答処理またはfallback制御にあると確認できた場合、その境界だけを修正し、原因を再現する失敗Testを先に追加する。Model／Server設定またはProvider側に原因がある場合は設定上の処置を明示し、製品コードへ推測の回避策を加えない。
- visionとtextの両方が失敗した場合、既存の安全なTask／page／target／stage／cause typeを保ちつつ、片方の失敗だけを見て誤判定しないよう診断Evidenceを整える。成功したfallbackは従来どおり処理を継続する。
- 自動品質Gate後に同じUUIDv7 Runを明示Resumeし、既完了SPLIT〜LOAD Artifactを再実行せず、STRUCTURE以降の進行と失敗時Atomic境界を検証する。再失敗時は追加の推測修正や無制限retryをせず停止する。
- 公開CLI option、Run layout、fingerprint、成果物形式、token予算、Model、Dependencyおよび逐次実行方針は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`establish-translate-ja-contracts`の`pdf-translation`と`run-lifecycle`には、読取り可能なPDFのTranslation、外部障害の有限retry、安全な原因表示およびResumeの契約が既にある。本Changeはその実装・運用適合を確認して修正するため、`.openspec.yaml`で`skip_specs: true`を指定する。

## Impact

- 実Run: `runs/01a0c97c-f5cf-7031-b808-4ad545133925/`の失敗記録とcheckpointを保持して使用する。旧token設定のRunは変更しない。
- 製品境界: 必要と確認された場合に限り`translate/adapters/llm.py`、`translate/tasks/structure.py`および安全なFailure伝播を最小変更する。
- Test／運用: Adapter、STRUCTURE、Lifecycleのfocused Test、全pytest、Ruff、Format、ty、OpenSpec strict validation、逐次実Model確認。
- 新規外部Service、Package、Data migrationおよび公開interface変更はない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: Runを自動的に作り直さず、現Runの失敗Taskから再開できるかを確認する。900秒timeoutは実行時設定として明示し、製品既定値はこの障害の原因と断定しない。
- 取得・供給: 既存LangChain、OpenAI互換API、LM StudioおよびModelだけを使用する。新しいDependencyやProviderは取得しない。
- 移行: Failureの旧形式、fingerprintおよび既存Artifactを変換しない。必要な診断fieldがあればoptionalかつ後方互換にする。
- Support／保守: 根本原因と再現条件を安全な分類値とTestで追跡する。raw SDK messageまたは本文を恒久保存しない。
- 廃止: 新旧Run、外部exportおよびQdrant Collectionは自動削除しない。原因が環境側なら製品コードを変更せず、その制約を記録して引き渡す。

## Quality Considerations

- Q-FUNC: page 3相当の実STRUCTURE経路が成功するか、失敗境界と再現可能な原因が特定されることをfocused Testと実Runで確認する。
- Q-PERF: request timeout 900秒、有限retry／deadline、同時Model／Embedding request最大1件を維持し、wall timeとattempt数を測る。
- Q-COMP: 既存Run、fingerprint、CLI／Streamlit Failure読取りおよび旧Failure JSONの互換性をTestする。
- Q-USE: Run ID、Task、page、target、vision／text stageと安全な原因だけで次の運用判断ができることを確認する。
- Q-REL: 成功済みArtifactのhash／mtime不変、失敗時の途中Artifact公開0件、明示Resumeのcheckpoint再利用を確認する。
- Q-SEC: prompt、本文、reasoning、raw応答、Credential、endpointおよび画像binaryのEvidence／log／Failure漏えい0件を検査する。
- Q-MAIN／Q-PORT: 原因を再現するTest、Ruff、Format、ty、全pytestおよびstrict validationを通し、新規DependencyとOS固有処理を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作や自律Actionを増やさないため、新規評価対象とせず既存回帰Testで確認する。

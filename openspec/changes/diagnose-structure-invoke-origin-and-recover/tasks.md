<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline and Runtime Evidence

- [x] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のstatus、Failure、fingerprint、page checkpoint、SPLIT〜LOADのfile数／aggregate hash／latest mtime、公開Artifactおよび外部exportを読取り専用で再取得し、前回Evidenceとの差分0件を`verification.md`へ記録する（Q-COMP／Q-REL、移行・廃止Evidence）
- [x] 1.2 LM StudioのModel、管理context、推論process context、parallel、queued／statusおよび再失敗時刻周辺のruntime logを確認し、生logを転記せずprocess終了、HTTP status有無、finish reason、既知exception型、assertion有無の固定値だけを記録する。Credential、endpoint、本文、response、pathおよびline textの保存0件をscanする（Q-PERF／Q-SEC、運用・Support Evidence）

## 2. Sequential Root-Cause Classification

- [x] 2.1 例外chain型とtraceback moduleをmemory内だけで確認し、`application`／`langchain`／`openai-sdk`／`transport`／`local-runtime`／`unknown`へ正規化する診断wrapperをTestまたは一時probe境界に用意する。raw message、function、path、line、prompt、本文、responseおよび画像がconsole／Fileへ出ないことをsentinel Testで確認する（Q-USE／Q-SEC）
- [x] 2.2 1.2だけでoriginを確定できない場合、保存済みpage 3 payloadをRun外一時directoryで有界vision→textの順に各一回、同時request 1、timeout 900秒、既存Task deadlineで実行し、mode、stage、origin、chain type、attempt、status有無、finish reason、数値usage、wall timeおよびschema適合だけを記録する。確定できる場合は追加Model requestを行わず`NOT NEEDED`と理由を記録する（Q-FUNC／Q-PERF／Q-SEC）
- [ ] 2.3 1.2／2.2を現行Adapter、lock済みLangChain／OpenAI SDKおよびLM Studio境界と照合して再現可能な原因を一つに分類する。`unknown`または非再現の場合は推測修正とfull Run Resumeを行わず未完了で停止し、追加権限やSpec変更が必要なら別Change条件を記録する（Q-MAIN／Q-USE、保守Evidence）

## 3. Failing-First Correction

- [ ] 3.1 確定したstage／origin／causeをclient stub、HTTP fixtureまたは保存済みpayloadの最小境界で再現する失敗Testを先に追加し、修正前に意図した一件だけが失敗すること、raw値がTest outputへ漏れないことを確認する（Q-FUNC／Q-SEC）
- [ ] 3.2 製品原因ならrequest構築、既知response正規化またはretry判定の該当境界だけを最小修正し、3.1を成功させる。環境原因なら製品コードを変更せずLM Studioの具体的処置を適用し、同じ診断probeで解消を確認する。一般的`TypeError`の無差別retry、parse緩和、別ModelおよびDependency追加を0件にする（Q-REL／Q-MAIN、取得・供給Evidence）
- [ ] 3.3 transport／408／429／5xxの有限retry、決定的request／SDK `TypeError`の即時停止、vision成功、vision失敗後text成功、両失敗、旧Failure読取り、Atomic Artifact、page checkpoint再利用およびfingerprint不変をfocused Testで確認する（Q-REL／Q-COMP）

## 4. Quality and Security Gate

- [ ] 4.1 `ruff check .`、`ruff format --check .`、`ty check`、focused pytest、全pytestおよび`openspec validate diagnose-structure-invoke-origin-and-recover --strict`を成功させ、Dependency差分0件、OS固有製品分岐0件、Model／Embedding同時request最大1を記録する（Q-MAIN／Q-PORT）
- [ ] 4.2 診断probe、Test output、Run Failure／log／metadata、checkpointおよびChange EvidenceをCredential、endpoint、prompt、文書本文、reasoning、raw response、traceback、path、画像binaryのsentinelでscanし、漏えい0件を記録する（Q-SEC、Support Evidence）

## 5. Targeted Proof, Resume and Handoff

- [ ] 5.1 context 30,208、parallel 1、queued 0／idle、他Model／Embedding request 0件、fingerprint一致およびArtifact baseline不変を確認し、page 3相当の有界vision→text probeを各mode一回・逐次で実行して完全なschema応答、Failureなし、attempt、usageおよびwall timeを安全に記録する。probe失敗時はfull RunをResumeしない（Q-FUNC／Q-PERF、運用Evidence）
- [ ] 5.2 5.1成功時だけ900秒request timeoutで同じrun IDを公開CLIから一度明示Resumeし、page 2再推論0件、page 3以降のcheckpoint、SPLIT〜LOAD hash／mtime不変、Failure、公開Artifact、Run output、外部export、進捗およびwall timeを記録する。再失敗時はRunを保持して追加Resumeしない（Q-REL／Q-COMP、移行・rollback Evidence）
- [ ] 5.3 実結果を`resolve-structure-model-invocation-typeerror`、`bound-structure-vision-and-recover-truncation`、`align-llm-token-budget-and-truncation-diagnostics`および`complete-sample-pdf-acceptance-verification`へ引き渡し、未完了Taskを実証結果だけで更新する。Word-to-PDF変換、目視比較およびComparison Reviewを本Changeで完了扱いにせず、Run／export／Qdrantの自動削除0件を確認する（Q-USE、Support・保守・廃止Evidence）

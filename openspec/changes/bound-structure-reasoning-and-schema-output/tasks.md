<!-- markdownlint-disable MD013 MD041 -->

## 1. Failing-First Provider and Resume Contracts

- [ ] 1.1 Adapter Testを先に追加し、schema-constrained modeが`reasoning_effort=none`、`response_format.type=json_schema`、実Response型のschema／name、`strict=true`を一回のrequestへ渡し、format instructionをpromptへ重複追加しないことを失敗確認する（Q-FUNC／Q-PERF／Q-MAIN）
- [ ] 1.2 Adapter Testでschema-constrained modeも`finish_reason=length`をparse前に`output-truncated`へ分類し、Pydantic不適合、400、retryable transport Errorおよび安全なusage診断が既存契約どおりであることを失敗確認する（Q-REL／Q-USE／Q-SEC）
- [ ] 1.3 STRUCTURE Testでvisionとtextがともに`none`＋schema-constrained modeを使用し、vision失敗時だけtextへ逐次fallbackし、Translation／Review／FIX／VERIFY／ALIGNの既存reasoningとmodeが変わらないことを失敗確認する（Q-FUNC／Q-COMP／Q-PERF）
- [ ] 1.4 page checkpoint Testで旧version、異なるreasoning、異なるschema modeまたはschema hashを再利用せず、新policyの同一keyだけを再利用し、Run fingerprintが不変であることを失敗確認する（Q-COMP／Q-REL、移行）

## 2. Bounded STRUCTURE Generation

- [ ] 2.1 `translate/adapters/llm.py`へ型付きreasoning effortと後方互換なschema modeを実装し、schema mode時だけ`ChatOpenAI.bind(response_format=...)`を使用して通常messageのfinish／usage抽出とPydantic再検証を維持し、1.1～1.2を成功させる（Q-FUNC／Q-REL／Q-MAIN）
- [ ] 2.2 `translate/tasks/structure.py`のvision／text両経路を`reasoning="none"`とschema-constrained modeへ切り替え、非制約生成への暗黙fallbackと同時requestを追加せず1.3を成功させる（Q-FUNC／Q-PERF／Q-REL）
- [ ] 2.3 STRUCTURE page checkpoint versionを更新し、reasoning effort、schema modeおよびcanonicalな`StructureResponse` schema hashをkeyへ含め、旧pageを無視して新pageをAtomic再利用できるよう1.4を成功させる（Q-COMP／Q-REL、移行／Rollback）
- [ ] 2.4 公開Run schema、fingerprint、CLI option、Dependencyおよび他Task requestの差分が0件であることを差分Reviewと既存Testで確認する（Q-COMP／Q-MAIN／Q-PORT、取得／供給）

## 3. Quality, Security and Lifecycle Gates

- [ ] 3.1 LLM Adapter、STRUCTURE、checkpoint、FailureおよびResumeのfocused Testを実行し、request回数／順序、400即時停止、有限retry、truncation非採用、旧page miss、新page hitおよび部分Artifact公開0件を確認する（Q-FUNC／Q-REL／Q-COMP）
- [ ] 3.2 Ruff check、Ruff format check、tyおよび全pytestを実行して全件成功させ、新規DependencyとOS固有の製品分岐が0件であることを確認する（Q-MAIN／Q-PORT）
- [ ] 3.3 Test output、console、Failure、run metadata、checkpoint、logおよびChange Evidenceをscanし、Credential、endpoint、prompt、本文、reasoning、raw response、tracebackおよび画像binaryの漏えい0件を確認する（Q-SEC／Q-USE、Support）
- [ ] 3.4 `openspec validate bound-structure-reasoning-and-schema-output --strict`を成功させ、正本Specに未同期deltaがなく`skip_specs: true`が実装修正の範囲と一致することを確認する（Q-MAIN、保守）

## 4. Sequential Local Runtime Proof

- [ ] 4.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のinput hash、fingerprint、SPLIT～LOAD Artifact hash／mtime、Failure、公開STRUCTURE欠落および外部output欠落をread-onlyでbaseline化し、LM Studioが対象Gemma 4、context 30,208、parallel 1、queued 0／idleで他Model／Embedding request 0件であることを確認する（Q-COMP／Q-PERF／Q-SEC、運用）
- [ ] 4.2 秘密と本文を出力しない短いOpenAI互換contract probeを一回だけ実行し、`reasoning_effort=none`、実`StructureResponse` strict schema、`finish_reason=stop`、reasoning 0、schema-validおよび有限wall timeを記録する。失敗時は以後のModel probeとResumeを行わない（Q-FUNC／Q-PERF／Q-REL）
- [ ] 4.3 4.2成功後、保存済みpage 3相当をRun外一時directoryでvision→必要時だけtextの順に各一回、同時request 1、request timeout 900秒、既存Task deadline内で実行し、完全schema、mode、stage、attempt、finish reason、数値usageおよびwall timeだけを記録する。失敗時はRunを変更せず停止する（Q-FUNC／Q-PERF／Q-SEC）

## 5. Same-Run Recovery and Handoff

- [ ] 5.1 4.3成功後だけbaselineとfingerprintを再確認し、公開CLIの`--resume 01a0c97c-f5cf-7031-b808-4ad545133925`を一度実行する。Model／Embeddingを逐次処理し、停止時は追加ResumeせずFailureとprivate page checkpointを保持する（Q-REL／Q-COMP／Q-PERF、運用）
- [ ] 5.2 Resume成功時は全Task完了、検証済みDOCX／Markdown／診断Artifact、表紙の一重出力、進捗100%、Atomic Artifact、旧SPLIT～LOAD保護および外部export境界を検査し、失敗時はTask／page／stage／causeと再開可能性を安全に記録する（Q-FUNC／Q-REL／Q-USE／Q-SEC）
- [ ] 5.3 `verification.md`へMock／品質Gate／Security scan／runtime probe／Resume／Lifecycle／移行／Rollback Evidenceとtask対応を記録し、残課題が0件の場合だけ後続Changeのacceptance taskへ成果物を引き渡す（Q-MAIN、保守／Support／廃止）

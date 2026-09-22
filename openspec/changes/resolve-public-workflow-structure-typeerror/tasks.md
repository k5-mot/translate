<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline and Reproduction Contract

- [ ] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のfingerprint、入力SHA-256、Failure、LangGraph checkpoint／writes、page checkpoint、SPLIT～LOAD file count／aggregate hash／latest mtime、公開Artifact、Run outputおよび外部exportを読取り専用で記録し、baseline取得による変更0件を確認する（Q-COMP／Q-REL、移行・廃止）
- [ ] 1.2 LM StudioのModel、context 30,208、parallel 1、queued 0／idle、Application timeout／deadline／retry、SDK retry 0、およびlock済みLangGraph／Langfuse／OpenTelemetry／LangChain OpenAI／OpenAI SDK versionを秘密・endpointなしで記録する（Q-PERF／Q-SEC、取得・運用）
- [ ] 1.3 成功した直接page 3 probeと失敗した公開Resumeについて、worker、SQLite Resume、node wrapper、ContextVar、進捗／Failure callbackおよび観測lifecycleの差だけをEvidence tableへ固定し、本文・raw応答を比較対象にしない（Q-USE／Q-SEC、Support）

## 2. Failing-First Real Graph and SDK Boundary

- [ ] 2.1 OS一時workspaceへ実`SqliteSaver`のpending STRUCTURE checkpointを作るTest fixtureを追加し、実Translation `build_graph()`／node wrapper／`compiled.stream(None, config)`がSPLIT～LOADを再実行せずSTRUCTUREだけからResumeすることを確認する（Q-FUNC／Q-COMP）
- [ ] 2.2 2.1へ実Langfuse span exporter、実ChatOpenAI／OpenAI SDK stackおよび`httpx2.MockTransport`のstrict-schema responseを結合し、修正前の成功またはTypeErrorを、Network 0件、Provider call、response return、parse、node returnおよびcheckpoint commitのcountで失敗先行Evidenceとして確定する（Q-FUNC／Q-MAIN）
- [ ] 2.3 worker thread identity、親観測ContextVar有無、OpenTelemetry current span、Model build／bind／invoke、観測update／endおよび安全な例外型／originだけを収集し、Provider call前／response後／観測終了／checkpoint commitの一つへ原因を分類する。分類不能なら製品修正を行わずTask 5のRun外graph probeへ進む（Q-USE／Q-SEC、Support）
- [ ] 2.4 Test output、exported spanの検査値およびfailing-first EvidenceをCredential、endpoint、prompt、本文、raw response、reasoning、tracebackおよび画像binaryのsentinelで走査し、漏えい0件を確認する（Q-SEC）

## 3. Cause-Specific Correction and Regression

- [ ] 3.1 Cause Gateが一意に再現した場合だけ、その所有境界を期待する失敗Testを追加し、Context束縛、worker内観測child作成、request thread内client生成またはnode返却順序の該当一箇所だけを最小修正する。再現不能なら製品Code差分0件を確認してTask 5へ進む（Q-FUNC／Q-MAIN、保守）
- [ ] 3.2 修正経路でProvider call 1件、response return／parse各1件、schema-valid Pydantic値、STRUCTURE ArtifactのAtomic公開、checkpoint commit 1件およびworkflow→Task→generationの親子traceを確認する（Q-FUNC／Q-REL）
- [ ] 3.3 観測create／update／end、Provider transport、parseおよびcheckpoint commitへ個別にFailureを注入し、観測障害だけがwarning継続し、その他は元Error identity、有限attempt、部分Artifact 0件および次RunのContextVar resetを維持することを確認する（Q-REL／Q-SEC）
- [ ] 3.4 TranslationとComparison Reviewの全Model／Embedding同時request最大1、408／429／5xx／parseの既存有限retry、未知の`TypeError`伝播、page checkpoint v4、zero-thinking、strict schema、Run fingerprint／schema、CLIおよびQdrant状態非依存に差分がないことをTestとdiffで確認する（Q-PERF／Q-COMP／Q-PORT、移行）

## 4. Automated Quality and Security Gate

- [ ] 4.1 実Graph／SQLite／Langfuse／ChatOpenAI Integration、Adapter、STRUCTURE、Translation／Comparison Review、Failure、Resume、Atomic公開およびfingerprintのfocused pytestを成功させ、Provider call countと有限attemptを記録する（Q-FUNC／Q-REL／Q-PERF）
- [ ] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、Dependency lock差分0件とOS固有製品分岐0件を確認する（Q-MAIN／Q-PORT）
- [ ] 4.3 Test output、warning、Failure、Run metadata、checkpoint、span exporterおよびChange Evidenceを秘密・本文・raw応答・reasoning・traceback・画像binaryのsentinelで走査し、漏えい0件を記録する（Q-SEC、Support）
- [ ] 4.4 `openspec validate resolve-public-workflow-structure-typeerror --strict`を成功させ、実装とtasks／designの対応、Migration、Rollback、Supportおよび廃止影響をEvidenceへ記録する（Q-MAIN、ISO/IEC/IEEE 12207）

## 5. Sequential Real Page 3 Graph Gate

- [ ] 5.1 自動Gate後に他のModel／Embedding request 0件、LM StudioのModel／context 30,208／parallel 1／queued 0／idle、Run fingerprint、入力SHA-256、page 2 checkpoint v4およびSPLIT～LOAD baselineを再確認し、条件不一致なら実requestを送らない（Q-COMP／Q-PERF、運用）
- [ ] 5.2 保存済みpage 3をRun外のOS一時workspaceへ複製した実Translation graph／SQLite pending STRUCTURE Resumeで、SDK retry 0、Application retry 1、timeout 900秒、同時request 1として一度だけ処理する（Q-FUNC／Q-PERF）
- [ ] 5.3 Page 3 graph probeのstage／boundary／origin、finish reason、数値usage、reasoning長、Provider call／response／parse／checkpoint count、wall time、trace階層および観測warningだけを記録し、schema-valid、Pydantic適合、非truncationおよび一response一消費を確認する。不一致なら追加requestと公開Resumeを行わない（Q-REL／Q-USE／Q-SEC）
- [ ] 5.4 Probe前後で正本Run、SPLIT～LOAD、private page checkpoint、公開Artifact、外部exportおよびQdrant writeが不変で、一時workspace残存0件、秘密漏えい0件であることを確認する（Q-COMP／Q-SEC、移行・廃止）

## 6. Conditional Public Resume and Handoff

- [ ] 6.1 Page 3 graph probe成功時だけRun fingerprint、入力SHA-256、SPLIT～LOAD baseline、LM Studio状態、DoclingおよびQdrantの読取り可能性を再確認し、Qdrant状態をResume拒否へ含めず公開Resume条件を固定する（Q-COMP／Q-PERF、運用）
- [ ] 6.2 全条件成立時に限り公開CLIから同じRun IDを一度だけ明示Resumeし、全Model／Embedding呼出しを逐次実行する。失敗時は有限retry後に停止してFailureとResume状態を保持し、同じChange内で追加Resumeを行わない（Q-FUNC／Q-REL、運用・保守）
- [ ] 6.3 Resume成功時にRun完了、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外、Atomic Artifact、既完了Task不変、外部exportおよび自動削除0件を実測し、失敗時は部分Artifact非公開と保存状態を実測する（Q-FUNC／Q-COMP／Q-REL、移行・廃止）
- [ ] 6.4 最終品質、Security、Lifecycleおよび受入Evidenceをまとめ、本Changeのverify／archive可否を実証結果だけで判定する。Translation未完なら原因を次の独立Changeへ引き渡し、Word-to-PDF変換、目視比較およびComparison Reviewを完了扱いにしない（Q-USE／Q-SEC／Q-MAIN、Support・保守）

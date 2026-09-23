<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe Baseline and Historical State Contract

- [x] 1.1 Run `01a0c97c-f5cf-7031-b808-4ad545133925`のstatus、fingerprint、input SHA-256、Failure、workflow thread ID、checkpoint／writes、page checkpoint、SPLIT～LOAD file count／aggregate hash／latest mtime、公開Artifact、Run outputおよび外部exportを読取り専用で記録し、取得前後の変更0件を確認する（Q-COMP／Q-REL、移行・廃止）
- [x] 1.2 LM StudioのModel、context 30,208、parallel 1、queued 0／idle、他のModel／Embedding／Python処理0件、Application timeout／deadline／retryおよびSDK retry 0を秘密・endpointなしで記録し、不一致時は実requestを送らない（Q-PERF／Q-SEC、運用）
- [x] 1.3 正本SQLiteをread-onlyで開いて最新snapshot、pending node、state key、path-valued fieldおよびwrites countだけを検査し、本文／画像binary／Credentialがcheckpointにないことと正本file hash／mtime不変を確認する（Q-REL／Q-SEC、Support）

## 2. Read-only Clone and Safe Path Rebase

- [x] 2.1 標準SQLite backupでhistorical DatabaseをOS一時directoryへ一貫して複製し、正本配下のregular Artifactだけを同じ相対layoutへcopyするTest fixtureを追加して、source／destination hash、Database integrityおよび正本不変を確認する（Q-FUNC／Q-PORT）
- [x] 2.2 複製Databaseの最新stateでallowlist済みpathだけをtemp Runへ写像し、実`SqliteSaver.update_state()`でtemp forkを作る。更新前後のthread ID、lineage、pending STRUCTURE nodeおよびSPLIT～LOAD非再実行をTestで確認する（Q-FUNC／Q-COMP）
- [x] 2.3 root外path、不明path field、symlink／junction、本文またはbinaryを含むcheckpoint、破損Databaseおよびcopy失敗を拒否し、正本write 0件、部分temp Artifact 0件、終了後temp directory 0件をfault-injection Testで確認する（Q-REL／Q-SEC、廃止）

## 3. Failing-first Offline Resume Matrix

- [x] 3.1 実Translation graph、実ChatOpenAI／OpenAI SDK stackおよび`MockTransport`の同一strict-schema responseを使い、fresh SQLite＋page 3だけの既知成功baselineとfresh SQLite＋full Document／page 2 checkpointを逐次実行し、差分をcall countとstate transitionで固定する（Q-FUNC／Q-PERF）
- [x] 3.2 Historical SQLite temp fork＋full Document／page checkpointを同条件でResumeし、Model build／bind／invoke、Provider call、response return、parse、node return、state updateおよびcheckpoint commitの最初の失敗境界または全成功を記録する（Q-FUNC／Q-USE）
- [x] 3.3 3.2へ`OutputLock`、run logging、progress／task status callbackおよび観測Contextを一要因ずつ累積し、前段成功・次段失敗となる所有境界、handler／lock cleanupおよびContextVar resetをTestで確認する（Q-REL／Q-MAIN）
- [x] 3.4 Temp `RunRepository`／`PreparedRun`から`execute_run()`と`execute_public_run()`を順に通し、保存済み完了Taskを再実行せず、Run status／Failure／progress／Artifact公開が公開Lifecycle契約に従うことを確認する（Q-FUNC／Q-COMP）
- [x] 3.5 全matrixでNetwork 0件、Model／Embedding同時call最大1、Provider response一回消費、有限attemptおよび正本変更0件を確認し、出力をCredential、endpoint、prompt、本文、raw response、reasoning、tracebackおよび画像binaryのsentinelで走査する（Q-PERF／Q-SEC、Support）

## 4. Cause-specific Correction and Regression

- [x] 4.1 Offline matrixがTypeErrorを一つの製品境界へ再現した場合だけ、その失敗Testを固定して該当するstate正規化、page checkpoint読取り、Lifecycle cleanupまたはAdapter call形を最小修正する。再現不能なら製品Code差分0件を確認してTask 6へ進む（Q-FUNC／Q-MAIN、保守）
- [x] 4.2 修正後の全matrixでProvider call／response／parse／node return／checkpoint commitが各期待回数、schema-valid Pydantic値、page 3 private checkpointおよびSTRUCTURE ArtifactがAtomicに一度だけ生成されることを確認する（Q-FUNC／Q-REL）
- [x] 4.3 Logging、lock、callback、観測create／update／end、Provider transport、parse、state updateおよびcheckpoint commitへ個別にFailureを注入し、Langfuse障害だけがwarning継続し、他は元Error identity、有限retry、部分Artifact 0件およびResume可能停止を維持する（Q-REL／Q-SEC）
- [x] 4.4 TranslationとComparison Reviewの全Model／Embedding同時request最大1、408／429／5xx／parse retry、未知の`TypeError`伝播、page checkpoint v4、fingerprint、CLI／Streamlit共有RunおよびQdrant状態非依存をfocused Testとdiffで確認する（Q-PERF／Q-COMP／Q-PORT、移行）

## 5. Automated Quality and Security Gate

- [x] 5.1 Clone／rebase、offline matrix、Adapter、STRUCTURE、Translation／Comparison Review、Failure、Resume、Lifecycle、Atomic公開およびfingerprintのfocused pytestを成功させ、case別call countと有限attemptを記録する（Q-FUNC／Q-REL／Q-PERF）
- [x] 5.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`および`uv run pytest -q`を成功させ、Dependency lock差分0件とOS固有製品分岐0件を確認する（Q-MAIN／Q-PORT）
- [x] 5.3 Test output、warning、Failure、Run metadata、checkpoint、run log、span exporterおよびChange Evidenceを秘密・本文・raw応答・reasoning・traceback・画像binaryのsentinelで走査し、漏えい0件とtemp残存0件を記録する（Q-SEC、Support・廃止）
- [x] 5.4 `openspec validate isolate-historical-resume-structure-typeerror --strict`を成功させ、実装とtasks／designの対応、Migration、Rollback、運用、Supportおよび廃止影響をEvidenceへ記録する（Q-MAIN、ISO/IEC/IEEE 12207）

## 6. Sequential Temp-run and Public Resume Gates

- [x] 6.1 自動Gate後にModel／Embedding／Python処理0件、LM StudioのModel／context 30,208／parallel 1／queued 0／idle、正本fingerprint、input SHA-256、checkpoint、SPLIT～LOAD baseline、DoclingおよびQdrant読取り可能性を再確認し、不一致なら実requestを送らない（Q-COMP／Q-PERF、運用）
- [ ] 6.2 正本の最新read-only snapshotから作ったtemp Run forkを`execute_public_run()`境界で、SDK retry 0、Application retry 1、timeout 900秒、同時request 1として一度だけ実Model Resumeし、stage／boundary／origin、finish reason、数値usage、call／checkpoint countおよびwall timeだけを記録する（Q-FUNC／Q-PERF）
- [ ] 6.3 Temp ResumeでSTRUCTUREがschema-validに完了し、成功済みTask非再実行、Atomic Artifact、正本Run／外部export／Qdrant write不変、秘密漏えい0件およびtemp cleanupを満たした場合だけ正本公開Resumeを許可する。失敗時は追加requestを行わず保存状態を記録する（Q-REL／Q-SEC、移行・廃止）
- [ ] 6.4 6.3のGate成功時だけ公開CLIから同じRun IDを一度明示Resumeし、全Model／Embedding呼出しを逐次実行する。失敗時は有限retry後に停止してFailureとResume状態を保持し、同じChange内で追加Resumeを行わない（Q-FUNC／Q-REL、運用・保守）
- [ ] 6.5 正本Resume成功時はSTRUCTURE以降のcheckpoint、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外、既完了Task不変、Atomic Artifact、外部exportおよび自動削除0件を実測する。失敗時はpage 3／公開Artifact／部分成果物と正本baselineを実測する（Q-FUNC／Q-COMP／Q-REL）
- [ ] 6.6 最終品質、Security、Lifecycleおよび受入Evidenceをまとめ、本Changeのverify／archive可否を実証結果だけで判定する。Translation未完なら原因を次の独立Changeへ引き渡し、Word-to-PDF変換、目視比較およびComparison Reviewを完了扱いにしない（Q-USE／Q-SEC／Q-MAIN、Support・保守）

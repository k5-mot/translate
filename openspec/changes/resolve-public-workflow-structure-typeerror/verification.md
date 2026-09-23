<!-- markdownlint-disable MD013 MD041 -->

## Apply Evidence

### Preserved Run Baseline

- Run ID／operation／status: `01a0c97c-f5cf-7031-b808-4ad545133925`／`translate`／`failed`（UUIDv7）。
- Input copy SHA-256: `0185cd9631266fad92ffcede31a447e51cffa94ee572308310a490dc78a74182`。保存値および現在fingerprintと一致した。
- Fingerprint: `fdd0ce952338a28d78dc2d99e976c812f8bce23f85e79e250ecc1f54b3cece96`。現在設定との互換性あり。
- Failure: `STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`。finish reason、usageおよびfailure kindは未取得。
- LangGraph checkpoint 9件／writes 51件。Private STRUCTURE checkpointはpage 2の`.complete.json`、`audit.json`、`meta.json`、`page.json`だけである。
- 完了済みSPLIT～LOAD: 313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`。
- 公開STRUCTURE Artifact、Run outputおよび外部export `outputs/sample-translation`はすべて0 files。Baseline取得によるRun、exportおよびQdrant変更は0件だった。

### Runtime Baseline

- LM Studio: `google/gemma4:12b`、context 30,208、parallel 1、queued 0／idle。他のPython processは0件だった。
- Application: context 30,208、output 16,384、image 2,048、request timeout 300秒、Task deadline 21,600秒、retry attempts 3。OpenAI SDK retryは製品Codeで0、Translation graphの`max_concurrency`は1である。
- Runtime packages: LangGraph 1.2.11、LangGraph SQLite Checkpoint 3.1.1、Langfuse 4.15.4、OpenTelemetry API／SDK 1.44.0、LangChain OpenAI 1.6.2、OpenAI SDK 3.16.2。
- 実機Gateだけprocess環境のrequest timeoutを900秒、Application retryを1へ上書きする。Model、製品既定、Run fingerprintおよびDependencyは変更しない。

### Direct Page and Public Resume Difference

| Boundary | Direct page 3 probe | Public CLI Resume |
| --- | --- | --- |
| Entry | `structure.run()`をmain threadから直接呼出し | `execute_public_run()`→Lifecycle→Translation `StateGraph.stream()` |
| SQLite Resume | なし | 保存済みpending STRUCTURE nodeを`SqliteSaver`からResume |
| Node wrapper | なし | Task status、Task observation、progressおよびstate updateあり |
| Observation context | 明示的detached workflow→Task→generationを同一実行Contextで作成 | LifecycleのContextVarからworkflow、worker Task、generationへ伝播 |
| Model result | Vision 1 request、`finish_reason=stop`、schema-valid | Vision Failure後のtext経路で`text-invoke`／`TypeError` |
| Provider count evidence | request／response各1件 | Failureにusageがなく、公開境界内の安全なcall count未取得 |
| Artifact | Run外一時directoryで成功後に全削除 | Page 3 checkpointと公開STRUCTURE Artifactは0件 |

本文、prompt、raw response、reasoning本文、Credential、endpoint、tracebackおよび画像binaryは差分比較またはEvidenceへ保存していない。

### Offline Real Graph Cause Gate

- OS一時workspaceの実`SqliteSaver`へLOAD完了stateを`as_node="load"`で保存し、snapshotのpending nodeがSTRUCTUREだけであることを確認した。実Translation `build_graph()`、node wrapperおよび`compiled.stream(None, config)`を通し、SPLIT～LOADを呼ぶと失敗するdoubleが一度も呼ばれないことを固定した。
- 実Langfuse／OpenTelemetry exporter、実ChatOpenAI／OpenAI SDK response stackおよび`httpx2.MockTransport`を結合した。外部Network 0件でstrict-schema responseを一件返し、Model build、bind、invoke、response return、Pydantic parse、STRUCTURE node returnおよびgraph state commitを各1回だけ観測した。
- 最初の仮説TestはModel handlerが別worker threadであることを期待して失敗した。実測ではlock済みLangGraph 1.2.11の同期`compiled.stream()`がcallerと同一threadでSTRUCTUREを実行したため、thread hopは公開Resumeとの差ではない。実測値を回帰条件へ変更後、Testは1 passedとなった。
- Handler内では親観測ContextVarあり、OpenTelemetry current spanなしだった。workflow→Task→generationは同じtrace IDと正しいparent span IDを持ち、Task statusはSTRUCTUREのstarted→completedだけ、観測warning 0件だった。
- Provider call、response return、parseおよびSTRUCTURE commitは各1件で、schema-valid Pydantic値、Atomic STRUCTURE `document.json`およびprivate page 3 checkpointが生成された。Offline公開Graph境界ではTypeErrorを再現しなかった。
- Cause GateはProvider call前、response後、観測終了またはcheckpoint commitのどれにも製品Failureを再現できなかったため、設計どおり製品Codeを変更せずRun外の実page 3 graph probeへ進む。`git diff -- translate`は0件である。
- Selected Test outputをCredential、API key、endpoint、本文、raw responseおよびschema payloadの6 sentinelで走査し、漏えい0件だった。Exported span、warningおよびEvidenceにもraw値を保存していない。

### Cause-Specific Regression

- Offline Cause Gateが成功して原因を一意に再現しなかったため、製品Code修正は行っていない。`git diff -- translate`、`pyproject.toml`および`uv.lock`の差分は0件である。
- `SqliteSaver.put()`のTask後commitへ専用`CheckpointCommitError`を注入するTestを追加した。Task／Provider相当処理は1回だけで、同じError identityが伝播し、Atomic Artifactは完全版だけ、temporary partial Artifactは0件だった。
- 既存fault injectionはLangfuse root／child create、update、endおよびwarning sinkを個別に失敗させ、warning継続、業務結果保持、次Runの親ContextVar resetおよびProvider再送0件を確認する。Adapter Testはtransport、408、429、5xx、parse、恒久4xx、未知の`TypeError`および有限attemptを固定している。
- Page checkpoint v4、zero-thinking、strict schema、Run fingerprint／schema、CLI、Qdrant状態非依存およびTranslation／Comparison Reviewの逐次実行方針に製品差分はない。
- 実Graph／SQLite／Langfuse／ChatOpenAI、Adapter、STRUCTURE、Translation／Comparison Review、Failure、Resume、Atomic公開およびfingerprintのfocused suiteは106 passedだった。Offline実Graph経路のProvider call／response／parse／node commitは各1件、retry failureは設定上限内だった。

### Automated Quality and Security Gate

- `ruff check .`成功、`ruff format --check .` 189 files、`ty check`成功、全pytest 210 passed／1 skippedだった。Formatは変更したTest fileだけへ適用し、無関係なFileを変更していない。
- `openspec validate resolve-public-workflow-structure-typeerror --strict`は成功した。`skip_specs: true`は既存`run-lifecycle`／`pdf-translation`への実装適合として受理された。
- `pyproject.toml`、`uv.lock`および製品`translate/`の差分は0件で、Dependency追加とOS固有製品分岐はない。
- Change Evidence、Run metadata、Failure、workflow metadata、Run logsおよびpage 2 checkpointの9 filesと、Langfuse／Workflow State Test outputをCredential／endpoint／page本文／prompt／画像data URIの20 sentinelで走査した。永続File leak 0件、Test output leak 0件で、span exporterのraw sentinel非保持もTest内で確認した。
- Data migrationと個別廃止処理は不要である。Rollbackは追加Test／Evidence commitだけを戻し、Run、checkpoint、外部exportおよびQdrant Collectionを保持する。Supportは実Graph境界TestとRun外graph probeの安全なcount／boundary値を使用する。

### Sequential Real Page 3 Graph Preflight

- 他のPython process、Model requestおよびEmbedding requestは0件だった。LM Studioは`google/gemma4:12b`、context 30,208、parallel 1、queued 0／idleである。
- 保存fingerprintと現在fingerprint、Run input copyのSHA-256、およびpage 2 checkpoint keyと現在実装が一致した。Checkpoint versionは4、Run statusは`failed`、SPLIT～LOAD baselineは313 files／aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`のままである。
- Run外graph probeはOpenAI SDK retry 0、Application retry 1、request timeout 900秒、Task deadline 21,600秒、同時request 1とする。不一致が発生した場合は追加requestと公開Resumeを行わない。

### Sequential Real Page 3 Graph Result

- OS一時workspaceへ保存済みpage 3だけを複製し、実Translation `build_graph()`、実`SqliteSaver`、LOAD完了state、pending STRUCTURE node、実node wrapper、実Langfuseおよび実ChatOpenAIで逐次実行した。
- Pending nodeは実行前`structure`、実行後`translate`だった。Vision 1 requestで成功し、text fallbackは0 request、`finish_reason=stop`、input 1,324／output 357／total 1,681 tokens、reasoning length 0、Pydantic適合、schema-validだった。
- Model build／bind／invoke／response return／parseは各1件、STRUCTURE state update 1件、checkpoint commit 1件だった。境界はすべて同一caller thread、Model handler内は親観測ContextVarあり／OpenTelemetry current spanなし、Task statusはstarted→completed、観測warning 0件である。
- 有界画像は879 × 1,137 pixels（999,423 pixels）。STRUCTURE Artifactとprivate page 3 checkpointは一時workspace内で完全に生成され、Task wall time 11.021秒、probe全体11.487秒だった。終了時に一時workspaceを全削除し、残存directoryは0件である。
- 正本Runは`failed`／STRUCTURE page 3／`text-invoke`／`TypeError`、private checkpointはpage 2の4 filesだけ、公開STRUCTURE、Run outputおよび外部exportは0 filesのままだった。SPLIT～LOADは313 files／同じaggregate hashで不変、probe経路のQdrant writeは0件である。
- EvidenceとRun関連9 filesをCredential／endpoint／page本文／prompt／画像data URIの20 sentinelで走査し、漏えい0件だった。Raw response、reasoning本文、tracebackおよび画像binaryは保存していない。

### Public Resume Preflight

- 他のPython／Model／Embedding processは0件、LM Studioは対象Model、context 30,208、parallel 1、queued 0／idleだった。保存fingerprintと現在fingerprint、およびRun input copyと保存SHA-256は一致した。
- Docling healthはHTTP 200、Qdrant Collectionは読取り可能でpoints 1,009だった。Qdrant状態はfingerprintおよびResume拒否へ使用していない。
- 公開Resumeはprocess環境だけrequest timeout 900秒とし、Application retry 3、OpenAI SDK retry 0、Model／Embedding同時request最大1を維持する。条件がすべて成立したため、同じRun IDを公開CLIから一度だけResumeできる。

### One Allowed Public Resume

- 公開CLIの`translate inputs/sample.pdf --output-dir outputs/sample-translation --resume <run-id>`を一度だけ実行した。別Runは作成せず、request timeout 900秒、Application retry 3、SDK retry 0、parallel 1を使用した。
- Result: exit code 1、total wall time 48.805秒。Runは`failed`／`STRUCTURE`、page 3、target `page/3`、stage `text-invoke`、cause `TypeError`で停止した。finish reason、usageおよびfailure kindは取得されなかった。設計どおり追加Resumeは実行していない。
- 終了後のLM Studioは対象Model、context 30,208、parallel 1、queued 0／idleへ戻った。Runは同じfingerprintとResume可能状態を保持した。

### Failed Resume Artifact and Lifecycle Audit

- LangGraph checkpoint 9件／writes 51件、private STRUCTURE checkpointはpage 2の4 filesだけだった。Page 3 checkpoint、公開STRUCTURE Artifact、Run outputおよび外部exportは0 filesで、部分成果物は公開されていない。
- 既完了SPLIT～LOADは313 files、aggregate SHA-256 `2267ecb3b65434e6352914e90b18e44bf4b5c734888b6b9445e4017ecf073a93`、latest mtime `2026-09-22T14:48:35.1483938Z`で不変だった。Run、外部exportおよびQdrant Collectionの自動削除は0件である。
- Translationが未完了のため、進捗100%、最終Markdown／DOCX、表紙画像一回、本文1ページ目除外およびAtomic最終Artifactは未達であり、成功扱いにしない。Word-to-PDF変換、利用者の目視比較およびComparison Reviewも未実施である。
- Run外のpage 3 graph probeが同一Modelで直前に成功した一方、正本公開Resumeだけが再失敗した。未再現差はhistorical SQLite checkpoint、full Document／page 2 checkpoint reuse、公開Lifecycle／loggingおよびそれらの組合せに限定された。次Changeでは正本を変更せず、これらをRun外へ複製したprobeで一つずつ比較する。

### Final Quality, Security and Decision

- 最終Gateは`ruff check .`成功、`ruff format --check .` 189 files、`ty check`成功、全pytest 210 passed／1 skipped、strict OpenSpec validation成功だった。Dependencyと製品Codeの差分は0件である。
- Changed Evidence、Run metadata、Failure、workflow metadata、Run logsおよびpage 2 checkpointの11 filesをCredential／endpoint／page本文／prompt／画像data URIの20 sentinelで走査し、漏えい0件だった。`git diff --check`も成功した。
- 実Graph／SQLite／Langfuse／ChatOpenAIのoffline TestとRun外page 3 graph probeは成功したが、正本公開Resumeは同じpage 3で`text-invoke`／`TypeError`を再現した。本Changeの23 tasksは診断、条件付き修正、停止および引渡しを含め完了したが、公開Resume受入は未達であるためverifyはCRITICAL、archive不可と判定する。
- Translation、最終DOCX、Word-to-PDF、目視比較およびComparison Reviewは完了扱いにしない。次Changeはhistorical checkpointとfull-document条件をRun外へ複製し、正本へ追加ResumeせずFailureを再現する。

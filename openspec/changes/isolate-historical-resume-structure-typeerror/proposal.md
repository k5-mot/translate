<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

Run外の新規SQLite checkpointと単一page 3を使う実Translation graph probeは同じModelで成功したが、正本Runの公開CLI Resumeだけは48.805秒後にSTRUCTURE page 3の`text-invoke`／`TypeError`で停止した。残る差はhistorical checkpoint、full Document／page 2 checkpoint、`OutputLock`、loggingおよび公開Lifecycleの組合せに限定されているため、正本Runを変更せず同条件を複製して原因を一意に隔離する必要がある。

## What Changes

- UUIDv7 Run `01a0c97c-f5cf-7031-b808-4ad545133925`の入力、`workflow.json`、historical `checkpoints.sqlite`、LOAD Artifactおよびpage 2 private checkpointを読取り専用で検証し、OS一時directoryへ必要な正本状態を複製する。
- 保存済みpage 3とNetworkなしの決定的responseを使用し、fresh／historical SQLite、単一page／full Document、page 2 checkpoint、`OutputLock`、logging、task callbackおよび`execute_run()`／`execute_public_run()`を段階的に組み合わせる失敗先行Testを追加する。
- Model build／bind／invoke／response／parse、ContextVar、logging handler、lock、LangGraph snapshot／pending writesおよびcheckpoint commitを、秘密を含まない型・境界・回数だけで比較する。Prompt、文書本文、raw response、reasoning、Credential、endpoint、tracebackおよび画像binaryは保存しない。
- TypeErrorを一つの製品境界へ再現できた場合だけ、その境界へ失敗Testを固定して最小修正する。再現不能なら推測修正や一般的な`TypeError`捕捉を行わず、安全なEvidenceを次の診断へ引き渡す。
- Translation／Comparison ReviewのModel・Embedding呼出しはすべて逐次実行し、有限retry、Langfuse fail-open、Atomic Artifact、page checkpoint v4、Run fingerprintおよびQdrant状態非依存を維持する。
- 自動Gate後、正本複製を使うRun外probeを実Modelで一回実行し、成功時だけ同じRun IDを公開CLIから一度Resumeする。失敗時は追加Resumeを行わず、正本RunをResume可能な状態で保持する。
- 公開CLI、Model `google/gemma4:12b`、context 30,208、token予算、成果物形式、Dependencyおよび永続schemaは変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`run-lifecycle`は成功済みTaskを再実行しないResume、有限retry、Resume可能停止、Atomic Artifactおよび秘密非出力を既に要求し、`pdf-translation`は読取り可能なPDFから検証済み日本語DOCXを生成することを既に要求している。本Changeは既存契約への実装適合であり、`.openspec.yaml`の`skip_specs: true`によりdelta specを作成しない。

## Impact

- 製品Code: 再現された原因に応じて`translate/workflows/translation.py`、`translate/common/lifecycle.py`、`translate/common/workspace.py`、loggingまたはLLM／観測Adapterの一境界だけを変更する。
- Test: historical SQLiteとfull Documentを複製するIntegration Test、公開Lifecycle／logging／lock、retry／Failure／Resume／Atomic公開の回帰Test。
- 実Run: 診断中は正本を読取り専用とし、全Gate成功後の一回だけ明示Resumeする。成功済みSPLIT～LOADとpage 2 checkpointを再実行しない。
- 公開API、Dependency、Model設定、Run layout、fingerprint、checkpoint versionおよびQdrant Collectionへの変更はない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: CLIとStreamlitで共有する失敗Runを、保存済み状態から安全に再開できる状態へ戻す。実機処理はcontext 30,208、parallel 1、queued 0／idle、timeout 900秒で逐次実行する。
- 取得／供給: 導入済みLangGraph、SQLite checkpointer、Langfuse、OpenTelemetry、LangChain OpenAIおよびOpenAI SDKを使用し、新規Packageと外部Providerを追加しない。
- 移行: Data migration、fingerprint、checkpoint v4、Failure形式および既存Run layoutを変更しない。複製probeはOS一時directoryだけを使用して終了時に削除する。
- 保守／Support: historical Resume固有差を段階的な回帰Testと安全なboundary／countへ固定し、同種障害を正本Runなしで再現可能にする。
- 廃止: 新規Service、公開optionおよび永続fieldを追加しないため個別廃止処理はない。Run、外部exportおよびQdrant Collectionは自動削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: 正本と同じhistorical checkpoint／full Document条件でSTRUCTURE page 3をschema-validに処理し、公開ResumeがSTRUCTUREを通過することを段階Test、Run外probeおよび同一Run結果で確認する。
- Q-REL（信頼性）: 成功済みTaskを再実行せず、一response一消費、有限retry、Atomic公開および失敗時のResume可能状態を維持する。
- Q-PERF（性能効率性）: offline診断を優先し、実Model／Embedding requestは同時数1、SDK retry 0、request timeout 900秒で、call countとwall timeを記録する。
- Q-COMP（互換性）: UUIDv7 Run、CLI／Streamlit共有layout、fingerprint、checkpoint v4およびQdrant状態非依存を変更しない。
- Q-USE（使用性）: `text-invoke`／`TypeError`をhistorical state、Lifecycle、loggingまたはModel境界の固定分類へ縮約し、利用者へ安全なFailureを示す。
- Q-SEC（Security）: 複製物をOS一時directoryへ限定し、Test、log、Failure、checkpointおよびEvidenceへの秘密・本文・raw値・画像binary漏えいを0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: 導入済みstackによる失敗先行Test、原因限定の最小修正、Ruff、Format、ty、全pytestおよびstrict validationを成功させ、Dependency追加とOS固有製品分岐を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作、自律Actionまたは設定面を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

歴史的checkpointを複製した実Model ResumeはSTRUCTURE 351ページを完了してTRANSLATEへ進んだが、約90分後にPTY sessionが終了し、TRANSLATEの完了・失敗原因・最終Run statusを安全に回収できなかった。正本Runは不変に保てたものの、終端Evidenceがないため、公開Resumeの許可判定と次の診断を証明できない。

## What Changes

- 長時間のRun外Resume GateをPTYの標準出力から分離し、detached processとwatchdogで実行・監視する。再起動や暗黙のretryは行わず、同じ実行handleのterminal状態だけを判定する。
- 一時Runの外側に、Run ID、phase／task、current／total、heartbeat、開始・終了時刻、safe exception type／stage／cause、数値usage、Model／Qdrant／checkpoint call countおよびprocess exit codeだけを原子的に保存する。Prompt、本文、raw response、reasoning、Credential、endpoint、tracebackおよび画像binaryは保存しない。
- `execute_run()`／`execute_public_run()`のFailure、外部processのunexpected termination、timeoutおよび正常終了を、秘密非含有の同一terminal schemaへ収束し、temp cleanup後もEvidenceを保持できるTest／probe境界を追加する。
- TRANSLATEのQdrant検索、LLM chunk、Atomic Artifactおよびcheckpoint進捗を逐次監視し、有限retry後の停止とResume可能状態を安全に判定する。
- detached temp Gateが完全成功した場合だけ、同じUUIDv7正本Runを公開CLIから一度Resumeする。Gateが未確定または失敗なら追加Model request／正本Resumeを行わない。
- 公開CLI、Streamlit、Run fingerprint、Run schema、Model／token設定、Dependencyおよび全Model／Embedding同時request最大1は変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`run-lifecycle`はFailure、checkpoint、Atomic Artifact、Resume可能停止および秘密非出力を既に要求し、`pdf-translation`は構造を保持した検証済みDOCX公開を既に要求している。本Changeは長時間実機検証の診断・運用境界を強化する実装適合であり、`.openspec.yaml`の`skip_specs: true`によりdelta specを作成しない。

## Impact

- 製品／検証Code: `translate/common/lifecycle.py`、`translate/common/progress.py`または既存Test／probeのterminal evidence境界を最小変更する。Product Run metadataへ本文を追加しない。
- Test／運用: detached process、watchdog、heartbeat、safe terminal record、Qdrant／LLM／checkpoint failure injectionおよびcleanup回帰Testを追加する。
- 実Run: 正本Runはread-only preflight後、temp Gate成功時に限り一度だけResumeする。外部exportとQdrant Collectionは自動削除しない。
- 公開API、Dependency、persistent Run schemaおよびfingerprintへの変更はない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 長時間Resumeの進捗と停止理由を失わず確認でき、未確定状態で誤Resumeしない。実Model／Embeddingはparallel 1、timeout 900秒で逐次実行する。
- 取得／供給: 導入済みPython標準library、既存Run／Lifecycle／Logging／Qdrant／LLM Adapterを使用し、新規Service／Packageを追加しない。
- 移行: 永続Run／checkpoint schemaは変更しない。Evidenceは検証用の明示directoryへ保存し、正本Run rootへ混入させない。
- 運用／保守／Support: process handle、heartbeat、phase、countおよびsafe failureを使用して、PTY切断と実処理Failureを区別する。watchdogのstale判定は実行停止後だけに適用する。
- 廃止: temp Run、detached process、lockおよびEvidenceは成功・失敗・timeoutの全terminal経路でcleanupし、外部exportは保持する。

## Quality Considerations

- Q-FUNC（機能適合性）: STRUCTUREからTRANSLATE、Reviewおよび最終公開までのphase終端を失わず、temp Gate成功時だけ正本Resumeへ進むことをdetached実機Evidenceで確認する。
- Q-REL（信頼性）: heartbeat、atomic terminal record、process exit、Failure identity、有限retryおよびResume可能停止を一度だけ記録し、session切断で結果を失わない。
- Q-PERF（性能効率性）: watchdogはModel／Embeddingと並列処理せず、同時request 1、SDK retry 0、timeout 900秒を保持する。監視I/Oは小さいJSONだけに限定する。
- Q-COMP（互換性）: UUIDv7、CLI／Streamlit共有Run、fingerprint、checkpoint v4およびQdrant状態非依存を維持する。
- Q-USE（使用性）: phase／task／current／total／safe causeを利用可能な診断へ収束し、未確定状態の再Resumeを防止する。
- Q-SEC（Security）: terminal Evidence、Run log、Failureおよびwatchdog outputをCredential、endpoint、prompt、本文、raw response、reasoning、tracebackおよび画像binaryのsentinelで走査し漏えい0件にする。
- Q-MAIN／Q-PORT（保守性／移植性）: Windows／PowerShellで再現可能なdetached境界、既存標準library、Ruff、Format、ty、全pytestおよびstrict validationを通し、OS固有製品分岐とDependency差分を0件にする。
- Interaction capability、SafetyおよびFlexibilityは公開操作・設定を増やさないため新規評価対象とせず、既存回帰Testで非退行を確認する。

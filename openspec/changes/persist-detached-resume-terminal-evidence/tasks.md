<!-- markdownlint-disable MD013 MD041 -->

## 1. Terminal Evidence契約と安全な書込み

- [ ] 1.1 `TerminalEvidence`のversion、Run ID、phase、task、current／total、status、safe stage／cause、finish reason、数値usage、checkpoint／artifact count、heartbeat、child PID、exit codeだけを受け付ける型とallowlistを実装し、任意文字列・本文・prompt・raw response・reasoning・credential・endpoint・traceback・画像binaryを拒否するUnit Testを追加する
- [ ] 1.2 temp Run root外のEvidence pathを解決し、既存`atomic_write_json()`と同一volumeの一時File、flush／fsync、replaceを用いるwriterを実装して、途中書込み・path traversal・root内配置がないことをTestで確認する
- [ ] 1.3 heartbeat／progress／Run Failureからphase、task、current／total、safe cause、数値usage、checkpoint／artifact countだけを収束するmapperを追加し、公開Run metadata／checkpoint schemaを変更しないことを回帰Testで確認する
- [ ] 1.4 Evidenceのterminal status enum（`completed`、`failed`、`unexpected-exit`、`timeout`、`unknown`）と一方向遷移を実装し、`unknown`／staleを成功へ昇格できないことをTestで確認する

## 2. Detached child runnerとwatchdog

- [ ] 2.1 既存temp clone／path rebase／`execute_public_run()`へ委譲するdetached child runnerを追加し、stdout／stderrを保存せず一回だけ実行して、公開CLI／Streamlit APIとfingerprintを変更しないIntegration Testを追加する
- [ ] 2.2 `subprocess.Popen`のprocess handle、child PID、exit code、heartbeatを保持する親watchdogを実装し、childを再起動せず、Model／Embedding request最大1・SDK retry 0・timeout 900秒の逐次境界をTestで確認する
- [ ] 2.3 childの正常終了、`PublicRunError`、non-zero exit、hard crash、Qdrant／LLM／checkpoint failureを分類し、Run内Failureと外部terminal Evidenceへ安全に反映するFailure-injection Testを追加する
- [ ] 2.4 watchdog timeout／heartbeat staleを検出した際に`watchdog-timeout`または`unknown`をatomicに記録して停止を待ち、再起動・追加Model request・正本Resumeを行わないことをTestで確認する
- [ ] 2.5 parent process終了後もchild／Evidenceを回収でき、child終了後にだけcleanupへ進む境界を作り、parent crash・child crash・lock競合のWindows／PowerShell相当Testを追加する

## 3. Evidence漏えい防止とcleanup

- [ ] 3.1 Evidence、Run log、Failure、watchdog出力へCredential、endpoint、prompt、本文、raw response、reasoning、traceback、画像binaryのsentinelを投入する回帰Testを追加し、検出件数0を確認する
- [ ] 3.2 checkpoint／artifact／LLM／Embedding／Qdrantのcountをroot containment検査後に数値だけ保存し、collection名、URL、payload、request本文を保存しないことをTestで確認する
- [ ] 3.3 completed／failed／unexpected-exit／timeoutの全terminal経路でchild、lock、temp cloneをcleanupし、外部Evidenceと明示exportだけを保持するIntegration Testを追加する
- [ ] 3.4 terminal Evidenceのflush確認前にcleanup・Resumeしない順序をTestで固定し、Evidence欠落・破損時は`unknown`として公開Resumeを拒否する

## 4. Gate判定と既存Run統合

- [ ] 4.1 synthetic detached runnerでphase／task／current／total／heartbeat／exit／safe causeがPTY切断なしに最終JSONへ残ることを検証し、結果を`verification.md`へ記録する
- [ ] 4.2 既存Runのread-only preflightとUUIDv7／fingerprint／checkpoint v4／Qdrant状態非依存を回帰Testで確認し、正本SQLite hashがtemp Gate前後で不変であることを記録する
- [ ] 4.3 実Model／Embeddingをparallel 1、timeout 900秒、SDK retry 0でdetached temp Gateへ一度だけ接続し、STRUCTUREからTRANSLATE、Review、成果物検査のterminal Evidenceを回収する。失敗・timeout・unknown時は追加requestを行わず、Runを保持する
- [ ] 4.4 temp Gateが`completed`、成果物検証済み、Evidence flush済みの場合だけ同じUUIDv7正本Runを公開CLIから一度Resumeし、公開Resumeのterminal Evidence、最終status、artifact pathを記録する。Gate未完了時は公開Resumeを実行しない

## 5. 品質・ライフサイクル検証と引継ぎ

- [ ] 5.1 detached runner、Evidence writer、watchdog、Failure／cleanup回帰Testを実行し、`pytest`、Ruff、format、tyが成功することを記録する（ISO/IEC 25010:機能適合性・信頼性・Security・保守性／ISO/IEC/IEEE 12207:検証・妥当性確認・運用・廃止）
- [ ] 5.2 strict OpenSpec validationを実行し、proposal／design／tasksと実装の差分、Dependency差分、OS固有製品分岐、並列実行数の差分が0であることを`verification.md`へ記録する
- [ ] 5.3 実機Evidenceが終端状態を証明できない場合は、正本Runを削除・再実行せず、未完了Task、safe cause、次の再開条件を明記してChangeを未完了のまま引き継ぐ
- [ ] 5.4 完了条件を満たした場合のみ、Change内の全Task、検証Evidence、受入判定を更新し、後続のarchive判定に必要なartifactとcommitを確認する。Word-to-PDF変換、目視比較、Comparison Reviewの未実施を完了扱いにしない

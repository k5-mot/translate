<!-- markdownlint-disable MD013 MD041 -->

## 1. Timeout settings

- [x] 1.1 Settingsと環境変数fallbackの既定request timeoutを1,800秒へ変更し、正の有限値検証と既存設定の回帰Testを通す
- [x] 1.2 ChatOpenAIへtimeoutが一元的に渡り、retry／backoff／task deadline／逐次実行が変わらないことをadapter Testで確認する

## 2. Safe timeout diagnostics

- [x] 2.1 timeout時のLLM invoke stage／fixed causeがFailureRecord、failure.json、Terminal Evidenceへ伝播し、本文・prompt・endpoint・credentialを含まないことをTestで確認する
- [x] 2.2 timeout FailureがRunを停止し、checkpointを保持して明示Resume可能な状態になることをLifecycle Testで確認する
- [x] 2.3 Run schema、fingerprint、Qdrant state、CLI／Streamlit contract、Model／Embedding並列数に変更がないことを回帰Testで確認する

## 3. Detached Gate

- [ ] 3.1 同じUUIDv7正本Runのcloneを実Modelで逐次実行し、timeout解消または安全なterminal Failureを外部Evidenceへ記録する
- [ ] 3.2 source SQLite SHA-256不変、Evidence terminal、heartbeat、detached temp cleanupを確認する
- [ ] 3.3 Gate成功かつEvidenceが許可する場合だけ同じRunを明示Resumeし、失敗／不確定ならResumeしない
- [ ] 3.4 Gate結果、source hash、Evidence path、cleanup、Resume判定をverification.mdへ記録する

## 4. Quality gate and archive

- [ ] 4.1 pytest、Ruff、format、tyの結果を記録する
- [ ] 4.2 strict OpenSpec validation／statusを通過させる
- [ ] 4.3 `.agents`、user-owned dirty files、秘密、raw PDF／LLM本文をcommitへ含めないことを確認する
- [ ] 4.4 すべて完了したときだけChangeをarchiveし、archive後statusとgit diffを確認する

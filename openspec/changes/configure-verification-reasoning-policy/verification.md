# 検証記録

## 2026-09-25: 利用者指示による旧処理中断と計画

利用者の「現在の処理を中断し、設定追加後にOFFで新規検証」に従い、Run `01a0d520-15a4-74a2-9eaf-afafa726a03a` の翻訳を停止した。新設定の実装・新規実検証はまだ行っていない。

- 対象はsession `43282`、実worker PID `19964`。停止前にcommand line、親PID `48068`（wrapper Python）、祖先PID `51980`（uv）との対応を確認してから実workerだけを停止した。
- 対象commandは`cli.py translate inputs/sample3.pdf --output-dir outputs/sample3-acceptance-latest --resume 01a0d520-15a4-74a2-9eaf-afafa726a03a`。停止後、sessionのterminal exit code 1を確認した。
- 09:09 JSTの再確認で上記3 PIDは存在しない。Runの`.workspace/checkpoints.sqlite`、`-wal`、`-shm`と`workflow.json`は存在する。既存ファイルの削除・状態の手動書換えは行っていない。
- 強制中断は正常完了でも自動検証の失敗判定でもない。保存metadataのrunningは生存証拠としない。LM Studio側の要求終了は別途確認が必要であり、停止済みと断定しない。
- OFF設定は提案のみ。新たなLLM/Embedding呼出し、Word処理、旧RunのResume、成果物の上書きは行っていない。

原因の実測は[REPORT検証記録](../preserve-public-review-finding-details/verification.md)の「原因の特定」を参照。推論OFFの効果・品質は未検証で、tasks.mdは全項目未完了とする。計画文書の検査成功と製品実装・実検証の成功を区別する。

## 計画文書の検査

- OpenSpec status: proposal/specs/design/tasksの4/4 artifacts complete。実装完了ではない。
- `openspec validate configure-verification-reasoning-policy --strict`: valid。
- `openspec validate preserve-public-review-finding-details --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、0.28秒。
- `git diff --check`: 指摘なし。
- 製品Codeを変更していないため、今回の提案操作で全製品Test・ruff/ty・実モデル要求は実行していない。これらはapplyの未完了Taskに残す。
- 既存configの`Unknown operation ID 'verify'`警告は継続。今回の設定追加とは無関係のためconfigを書き換えていない。

## 2026-09-25: OFF設定の実装と自動検査

### 実装範囲

- 共通Settingsでtask-default/offを検証し、Adapterの送信・観測より前に実効none/disabledを決定する。既存のtemplate hintと整数thinking budget 0を再利用し、Embeddingは変更しない。
- 公開fingerprint/両WorkflowはOFFだけに識別項目を追加し、通常の旧hash/thread IDを維持する。直接Workflow呼出しでも異なる設定のworkspaceをmetadata書換え前に拒否する。
- TRANSLATEは全体OFFで同じ要求を無効化再試行せず、既存の有限・逐次分割を使う。単一要素/分割深さ上限/非切断Errorは失敗を保持する。
- Settings・Adapter・観測・切断回復、公開Run、CLI/UI相互Resume、両Workflowと旧SQLite serializerの再接続をdefault/offで検査した。新しい依存、Module、再開台帳は追加していない。
- README/.env.sampleに通常値と検証プロセス限定OFF、互換性、旧CodeへのRollback注意を記載した。

### 検査結果と限界

- 先行関連Test: 193 passed。追加した互換性/Workflow/公開Run Test: 42 passed。
- 全体初回: 636 passed / 1 failed / 1 skipped、42.98秒。失敗は既存の秘密非出力Testで、実行中に同Test fileをformatした結果、tracebackの行番号と読み直されたsourceがずれてmarkerの代入行が表示された。製品からの実入力露出とは分離する。
- 実行中のfile更新を止めて全体を再実行: **637 passed / 1 skipped、40.18秒**。初回失敗の事実は上記へ保持し、変更中のsourceを用いた検査を安定した証拠にしない。
- `ruff check .`、`ruff format --check .`（336 files）、`ty check`、OpenSpec strict、`git diff --check`: 成功。
- 全体検査は既存未コミットのcontext/timeout分類、REVIEW回復、Lifecycle、diagnostic I/Oの差分を含むworktreeを対象とした。今回のcommitにはOFF設定の差分だけを選び、既存差分は維持する。
- 実装タスク1.1〜2.4は完了。新規実翻訳・Word PDF・Review・利用者目視は未完了で、正式verify/archiveはまだ不可。

### 新規検証前の外部状態確認

旧CLI translate/review processは存在しない。既存Langfuse Provider観測を本文なしで読取り、旧実行の最終chat（ID `3690d4572ad55107`）が09:05:43.740〜09:07:48.817 JSTで終端となったことを確認した。取得範囲08:55 JST以降のchatは5件、cursorなし。新しいモデル要求は発行していない。sample3の入力SHA-256は`5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`、予定export先`outputs/sample3-acceptance-off`は09:26 JST時点で未存在。

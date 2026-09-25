<!-- markdownlint-disable MD013 MD041 -->

## 1. 共通設定とLLM要求

- [ ] 1.1 Settings/load_settingsへ`LLM_REASONING_MODE`（task-default/off、未指定task-default）を追加し、`tests/test_settings.py`で許容値、既定値、未知値の秘密非出力と外部要求前の拒否を確認する（Q-FUNC/Q-USE/Q-SEC）。
- [ ] 1.2 `adapters/llm.py`の既存送信境界で実効reasoning/thinkingを適用し、`tests/test_adapter_retry.py`と`tests/test_langfuse.py`でhigh/low/none、schema/text/image要求、retryを含むOFF送信と実効metadata、default不変、Embedding不変を確認する（Q-FUNC/Q-SEC）。
- [ ] 1.3 TRANSLATEの全体OFFを既存推論無効化回復へ接続し、`tests/test_translation_output_failures.py`でOFF→重複再送なしの有限分割、単一要素/深さ上限の失敗、非切断Error、defaultの従来回復を確認する（Q-REL/Q-PERF）。

## 2. 互換性と利用手順

- [ ] 2.1 公開fingerprintにOFFだけを識別する設定を反映し、`tests/test_fingerprint.py`と公開Run Testで旧default hash不変、default/off双方向拒否、off/off互換、Qdrant除外を確認する（Q-COMP/Q-REL）。
- [ ] 2.2 両Workflowの識別へOFFを反映し、既存workspaceの異なる推論設定を書込み前に拒否する。Workflow Testでthread識別のdefault不変/OFF分離、直接呼出し拒否、Checkpoint/Artifact/cache不変、同設定Resumeを確認する。完了状態を新設しない（Q-COMP/Q-REL）。
- [ ] 2.3 `.env.sample`、README、`tests/test_documentation.py`の許容設定を更新し、通常値維持・プロセス限定OFF・新規Run・通常への戻し方を文書Testで確認する。無関係な既存設定値は変更しない（Q-USE/Q-MAINT/運用・移行）。
- [ ] 2.4 関連Testと全体pytest、ruff check、ruff format --check、ty check、OpenSpec strict、git diff --checkを実行し、既存未コミット差分を含む検証範囲と結果をverification.mdへ記録する（Q-MAINT/Q-PORT）。

## 3. OFFでの新規実検証

- [ ] 3.1 停止済みworkerとProvider側の旧要求が稼働していないことを確認後、プロセス限定OFF、非対話、`--resume`なし、未使用export先でsample3翻訳を開始する。新旧Run IDの相違、Code/入力hash/設定、旧Artifact保持をverification.mdへ記録する（Q-COMP/Q-REL/運用）。
- [ ] 3.2 初回と後続の取得可能なProvider観測で推論OFF指定と実測tokenを分けて確認し、所要時間/推論token/通常出力token、取得不能項目、翻訳の終端結果を記録する。非0の推論が判明した場合は合格とせず診断し、highへ暗黙に戻さない（Q-FUNC/Q-PERF）。
- [ ] 3.3 新規DOCXの本文/表/表紙/目次・図表一覧を検査し、Microsoft Wordの手動相当操作で別PDFを作成する。実成果物hashと検査結果を記録し、利用者目視へ提示する。Word PDF化を製品へ追加しない（Q-FUNC/検証・供給）。
- [ ] 3.4 原本sample3と新規Word PDFをOFFの新規Reviewで比較し、公開Finding詳細・実効設定・終端結果を記録する。既知ALIGN問題や目視未確認は残し、成功終了だけで品質合格としない（Q-FUNC/Q-REL）。
- [ ] 3.5 関連Changeのverification.mdへ新規検証への参照を追加し、未完了条件を保ったまま正式verifyへ引き継ぐ。差分を限定してcommitし、`.agents`、サンプル、outputs/runs、秘密が含まれないことを確認する。受入未完了でarchive/mergeしない（Q-SEC/保守・廃止）。

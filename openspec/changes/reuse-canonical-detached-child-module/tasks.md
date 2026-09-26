<!-- markdownlint-disable MD013 MD041 -->

## 1. Debug childの計数経路修正

- [ ] 1.1 `tests/test_terminal_evidence.py`に本番runnerの実`-m`子processを通す通信禁止fixtureを追加する。成功/`PublicRunError`の両方で既知の非ゼロLLM・Embedding・Qdrant hook回数が終端JSONへ残らないことを修正前に再現する（Q-FUNC/Q-REL/Q-SEC/Q-PORT）。
- [ ] 1.2 Debug入口を通常importの既存`main()`へ委譲し、1.1のstatus・exit code・実行1回・全計数一致を確認する。新Module・依存・状態台帳・公開設定の追加がないこと、既存未コミット差分を混入させないことをdiffで確認する（Q-COMP/Q-MAIN）。
- [ ] 1.3 実LLM Adapterと応答stubで有限retry後の成功/失敗の試行数を確認し、入れ子/例外後復元・未束縛・連続実行の非混入、convert実child・watchdog・排他・cleanup回帰を通す（Q-REL/Q-PERF/Q-SEC）。

## 2. 検証と引継ぎ

- [ ] 2.1 Ruff・format・ty・全pytest・OpenSpec strict validation・diff checkを実行し、結果と既存差分の範囲をverification.mdへ記録する。既存の診断JSONは保持し、過去の0値、Embedding/Qdrant粒度、timeout途中値の限界を関連verification.mdへ追記してコミットする（Q-USE/Q-MAIN/移行・保守）。
- [ ] 2.2 sample3の新規Translation→Microsoft Word PDF化→入力/生成PDFのComparison Reviewをreasoning OFF・逐次で実行する。他Changeと同じ実検証を共有してよい。終端JSON・LLM試行数・Langfuse観測の差を説明し、入力/成果物保持・process終了・cleanupを確認する。成果物を利用者へ提示し、未解決の品質指摘と区別して正式verify・archive可否を記録する（Q-FUNC/Q-COMP/Q-SEC/運用・廃止）。

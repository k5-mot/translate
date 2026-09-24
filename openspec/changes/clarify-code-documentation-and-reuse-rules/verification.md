<!-- markdownlint-disable MD013 MD041 -->

## 中間検証（2026-09-25）

正式verifyは未完了。実translation→Microsoft WordでPDF化→reviewの順の証拠が揃うまでarchiveしない。

| 観点 | 結果 |
| --- | --- |
| Completeness | 5/10 tasks完了。2.2は実処理の完了待ち、3.1〜3.4は仕様に対する未実装・未検証事項 |
| Correctness | 汎用規約と製品固有仕様の分類を確認。製品コードの適合を意味しない |
| Coherence | 利用者の訂正に合わせてskip_specsを解除しrun-lifecycle deltaを追加。製品module、依存、保存形式は変更なし |

## 要求対応

| 利用者要求 | 管理先と対応 |
| --- | --- |
| ③-1 全関数の説明 | コメント節で非公開・特殊Method・入れ子・Testを含む。Lambdaと実行文字列も点検対象。Docstring以外の説明を排除しない |
| ③-2 導入済み機能の再実装禁止 | 単純性節で既存APIの契約比較、同等機能への委譲、差分の根拠を必須化 |
| ④ Resume二重管理禁止 | run-lifecycle deltaで一元化を要求。LangGraphへの委譲はdesign.md。CODING_RULESの再開状態節は削除 |
| ① common整理・乱雑な共通化の抑制 | 汎用的な説明責任はCODING_RULESに残し、logger/settings限定という配置制約はdesign.mdへ移管 |
| 公開入口、対応Python版、各Taskの計測 | 公開契約はrun-lifecycle delta、time.perf_counterによる実現手段はdesign.mdへ移管 |
| 製品metadata/依存/除外Pathの参考例 | CODING_RULESから除去。実際の値はpyproject.toml/uv.lock、管理方針はOpenSpec設計とし、古い例を製品要件として転記しない |

## 実施した検査

- `uv run pytest -q tests/test_documentation.py`: 3 passed。
- `git diff --check`: 指摘なし。
- `openspec validate clarify-code-documentation-and-reuse-rules --strict`: valid。skip_specsを解除したdelta追加後も再実行して合格。
- 関数説明規則は目的・非自明な制約を対象とし、既存の「自明な行の言い換え禁止」と両立する。
- 独自の再開位置管理と、入力互換性検証・Artifact入出力・副作用の冪等性を区別した。
- CODING_RULES全文を点検し、design.mdの分類表にすべての節を対応付けた。Ruff/ty/pytestなどの品質規則、汎用Package選択指針、TypeScript/Java規則は製品の動作仕様ではないため維持した。
- `rg`でLangGraph、common/、cli.py、main.py、perf_counter、3.12、製品metadataと依存名の残存を確認し、CODING_RULES内の該当0件を確認した（検索終了コード1は該当なし）。

## 未完了・既存違反

- CRITICAL: task 2.2。実translationをRun `01a0d44f-1efa-7597-9d1b-0be4c5748b85`で実行中。入力は`inputs/sample3.pdf`、出力指定は`outputs/sample3-acceptance-v2`。STRUCTUREまで完了したが、Word PDF化とComparison Reviewはまだ開始していない。
- CRITICAL: tasks 3.1〜3.4。新たに明文化した再開要求に対し、移行設計、独立状態の廃止、common整理、障害/Resume検証が未完了。規約から仕様へ移したことだけで完了にしない。
- [追加監査](../restore-docx-tables-and-indexes/coding-rules-audit.md)にある説明欠落候補474件、導入済み機能の重複、独自Resume記録は未是正。本Changeによる規約整備で解消済みにしない。
- [配置監査](../restore-docx-tables-and-indexes/architecture-audit.md)のdocument_processing/4file新設案は撤回済み。utils/redaction.pyの独立性は未承認。今回は配置を変更しない。
- 診断I/Oの間欠障害、表を含む内容検証、Run排他の指摘も本Changeで修正していない。

## 判定

実処理の証拠不足につき正式verify・archive・mainへのマージは未実施。文書検査の合格を製品の検証合格へ読み替えない。

## 再開統合の追加調査（2026-09-25）

上記は以前の時点の記録。関数説明の監査は別Changeで完了し、`4cc80e8`に記録済み。現在の実translationは同じsession 40709のlive handleで継続を確認し、Workflow内REVIEWは2535.912秒で完了した。最終DOCX・Word PDF化・Comparison Review・目視確認はまだ完了していない。

### 導入済み機能の再利用証拠

- LangGraph 1.2.11 / checkpoint 4.2.0 / sqlite 3.1.1の実APIとソースを確認。`:memory:` SQLite、`max_concurrency=1`、`durability="sync"`の合成試験で、flatな永続Taskの成功結果がResume後に再利用された。
- Page試験の呼出履歴は`[1, 2, 3, 3]`。親分割→左成功→右失敗の試験は`[root, root.0, root.1, root.1]`。後者では通常関数で再帰し、各要求の結果を一件ずつ待った。親の分割判断と左Artifact参照はLangGraphが保持し、独自Cacheは使用していない。
- ネストしたdurable Taskから別Taskの結果を待つ試験は同時実行数1で完了せず、対象の合成試験processだけを停止した。スタックによるdeadlock確定診断まではしていない。この方式を確認済みの実装手段として採用しない。
- 合成markerによるSQLite全列検査では、Task戻り値、Task例外message、config metadata、Graph入力が保存された。Task引数だけのmarkerはこの試験では保存されなかったが、観測経路もあるため秘密を渡してよいという保証には使わない。
- すべて外部モデル・利用者Fileを使用しない合成試験。別processでの再開、強制終了時の永続化、実Artifactの復元と副作用重複防止は未検証。これらは是正実装の回帰条件へ残す。

### SECURITY-CHECKPOINT-001（新規・未解決）

既存`translation.build_graph(settings)`のSPLITだけを、合成本文markerを含むValueErrorを投げるdoubleへ置換して実Graphを実行した。Langfuseは未設定、socket.connectは禁止し、保存先はメモリSQLiteのみ。status通知側で`safe_failure_reason`を適用した結果は`ValueError`だけだったが、SQLite writesの`__error__`と`get_state().tasks[*].error`には合成本文markerが保存された。

公開FailureRecord/ログの安全化だけでは、Graphが先に保存する例外本文を保護できない。Task/nodeから例外が出る前に安全な分類値へ変換し、本文・Credential・raw応答がCheckpointへ入らない回帰Testが必要。機能の移動だけで解消しない。

追加調査により、nodeで例外型を変えなくても、公開`SqliteSaver(conn, serde=...)`の保存境界で直接例外だけを安全化できることを確認した。上記のnode変換は唯一の実現手段ではない。元の例外型・retry・制御フローを保持する案を別Change [sanitize-workflow-checkpoint-errors](../sanitize-workflow-checkpoint-errors/proposal.md)として提案し、実験結果と適用範囲を同Changeの[verification.md](../sanitize-workflow-checkpoint-errors/verification.md)へ記録した。製品実装はまだなく、本指摘は未解決のまま。

### 配置と移行の状態

- 現行共通root内にrun.jsonが8 files、新しいoutputs配下のmanifest.jsonは0 filesだった。これは有効性検証済みRun数ではなくFile件数。旧データを移動・削除していない。
- 現コードには独自Page/Chunk Cache、GraphState完了一覧、WorkflowProgress集合、RunRecord.status/last_taskが残っている。さらに公開入口とWorkflowでfingerprintを別々に構築している。
- `runs.collect_input_sources`と`qdrant._registration_sources`の登録入力展開・source key生成も重複している。製品利用ゼロのatomic_publish_directory、診断だけが使うload_jsonを確認した。新配置へ丸ごと持ち込まない。
- design.mdへ責務縮小とoutputs.py案を記載したが、Q1（旧UUIDv7移行）、Q2（全操作の保存形式）、Q3（配置）の回答待ち。grill-with-docsの判断確認に従い、正式な新Change作成と製品実装へは進めていない。tasks 3.1〜3.4は未完了のまま。

今回の文書検査は`tests/test_documentation.py`が21 passed（0.25秒）、OpenSpec strict validationがvalid、git diff --checkは指摘なし。製品コードを変更していないため全製品Testは再実行していない。先行Changeの409 passedは今回の再開統合が実装済みという証拠には使わない。

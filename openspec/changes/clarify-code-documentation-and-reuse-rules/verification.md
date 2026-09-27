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

2026-09-26追記: 診断I/Oの排他は[serialize-detached-evidence-ioの統合結果](../serialize-detached-evidence-io/verification.md)へ対応付けた。承認済み後継の直接上書き方式でRepository内の実親子3 Test×10回が30/30成功し、全体811 passed / 1 skipped。これは該当保存境界の自動検証であり、旧原子的置換の原因特定、common配置、独自Resume廃止、Evidence identityや全体E2E受入の完了を意味しない。

## 承認済みの是正方針（2026-09-27）

利用者は次の6点を承認した。これは仕様判断の記録であり、実装・実E2E・archiveの完了を表さない。以前の「回答待ち」は当時の記録として残し、本節を最新の判断とする。

1. 表内画像の所属セルを確定できない場合はWorkflowを停止し、再開可能な状態を保持する。
2. 本文・Caption・表セルで、非空白の原文に対する出力訳が未作成・空配列・空文字・空白のみなら公開前に停止する。表紙と空の原文は除外する。[空訳検査Change](../require-translated-text-units-before-export/proposal.md)で具体化する。
3. 結合対象が曖昧な場合は結合せず、内容を保持して警告する。
4. 原文と訳文の対応を確定できない場合はComparison Reviewを停止し、順番だけの対応へfallbackしない。
5. 新構成のみ対応する。移行機能、旧形式読込み/Resume、互換コードおよび旧実装の併存を残さない。削除対象未指定の既存利用者データは無断で削除しない。
6. `outputs/<file-basename>/<uuidv7>/.artifacts/`とmanifestの外枠を翻訳・比較・登録・変換すべてへ適用する。複数入力は役割別に保存する。

具体的なcommonの移管先表、未確定の細部設計、製品実装、最新成果物の受入は別途必要。LLM接続障害が回復したという回答もないため、承認だけを根拠に実推論を再起動しない。

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

その後のapplyで保存境界を両Workflowへ接続し、実Graphの障害注入、公開診断、既存DBの再接続Resumeを検証した。全体441 passed / 1 skipped。過去5 DBの読取り専用検査では旧形式の例外行が4 Runに計6行残っている。修正後の実translation→Word PDF→Comparison Reviewと過去行の安全性確認は未完了であり、SECURITY-CHECKPOINT-001の最終解決は保留する。詳細・対象ID・検証範囲は同Changeの最新検証節を参照。

10:07〜10:10 JSTの追加監査で、現行rootの全10 DBと4728非空文字列/BLOBセルを検査した。旧4 Run・6行は残存し、最新OFF実失敗2件は固定TaskErrorで保存されていた。既知Credential6値と64文字本文窓の一致0だが、未知秘密・短い断片・空き領域までは保証しない。監査中のSQLite補助File作成/更新と、WAL空確認後のimmutable再監査で全File hash不変だったことも[監査結果](../sanitize-workflow-checkpoint-errors/verification.md)へ記録した。Task 4.1の影響確認は完了したが、過去浄化・実成果物受入・本指摘の最終解決とは区別する。

2026-09-26の追加監査では、修正後の完了済みOFF翻訳・Word PDF比較と直近STRUCTURE失敗の3 DBをimmutableで検査した。state/pending writeの949値はpathと許可済小metadataへ分類され、1568 logicalセルの既知秘密/本文窓一致0、最新失敗1行は固定TaskError、全DB一式のhash不変だった。[同Changeの正式verify](../sanitize-workflow-checkpoint-errors/verification.md)で実E2Eと対応付け、9/11 tasksへ更新した。新規例外保存の保護は実成功・実失敗で確認済みだが、利用者目視と旧例外行監査の限界は残り、過去浄化・Goal全体の完了とはしない。

### 配置と移行の状態

- 現行共通root内にrun.jsonが8 files、新しいoutputs配下のmanifest.jsonは0 filesだった。これは有効性検証済みRun数ではなくFile件数。旧データを移動・削除していない。
- 現コードには独自Page/Chunk Cache、GraphState完了一覧、WorkflowProgress集合、RunRecord.status/last_taskが残っている。さらに公開入口とWorkflowでfingerprintを別々に構築している。
- `runs.collect_input_sources`と`qdrant._registration_sources`の登録入力展開・source key生成も重複している。製品利用ゼロのatomic_publish_directory、診断だけが使うload_jsonを確認した。新配置へ丸ごと持ち込まない。
- design.mdへ責務縮小とoutputs.py案を記載したが、Q1（旧UUIDv7移行）、Q2（全操作の保存形式）、Q3（配置）の回答待ち。grill-with-docsの判断確認に従い、正式な新Change作成と製品実装へは進めていない。tasks 3.1〜3.4は未完了のまま。

今回の文書検査は`tests/test_documentation.py`が21 passed（0.25秒）、OpenSpec strict validationがvalid、git diff --checkは指摘なし。製品コードを変更していないため全製品Testは再実行していない。先行Changeの409 passedは今回の再開統合が実装済みという証拠には使わない。

## LangGraphの別process再開と公開境界の試験（2026-09-25追記）

task 3.1の実現手段を確認するため、既存のLangGraph 1.2.11 / checkpoint 4.2.0 / sqlite 3.1.1で、先行のメモリ試験を別process・実SQLite Fileへ拡張した。製品コード・Test File・利用者Runは未変更。`langgraph-persistence`のCheckpointer/thread単位の考え方を用い、Storeや独自完了記録は追加していない。既存SQLiteを利用し、新たなService/依存は導入していない。

### 試験構成

- `uv run python -`の親processから、同じGraph定義を持つ新しいPython childを順番に起動した。初回とResumeは別processであり、in-memory saverの使い回しではない。
- StateGraphはSTART→pages→ENDだけ。pages node内で`langgraph.func.task`を1、2、3の順に呼び、一件ずつ`.result()`を待つ。`max_concurrency=1`、`durability="sync"`、同じthread_idと既存`open_checkpoint`を使用する。
- 各durable taskは既存`atomic_write_text`で合成Artifactを安定pathへ保存し、path文字列だけを返す。Graph stateもpath配列だけで、完了ID集合・skip用digest・独立Page/Chunk Cacheを持たない。標準出力のcall番号は試験観測用で、Resume判定に読ませていない。
- socket接続は禁止、LangSmith tracingは無効。LLM/Embedding/Qdrantは呼ばない。45秒の子process timeoutは試験の異常終了保護であり、製品のローカルLLM timeoutを変更するものではない。
- 新規TemporaryDirectoryの解決済み親がRepository直下であることを確認し、試験のSQLite/合成Artifactだけをその配下へ作った。試験後に自動cleanupした。利用者Runや稼働中Reviewのprocessへ終了要求を送っていない。

### 結果

| 障害位置 | 初回終了コード / 呼出 | 別processのResume終了コード / 呼出 | 観測 |
| --- | --- | --- | --- |
| Page 3がValueError | 17 / 1,2,3 | 0 / 3 | Page 1/2はSQLiteの成功結果を再利用。失敗後のnextはpages、errorはTaskError |
| Page 3開始時に試験childがos._exit | 23 / 1,2,3 | 0 / 3 | Pythonのfinallyを通さず終了しても、今回の試験ではPage 1/2の結果を再利用 |
| Page 2のArtifact保存直後、task戻り値を返す前にos._exit | 29 / 1,2 | 0 / 2,3 | Page 2 Fileが既にあっても再実行。File存在による独自skipをしない |

前二つのResumeは3件のArtifact pathと実在Fileを返し、nextは空になった。復元したCheckpoint値のreprに合成本文/例外markerはなかった。公開境界試験でも最終nextは空で、接続終了後のSQLite関連Fileのbyte列に合成本文markerはなかった。これは上記の限定入力に関する検査であり、任意のstateや過去DBの秘密値が安全という保証ではない。

### 実装方針への含意と残る検証

- 成功した細粒度の結果を別processで再利用する機能は既存APIにある。これと同じ目的のPage完了File、Chunk完了Cache、独自進捗台帳を新設する根拠にはならない。
- 成果物公開とCheckpointへの完了保存の間には中断可能な境界がある。未記録の処理は再実行されるため、Artifactの原子的置換・外部副作用の冪等性を別契約として扱う必要がある。「一度公開済みだから全Taskを完了扱いにする」台帳で隠してはならない。
- 今回は同じ内容を同じpathへ上書きする合成Artifactだけである。Qdrant登録などの外部副作用、実Page/Chunkの欠損・改変、公開中断時の整合性、製品の可変分割処理の呼出順安定性は未検証。
- os._exitは試験child自身の強制終了であり、電源断・OS crash・POSIX環境を検証したものではない。少数回の観測から全故障条件の永続性を保証しない。
- 製品の独自状態を廃止する実装は未着手。旧UUIDv7移行・全操作の保存形式・責務配置の判断も未確定であり、tasks 3.1〜3.4は未完了に維持する。これを実translation→Word PDF→reviewの代替証拠にはしない。

追記後の既存文書/Workflow state Testは28 passed（2.22秒）、本ChangeのOpenSpec strict検査はvalid、git diff --checkは指摘なし。試験用TemporaryDirectoryの残存0件を確認した。製品コード未変更のため全製品suiteは再実行していない。

## 成功済みArtifactの欠損・改変と再検証位置（2026-09-27）

基点`4915bc6`。直前Goal Turnは仮ヘッダーの出所と有効参照を確定したため進捗ありと分類した。表示契約・登録経路・具体的なModule配置の回答を推測せず、未確認だったArtifact整合性の境界を合成実行で確認した。

`langgraph-persistence`を全文参照し、thread内Checkpointと外部Fileの責務を区別した。既存のLangGraph 1.2.11 / checkpoint 4.2.0 / sqlite 3.1.1を使用し、新しいStore、Service、依存、製品Code、Test Fileは追加していない。

### 未完了GraphのResume

START→pages→ENDのStateGraphで、Page 1/2/3の`@task`を逐次`.result()`で待つ。Taskは既存`atomic_write_text`で専用TemporaryDirectoryへ合成Fileを保存し、pathと`sha256_file`のhashだけを返す。初回はPage 3で安全な固定例外を発生させ、呼出列`[1,2,3]`、next=`pages`を確認した。その後、**試験が作ったPage 1だけ**を欠損/改変させ、SQLite接続を閉じて開き直し、同じthreadをResumeした。

| 検査位置 | Page 1欠損時 | Page 1改変時 | Resume中のTask呼出 |
| --- | --- | --- | --- |
| 検査なし | 不正Artifact参照を含んだままGraph終了 | 同左 | `[3]` |
| 成功したdurable Taskの内部のみ | Task自体が再実行されず見逃す | 同左 | `[3]` |
| `.result()`でCheckpoint由来の参照を受け取った直後 | `ArtifactIntegrityError`で停止、next=`pages` | 同左 | `[]` |

受領直後に検査する2ケースでは、試験所有Fileを元の内容に戻すと`[3]`だけを実行して正常終了した。Page 1/2の再実行、独立した完成一覧、hash一致による独自skipは不要だった。hashはFile整合性の検査にだけ使い、再開位置はLangGraphに任せた。

6ケースすべてで外部socket接続を禁止し、`max_concurrency=1`、`durability="sync"`を使用した。専用TemporaryDirectory内の対象を解決・検査してから欠損/改変させ、利用者Artifactや旧Runは変更していない。SQLite関連Fileに合成本文markerがないことを確認した。これは同一process内の別SQLite接続による検査であり、先行の別process/強制終了試験とは区別する。

### 完了済みGraphからの結果取得

別の合成Graphで、durable Taskの結果受領後にhash検査して正常完了させた。出力を改変してから別SQLite接続の`invoke(None)`を呼ぶと、node/Taskが0回のまま保存済み参照が返り、nextは空のままだった。Graphから返った参照を公開境界で検査すると、改変を拒否できた。

したがって、再開node内の検査だけでは完了済みGraphの再取得を保護できない。これはLangGraphが外部Fileを管理するという契約ではなく、Fileを受け渡す製品境界が検証すべき問題である。再開状態をFile存在や別の完了一覧から作り直す理由にはならない。

### 現行Codeとの照合と引継ぎ

- `translation.py:519`はnextなし・保存path存在でDOCXを返し、内容hashを照合していない。`comparison_review.py:457`もnextなし・出力存在で戻る。欠損時にはinitialを再投入する分岐であり、新構成のArtifact整合性Error方針と合わせて整理が必要である。これは当該Codeの読取り結果であり、現行公開CLIで欠損/改変の実再現を完了したという主張ではない。
- `common/lifecycle.py:395`のexportは独立Run statusとFile列挙に依存し、Graph由来の成果物参照との整合性を検証していない。outputsへの単なる改名移動では、この重複状態を解消できない。
- 新構成の計画では、Checkpointに保存した参照の受領直後と、完了結果の取得/export境界で同じArtifact読取り契約を使う必要がある。Task内部の独自Page/Chunk Cacheへ検査を押し込んで残さない。既存loader/saver/hashの責務へ寄せ、別の完了一覧や再開Cacheを作らない。
- 試験終了後の一時Fileはcleanup済み。製品Code/保存rootの変更、旧形式移行、実Translation/Word PDF/Reviewは行っていない。Task 3.1〜3.4は未完了。具体的な配置と公開境界の設計を承認済みへ昇格させず、正式是正Changeへ引き継ぐ。

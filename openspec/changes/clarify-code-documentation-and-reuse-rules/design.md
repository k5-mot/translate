<!-- markdownlint-disable MD041 -->

## Context

proposal.mdのWhyを参照。全関数の説明範囲とPackage再利用は汎用規約に属する。一方、再開状態の管理と採用するFramework・Module配置は製品固有の仕様・設計であり、CODING_RULESへ混在させない。監査の具体例は[追加監査](../restore-docx-tables-and-indexes/coding-rules-audit.md)にある。

## Goals / Non-Goals

関数説明と依存機能の契約比較を汎用規約へ、再開状態の要求をrun-lifecycleのdeltaへ、実現手段と配置制約を本設計へ分類する。今回の文書編集では既存コードの全是正、未承認directory配置、旧Run移行の決定は行わず、未実装事項をtasks.mdに残す。

## Decisions

1. 関数の説明はPythonではdocstringを基本とするが、利用者要求の「コメント」を勝手に一律docstring必須へ狭めず、定義に対応する説明コメントも認める。特殊method・入れ子・Testを除外しない。lambdaは周囲の説明と可読性で点検し、説明のためだけのwrapperを増やさない。
2. 機能名の一致だけで置換を決めない。導入済みversionのAPIと、入出力・例外・retry単位・永続化・副作用を比較する。同等なら再利用し、契約差があるなら差の根拠を記録する。新しい汎用adapter/frameworkを増やさない。
3. 再開状態の一元化の実現には既存のLangGraphを使用する。Taskの順序・分岐はGraph定義、再開位置・完了履歴はLangGraph checkpointを正本とし、進捗表示はその実行情報から導出する。再開を制御する独立した完了一覧、進捗台帳、Page/Chunk Cacheを追加しない。細粒度の再開もLangGraphの永続化機能を用い、Task内部に別の機構を持たせない。入力・設定の互換性検証、Artifact入出力、外部副作用の冪等性確認は残せるが、独立したTask完了状態を持たせない。移行時には障害後の再開と副作用の重複防止をTestし、既存の再開粒度を維持する。
4. commonにはlogger/settingsだけを残すという製品固有の配置制約を、本OpenSpec設計で管理する。他の既存追加は追認しない。具体的な移管先は責務監査に基づいて確定し、document_processing/4file案やutils/redaction.pyの独立配置を承認済みとして扱わない。
5. spec.mdは再開時の振る舞いと品質要求、本design.mdはLangGraphの採用と配置制約を保持する。CODING_RULES.mdにはそれらを重複記載しない。用語の変更はないため、この分類訂正だけのために新しいGlossaryやADRは作らない。
6. 公開entry pointをcli.pyとmain.pyに限定し、内部ModuleのDebug入口は公開Interfaceに含めない。Python対応版は3.12以上とする。Task経過時間はtime.perf_counter()で計測する。関数入口とBaseTask/各Taskクラスを併用する既承認方針でも、計測のために独立したTask完了台帳を設けない。
7. CODING_RULES内のpyproject参考例から製品名、Version、実行時/開発依存一覧と型検査除外Pathを除去する。実設定の正本は[pyproject.toml](../../../pyproject.toml)、解決済み依存は[uv.lock](../../../uv.lock)とし、本設計に数値一覧を複製しない。LangChain/LangGraph、Streamlit、Typer、Docling接続、Qdrant接続、PDF/DOCX処理などの製品固有の採用構成は各CapabilityのOpenSpecで扱う。例にだけ存在した直接openai依存などを、移管を理由に製品要件へ昇格させない。型検査の既存除外は今回変更も妥当性の追認もしない。

## CODING_RULES全体の分類

| 対象 | 管理先と判断 |
| --- | --- |
| 最小実装、既存API再利用、共通化の説明責任 | 汎用の開発原則としてCODING_RULESに維持 |
| 関数説明、定数根拠、古いComment更新 | 言語・製品に依存しない保守規則として維持 |
| 品質検査、秘密/生成物混入防止、無関係な一括変更禁止 | 汎用の開発完了条件として維持 |
| LangGraphでの再開管理、common配置 | 本設計とrun-lifecycle deltaへ移管 |
| Python 3.12以上、cli.py/main.py、内部Debug非公開 | run-lifecycle deltaへ契約を移管 |
| 各Task経過時間、time.perf_counter | 計測可能性はdelta、実現手段は本設計へ移管 |
| main guard、Debugから既存関数へ委譲、不要な入口の追加禁止 | ファイル名を伴わない汎用Python実装規則として維持 |
| pathlib/subprocess、Ruff/ty/pytest、標準品質Command | 開発手法・品質規則であり製品動作の要求ではないため維持 |
| 推奨Package表 | 導入必須ではない汎用的な選択指針として維持 |
| pyproject例の製品metadata/依存/除外Path | CODING_RULESから除去し、実設定と本設計の管理方針へ集約 |
| Ruffの汎用Lint/Format例、TypeScript/Java節 | 製品固有の振る舞いや構成を定めていないため維持 |

## Quality Attribute Design

Q-MNT: 汎用規約と製品固有要求の管理先を分離する。Q-REL: 再開正本を増やさず、既存違反の修正には障害/Resume Testを必須とする。文書検査は分類とScenarioの存在を確認するものであり、Runtime適合の検証を代替しない。

## Lifecycle, Migration and Operations

製品の起動方法、データ、依存を変更しない。既存監査は未解決として維持する。正式verifyの実行条件はtranslation→Word PDF化→reviewとし、製品codeが変わらない文書変更でも勝手に省略しない。

## Risks / Trade-offs

- [Risk] コメントが存在するだけで適合とする → 目的、制約、副作用の説明を実装と照合する。
- [Risk] Packageへ機械的置換してretry範囲や失敗時の保存契約が変わる → 契約差と回帰Testを要求する。
- [Risk] 規約整備を全違反の解消と取り違える → 本Changeの完了と監査是正の完了を区別する。

## Migration Plan

製品固有の再開状態節とcommon配置制約をCODING_RULESから除去し、OpenSpecの要求・設計へ移す。独立したPage/Chunk記録、独自完了情報、公開状態の正本統合は未実装として追跡する。register/convertを含む移行設計と既存UUIDv7データの扱いを確定する前に、再開データを削除・変換しない。

## 再開統合の事実調査と未承認案（2026-09-25追記）

本節はtask 3.1の判断材料であり、移行・配置の承認や実装完了を意味しない。新しい是正Changeの正式提案は、末尾の未決事項への回答後に作成する。

### 導入済み機能へ戻す対象

- 導入版はLangGraph 1.2.11、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1。Graph nodeから`langgraph.func.task(...).result()`を一件ずつ呼び、成功結果をSQLite pending writesから再利用できる。既存の`max_concurrency=1`を維持する。
- メモリSQLiteの合成試験でPage 3失敗後のResumeは呼出履歴`[1, 2, 3, 3]`となり、成功したPage 1/2は再実行されなかった。別の分割試験でも`[root, root.0, root.1, root.1]`となり、保存した分割判断と左結果を再利用できた。実Page/Chunk Artifactや別process再起動を含む検証はまだ行っていない。
- `@task`内で別の`@task(...).result()`を待つネスト試験は同時実行数1で完了しなかった。全再帰関数をdecoratorで包む案は採用しない。通常関数の再帰制御からdurableな要求をflatに逐次呼ぶか、逐次subgraphを用いる。安全な分割判断もLangGraphの結果として保持し、Resume前後の呼出順を変えない。
- Graph state、Task戻り値、config metadata、例外文字列は永続化対象になる。本文・画像・Settings・Credentialを渡さず、安定したArtifact path/ID/hashと安全な小metadataへ限定する。Settingsは実行時closure等で参照する。Task引数だけを秘密の安全な逃がし先として扱わない。
- Page/Chunkの完成ArtifactはTask全体のランダムな一時directoryとは別に安定保存し、LangGraphへその参照だけを返す。独自`.complete.json`やdigest一致をskip判定の正本にしない。checkpointが参照するArtifactの欠損・改変は整合性Errorとして検出し、黙って成功扱いしない。
- 進捗はGraph定義と`get_state().next/tasks`、履歴・`tasks/checkpoints` streamから導出する。`completed_tasks/current_task/current/total`、`WorkflowProgress.completed`、保存metadataの`status/last_task`を独立して更新する方式を廃止する。省略したTaskを架空の成功として記録しない。process生存/排他所有権と、Graphの再開位置は別の情報として扱う。
- register/convertは現在LangGraph外で直接実行している。各操作を既存処理へ委譲する最小Graphにすれば同じ状態照会が使える。登録処理を新たに全段階へ分解することや、汎用実行frameworkの追加は前提にしない。Qdrantの決定的ID・登録後照合は副作用の冪等性確認として残す。

### 機能を縮小した後の配置候補

| 現行 | 候補 | 残す責務と廃止する責務 |
| --- | --- | --- |
| runs | 新設`translate/outputs.py` | 入力copy、UUIDv7、manifest、一覧/検索、削除/exportと保存先排他のみ。Workflow・LLM/Qdrantをimportせず、Task完了状態や処理選択を持たない |
| fingerprintとlifecycleのsnapshot構築 | settingsの設定値選別＋outputsの非公開照合 | 入力・補助Fileのhashと出力影響設定を一度だけ比較。Workflow内の別fingerprint/thread ID生成も統合し、共通の実行IDをthreadへ対応させる。Qdrant状態は照合対象外 |
| lifecycle | 各Workflowと保存境界へ分解後、module廃止 | Graph実行と再開はWorkflow、入出力保存はoutputs。新しい汎用実行管理Layerへ改名移動しない |
| progress | Graph由来の通知へ置換後、独立管理を廃止 | CLI/UIは導出した通知を表示するだけ。共通完了集合やTask状態台帳を置かない |
| workspace | `translate/utils/artifacts.py` | 実利用loader/saver/hash。製品利用のないatomic_publish_directoryは廃止候補、診断だけが使うload_jsonはtests側。保存先の排他はoutputs側 |
| redaction | ログ/Trace/表示/保存の各境界へ縮小 | 設定秘密抽出はsettings、ログの既知秘密置換はlogger、Langfuse送信はadapterで許可値を選別。Artifact本文は変更しない。独立utils/redaction.pyは新設しない案 |
| terminal_evidence | `tests/`直下 | 検証child/watchdog/Evidenceに限定。製品からのcounter依存は試験側spy等へ置換し、製品からtestsをimportしない |

`identifiers.py`は既に廃止され、uuid_utils.compat.uuid7を使用しているため再移動しない。登録固有の拡張子選別・論理path/source key生成は登録Workflowで一度だけ行う。現在のruns.collect_input_sourcesとqdrant._registration_sourcesの二重展開をoutputsへ持ち込まない。安全なpath/link/重複先の拒否は保存境界にも残す。

失敗情報の共通型・変換の最終配置は未確定。既存FailureRecord全体をoutputsへ移して再び集約先にしてはならない。Graphが保存する前に安全な例外へ変換し、公開表示直前だけのredactionに依存しないことが必要。詳細はverification.mdのSECURITY-CHECKPOINT-001を参照。

### 利用者へ確認中の判断

1. 既存UUIDv7の旧保存形式を移行して同一IDのResumeを維持するか、新規処理だけ新形式とし旧データは削除せず保全・Resume非対応とするか。UUIDv4互換不要という既決定から推測しない。
2. 比較Review・登録・Markdown変換にも`outputs/<主入力名>/<uuidv7>/.artifacts/`とmanifestの共通外枠を適用するか。複数入力はrole/論理pathで区別し、一つのinput.pdfへ統合しない。
3. 上表のoutputs.py等の責務分担・配置案を採用するか。撤回済みdocument_processing/4file案を再導入しない。

いずれも回答待ち。新しい用語の合意はないためGlossaryは作らず、未承認案を採用済みADRにしない。今回の調査だけでtasks 3.1〜3.4を完了にしない。

## 参考資料（再開統合の調査）

- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence): CheckpointerとStoreの役割。今回の再開にはthread内のCheckpointを使い、別Storeを進捗台帳として追加しない。
- [LangGraph task API](https://reference.langchain.com/python/langgraph/func/task): StateGraph内からのTask呼出。Web本文の取得に制限があったため、詳細は導入済み`langgraph/func/__init__.py`、`pregel/_runner.py`、`pregel/_algo.py`、`checkpoint/sqlite/__init__.py`と合成実行で確認した。

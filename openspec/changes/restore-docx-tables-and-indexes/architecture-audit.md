# Architecture / Coding Rules audit — 2026-09-25

## 判定と調査範囲

**未解決・設計合意前。** 現在の実装が存在することと、配置が利用者に承認されていることは別である。本書はARCH-001/ARCH-002/ARCH-003の説明と判断材料であり、配置変更やTask class化の承認記録ではない。製品コードは変更していない。

対象は現在のworktreeの製品Python（CLI/UI、document、adapters、common、tasks、workflows）と追跡対象tests。既存の未commit差分も含む。`.agents/`内の第三者skill実装と`.venv/`は製品監査の対象外。入力PDF、生成物、過去Runの全データをソースコードと同じ意味で監査したものではない。ルールの参考設定を、現行Projectへの一括適用義務とは解釈しない。

担当を分けた全文確認範囲は、common 11ファイル、tasksの20 Taskとpackage marker、残りの製品15ファイル、追跡tests 43ファイル。設定はpyproject、quality CI、.env.sample、.gitignore、OpenSpec config/schemaを確認した。uv.lockはPython要件と直接依存の対応のみ確認し、全間接依存の脆弱性監査を完了したとはしない。未追跡manual_detached_historical_gate.pyも親が読取り確認したが、実LLMを起動する一時probeのため実行・commitしていない。

## ARCH-001: common全ファイルの説明

### 責務・API・利用元

| ファイル | 公開APIと現実の責務 | 利用元・依存 |
| --- | --- | --- |
| `__init__.py` | 公開APIなし。package marker | import境界だけ |
| `logger.py` | `RedactionFilter`、`configure_logging`。logging設定、機密値除去、HTTP log抑制 | lifecycleから使用。redactionに依存 |
| `settings.py` | `Settings`、`Backend`、`Command`、`load_settings`、`read_rules`。環境変数、必要値・範囲検証、rules読取り | CLI/UI、Task、Workflow、adapter。Pydantic/dotenv |
| `fingerprint.py` | `Fingerprint`、`SnapshotDifference`、`ResumeCompatibility`、`build_fingerprint`、`diff_snapshots`、`check_resume_compatibility`。入力/出力影響設定のhashと互換性差分 | 製品入口はlifecycle。settings/runs型、hashlib/json |
| `identifiers.py` | `uuid7`。時刻と乱数からUUIDv7を生成 | 製品利用元はrunsの1か所。time/secrets/UUID |
| `runs.py` | `InvalidRunIdError`、`RunInput`、`InputSource`、`RunRecord`、`RunPaths`、`RunScan`、`RunRepository`、`collect_input_sources`。Run保存、入力copy/hash、UUID/path検証、一覧、削除 | CLI/UI/lifecycle/診断child。identifiers/redaction/workspace/Pydantic |
| `lifecycle.py` | `ResumeRejectedError`、`FailureRecord`、`PublicRunError`、`PreparedRun`、`RunCandidate`、`fingerprint_for`、`candidates_for`、`prepare_run`、`execute_run`、`execute_public_run`、`export_run`、`run_size`、`load_failure`、`format_failure` | CLI/UI/診断child。Run/設定/進捗/保存に加え、Workflow、DOCX Task、Qdrant/LLM/Langfuse adapterへ依存。実際は公開操作の実行制御 |
| `progress.py` | `ProgressEvent`、`ProgressCallback`、`TaskPhase`、`TaskStatusEvent`、`TaskStatusCallback`、`bind_task_status`、`report_task_status`、`report`、`WorkflowProgress`。進捗、Task境界通知、context-local callback、完了slot重複抑止 | Workflow/lifecycle/CLI/UI。dataclasses/contextvars |
| `redaction.py` | `credential_values`、`redact_text`、`redact_value`、`safe_error`、`safe_failure_reason`。秘密値・本文・binaryの公開防止 | logger/runs/lifecycle/Langfuse/FIX/VERIFY/UI。log専用ではなく保存・表示境界でも利用 |
| `workspace.py` | `sha256_file`、`atomic_write_text/bytes/json`、`atomic_publish_directory`、`atomic_directory`、`load_json`、`OutputLock`。hash、原子的保存、fsync、directory公開/rollback、排他 | 多数のTask/Workflow、PDF/Qdrant adapter、Run/CLI/UI/診断。portalockerと標準filesystem |
| `terminal_evidence.py` | `bind_call_counts`、`count_external_call`、`TerminalEvidence`、`EvidenceStore`、`evidence_from_progress/failure`、`workspace_counts`、`DetachedResult`、`run_public_run_detached`、`cleanup_detached_temp`、`run_detached`、debug `main` | 証拠保存、OS別lock、counter、child、watchdog、heartbeat、削除が同居。LLM/Qdrant adapterはcounterのためimport。childはlifecycleへ逆依存 |

### 追加理由と、配置の妥当性の区別

- `bd0210b`はRun共有と検証基盤のため当初のcommon 9ファイルを追加した。Run共有、fingerprint、原子的保存、状態通知、秘密保護は`openspec/specs/run-lifecycle/spec.md`の要求に対応する。しかし機能の必要性はcommonへの配置承認を意味しない。
- `b881365`と`archive/2026-09-21-harden-run-identity-and-reference-registration/design.md`は、Python 3.12で依存追加なしのUUIDv7を扱う背景。1か所利用の独立helperが必須である根拠とは別。
- `4b20bc0`と`persist-detached-resume-terminal-evidence/design.md`は、長時間実行の観測喪失に対する検証専用の証拠保存・child監視の背景。製品adapterが検証runner全体へ依存することは、この検証専用境界と整合していない。
- `archive/2026-09-23-resolve-translate-contract-verification-gaps/design.md`の当時のNon-goalにはTask基底classがある。今回の利用者による再検討依頼を禁止するものではない。

### 現在の依存上の問題

```text
CLI/UI -> common.lifecycle -> workflows -> tasks -> adapters
                |                              |
                +-> common.runs/workspace       +-> common.terminal_evidence
                                                        |
                                                        +-> common.lifecycle（child実行時）
```

即時の循環importエラーではないが、汎用領域が上位の製品操作を所有し、製品から検証runnerへ依存する責務上の循環がある。ファイルを移動するだけでは解消しない。

### 配置案（未承認）

| 現在 | 推奨候補 | 代替案と判断理由 |
| --- | --- | --- |
| logger/settings | commonに保持 | 利用者承認済み。機能追加時も無制限な集約先にはしない |
| redaction | loggerの機密除去責務と統合し、保存/表示でも使うことを明記 | 独立security moduleには明確な説明価値があるが、新たな配置承認が必要。log専用だと偽って移動しない |
| workspace | 既存adapters内のfilesystem責務へ移す | 実利用が多く、保存機能自体は削除不可。製品利用のないwrapperは別途削除候補 |
| runs/identifiers | Run永続化adapterへ整理し、単一利用のUUID生成を同じ責務へ戻す | 汎用IDライブラリ化は現在の利用先から必要性を示せない |
| lifecycle/fingerprint/progress | 既存workflows内の公開操作・Resume・通知境界へ整理 | 専用runtime packageも可能だが、新しい層を増やす承認が必要。巨大な1ファイルへの単純連結はしない |
| terminal_evidence | runner/child/watchdogをtestsの検証支援へ分離。製品counter hookは必要性を再評価 | 製品がtestsをimportしてはならない。既存callback/観測境界で代替する案と最小hook維持案を比較。新event busは作らない |

移行時は、型だけを上位層へ置いてadapterから逆importする形にも注意する。Run共有/UUIDv7/fingerprint/Qdrant非包含/Resume/排他/障害記録を回帰検証し、import境界をTestする。共通root、保存形式、公開entry pointは変更しない。

### 規約に追加する案（未承認）

1. commonの承認済み責務をlogger/settingsと明示し、追加・移動は配置理由と利用者の判断をOpenSpecへ記録する。
2. 新moduleには責務、利用元、依存先、既存moduleで解決できない理由を示す。単一利用helperは独立の汎用moduleへ昇格させない。
3. CLI/UI → Workflow → Task → Adapterを基本とし、製品→検証支援の依存を禁止する。共有型・通知・設定の例外境界を明示して循環を作らない。
4. 既存dependencyの代替可否を先に調べ、独自実装や例外抑制には局所的な理由を残す。
5. 責務移動だけで既存不具合を正当化しない。保存・排他・秘密保護の契約を移行Testで保証する。

## ARCH-002: 全Taskの構造と基底class検討

20 Taskはすべてmodule-level `run()`と`perf_counter()`を持つ。Task instanceに永続状態はなく、WorkflowのTypedDict/SQLite checkpointが再開状態を保持する。

| Task（run定義行） | 入力 → 戻り値 | 保存・retry・失敗境界 |
| --- | --- | --- |
| SPLIT:24 | PDF/分割設定 → manifest | PDF adapterでdirectory atomic。入力異常は停止 |
| DOCLING:22 | PDF part列/Settings → ZIP path列 | 全part directory atomic。通信retryはadapter |
| UNPACK:36 | ZIP列 → JSON path列 | partごとatomic。後続失敗でも先行partは残る |
| MERGE:94 | JSON列/元PDF → JSON path | assetsを含むdirectory atomic |
| POSITION:304 | JSON path → JSON path | JSON/reportをdirectory atomic |
| NORMALIZE:77 | JSON path → JSON path | JSON/reportをdirectory atomic |
| LOAD:689 | Docling JSON → Document | Document JSONをdirectory atomic。未知の内容保持要素は停止 |
| STRUCTURE:402 | Document/PDF/rules/Settings → Document | 最終directory atomic＋独立page checkpoint。有限fallback |
| TRANSLATE:388 | Document/rules/glossary/Settings → Document | 全page directory atomic。応答retry/枯渇時の逐次分割 |
| TRANSLATE-LITE:29 | Document/Settings → Document | 全page directory atomic。通信retryはadapter。保護文字欠落は停止 |
| CHECK:300 | Document/glossary → page別Finding辞書 | 全page Finding directory atomic |
| REVIEW:178 | Document/checks/rules/glossary/Settings → Finding辞書 | 最終directory atomic＋chunk cache。超過/枯渇/timeoutで逐次分割 |
| FIX:78 | Document/findings/rules/Settings → Document | deepcopy後にdirectory atomic。LLM失敗は修正だけskip |
| VERIFY:45 | Document/findings/Settings → Document | deepcopy後にdirectory atomic。不承認/LLM失敗で初回訳へ戻す |
| COVER:18 | PDF/PNG path → PNG path | PNG/manifestを検証後directory atomic。失敗は停止 |
| VALIDATE:73 | Document/asset root/report path → Document | report単体atomic。入力Documentのasset pathをin-place変更 |
| MARKDOWN:518 | Document/output/cover/assets → path | Markdownとassetsをdirectory atomic |
| DOCX:14 | Markdown/output/template → path | adapterがDOCXを単体atomic公開 |
| ALIGN:54 | 英日Document/任意Settings → AlignmentGroup列 | directory atomic。LLM失敗は順序対応へfallback |
| REPORT:17 | alignment/checks/reviews/output/work → path | Markdown/JSONを個別atomic。2ファイル全体のtransactionではない |

### 実際の重複と注意点

- 計測のstart/end/printが20か所。すべて成功経路のみで、失敗時の時間は出ない。
- MERGE、STRUCTURE、MARKDOWNは内側の`_run_into()`で計測終了するため、外側のatomic公開完了までの時間を含まない。
- `translation.py:140`と`comparison_review.py:151`にはTask開始/完了/失敗と観測のwrapper重複がある。
- Taskがdirectoryを公開した後でWorkflowがdocument/findings総合JSONを追加する箇所があり、保存責務も完全には統一されていない。
- 全Taskのatomic境界・失敗継続・page/chunk cacheを基底classで一律化すると既存契約を変更する。型を`*args: object`/汎用dictへ弱めて共通化してはならない。
- Workflowは`max_concurrency=1`で、比較の左右parseも逐次。ローカルLLM/Embeddingの逐次実行を維持する。

### 選択肢（未承認）

| 観点 | 型付きBaseTaskと20個のTask class | 関数維持＋計測の共通化 |
| --- | --- | --- |
| 共通境界 | `execute()`のfinallyで計測し、固有処理へ委譲 | 各runの具体的signatureを保ち、計測contextを使用 |
| 型 | Task別InputT/OutputTが必要 | 既存の具体型を保持 |
| 差分 | class、入力型、呼出側、Testの移行。旧runを恒久wrapperにしない | 計測と必要な通知重複に限定 |
| 強制力 | 共通入口を継承契約として保証できる | 全runでの利用をTestで保証する必要がある |
| 固有責務 | retry、保存、page/chunk再開は基底に移さない | 同じ |
| checkpoint | class instanceを保存しない | 現行どおりArtifact pathを保存 |

現在の要求だけなら関数維持が最小差分。全Taskで同じ実行境界を強制する設計を採るなら、最小BaseTaskにも現在の必要性がある。class化そのものを品質改善の完了条件にしない。

## ARCH-003: CODING_RULES監査

### 実行した全体検査

| 検査 | 結果 |
| --- | --- |
| `uv run ruff check .` | 1件失敗。未追跡`tests/manual_detached_historical_gate.py:64`のprint |
| `uv run ruff format --check .` | 267 files already formatted |
| `uv run ty check` | 23 diagnostics。terminal_evidenceの5件、structureの18件 |
| `uv run pytest -q`（1回目） | 268 passed / 1 failed / 1 skipped。detached convertがexit 2、cause情報なし |
| 同失敗Testだけ再実行 | 1 passed |
| `uv run pytest -q`（2回目） | 269 passed / 1 skipped |

再実行の成功で初回失敗を消さない。非決定的な失敗の原因は未特定。外部LLM/Embeddingを呼ばずに実行した。`uv sync --dev`は本監査では未実施（依存更新はしていない）。

### 規則別判定

| 規則 | 現状と対応 |
| --- | --- |
| Python 3.12以上 | pyprojectのrequires-pythonに明記。依存更新は今回の範囲外 |
| 公開entry point | cli.py/main.pyに実行境界。terminal_evidenceのdebug入口は既存処理へ委譲するが、配置と製品依存は要整理 |
| 各Taskのperf_counter | 20 Taskに存在。失敗時・公開完了まで計る意味は規約を明確化する必要がある |
| Ruff/format/ty/pytest | 上表の通り、全完了条件を満たさない |
| 不要なwrapper/helper禁止 | workspace:87のatomic_publish_directoryは製品利用0・Testのみ。terminal_evidence:563の_run_id_from_heartbeatは呼出0。削除/統合候補 |
| 既存依存の再利用 | terminal_evidence:25–52がmsvcrt/fcntlのlockを再実装。既存portalockerでは代替不可な理由がなく、置換または例外理由が必要 |
| 責務と無関係なarchitecture変更禁止 | common配置の承認根拠不足。ARCH-001の利用者判断後に別Changeで移行 |
| 非自明な値への説明 | 下記の閾値・単位・根拠が不足。根拠を調べ、推測した説明を後付けしない |
| 古いコメント更新 | pyproject:133の「formatterと競合」にSecurity等の除外が混在、:172の「S101だけ」と実際の4項目が不一致 |
| 無関係な一括format禁止 | 本監査はソース未編集。修正時も論理変更を分離 |
| 生成物・秘密の差分混入禁止 | 本監査のcommitは説明/検証文書のみとする。既存未追跡outputs/manual成果物は含めない |
| TypeScript/Java固有規則 | 今回の追跡対象製品に該当ソースなし |

### 修正すべき型エラー

- `terminal_evidence.py:96–97`: contextmanager generatorをMapping戻り値と宣言。Iterator型にする。
- 同`:300`: `object.run_id`参照。FailureRecord等の明確な入力契約を持たせる。
- 同`:607,611`: str/objectをLiteral型として返す。検証と型の絞込みを一致させる。
- `structure.py:77,81`: `_structure_request(*args: object, **kwargs: object)`がstructuredのSettings、model、response型、reasoning等を失わせる。具体的な型付き署名へ戻す。ignore追加で隠さない。

### コメント・閾値の説明対象

`review.py:32–35`（深度3、8 items、2文字/token、2048 tokens）、`translate.py:40`（深度2）、`position.py:104–106,244`（重なり0.8、間隔−2〜24、中央値×0.6）、`align.py:105,116`（0.95/0.6/0.8）、QdrantのCHUNK_SIZE=1000/OVERLAP=100、Langfuse cacheの4、LLM診断chainの8、redactionの512文字、診断識別子の80文字、watchdogの900秒/0.25秒とLLM timeoutの関係。CHECKの長さheuristicは説明があるが、閾値の根拠は追加確認が必要。

`pyproject.toml`のtranslate全体へのcomplexity・引数数・Any等の広範除外は、参考設定からの逸脱だけで違反とは断定しない。ただし局所的必要性と除外範囲が対応するかを精査する。Lint成功を単純性の証明にしない。

追加の説明対象は`comparison_review.py:140`の比較用Page番号2、`pandoc.py:143`のgrid table幅100文字、`pdf.py:65`の画像120 DPI。`.env.sample:19`の「Contextはdeployment上限16384へ制限」という説明は現在の30208契約に一致しない。sampleの値が既定値と異なること自体と、古い上限説明は分けて修正する。

### 依存と抑制の採否

- `tests/conftest.py:16`のFakeHttpResponseは追跡コードからの参照がなく、既存httpx.Response等でTestしている。未使用helperの削除候補。
- dev依存のplaywright/pytest-playwrightは追跡TestにAPI/fixture利用がなく、browser markerの実体はStreamlit AppTest/health check。必要性を説明できなければ除去する候補。
- langsmithは直接importがなくてもarchive済み設計に運用上の理由がある。単純なimport検索だけでは削除しない。
- LLMの_exception_chain_types/_exception_originは一時probe/Test向けの設計記録がある。役割完了時の廃止判断を行う。
- Pandocの_publish_docxは障害注入Testで利用する境界であり、一行wrapperという理由だけで不要と判断しない。
- Langfuseの広い例外捕捉は「観測障害でも継続」の要求に対応。TestのPopenは稼働中server等の制御に必要で、subprocess.run推奨の妥当な例外。
- `.gitignore`はinputs/runs/.agentsを除外するがoutputsは除外していない。利用者のサンプル非commit要求に対する予防策が必要。現時点で成果物がcommit済みであるとは断定しない。

### Testの信頼性

- `test_streamlit_ui.py:183–186,215–217`のAppTest内scriptはmainの関数を直接置換し復元しない。同一processの後続Testへ影響し得る。monkeypatch/finally等で復元する。
- `test_terminal_evidence.py:255`で作ったSettingsはchildへ渡されず、childはload_settingsで実環境を読む。単体/全体差の切り分けでは設定を固定する必要がある。
- 計測・traceabilityの文字列存在Testは、失敗経路の実行保証や全現行Requirementの証明ではない。Testが通ることと、検査範囲が要求を覆うことを分ける。

## 監査中に追加で再現した製品不具合

### DATA-001: 表が品質検査・比較から脱落する

外部サービスなしで、原文セル`Budget 100 million`、訳文セル`予算`だけを持つ表Documentを作り、実Taskを呼んだ。

- 同じ文字列を`check.deterministic_findings()`へ直接渡すと`number-unit`指摘が1件。
- `check.run(document, None, output)`では`{2: []}`。
- 英日それぞれが表のみのDocumentを`align.run(..., settings=None)`へ渡すと対応群は`[]`。

CHECK:310–315とALIGN:32–38がblock.sourceのみを参照することが原因。REVIEW:196–204、VERIFY:58–68、comparison_review:122–129にも同じ範囲の欠落がある（これらの実LLM経路は本監査では実行していない）。翻訳/FIXはセルも処理するため、Task間で対象単位が一致していない。BaseTask化では直らない。表・Captionを含む比較契約と回帰Testを別Changeで修正する。

### RUN-001: 排他拒否した呼出が実行中Runをfailedにする

一時Runでstatusをrunningにし、実`OutputLock`を保持したまま、同じRunへ`execute_public_run()`を同期的に呼んだ。処理は排他エラーとして拒否されたが、元のlockを保持したままstatusが`running → failed`となり、failure.jsonが生成された。LLM/Embeddingや並列処理は起動していない。

原因箇所は`lifecycle.py:240`のlock前status更新と`:319`付近のlock取得失敗も含む失敗保存。拒否された呼出が所有者のRun状態を変更しない契約に修正する必要がある。`runs.py:280–282`のlock解放後削除も競合の疑義として残すが、削除競合は本監査で再現していない。

### DOCX境界修正の技術試験

V-C2のMERGED/HEADER/BODY表について、メモリ内の試験用構文木で全行を同じbodyへ置くと、grid tableとDOCXでMERGEDのrestart/continueが残り、BODYは第2行第2列に保持された。製品sourceは変更していない。境界をまたぐ表だけ繰返し見出しを使わず、見出しセルを太字で区別する案を利用者へ確認中。通常の表の見出し行保持、複数見出し行、Inline/Link/Code/装飾は別途実装・検証が必要。

## 次の判断と完了条件

### 利用者回答を受けた具体案（2026-09-25、配置は未承認）

「関数かclassか」の二者択一は撤回する。関数を既存呼出interfaceとして残し、BaseTaskを継承した各Task classへ委譲する併用案とする。実処理を両方へ実装する案ではない。以下の配置も、移動済み・承認済みではなく利用者への説明案である。

以下のpathは`translate/`相対。ただし`tests/`はRepository直下。

| 現行module | 実際に行う処理 | 具体的な配置案・統合/削除 |
| --- | --- | --- |
| common/__init__.py | package marker | 残す。汎用APIの再export集約には使わない |
| common/logger.py | handler/level設定、LogRecord filter、外部HTTP log抑制 | 残す。Run制御やファイル保存を追加しない |
| common/settings.py | 環境設定読取り、Pydantic検証、操作ごとの必須設定検証、rules読取り | 残す。Run状態や処理実行を保持しない |
| common/workspace.py | file hash、UTF-8/JSON/binary原子的保存、directory公開/rollback、fsync、OutputLock | adapters/filesystem.pyへ移す。製品未使用のatomic_publish_directoryは除去し、実利用のatomic_directoryをTestする |
| common/runs.py | RunRecord/Input/Paths、入力copy/manifest/hash、一覧/検索/metadata保存/削除 | adapters/run_repository.pyへ移す。ファイルとしてのRun保存境界を担当し、Workflow実行はしない |
| common/identifiers.py | Python 3.12対応UUIDv7生成 | 唯一の製品利用元であるadapters/run_repository.py内へ統合。独立moduleと旧import aliasは廃止 |
| common/fingerprint.py | 入力/モデル/OCR/token/rules/glossary/templateのsnapshot/hash、差分、Resume互換性 | workflows/run_compatibility.pyへ移す。SHA-256のfile読取りはfilesystemを再利用。Qdrant状態を含めない契約は維持 |
| common/lifecycle.py | CLI/UI共通の候補提示、新規/Resume準備、操作振分け、Run実行/成功失敗管理、障害表示、export/サイズ計算 | 実行制御はworkflows/run_lifecycle.pyへ。exportのcopy処理と保存物サイズ計算はrun_repositoryへ移し、run_lifecycleは実行順序だけを指示する |
| common/progress.py | TaskStatusEvent/context-local通知、ProgressEvent、Workflow完了slot数とResume後の進捗集計 | workflows/progress.pyへ移す。Task classはここへ依存させず、Workflow側がnode全体の成否を通知する |
| common/redaction.py | Credential置換、body/binary除外、metadata再帰処理、例外の安全な表示 | adapters/redaction.pyへ移す。ログだけでなく保存/UI/Langfuseの出力境界から利用する。loggerへの統合は、承認済みloggerを再び万能moduleにしないため採用しない |
| common/terminal_evidence.py | 検証専用Evidence型/保存、heartbeat、child/watchdog、診断counter、temp cleanup、debug入口 | tests/support/detached_runner.pyへ移す。製品adapterのcounter専用import/callは撤去し、必要な計測は検証runner側で外部呼出境界を一時的に計測する。製品からtestsをimportさせない。不要helperは廃止 |

「adaptersへ移す」の意味は、余った共通処理を押し込むことではない。filesystemはOS入出力、run_repositoryはRun永続化、redactionは外部へ出す診断/metadataの安全化、と責務を固定する。redactionは下位の純粋な変換で、Task/Workflow/Runを参照しない。loggerからredactionを使う例外方向は規約とimport検査へ明記する。class化に合わせてprogressの機能をBaseTaskへ移す必要はない。

### 新規directoryも含めた配置の再検討（2026-09-25、未承認）

利用者は既存directoryだけへの移動に限定せず、ui/・cli/等の新設も検討するよう指示した。上表はcommonの移動先の初案であり、配置の承認ではない。cli.py・main.py・common/lifecycle.py・common/progress.pyの実装を再確認した。

現状のcommon/lifecycle.pyのcandidates_forは候補と互換性を返す処理であり、対話確認や画面描画は行わない。「候補提示」という前述の説明は、候補の計算と利用者への表示に分けて読む必要がある。

| 配置候補 | 移す具体的な処理 | 採否案・理由 |
| --- | --- | --- |
| translate/cli/app.py（新設） | ルートcli.pyのTyper app、command定義、引数の受取り、終了codeへの変換 | 採用案。CLI固有の入口と製品処理を分離する |
| translate/cli/presentation.py（新設） | cli.pyの_progress、_is_interactive、_candidate_resume、端末へのRun一覧・失敗表示と確認 | 採用案。TTY判定、y/n、非対話時の新規Run方針をここへ限定する。互換性そのものは判断しない |
| translate/ui/app.py（新設） | main.pyのmain、操作選択、各操作の入力フォームと実行要求 | 採用案。Streamlit再描画を含む画面側の制御を担当する |
| translate/ui/run_management.py（新設） | main.pyの_resume_choice、_execute_ui、_run_selected、_run_management | 採用案。Run選択・確認・一覧・export/削除ボタンと共通実行への委譲。Resumeの許可判定・永続化は持たない |
| translate/ui/files.py（新設） | main.pyの_save、_downloads、UploadedFileから一時入力を作る処理 | 採用案。Streamlit固有の入出力を担当し、原子的書込みはadapters/filesystem.pyへ委譲する。Run内の入力コピーはRepositoryに残す |
| translate/ui/progress.py（新設） | main.pyの_progress_callback | 採用案。共有ProgressEventを受けて進捗バー・状態欄を描画するだけにする |
| workflows/run_lifecycle.py・run_compatibility.py・progress.py | commonの共有実行制御・互換性判定・進捗集計 | 前案を維持。CLI/UIのどちらにも属さないため、新設cli/uiへ押し込まない |
| translate/runs/ または application/（追加の候補） | Run実行制御・互換性・Repositoryを新たなまとまりへ移す案 | 今回の推奨案では見送る。共有実行はworkflows、保存はadaptersで説明でき、さらに入口と呼出層を増やす必要性がない。データ保存先runs/との区別も必要になる |

ルートのcli.pyとmain.pyは、既存の公開起動方法と総時間計測を維持し、それぞれtranslate.cli.app・translate.ui.appへ委譲する。ルートにcli/を作ってcli.pyと同名にせず、package配下へ配置する。内部moduleを新たな製品直接実行entry pointにはしない。

依存方向は「公開起動file → cli/ui → 共有Workflow → Task/adapter」を基本とする。cli/uiが一覧・サイズ取得等でRunRepositoryを直接利用する箇所も明示する。cliとuiは相互importしない。workflows/tasks/adaptersはTyper・Streamlitやcli/uiをimportしない。ProgressEventの生成・集計と、その表示を分ける。Run root・UUIDv7・fingerprint・削除対象・逐次実行の既存契約は変更しない。

commonのlogger/settings以外の移動先は上表の初案を維持しつつ、CLI/UI固有の処理を現在のルートfileから新設directoryへ分離する。この違いを明示し、common内にUI固有コードがあるかのような名目だけの移動は行わない。新設directoryも責務・利用元・依存方向を説明し、承認後に別Changeで実装する。テストは実装moduleへpatch先を更新し、公開起動方法とCLI/UI間のRun共有を回帰検証する。

### 関数とTask classの併用（方針承認済み、未実装）

```text
Workflow → tasks.docx.run(markdown, output, template)
                → DocxTask(markdown, output, template).execute()
                      → BaseTask: 開始時刻/終了時計測（finally）
                      → DocxTask._run(): DOCX変換と成果物返却
```

- `tasks/base.py`に`BaseTask[ResultT]`を置く。各Taskは既存のTask module内にclassを定義し、新規に20個の別moduleを作らない。
- 各classのconstructorはTask固有の具体型付き引数を持つ。すべてを汎用dictやobject可変引数へ変換せず、一律のInput DTOも増やさない。
- module-level runは既存署名/戻り型を維持し、instance生成とexecuteへの委譲だけを行う。直接classを使う場合も同じexecuteを通る。補助的な変換関数は関数のまま利用する。
- BaseTaskは全体の経過時間を成功/失敗ともfinallyで一回だけ計測し、元の例外をそのまま伝播する。固有処理側の重複計測は除去する。
- retry、atomic公開、page/chunk cache、部分失敗時のskip/revertは各Task/adapterに残す。モデル並列処理は導入しない。
- WorkflowはTask後の総合Artifact保存とcheckpoint更新も担当しているため、開始/完了/失敗通知は引き続きWorkflowのnode全体を囲う。Task.executeの終了だけをWorkflow完了として二重通知しない。
- Run状態/再開/全体進捗はWorkflow側に残し、Task instanceはcheckpointへ保存しない。
- 関数runとclass.executeの両経路について、同一結果・同一例外・計測一回・逐次call回数をTestする。

この併用は既存関数interfaceの維持と共通実行境界という別の目的を持つ。単なる互換wrapperの増殖や、同じ処理の二重実装にはしない。

### 確定した表方針

利用者は、見出しから本文へ縦結合する表について、セル位置・結合を優先し、その表の繰返し見出しを無効化して見出しセルを太字で区別する案に同意した。通常の表の見出し保持とHTML非使用は維持する。実装とWord/PDF受入は未完了。

- [ ] commonの配置案・全説明への利用者確認。
- [x] Task関数とBaseTask＋各Task classの併用方針への利用者承認（実装は未完了）。
- [x] 結合が見出し/本文をまたぐ表の表示方針の確認（実装・目視検証は未完了）。
- [ ] 型/Lint/Test再現性、コメント、不要コード、排他、表の検証範囲を対応するChangeへ分けてpropose/apply/verify。
- [ ] 規約に配置・依存・例外・計測の意味を追加し、実コードとTestで検証。
- [ ] sample3でWord/PDFを再生成し、利用者の目視確認を得る。
- [ ] 各Changeの指摘解消後に同期/archive、PR/CI、main merge/push。現時点では未実施。

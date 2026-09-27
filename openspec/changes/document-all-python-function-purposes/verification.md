<!-- markdownlint-disable MD013 MD041 -->

## 中間検証（2026-09-25）

本Changeは実検証待ち。以下は時点ごとの監査履歴であり、最新の進捗は末尾の追記を参照する。説明の補足・意味確認は完了したが、実E2Eと利用者目視が未完了のため、正式verifyとarchiveは行わない。

## 今回の差分

- 追跡Python 92 filesについて、開始時963関数中465関数にdocstringがなかった。193関数へ目的・境界・副作用の説明を追加し、欠落は272関数となった。残りはすべてtests配下である。既存の説明Commentを認めるため、この件数だけを規約違反数とはしない。
- 製品Pythonのdocstring欠落は0件。ただし既存docstringを含む全件の意味確認は完了しておらず、tasks 1.1と1.3は未完了のままにする。
- 両Workflowを全文確認し、43関数に説明を補足した。比較文書のID組替えと、左右文書を逐次抽出するGraphの既存説明も修正した。node接続・入出力・通知と副作用を確認し、task 1.2を完了した。
- commonの独自進捗情報、STRUCTURE Page/REVIEW Chunkの独自再開記録は現状の動作として説明し、承認済み配置・仕様適合済みとは記載していない。これらの是正は依然必要。
- 未追跡の手動診断probeにも目的説明を追加した。標準出力へ本文なしの終了JSONを返す箇所に、理由付きの局所的なT201除外を付けた。probe自体はcommit対象にしない。

## 検証証拠

- 編集開始前と編集後の追跡Python 92 filesを標準astで比較した。Module/Class/Function/AsyncFunctionの先頭docstringだけを除去したASTのSHA-256は全件一致した。既存未commitの機能差分を開始時baselineに含め、本Changeでロジックが変わっていないことを確認した。
- commit対象のPython 40 filesについても、HEADとindexの説明除去後ASTが全件一致した。既存の診断修正はstageせず、`.agents/`・inputs/outputs・PDF/DOCXがindexにないことを確認した。
- `uv run ruff check .`: 初回は未追跡probeのT201が1件。上記の目的を確認して局所的除外を追加後、合格。
- `uv run ruff format --check .`: 306 files、合格。
- `uv run ty check`: 合格。
- `uv run pytest -q`: 最終補足後にも再実行し、383 passed, 1 skipped（25.56秒）。WindowsでPOSIX PTY Testをskipしており、非対話の実CLI検査は成功した。
- `openspec validate document-all-python-function-purposes --strict`: valid。振る舞いを変更しないためskip_specsでdeltaなし。
- `git diff --check`: 指摘なし。

## 実処理の状況

- 実translationのexec session 40709をpollし、実行継続を確認した。Runは`01a0d44f-1efa-7597-9d1b-0be4c5748b85`、入力は`inputs/sample3.pdf`。
- 最新に確認した参照検索Artifactは`page-0013-chunk-0001.json`（2026-09-25 02:52:11 JST）。これは翻訳完了の証拠ではない。
- 稼働中Processは以前の実装を読込み済みであり、その結果を後続の製品修正の実E2E証拠には流用しない。
- Microsoft WordによるPDF化、原文PDFと生成PDFのComparison Review、利用者目視確認は未実施。モデルの並列実行は追加していない。

## 残作業

- CRITICAL: tasks 1.1、1.3。既存説明も含む全製品関数の意味確認。
- CRITICAL: task 1.4。残るTest関数の説明補足と既存説明の確認。
- CRITICAL: tasks 1.5、2.1。lambdaと実行Python文字列の棚卸し、および標準ast/tokenizeを用いた説明存在検査とfixture。
- CRITICAL: task 2.2。全対象完了後の最終検査と意味確認の証拠。
- CRITICAL: task 2.3。実translation→Word PDF→reviewと利用者目視の完了証拠。

## Test説明と再発防止検査の追加

- Test側の残る272関数を確認し、260関数へdocstring、空のdouble 12関数へ説明Commentを追加した。空のdoubleはpass/returnの実行構文を維持した。既存説明の全件の意味確認は別途継続する。
- 同名の入れ子関数に対する短いpatch contextが曖昧で、目的説明を取り違えた箇所があった。親関数とclassを含む完全名で追加対象を照合して修正した。前回commitのatomic File/directory障害注入の説明も入れ替わっていたため訂正した。AST一致だけでは説明の正しさを証明できないことを検査方針へ反映した。
- 公開入口・translate・testsを対象とした存在検査は93 files・967関数（未追跡の手動probeを含む）で欠落0件。noqa/type ignore/記号だけのComment、空白docstring、無関係な行のCommentは合格にしない。非公開・async・特殊method・入れ子・decorator前の説明を含む17ケースを追加した。
- 実行文字列の棚卸しで、adapter診断のexec 2関数とStreamlit AppTestの1関数へ説明を補足した。診断childの文字列には関数定義がないことを確認した。通常のTest文字列fixtureは実行対象と混同しない。lambda全件の意味確認は未完了。
- 開始時の92 filesとの比較では、docstringおよび上記3つの実行文字列内Commentを除いたASTの変更は、再発防止検査を追加した`tests/test_documentation.py`だけだった。製品の実行ASTは変更していない。
- 最終検査: Ruff合格、Format 307 files合格、ty合格、pytest **401 passed, 1 skipped（25.70秒）**、OpenSpec strict valid、diff check指摘なし。
- indexのPython全件も存在検査した。別の未commit診断修正で削除予定の`_run_id_from_heartbeat`がHEAD側にだけ残っていたため、削除は取り込まず旧関数の説明だけをstageして、indexも欠落0件とした。既存の未commit機能差分は維持し、今回のcommitへ混ぜない。
- 実translation session 40709は引き続きlive。最新の検索Artifactは`page-0016-chunk-0003.json`（03:12:10 JST）。Task完了、Word PDF化、Comparison Reviewの完了証拠にはしない。

## 更新後の残作業と判定

2/8 tasks完了。task 2.1は完了したが、1.1/1.3/1.4の既存説明を含む全件の意味確認、1.5のlambda全件確認、2.2の最終監査、2.3の実E2Eと目視が未完了。目的説明の追加だけで再実装・二重状態管理・common配置の指摘は解消しない。未実装と実検証不足を残してarchive・main merge・pushはしない。

## 公開入口・Taskの意味確認（2026-09-25、追記）

- `cli.py`、`main.py`、`translate/tasks/`全22 files（baseと空のpackage入口を含む）の全文を確認した。目的、対象範囲、入力の変更、副作用、失敗時の動作を既存説明と照合した。
- CHECKはcritical限定でなくerror/warningを返し、否定などの照合はheuristicである。VERIFYはFIX成功の有無でなくFindingの存在でページを選び、失敗時にはページ全体の初回訳を最終層と共有してskip情報を付ける。FIXのID検査はページ内の初回訳IDまでで、Finding対象に限定しない。これらを過大な説明から実態へ訂正した。
- ALIGNは低信頼対応があれば全対象をモデルへ渡す。TRANSLATEの保護処理はsplit fallback限定ではない。MERGE/STRUCTUREの「検証後に公開」は独立した全体検証を保証していないため、正常終了後の公開と記載した。BaseTaskはfinallyの標準出力も失敗し得るため、元例外を無条件に保持するという説明を除いた。
- Markdownの最終層選択はReview承認の保証ではなく、Noneでない層を優先して空列も保持する。REVIEWの重複判定keyはFindingの全JSONを含み、匿名化済みではない。文字数からのtoken見積もりはProvider上限の保証ではない。既存の独自再開記録は現状の動作として記載し、仕様適合の説明へ置き換えない。
- 24 filesのdocstring除去後ASTは、本Change開始時baselineと全件一致した。既存未commitのREVIEW機能差分はbaselineに含まれるため、commit時にはその機能変更を除外して説明だけを選択stageする。
- task 1.1を完了し、進捗は3/8。adapter/common、Test既存説明、lambda/実行文字列の最終確認と正式E2Eは引き続き未完了。

### 意味確認から判明した製品不具合（未解決）

- **CONTENT-VALIDATE-001**: `validate._require_translations`はcaptionの原文/訳文層を確認しない。第2ページに原文captionだけを持つFigureを与えて例外なしを確認した。`markdown._caption_current`はそのcaptionを原文へfallbackする。本文/セルの存在検査をcaptionへ適用する製品修正と回帰Testが必要。後続の[診断と提案](../require-translated-text-units-before-export/verification.md)で、最終層の空配列・空文字・空白も検査を通過することを再現した。先行実ArtifactのCaption 15件に層欠落はなかったが、翻訳品質の合格ではない。停止範囲を確認中であり、本指摘は未解決。
- **CONTENT-MERGE-001**: `position._merge_fragments`は結合元をbodyのchildrenから除くが、texts collectionには残す。`load.load_document`がcollectionの未出現要素を補完するため、合成した隣接paragraph `A`/`B`は結合記録1件、body参照1件に対し、LOAD後に`A B`と`B`の2 Blockとなった。表も含む結合元の所有権・除外方法をOpenSpecで確定して是正する。単純なcollection補完廃止で、bodyに現れない正当な内容を失わせてはならない。
- 上記診断はメモリ内の合成入力だけで実行し、LLMや外部Serviceを呼ばず、利用者文書・Runを変更していない。説明のみの本Changeへ製品修正を混ぜず、後続Changeで扱う。

### 実translationの進展

- 同じexec session 40709のlive handleをpollした。TRANSLATE 5703.479秒、CHECK 0.139秒の完了通知を確認し、翻訳Workflow内REVIEWへ進んだ。検索Artifactは`page-0002-review-0001.json`（03:23:25 JST）。まだ最終DOCX、Word PDF化、原文PDFとのComparison Reviewの完了証拠ではない。

### 今回の検査

- Ruff、Format（307 files）、ty、diff checkは合格。pytestは401 passed, 1 skipped（26.99秒）。skipはWindows上のPOSIX PTY検査。
- PATH上ではOpenSpec commandが見つからなかったが、導入済みnpm cache内のOpenSpec 1.13.1をnodeから起動し、project root、Change status、apply instructionsを取得した。strict validationもvalid。新しいpackageは導入していない。
- 既存configの`operations.verify`をCLIが未対応operationとして警告するが、apply instructionsとstrict検査は成功した。既存未commitのconfig編集は今回変更・commitしていない。

## adapters/commonの意味確認（2026-09-25、追記）

- `translate/adapters/`の8 files、`translate/common/`の10 filesを全関数・入れ子まで全文確認した。併せて`translate/document.py`と`tests/test_redaction.py`を確認した。20 filesのdocstring除去後ASTはChange開始時baselineと一致した。Testの空double 2関数は既存の本文先頭説明Commentで説明されている。
- 秘密除去は既知の値・field名・表記によるもので、任意の自由文の機密性を識別しない。`safe_error`、snapshot validator、ログfilter、fingerprint差分表示、FailureRecord表示の保証を過大に記載していた箇所を訂正した。既存redaction Testの説明も、実際の既知field/値のfixture範囲に合わせた。本文を出力しないという製品要求を弱めたのではなく、現行実装の不足を明示した。
- directory公開は旧先の退避と新先の公開の二段階であり、間に保存先が存在しない時間がある。例外時の復元試行とprocess強制終了後の復元は異なる。File fsyncだけでdirectory entryの永続性まで保証する説明は除いた。`OutputLock`は同じlockを使用する呼出間で保持中だけ有効であり、全更新を自動的に保護するものではない。
- Run削除は排他取得可否の確認後にlockを解放してrmtreeしている。exportはFile単位のcopyで、指定先がRun外かは検査しない。これらを現状の制約として記載し、既存の未解決事項を解消扱いにしない。
- Evidenceの`checkpoint_count`は.workspace内のFile数で、LangGraph checkpointの履歴件数ではない。Gateの`finished_at`存在はflushの実証ではない。識別子の文字種制限も機密性検証ではない。説明を修正し、検証結果の解釈を限定した。
- Langfuseの非detached経路は処理例外をSDK context managerへ渡す。導入済み`langfuse/_client/client.py`の`_start_as_current_otel_span_with_processed_media`と`opentelemetry/trace/__init__.py`の`use_span`で、既定の例外記録経路を確認した。ただし現在の製品呼出（両Workflow/Task/LLM）はすべて`detached=True`であり、これだけで現行製品からの本文漏洩が発生したとは判定しない。既存API境界を整理する際の回帰対象とする。
- task 1.3を完了し4/8。全Testの既存説明の意味確認、lambda等の最終確認、最終検査、実E2E・利用者目視は残る。common配置、独自再開記録、導入済み機能の再実装の是正は本Changeでは未解決。

### 再現した境界不具合（未解決）

- **EVIDENCE-IDENTITY-001**: 別UUIDv7・別operationのheartbeatと現在の保存Evidenceをmockから返すと、`_read_heartbeat`は拒否せず現在のID/operationへ上書きし、別実行の`llm_calls=123`を引き継いだ。識別の照合と保存先再利用の契約を是正する必要がある。
- **SETTINGS-FINITE-001**: `_positive_float`へ合成した`nan`を渡すと非有限値が受理された。環境変数のtimeout/retry/deadlineを有限正数として検証する回帰Testと是正が必要。実サービスで無期限待機が発生したことを示す診断ではない。
- SETTINGS-FINITE-001の後続調査で4秒数設定のNaN/正Infinity/overflow受理と、無効文字列のCLI原因表示を再確認した。[reject-nonfinite-service-settings](../reject-nonfinite-service-settings/proposal.md)で既存Pydanticを使う是正を提案し、内部retry=0との互換性と公開設定の正数制約を区別した。提案のみで、指摘は未解決。[検証範囲](../reject-nonfinite-service-settings/verification.md)を参照。
- 後続applyで4 fieldとenvの有限値検証を実装した。修正前32件の失敗を再現後、公開CLI/UIを含む全体556 passed / 1 skippedを確認した。実装・自動回帰は是正済みだが、修正後の実translation→Word PDF→Comparison Reviewが未完了のため、最終解決は保留する。詳細は上記の検証範囲のApply節を参照。
- **INPUT-COPY-001**: `_copy_verified`のtarget.openへ`FileExistsError`を注入すると、target.unlinkが1回呼ばれた。新規作成に失敗した対象までcleanupする。Fileの所有権を確認したcleanupへ修正する必要がある。mockだけの再現で、利用者の既存Fileが消えたとは主張しない。
- source open失敗時にも未作成targetへのunlinkを呼ぶことを再確認した。[preserve-unowned-input-copy-targets](../preserve-unowned-input-copy-targets/proposal.md)で作成成功に限定した後始末と標準copy/hash APIへの委譲を提案した。提案のみで未解決。通常の公開経路のroot衝突は既存Runを削除しないため、helperの不備と実データ喪失を区別する。
- 後続applyで4件の合成File再現Testの失敗を確認後、所有境界を是正し、独自copy/hash loopを標準APIへ置換した。関連32件と全体572 passed / 1 skippedを確認。実装・自動回帰は是正済みだが、修正後Codeの実translation→Word PDF→Comparison Reviewと目視は未完了。[最新証拠](../preserve-unowned-input-copy-targets/verification.md)にScenario対応と限界を記録し、最終解決は保留する。
- **SECURITY-BOUNDARY（既存指摘の補強）**: `safe_error(ValueError("SYNTHETIC_BODY_TEXT"))`がその自由文を保持した。既知値のマスクが任意の本文非出力を保証しないことを確認した。安全な型/固定fieldによる公開境界への縮小は配置監査の未解決方針に対応する。
- 上記4件は合成値・mockのみで検査し、外部Service呼出と実データの保存・削除は行っていない。配置整理だけでこれらの振る舞いの不具合が直るとは扱わない。

### 今回の品質検査

- Ruff、Format（307 files）、ty、diff check、OpenSpec strict validationは合格。pytestは401 passed, 1 skipped（25.86秒）。これは製品不具合の不存在や実E2E完了を意味しない。
- 同じtranslation session 40709をpollしliveを確認した。翻訳Workflow内REVIEWは継続中で、モデル要求を重複起動していない。Word PDF化とComparison Reviewはまだ開始していない。

## Lambda・実行文字列とTest説明の監査（2026-09-25、追記）

- 公開入口・translate・testsの93 filesを再列挙した。通常のFunctionDef/AsyncFunctionDefは967件、説明存在検査の欠落0件。うち1 fileは未追跡の手動probeであり、commit対象外。
- 通常source内のlambdaは37 files・149件（製品26、Test 123）。各呼出文と包含関数の目的説明を読み、sort key、stream読込み、Graph分岐、表示、retry単位、clock固定、外部呼出double、障害注入の意図を確認した。比較Graphの7 nodeには、遅延実行時の側を既定引数へ固定する理由を1か所に補足した。説明用wrapperや新しいAPIは追加していない。
- `exec` 2か所、`AppTest.from_string` 2か所、Python `-c` 4か所を確認した。最後のparametrizeは2つのCodeを持つため、実行sourceは合計9個。計3関数は既存の本文先頭Commentで説明され、説明存在検査でも欠落0件。文字列内の4 lambdaはUIの選択固定・進捗無効化・実処理置換であり、包含Testと代入先から意図を確認した。通常sourceと合わせて153 lambdaを確認した。
- Graph/正規表現のcompile、SQLのexecute、PandocのsubprocessはPython文字列実行ではない。文書検査Testの意図的に説明を欠くsource fixtureは構文解析だけで、実行対象へ数えない。
- 未追跡の`manual_detached_historical_gate.py`を全文確認した。mainの不変性の説明は、実際に比較している元checkpoint DBへ限定した。Run全体の不変性をこの比較だけで保証しない。またsummaryの`failure_present_before_cleanup`はstatusから算出する値であり、failure Fileを直接観測した証拠としては扱わない。実モデルを使うprobe自体は今回実行していない。

### 通常sourceのlambda棚卸し

| File | 件数 |
| --- | ---: |
| `main.py` | 1 |
| `tests/test_adapter_retry.py` | 20 |
| `tests/test_align_contract.py` | 1 |
| `tests/test_atomic_artifacts.py` | 1 |
| `tests/test_cli_runs.py` | 7 |
| `tests/test_comparison_capability.py` | 1 |
| `tests/test_comparison_workflow.py` | 1 |
| `tests/test_execution_exclusion.py` | 3 |
| `tests/test_failure_contract.py` | 2 |
| `tests/test_historical_resume.py` | 4 |
| `tests/test_langfuse.py` | 20 |
| `tests/test_output_contract.py` | 9 |
| `tests/test_pdf_translation_capability.py` | 4 |
| `tests/test_qdrant_registration.py` | 8 |
| `tests/test_qdrant_search.py` | 4 |
| `tests/test_redaction.py` | 1 |
| `tests/test_review_output_recovery.py` | 5 |
| `tests/test_run_interoperability.py` | 8 |
| `tests/test_run_repository.py` | 1 |
| `tests/test_streamlit_ui.py` | 7 |
| `tests/test_structure_checkpoints.py` | 1 |
| `tests/test_text_unit_review.py` | 1 |
| `tests/test_timing_contract.py` | 1 |
| `tests/test_translation_output_failures.py` | 11 |
| `tests/test_translation_workflow.py` | 1 |
| `tests/test_workflow_state.py` | 1 |
| `translate/adapters/qdrant.py` | 4 |
| `translate/common/fingerprint.py` | 2 |
| `translate/common/redaction.py` | 1 |
| `translate/common/runs.py` | 3 |
| `translate/common/workspace.py` | 1 |
| `translate/document.py` | 2 |
| `translate/tasks/align.py` | 1 |
| `translate/tasks/markdown.py` | 1 |
| `translate/tasks/position.py` | 1 |
| `translate/workflows/comparison_review.py` | 7 |
| `translate/workflows/translation.py` | 2 |

文字列内は`test_streamlit_apptest_renders_structured_failure`に1件、`test_streamlit_apptest_requires_resume_confirmation`に3件。File表の通常AST件数には含めていない。

### Testの既存説明の意味確認

今回、次の22 filesを既存docstring・fixture・assertまで全文確認した。前回の`test_redaction.py`と合わせて23 filesを確認済みとする。空の`tests/__init__.py`は関数なし。

- `tests/conftest.py`
- `tests/test_align_contract.py`
- `tests/test_atomic_artifacts.py`
- `tests/test_cover_contract.py`
- `tests/test_documentation.py`
- `tests/test_finding_contract.py`
- `tests/test_position_layout.py`
- `tests/test_position_tables.py`
- `tests/test_smoke.py`
- `tests/test_streamlit_ui.py`
- `tests/test_task_artifacts.py`
- `tests/test_timing_contract.py`
- `tests/test_validate_contract.py`
- `tests/test_settings.py`
- `tests/test_fingerprint.py`
- `tests/test_run_repository.py`
- `tests/test_run_input_manifest.py`
- `tests/test_workflow_state.py`
- `tests/test_qdrant_search.py`
- `tests/test_cli_process.py`
- `tests/test_streamlit_process.py`
- `tests/test_structure_checkpoints.py`

- HTTP response doubleが投げるのはRuntimeErrorで、httpx例外型ではない。Settings factoryはTemplate保存先を分けるが、全外部設定を自動隔離しない。説明を訂正した。
- Atomic保存Testは例外後の状態を確認するもので、並行observerやprocess強制終了時の不可分性までは検査しない。直接write検査・計測状態検査はsource文字列やFile名の検査であり、任意の別実装が存在しないことの証明ではない。
- ALIGNの当該fixtureはtarget_onlyを検査するがsource_onlyは検査しない。POSITIONの当該fixtureは段組・欄外・座標欠落を検査し、重なりは含まない。指摘は説明とcoverageの差であり、それらの製品要求を削除したのではない。
- Settings Testは固定設定値と0の拒否を検査し、稼働Providerのcontext上限やNaN/Infinity拒否の検証ではない。既存SETTINGS-FINITE-001は未解決。fingerprintの当該TestはModel変更を検査し、Rule変更は含まない。
- 非UUID名の破損directory TestはID検証で除外されるため、UUIDv7内の壊れたJSON解析失敗を証明しない。link Testはsymlinkまたはその判定mockであり、junctionを作るTestではない。copy Testはread_bytes禁止とsize一致までで、全読込みAPIのmemory使用を検証しない。
- 最小Graphのcheckpoint Testは同一invokeでのTask一回実行と失敗後の完全Artifactを確認する。障害後のResumeを起動していないので、再開後の副作用重複防止をこのTestだけで合格にしない。
- STRUCTUREのPage Cache TestはTask直接再呼出の現行挙動であり、LangGraphのcheckpoint統合済みと解釈しない。画像path変換Testも旧checkpointを実際に読んでいない。これらの説明を実装に合わせた。

### 検査結果と残作業

- 今回編集した16 Python files（未追跡probeを含む）は、先頭docstringを除いたASTが編集前と全件一致した。実行文字列には今回変更を加えていない。
- 最終補足後の検査はRuff、Format（307 files）、ty、diff check、OpenSpec strict validationが合格。pytestは401 passed, 1 skipped（25.62秒）。Windows上のPOSIX PTY Testだけがskipであり、実LLMのE2E合格を意味しない。
- task 1.5を完了し、進捗は5/8。task 1.4は残る21 Test filesの既存説明の意味確認が必要。2.2は全対象完了後の最終監査、2.3は実E2Eと利用者目視が必要であり、未完了のままとする。
- 実translation session 40709の同一live handleを再pollした。翻訳Workflow内REVIEWは継続しており、03:45:39 JSTに.review領域の更新を確認した。これは最終DOCXの完成やComparison Reviewの完了ではない。モデル・Embeddingを並列起動していない。

## 全Testの意味確認完了（2026-09-25、追記）

残る21 filesをfixture・double・入れ子・assertまで確認した。先の24 files（空のpackage入口を含む）と合わせ、追跡対象Test 45 filesの意味確認を完了した。未追跡の手動probeは前節の別枠監査を維持し、commitしない。

- `tests/test_adapter_retry.py`
- `tests/test_cli_runs.py`
- `tests/test_comparison_capability.py`
- `tests/test_comparison_workflow.py`
- `tests/test_execution_exclusion.py`
- `tests/test_failure_contract.py`
- `tests/test_historical_resume.py`
- `tests/test_invalid_pdf_lifecycle.py`
- `tests/test_langfuse.py`
- `tests/test_output_contract.py`
- `tests/test_pdf_translation_capability.py`
- `tests/test_qdrant_registration.py`
- `tests/test_review_output_recovery.py`
- `tests/test_run_failure_resume.py`
- `tests/test_run_interoperability.py`
- `tests/test_structure_diagnostics.py`
- `tests/test_terminal_evidence.py`
- `tests/test_text_unit_review.py`
- `tests/test_traceability.py`
- `tests/test_translation_output_failures.py`
- `tests/test_translation_workflow.py`

### 説明と証拠の範囲

- CLI/UI共有Testは一部のWorkflowを置換している。Resume準備だけのTestを、再開後の製品処理完了と表現しない。比較Capabilityは合成Documentを使用し、実PDFの抽出品質を検証していない。
- Qdrant登録のbatch TestはVectorStore/retrieveのdoubleを使い、実Embeddingのbatch制限を検証していない。原PDFのPath.read_bytes禁止も、あらゆる読込みAPIのmemory使用を測る検査ではない。revision Testが変更する設定と、固定schema名のassertを区別した。
- LLM retry TestのHTTP status、構築境界、指定試行回数を具体化した。例外chainのTestは非循環の二段で、循環耐性を検査していない。
- Historical Resumeのfixtureは合成三頁で、page 2の独自Cacheを再利用する現状の挙動を確認する。LangGraphへの状態統合済みや実履歴PDF全体の合格とは扱わない。link拒否Testも判定のmockであり実junctionではない。
- LangfuseのGraph Testは呼出元threadでの実Graph/SDK処理と固定応答を検証する。SDK障害Testは各fixtureが注入した境界だけを証明する。Evidenceの安全性Testには秘密値を入力していないものがあり、一般的な秘密除去の証明とは扱わない。
- traceability Testは初期archiveの件数・行番号・参照Test名の存在を確認する。現在の全要求とTestの意味的な一対一対応を自動検証するものではない。実Pandoc Testと最小OOXML doubleによる公開境界Testも区別した。
- 説明を実態へ修正したのであり、製品要求や未解決の検証項目を弱めてはいない。

### 追加の製品不具合（未解決）

- **CONTENT-PROTECTED-001**: `translate._restore_chunk_placeholders`は保護対象の対応表が空なら検査せず応答を返す。合成応答に未知の`__PROTECTED_9_9__`だけを入れた呼出で、応答identityと未知markerがともに保持された。split fallbackの既存Testでも保護対象がない後半Chunkを検査していない。対応表が空の通常/分割Chunkを含む未知marker拒否と回帰Testが必要。今回の診断はメモリ内だけで、外部Service・利用者Fileの変更はない。説明のみの本Changeへ製品修正を混ぜない。

### 最終静的・オフライン検査と残作業

- 上記21 Test filesのdocstring除去後ASTは編集開始時baselineと全件一致した。`translate/tasks/translate.py`もHEADと説明除去後ASTが一致し、今回の製品差分は空対応表の現状説明だけである。先行節の全製品・lambda・実行文字列監査と合わせ、tasks 1.4/2.2を完了した。
- Ruff、Format（307 files）、ty、diff checkは合格。pytestは**401 passed, 1 skipped（26.51秒）**。skipはWindowsのPOSIX PTY Test。OpenSpec strict validationも再実行しvalidを確認した。
- 進捗は**7/8**。task 2.3の実translation→Microsoft Word PDF化→Comparison Reviewと利用者目視が残る。記載した製品不具合、common整理、独自再開記録と依存API再利用の指摘は別途是正が必要であり、説明監査完了を製品全体の適合としない。
- 同じtranslation session 40709のlive handleを再pollした。翻訳Workflow内REVIEWを継続中で、03:59:32 JSTの中間領域更新を確認した。最終DOCXは未確認。Word PDF化とComparison Reviewは未開始。旧実行中Processへ後から加えた実装修正は反映されないため、その結果だけで新実装のE2Eを合格にしない。

### 指摘の後続対応

CONTENT-PROTECTED-001は既存Change [harden-protected-fragment-restoration](../harden-protected-fragment-restoration/verification.md)で実装修正し、通常・分割Chunkの回帰Testを追加した（全体409 passed, 1 skipped）。本説明Changeへ機能変更を混ぜず別commitで扱う。実E2E受入は未完了であり、ほかの指摘を解消扱いにしない。

### CONTENT-MERGE-001の追加調査（2026-09-25、未解決）

grill-with-docsの環境事実調査として、外部Serviceを呼ばないメモリ内の合成Docling文書でPOSITIONの結合とLOADを連続して検査した。製品・Test Fileは変更していない。

| 条件 | 観測 |
| --- | --- |
| 近接する本文A/Bと、bodyに現れない別本文 | LOADは結合済み`A B`に加えて`B`と別本文を出力する。正常なcollection補完も必要なため、fallback全廃は不可 |
| 近接する同列数の表TA/TB | LOADは結合先にTA/TB、結合元にTBを出力し、後半行が重複する |
| 同じA/Bを二つのgroupがchildrenから参照 | 同一POSITION呼出内に二回結合され、結合先本文が`A B B`になる。LOADだけの除外では修正できない |
| 結合した表の各先頭cellが独自self_refを持つ | 現在の文字列置換後は双方が`#/tables/0/cell/0`となる。LOADはcell IDを別に生成するが、中間文書の参照衝突を解決済みとはみなせない |
| 各表にgridとtable_cellsが共存 | POSITIONはtable_cellsだけをTA/TBへ更新し、LOADは未更新gridを優先する。現状は別表のTBで偶然残るため、結合元の除外だけを追加するとTBが欠落する |
| POSITIONを結合後の同じ文書へ再適用 | 追加のmerged記録は空でも、collectionに残る結合元はLOADで再出力される |

#### 保存契約と既存APIの事実

- `PositionTask.run`は結合出典を同じdirectoryのreport.jsonにだけ保存する。戻り値のdocument.jsonには含めず、NORMALIZE/LOADはreportを受け取らない。既存のlayout_merges等を利用できるという前提は誤りである。
- NORMALIZEは文書をdeep copyして加工するため、中間文書内に明示した出典対応を維持する案は検討できる。ただし新しいArtifact契約になる。採用する場合もTask完了・再開位置・skip判定を持つ台帳にしてはならない。
- 既存MERGEの`_remap`はself_ref/$refを再帰的に見てcollection indexへ一定offsetを足す処理であり、削除後の疎なindexの詰め替え、結合先への対応、cell suffixの更新をそのまま提供しない。名前だけで同等APIと判定しない。
- 導入済み依存にはdocling/docling_coreの文書編集APIが見つからず、現在はDocling ServiceのJSONを扱っている。未導入Packageを再利用可能と主張したり、この小修正のためだけに依存を増やしたりしない。
- 修正範囲には、結合元の再出力防止だけでなく、共有参照の二重結合防止、表の複数表現の整合、子要素・Caption・cell参照の保全が必要。未結合の正常要素は保持する。同じ文字列というだけの内容ベース除重は行わない。

#### 未確定の振る舞い

複数親やCaption/子要素の帰属を安全に引き継げない場合について、「結合せず内容を保持して警告・続行」（推奨）と「Workflow停止・Resume保持」を利用者へ確認した。回答前に方針を確定した新Changeや製品修正は作らない。提案候補は`preserve-merged-fragment-content-on-load`。既存の曖昧な表を未結合で残す挙動を参考とするが、本文の共有参照等まで承認済みとはみなさない。

実sample3への発生件数や修正結果はまだ未確認。最新実translationは別のHTTP 500で停止しており、[実機記録](../sanitize-workflow-checkpoint-errors/verification.md)を参照。本調査を実translation→Word PDF→Comparison Reviewの代替証拠とせず、CONTENT-MERGE-001とtask 2.3は未完了に維持する。

記録更新後の既存文書/POSITION Testは25 passed（0.37秒）、本ChangeのOpenSpec strict validationはvalid、git diff --checkは指摘なし。POSITION Testは結合後の値・body参照等を検査するがLOADとの連続実行や上記の追加条件を含まない。この既存Testの成功は不具合がないことの証明ではなく、修正前に統合回帰Testを追加して失敗を確認する必要がある。

### CONTENT-MERGE-001の実sample3影響確認（2026-09-26、未解決）

前節の合成再現を繰り返して修正済みとはせず、既存の完了済みOFF翻訳Run `01a0d8b6-c2ab-7c92-bed9-58403a8410b3` の保存Artifactを読取りで照合した。現在のCodeはc072161で、POSITION/LOAD/NORMALIZEにHEADからの差分はない。新規翻訳・外部Model要求・Word PDF生成は行わず、本文を診断出力へ転記していない。

| 確認境界 | 観測 |
| --- | --- |
| POSITION report | 結合19件、すべてlabel=text、warning 0件。実Runでは表の結合記録なし |
| LOAD | 全156 Block中、結合元17件とそれぞれの結合先が共存。17件すべてで結合元の非空source文字列が結合先source文字列にも含まれる |
| STRUCTURE/VERIFY/VALIDATE | 結合元17件と結合先が引き続き共存。STRUCTURE以降のsource文字列包含は13件で、残る4件について文字列一致だけで意味の重複を断定しない |
| 既存Markdown | 最終Documentの既存render_blockをメモリ上で適用し、13組で結合元/結合先の両方の非空描画文字列が保存済みMarkdownに存在することを確認。17組すべてのDOCX/PDF表示を目視確認した証拠ではない |
| 残る結合元2件 | `#/texts/96`と`#/texts/98`、元ページ7。LOADのpicture配下内容の除外集合に含まれ、caption所有/目次ページ除外ではない。結合が正当かをこれだけで承認しない |

再出現17件の元ページ別内訳は、2:4件、3:2件、4:2件、5:1件、6:2件、7:1件、8:1件、9:2件、11:1件、12:1件。例として`#/texts/27→#/texts/26`（ページ2）の結合元と結合先がLOAD以降にも残る。内容が同じという推測ではなく、POSITIONのfrom/into ID対応とLOAD Block IDを照合した。

読取前後の対象Artifact hashは不変。再照合用SHA-256:

- `.workspace/position/report.json`: `282a3e23b80924532189c0647d9b75d6258bc1ef527f7d02b315541a2c037656`
- `.workspace/verify/document.json`および`validate/document.json`: `2aaebd292e1f69bb99bbcf8b89255961c590e0ee3663214dcf48b224a7587485`
- `.workspace/markdown/document.ja.md`: `7251a91831914f26251b44dd48a21311e8318d052315df55b44647374de159c3`

#### 参照書換えによる本文改変の追加事実

grillingの限定した読取りsub-agentが`position._rewrite_ref`と実`_merge_table`をメモリ上で検査し、main agentも前者を再現した。`_rewrite_ref`（position.py:91）はself_ref/$refだけでなくセル全体の全文字列に部分一致replaceを行う。`#/tables/1`から`#/tables/0`への付替えで、合成セル本文`literal #/tables/10 then #/tables/1`は`literal #/tables/00 then #/tables/1`へ変化する。実_merge_tableでも結合先へコピーしたセル本文が同じように変化する一方、元セルはdeep copyで保持される。

これは合成例での不具合証拠であり、今回の実Runは表結合0件なので実sample3にこの本文改変が発生したとは主張しない。結合元の除外だけを直すのではなく、参照フィールド限定・参照境界一致・cell ID衝突・gridとの整合を修正計画へ含める必要がある。既存POSITION Test 4件には参照風の本文保存、LOADとの連続検査がない。導入済環境を再確認してもdocling_coreは未導入であり、新しい依存を追加したり既存Libraryで解決済みと仮定したりしない。

#### 未回答の判断と計画境界

実データへの影響が確認できたため優先度は維持する。ただし「複数親・Caption/子要素の帰属が曖昧なとき、結合せず保持＋警告で続行するか、Workflowを停止するか」は未回答のまま。grill-with-docsの判断待ちとして、製品変更・方針を確定した新Change作成は行わない。推奨は前節と同じく前者で、これは曖昧な結合の回避であって、17件の再出現を許容する意味ではない。確定した結合元は一度だけ扱い、正当な未参照内容は保持するという修正目的を変えない。

### CONTENT-MERGE-001の判断確定と是正計画（2026-09-27）

前節の未回答状態は解消した。利用者は曖昧な結合について「結合せず内容保持＋警告で続行」を承認した。別Change [preserve-merged-fragment-content-on-load](../preserve-merged-fragment-content-on-load/proposal.md)に仕様・設計・実装Taskを作成した。結合元の再出現、共有参照、Caption/children、grid/cells、cell IDと一般文字列の保全を対象とする。今回は計画のみであり、CONTENT-MERGE-001と本Changeの実受入Taskはまだ完了にしない。

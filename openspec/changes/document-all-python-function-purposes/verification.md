<!-- markdownlint-disable MD013 MD041 -->

## 中間検証（2026-09-25）

本Changeは実装途中。全関数の意味確認・Test側の補足・再発防止検査・実E2Eが未完了のため、正式verifyとarchiveは行わない。

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

- **CONTENT-VALIDATE-001**: `validate._require_translations`はcaptionの原文/訳文層を確認しない。第2ページに原文captionだけを持つFigureを与えて例外なしを確認した。`markdown._caption_current`はそのcaptionを原文へfallbackする。本文/セルの存在検査をcaptionへ適用する製品修正と回帰Testが必要。実PDF全体での発生件数は未確認。
- **CONTENT-MERGE-001**: `position._merge_fragments`は結合元をbodyのchildrenから除くが、texts collectionには残す。`load.load_document`がcollectionの未出現要素を補完するため、合成した隣接paragraph `A`/`B`は結合記録1件、body参照1件に対し、LOAD後に`A B`と`B`の2 Blockとなった。表も含む結合元の所有権・除外方法をOpenSpecで確定して是正する。単純なcollection補完廃止で、bodyに現れない正当な内容を失わせてはならない。
- 上記診断はメモリ内の合成入力だけで実行し、LLMや外部Serviceを呼ばず、利用者文書・Runを変更していない。説明のみの本Changeへ製品修正を混ぜず、後続Changeで扱う。

### 実translationの進展

- 同じexec session 40709のlive handleをpollした。TRANSLATE 5703.479秒、CHECK 0.139秒の完了通知を確認し、翻訳Workflow内REVIEWへ進んだ。検索Artifactは`page-0002-review-0001.json`（03:23:25 JST）。まだ最終DOCX、Word PDF化、原文PDFとのComparison Reviewの完了証拠ではない。

### 今回の検査

- Ruff、Format（307 files）、ty、diff checkは合格。pytestは401 passed, 1 skipped（26.99秒）。skipはWindows上のPOSIX PTY検査。
- PATH上ではOpenSpec commandが見つからなかったが、導入済みnpm cache内のOpenSpec 1.13.1をnodeから起動し、project root、Change status、apply instructionsを取得した。strict validationもvalid。新しいpackageは導入していない。
- 既存configの`operations.verify`をCLIが未対応operationとして警告するが、apply instructionsとstrict検査は成功した。既存未commitのconfig編集は今回変更・commitしていない。

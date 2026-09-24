<!-- markdownlint-disable MD013 MD041 -->

## 計画時点の状態（2026-09-25）

本Changeは提案のみ。製品実装0/11 tasks、正式verify・archive・merge・pushは未実施。[元の指摘](../clarify-code-documentation-and-reuse-rules/verification.md)のSECURITY-CHECKPOINT-001は未解決のまま。

## 再現と導入済みAPIの証拠

- 実製品`translation.build_graph()`のSPLITだけを合成例外へ置換し、network禁止・メモリSQLiteで調査した。既定の保存では`__error__`とsnapshotに本文markerが残る。
- 同じ実Graphへ公開`SqliteSaver(conn, serde=...)`から、直接BaseExceptionだけを固定文字列へ変換する実験用serializerを渡すと、SQLite内本文marker=false、custom repr marker=false、再読込のtasks.error=`TaskError`となった。呼出元へは元のRawError型が伝播した。
- 標準serializerでは、普通の例外のcause/context/notes/任意属性は直接保存されなかったが、dataclass例外のfieldとcustom reprが参照する属性は保存された。通常例外一種類のTestだけでは不十分。
- 直接例外だけの変換ではnested dict/list内例外とconfig metadataの文字列は保護されなかった。後者はSqliteSaverのjson.dumpsでserdeを迂回する。製品Graphのstate/configへの本文持込み禁止を緩めない。
- Graph task/debug event formatterは元errorオブジェクトを保持した。永続化の対策をstream/ログの安全化と同一視しない。
- 同期・逐次の実Graph合成試験で、GraphBubbleUpは同型伝播しerror保存なし、GraphInterruptはLibraryが処理してinterrupt payloadを保存、asyncio.CancelledErrorはNodeCancelledErrorへ変換、KeyboardInterrupt/SystemExitは同型伝播し当該経路でerror保存なし。製品wrapperはこれらもfailed通知するため、将来interruptを製品へ導入するときの扱いは別途検討が必要。
- 上記はすべて外部Service・利用者文書を使わない調査用試験で終了コード0。製品ファイルとTestファイルは未編集。提案の有効性を示すが、正式な回帰Test・製品への接続・別接続Resume・実機検証の代わりにはならない。

## 既存実翻訳

session 40709へwrite_stdinを行い、同じlive sessionが返ることを確認した。初回は追加出力なし、再確認時には`FIX 1440.792 s`と`[12/17] FIX`の完了通知が得られた。終端結果はまだ得ていない。沈黙を失敗と判定せず、停止・再起動や追加モデル処理を行っていない。このprocessは本Changeの未実装コードを読み込んでいないため、完了しても修正検証の証拠にはしない。

## 残課題と判定

- CRITICAL: 本Changeの全実装・統合・実成果物Taskは未完了。メモリ試験のみで安全性を達成したと判定しない。
- 過去に保存された例外情報は未調査・未変更。新規保存を防ぐ修正で過去分も消えたとは主張しない。
- common最終配置、旧UUIDv7移行、全操作の新layoutの未回答事項は、独立した既存の確認事項として保持する。本提案をそれらの承認に読み替えない。
- 正式verifyには修正後translation→Word PDF化→原文/生成PDFのComparison Reviewとユーザ目視が必要。新たな指摘があれば保持し、archiveへ進めない。

## 計画文書の検査

- `openspec status --change sanitize-workflow-checkpoint-errors --json`: proposal/design/tasksがdone、specsは既存要求の不具合修正のためskip_specsでskipped。これは計画Artifactの存在確認であって、実装完了を意味しない。
- `openspec validate sanitize-workflow-checkpoint-errors --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed（0.24秒）。
- `git diff --check`: 指摘なし。
- 製品Codeを編集していないため、全製品Test・Ruff・型検査・実機Gateは本提案ターンでは未実行。tasks.mdに残す。

## Apply中間結果（2026-09-25）

以下は上記計画時点からの更新。6/11 tasksを完了した。正式verify・archive・merge・pushは未完了で、実機Gateを自動Testに置き換えていない。

### 実装と自動検証

- `adapters/checkpoint.py`で直接BaseExceptionだけを固定文字列`TaskError`へ変換する。通常値の保存・全値の復元はJsonPlusSerializer、SQL・transaction・pending writes・ResumeはSqliteSaver/LangGraphへ委譲する。Translation/Comparison Reviewの接続生成だけを変更した。
- 既定serializerの両製品Workflowで本文markerが残る追加Test 2件が失敗することを確認後、修正後の成功を確認した。Workflow全体を置換せず、失敗Taskだけをdoubleとした。
- 新規adapter Testは26 cases。例外args/custom repr/dataclass/未知型名/chain/notes、通常値互換、成功/失敗時の接続close、両Graphの制御例外、型指定retryの成功/枯渇を検査した。元の例外と制御フローは維持する。
- 両Workflowの旧serializer DBと新DBについて、接続を閉じてから製品入口でResumeし、成功済みTaskの呼出数が増えず、失敗Taskだけ追加実行されることを確認した。
- 公開CLIから実GraphのSPLIT失敗を通し、Task/Page/role/group/stage/原因分類/token数を維持し、診断出力・failure.json・Run metadata・DB/WALに合成markerが残らないことを確認した。入力copyの本文は意図された保存であり除外した。
- 対象Test群は55 passed。全品質Gateを再実行し、Ruff lint成功、format 314 files成功、ty成功、pytest **441 passed / 1 skipped（28.19秒）**、OpenSpec strict validation valid、git diff --check指摘なし。
- 実行時HEADは`b72716b`。本Changeの差分は新adapter、2 Workflowの接続箇所、新Testと既存3 Test files。本Change前から未コミットのLLM/review/lifecycle/terminal_evidence関連差分も存在するworktreeで検証したため、HEAD単体の検証結果とは報告しない。無関係な差分は今回のcommitに含めない。
- 全追加関数に目的説明があり、新Dependency・common追加・独自完了台帳はない。nested例外、state/configの本文、Graph task/debug streamは本serializerだけでは保護されないという設計上の適用範囲を維持する。

### 先行する実translationとWord/PDF

session 40709は終了コード0、TOTAL 10053.468秒で終了した。Runは`01a0d44f-1efa-7597-9d1b-0be4c5748b85`。このprocessは修正前に起動しており、本Changeや起動後の他ChangeのRuntime証拠には使わない。

- DOCX: `outputs/sample3-acceptance-v2/document.ja.docx`
- PDF: `outputs/sample3-acceptance-v2/document.ja.pdf`
- DOCX SHA-256: `02670602e0ac7f3edd65a9ee8a549a22f3bcb02dda29a52964124e606c0a6383`
- PDF SHA-256: `c6ddeac815919742b20a95af5882832658261eed797a7732c0635fca543cbab4`
- 自分で起動した非表示Microsoft Word 16.0で読取り専用Open、Repaginate、ExportAsFixedFormatを実施し、そのinstanceをClose/Quitした。リンク更新とmacroを無効化し、DOCXは保存し直していない。Wordは表3個・28ページを認識した。DOCX内field instructionは0個で、一覧は静的である。
- PDF renderの1/2/3/4/5/25/26/27ページを目視した。表紙は1ページ目、目次は2ページ目、図一覧は3〜4ページ目、表一覧は5ページ目。いずれも空ではない。25ページに評価表の枠・セル本文がある。
- **既存品質指摘が残存**: 26ページのステータス表は丸印を欠き、黄・緑の10個の丸が27ページに独立配置される。消失ではなくセルとの関連付け・配置の不備である。図一覧はFigure 2から始まり、テンプレートの仮ヘッダー/フッターも残る。[表出力Changeの残課題](../restore-docx-tables-and-indexes/verification.md)を解消扱いにしない。
- 利用者へ上記Word/PDFと問題箇所を提示し目視を依頼したが、回答はまだない。3.2の修正後成果物の確認をこの先行結果で完了にしない。

### 過去Checkpointの読取り専用調査

現在の共通rootから`*/.workspace/checkpoints.sqlite`を対象に、SQLite URIの`mode=ro`で5 DBを開いた。`writes.channel='__error__'`のtype/valueを読み、固定分類のbyte列との一致件数だけを確認した。例外本文の表示・復元やDB書換え・削除は行っていない。

| Run ID | Checkpoint数 | 過去例外行数 | 固定分類以外 |
| --- | ---: | ---: | ---: |
| 01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5 | 9 | 1 | 1 |
| 01a0c97c-f5cf-7031-b808-4ad545133925 | 9 | 1 | 1 |
| 01a0d080-2c51-7da5-a91b-700b9a21e7a9 | 19 | 3 | 3 |
| 01a0d2fc-f952-722c-86bc-866103f75773 | 20 | 1 | 1 |
| 01a0d44f-1efa-7597-9d1b-0be4c5748b85 | 19 | 0 | 0 |

固定分類以外の計6行は、本文・秘密を含まないことをこの件数調査だけでは証明できない。新実装で過去行も浄化されたとは扱わない。別layout/削除済みDB/空き領域を含む完全調査ではない。task 4.1は実機証拠との対応付けが残るため未完了のままとする。

### 修正後の実translation開始

- 起動: `uv run python cli.py translate inputs/sample3.pdf --output-dir outputs/sample3-checkpoint-acceptance`
- Run ID: `01a0d4f7-20bf-7ed0-b580-7ddd2cb6299d`、追跡session: `58094`。SPLIT〜STRUCTUREの8 Taskが完了し（STRUCTURE 102.352秒）、同じlive handleでTRANSLATE処理中。終了コードと成果物hashは未取得のため3.1を完了にしない。
- code commit: `419b6e15e16a2c4f63383b05d3a639bc93db0eda`。起動時の追跡File差分（`git diff --binary`）SHA-256: `f4f834059bc84c6ef2158dc4da64e65063eb4b4a95a63e13609ce703295fba7e`。
- 入力SHA-256: `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`。
- 未コミットの製品File SHA-256: `translate/adapters/llm.py` = `d75bef0d3baea485a9d3b6510cd0aef8badfb0f45fcfdd77ec9aef0951186014`、`translate/common/lifecycle.py` = `d15eb3dff4782da13cc747f695e9731b8f4da1b3103e3a5ba73e5214499ddc8a`、`translate/common/terminal_evidence.py` = `881339c47e68857e782f21b4d7c2e2609c65ab4e6458584c3a5e6c1cd565b6f8`、`translate/tasks/review.py` = `b968b2ac43d23032f435c7a8486901c07334cf0a3c76f4899a9b7f4f01e54c14`。
- contextは30,208 tokens、request timeoutは1,800秒、Task deadlineは21,600秒。実Model/Embeddingは逐次実行し、先行translationの終端後に起動した。実行中の製品Fileを変更しない。
- 接続時にQdrant clientから`Api key is used with an insecure connection.`という環境警告が出た。鍵値は表示されていない。Checkpoint修正とは別の通信保護上の確認事項として残し、警告の抑止や接続先の無断変更は行わない。

### 先行実translationの終端と実失敗保存（2026-09-25）

- session 58094は終了コード1で終端した。Run `01a0d4f7-20bf-7ed0-b580-7ddd2cb6299d`はTRANSLATEの`text-invoke`で`OpenAIConnectionError`となり、TRANSLATE 2321.043秒、TOTAL 2455.420秒。failure.jsonの時刻は`2026-09-24T20:30:12.019004Z`。DOCXは0件で、Word PDFとComparison Reviewへは進めない。
- 同じprocessの停止を終端handleで確認した後、SQLiteをmode=roで検査した。checkpointは10件、writesの`__error__`は1件。その1件のtype/valueは既定Serializerが生成する固定値`TaskError`と一致した。raw例外や本文は表示・復元していない。実際の失敗でも今回の例外保存境界が働いた証拠だが、全Checkpoint値の本文不在や過去DBの浄化まで証明するものではない。
- 終了時にOpenTelemetryのspan export timeoutも記録された。翻訳停止の公開原因は上記LLM接続Errorであり、観測Serviceの障害だけが本処理を停止させたとは判定しない。
- 接続診断はモデル処理の終端後に逐次実行した。設定済みendpointのGET `/models`は3回とも200、翻訳/Embeddingモデルあり。合成promptのPOST `/chat/completions`はmax_tokens=16で200・16 tokens・最終contentなし、256へ増やした一件は200・40 tokens・finish_reason=stop・contentあり（1.391秒）。promptの応答本文・URL・認証値を証拠へ転載していない。
- 現在の小要求は成功しており、長い翻訳途中の接続断は再現・原因確定できていない。診断結果を根本修正済みとは扱わず、LLM Serverの再起動、timeout短縮、retry変更は行っていない。

### 最新コードの新規受入Run

- 入力コピーと有限設定の後続修正も実データで通すため、失敗Runを保全したまま新規Runを開始した。失敗Runを黙って削除したり、過去の失敗証拠を成功へ置換したりしない。
- 起動: `uv run python cli.py translate inputs/sample3.pdf --output-dir outputs/sample3-input-safety-acceptance`。
- 新Run: `01a0d520-15a4-74a2-9eaf-afafa726a03a`、session `3343`。同じlive handleでSPLIT〜LOADの7 Task完了を確認した（DOCLING 34.815秒）。まだ最終成果物・終了コードはなく、3章のTaskは未完了。
- code commit: `848296e9276edfcc46fe936dc3f61e97b9d91910`。既存の未コミット製品4 File（llm.py/lifecycle.py/terminal_evidence.py/review.py）のSHA-256は上の先行Run記録と全件一致し、今回変更していない。HEADだけの検証ではない。
- 入力と保存copyはともに5,284,914 bytes、SHA-256 `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`。保存copyを標準file_digestで読み、metadataのhash/sizeとも一致を確認した。
- 新processのcontextは30,208、request timeoutは1,800秒、Task deadlineは21,600秒、retry_attemptsは3。先行モデル処理と診断要求がすべて終了してから起動し、並列のModel/Embedding要求は追加していない。
- 本ターンは実機失敗の診断と新規受入実行、証拠文書だけを扱う。予定していたCONTENT-MERGE-001の新規提案は作成しておらず、指摘は未解決のまま。

### 最新受入RunのHTTP 500による終端（2026-09-25）

- session 3343の同一handleをpollし、終了コード1を取得した。Run `01a0d520-15a4-74a2-9eaf-afafa726a03a`はSTRUCTUREまで完了し、TRANSLATEで`InternalServerError status=500`となった。TRANSLATE 136.827秒、TOTAL 279.156秒。接続断だった先行Runとは失敗分類が異なる。
- failure.jsonを読取り専用で確認した。taskはTRANSLATE、error_typeはInternalServerError、failed_atは`2026-09-24T20:38:43.954349Z`。target_id/stage/cause_typeはnullであり、この記録から翻訳生成・Embedding等の呼出先や失敗単位は断定できない。例外本文、入力本文、認証値は表示していない。
- 終端確認後のSQLite mode=ro検査ではcheckpoint 10件、`writes.channel='__error__'`は1件。そのtype/valueはJsonPlusSerializerの固定値`TaskError`と一致した。公開診断の不足や外部500の根本原因をこの一致で解決済みとはしない。
- Run内DOCXは0件。Word PDF化・Comparison Review・利用者目視は未実施で、実機Gateは不合格のまま。失敗Runの入力、Artifact、checkpointを保全し、再実行・新規Run作成・設定変更は行っていない。
- 本観測ではServer側の原因を特定しておらず、再起動やtimeout/retry変更を修正策と決めつけない。製品Codeは変更していない。task 3.1以降と最終verify・archive・main merge・pushは未完了のまま。
- 記録更新後、文書Test 21 passed（0.26秒）、本Change・入力コピーChange・有限設定ChangeのOpenSpec strict validationはvalid、git diff --checkは指摘なし。文書検査の合格を失敗した実機Gateの合格へ読み替えない。

### HTTP 500の逐次再現確認（2026-09-25）

- diagnosing-bugsのPhase 1として、公開失敗にTask以外の呼出位置がないため、TRANSLATEが利用する既存`qdrant.search`の経路を切り出した。`uv run python -`でSettingsを読み、`search(settings, query, limit=5)`を逐次呼出し、例外時は型・HTTP status・固定分類のroute・stackのFile/関数/行番号だけを出して終了コード1とする診断を実行した。検索結果・query本文・URL・認証値は出力せず、artifact_pathも指定しない。これは検索系の再現確認であり、翻訳生成そのものの再現ではない。
- 短い合成queryは結果1件、0.907秒で成功した。次に失敗Runの保存済み`structure/document.json`から、製品の`units`と`_chunks`で実queryを組み立て、製品と同じ先頭2,000文字の切出しを用いた。
- 最初の実queryはpage 2/chunk 1、結果5件、21.844秒で成功。残る23件はsession 22682で一件ずつ実行し、同じhandleから終了コード0と`remaining_queries_completed=23`を取得した。合計24件すべて結果5件、所要時間は4.109〜25.781秒、個別時間の合計410.578秒。実query長は275〜2,000文字。再試行が内部で起きていないことや外部HTTP呼出数まで計測した試験ではない。
- 現在の検索経路ではHTTP 500を再現できず、過去失敗の原因は未確定。失敗が検索系にあったとも、現在の成功で外部障害が修復済みとも断定しない。HTTP 500を安定再現するloopは得られていないため、仮説に基づく製品修正へ進んでいない。
- 利用者へ2026-09-25 05:38:43前後（日本時間）のLM Studio側ログを、本文・prompt・秘密値を除いて共有するよう依頼した。timeout/retry、Server設定、失敗Runは変更せず、翻訳の再試行・新規Run作成も行わなかった。
- 全検索診断の終端確認後、別の既存成果物を用いるComparison Reviewを開始した。[表・一覧Changeの実機継続記録](../restore-docx-tables-and-indexes/verification.md)を参照。旧翻訳成果物であるため、本Changeと後続入力コピー・有限設定修正を含む最新translation Gateの代替にしない。

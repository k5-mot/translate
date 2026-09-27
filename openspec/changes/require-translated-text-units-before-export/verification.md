<!-- markdownlint-disable MD013 MD041 -->

## Apply検証（2026-09-27、基点e027e18）

製品修正は`translate/tasks/validate.py`の訳文存在検査のみ。既存`block_text_units`と`inline_text`を使い、非空白原文に対する出力訳を`final is not None`の優先順位で検査する。Captionも対象とし、未作成・空配列・空文字・空白のみを拒否する。Page 1と空原文は除外する。新Module・Dependency・Schema・再開台帳は追加しない。セルIDは既存TextUnitの行列形式を使う。

### 失敗先行と単体回帰

- 修正前に既存4件と追加68ケースを実行し、**40 failed / 32 passed（0.43秒）**。Caption未検査、空の最終訳の見逃し、空文字/空白訳の通過、空原文の誤拒否を確認した。セル2ケースは旧Error文言/配列indexと、新しい共通文言/行列IDの差も失敗理由に含む。全40件を欠落見逃しとして数えない。
- 修正後は同じTestが **72 passed（0.35秒）**。表紙・空原文・原文同一の数値訳、最終訳優先、line_breakのtext属性が描画されないことも確認する。

### 公開失敗と別接続Resumeの合成試験

本文・図Caption・表Caption・結合セルの4対象と、既存成功report有無の2条件を組み合わせた8ケースを追加した。実`prepare_run`/`execute_public_run`、実Translation Graph、実VALIDATE、実Markdown、永続SQLiteと既存checkpoint adapterを使う。SPLITで一度fixture初期化を停止し、公式`update_state(..., as_node="verify")`で合成の前段Artifact参照を与える。これは前段SPLIT〜VERIFYの正常実行を証明するTestではない。

外部socket.connect/connect_exを禁止し、観測送信を無効化。表紙生成とDOCX変換だけは合成出力へ置換する。初回Testは合成COVERのmanifest不足で、正常訳に直した後のMARKDOWNが失敗した。fixtureへ製品COVER契約のmanifestを補い、製品Markdownの処理は変更していない。

最終結果は **80 passed（5.17秒）**（単体72＋統合8）。全8ケースで次を確認した。

- 初回の公開失敗TaskはVALIDATE。後続MARKDOWN/DOCX呼出0回、既存DOCX hash不変、新しい成功reportなし、既存report byte列不変、検証済みdocument/Markdown directoryの新規生成なし。
- 失敗後のSQLite接続を閉じ、別接続で復元してnext=validate、pending writesのerrorあり、固定TaskErrorを確認した。
- 本文・周辺訳文・認証の合成markerが公開Error/Failure、Run metadata、log、復元Checkpoint/pending writes、SQLite関連Fileへ追加保存されていない。文書Artifactは本文保存が責務のため漏えい走査から除外した。
- Test所有の合成Artifactに正常訳を与えて公開Resumeし、VALIDATEは計2回、先行COVERは計1回、MARKDOWN/DOCXは各1回。nextは空、Run completed、Failure削除を確認した。これは製品の自動再翻訳や利用者Artifact書換え機能を追加するものではない。

`langgraph-persistence`のthread/checkpointerと再開の手順に従った。新しいStoreや状態台帳は使わず、既存のローカルSQLiteを使用する。本ChangeにPostgreSQL導入は不要であり行わない。

### 品質Gate

6/8 tasks完了。全pytestはsession 58302で **893 passed / 1 skipped（56.01秒）、exit 0**。Ruff check成功、formatは376 files already formatted、ty成功、OpenSpec strict valid、git diff --check成功。既存のFIX skip/asset/TextUnit/Markdown/独立convert回帰を含む。実行時の既存未commit差分は保持したままであり、本Changeの差分としてcommitしない。

検査対象SHA-256: `translate/tasks/validate.py`は`9f09726e72848bdd415e8e6b934ec1bb5eb62a6daa88befae1a5c1574d7ad85c`、`tests/test_validate_contract.py`は`976c07f83899b3f7c01eca348ea8aafec6e4fd94b0ef64bdb50e9d8bf18b4d0c`。目的説明を各追加関数に付け、製品は既存関数1件の変更とimportだけである。成果物・サンプル・.agents・他Changeの製品差分は本commitに含めない。

### 実E2Eと残る条件

Task 3.1/3.2は未完了。LLMの直近の単発確認はHTTP 500で失敗しており、復旧の連絡はまだない。今回の合成Testを実Translation→Word PDF→Comparison Reviewまたは利用者目視の代替としない。表内画像・ALIGN・POSITION・新保存構成・common整理も別途未完了。同期/archive・PR/CI・main merge/pushの条件は満たしていない。

## 方針承認と計画確定（2026-09-27）

利用者が空訳停止を承認したため、proposalを更新し、pdf-translation delta、design、tasksを作成した。本文・Caption・表セルの非空白原文に対する出力訳の未作成/空配列/空文字/空白のみを拒否し、表紙と空原文を除外する。過去の「回答待ち」「Artifact未作成」は当時の記録であり、現在の計画状態ではない。

現行`validate._require_translations`、`document.block_text_units`/`TextUnit`/`inline_text`、Markdownの3種の層選択、実GraphのVALIDATE→MARKDOWN→DOCX境界と既存Testを再読した。grillingの限定した読取りsub-agent調査でも同じ層選択の不整合と既存APIの再利用先を確認した。新しいDomain用語や不可逆な設計判断は追加しないため、Glossary/ADRは新設していない。

承認された他の5方針と旧形式非対応の指定は[承認記録](../clarify-code-documentation-and-reuse-rules/verification.md)に集約する。本Changeだけで表内画像・ALIGN・POSITION・保存構成の是正を完了扱いにしない。

実装は0/8 tasks。製品Code/Test、設定、既存Run/成果物は変更していない。新規LLM/Embedding要求も送っていない。計画Artifactの完成は実E2E・正式verify・archiveの合格ではない。

計画確認: OpenSpec statusは4/4 Artifact complete。本Changeとclarify-code-documentation-and-reuse-rulesのstrict validation成功、文書Test 21 passed（1.21秒）、git diff --check成功。対象のOpenSpec文書だけをcommitし、既存未commitの製品差分・.agents・サンプル・outputs/runsは含めない。

## 計画段階の診断（2026-09-25）

CONTENT-VALIDATE-001は未解決。提案は作成途中で、製品コード・Testは未変更。正式verify、archive、main merge、pushの条件を満たしていない。

### 現実装の再現

`validate._require_translations`、`markdown`の層選択、`document.block_text_units`、WorkflowのVALIDATE→MARKDOWN→DOCX接続を確認した。外部Serviceを呼ばず、メモリ内の合成Documentで以下を再現した。

| 条件 | 現在の結果 | 問題 |
| --- | --- | --- |
| figure/table × page 1/2 × Captionの初回訳/最終訳が各None/空配列/非空配列 | 全36組が通過 | Caption検査が存在しない。page 1除外は意図どおりだが、page 2の欠落も見逃す |
| page 2、原文Captionあり、初回訳と最終訳がNone | 通過しMarkdownに合成原文Captionを出力 | 原文fallbackが訳欠落を隠す |
| page 2、初回訳非空、最終訳が空配列 | 本文・Captionとも通過し、描画は空の最終訳を選ぶ | `final or translated`と`final is not None`の不一致 |
| page 2、原文あり、初回訳が空文字Inline一件 | 本文・Captionとも通過 | 配列の要素数だけでは空訳を検出できない |
| page 2、原文あり、初回訳が空白/タブ/改行だけのInline一件 | 本文・Captionとも通過 | 空白のみを出力しても現在は成功扱い |

本文条件をCaptionへコピーするだけでは、空の最終訳と非空の初回訳の組合せを見逃す。既存`TextUnit.text("final")`も、両訳層がNoneなら原文へfallbackするため、その戻り値だけで訳文の存在を判断できない。

`block_text_units`は本文・Caption・結合セルの起点を列挙できる。セルIDは行列座標形式であり、既存VALIDATE例外の配列index形式と異なる。診断IDを統一する場合はこの変更を回帰Testで明示する。既存Testで見つかった例外文字列依存は本文の`missing translation`部分一致で、セルの完全一致依存は見つからなかった。

### 先行実文書の観測範囲

先行成功Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`の`.workspace/verify/document.json`を読取り専用で確認した。16ページ、表紙以外で原文のあるCaptionは15件。両訳層None、既存本文条件相当の欠落、出力に選ばれる空配列はいずれも0件だった。文書本文を診断ログへ出力していない。

これは先行Artifactにおける層の存在確認であり、15件の翻訳品質、実PDFからの抽出漏れなし、最新製品のE2E合格を意味しない。合成入力で再現した製品不具合は未解決のままとする。

### 判断の分岐と確認中の事項

1. 本文・Caption・セルで、出力に使用する訳文層を検査する。最終訳が存在する場合は空配列でもその層を選び、古い初回訳で合格にしない。
2. 原文があるのに訳文層がNone/空配列なら公開前に失敗する。原文を自動補充して欠落を隠さない。
3. **回答待ち**: 原文に文字があるのに、選ばれた訳が空文字・空白だけの場合も停止するか。推奨は停止対象へ含めること。原文自体が空のセル・表紙は除外し、保護対象など原文と同一でよい内容を「日本語ではない」という理由では拒否しない。

3の判断を無断で確定せず、specs/design/tasksは回答後に完成させる。新しいDomain用語はなく、小さい検査条件の修正に独立Glossary/ADRは追加しない。未知の意味品質や部分的な訳抜けを、この有限の空訳検査だけで検証済みとはしない。

### 実装時に必要な検証

- None/空配列/非空訳/空文字/空白、初回訳と最終訳の優先順位を本文・図表Caption・結合セルで検査する。表紙と原文が空の対象を含める。
- 正常訳、FIX skip警告、保護対象、asset検査、独立Markdown→DOCX変換を回帰確認する。共通rendererの原文fallbackを一律削除しない。
- 実製品GraphをVALIDATE直前から実行し、欠落時に後続Taskが呼ばれず、新しいvalid reportを公開せず、既存成果物を上書きしないことを確認する。
- Checkpointの未完了位置がVALIDATEで、本文や秘密値が診断・SQLiteに混入しないことを確認する。独自の再開台帳・巻戻し・自動再翻訳は追加しない。
- 修正後の実translation→Microsoft WordでPDF化→入力PDFと生成PDFのreview→利用者目視を完了してから正式verify/archiveを判断する。

### 今回の検査と稼働中の処理

- メモリ合成で上表の36組と、本文/Captionの空配列・空文字・空白の不一致を再現した。ファイル・Runの変更、LLM/Embeddingの呼出は行っていない。
- `uv run pytest -q tests/test_validate_contract.py tests/test_text_unit_review.py tests/test_documentation.py`: **54 passed（2.01秒）**。既存Testが通っても上記の不具合が残るため、修正前の失敗Test追加が必要。
- 先行Comparison Reviewのsession `12758`を同じhandleでpollし、実行継続を確認した。追加のモデル処理は並列起動していない。先行Reviewは本Changeの未実装修正を検証するものではない。
- OpenSpecの必要Artifactはproposal以外が未作成。Deltaなしを隠す`skip_specs`は設定せず、strict検証合格やapply準備完了を宣言しない。

## 先行成果物の全翻訳対象への追加照合（2026-09-25）

同じ先行成功RunのVERIFY Artifactを読取り専用で集計した。第1ページを除き、本文・Caption・セルそれぞれの原文文字列と、最終層がNoneでない場合は最終層、そうでなければ初回訳を選択した文字列を調べた。原文と訳文の本文は出力せず、識別子と件数だけを扱った。

| 対象 | 対象枠数 | 原文に非空白文字あり | 原文が空/空白 | 原文ありに対する訳層なし | 原文ありに対する出力訳が空/空白 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 本文 | 142 | 107 | 35 | 0 | 0 |
| Caption | 142 | 15 | 127 | 0 | 0 |
| Table cell起点 | 151 | 122 | 29 | 0 | 0 |

本文/Captionの対象枠数は全Block分であり、文字のないFigure等も含む。`block_text_units`が実際に返す件数とは同一視しない。原文に非空白文字がある244対象では、出力に選ばれる空配列、および非空初回訳に対する空の最終配列も0件だった。

これにより、今回確認中の停止条件を適用しても、この先行Artifactの244対象が空訳として拒否されることはない。一方、29個の原文空セルを一律に「訳欠落」として拒否する実装は誤りになる。画像だけのセルの図形欠落は文字列検査では分からず、表内画像の問題をこの検査で解決済みにしてはならない。

### 実DOCXへのセル保持

先行`outputs/sample3-acceptance-v2/document.ja.docx`をZip/XMLとして読取り、VERIFY Artifactの各表と文書順で照合した。表ごとの非空訳の出現回数を確認した後、各セルの行・列位置と横結合幅まで比較した。OOXMLのgridBefore/gridSpanを位置算出に使い、単なる全文検索だけでは合格にしていない。文字列はレイアウト上の空白を除去して比較した。

| 原本ページ / Table ID | Internal cell起点数 | Word物理セル数 | 同じ行列位置の文字列・横結合幅一致 | 非空訳セル数 |
| --- | ---: | ---: | ---: | ---: |
| 14 / #/tables/0 | 28 | 28 | 28 | 28 |
| 15 / #/tables/1 | 18 | 18 | 18 | 7 |
| 16 / #/tables/2 | 105 | 105 | 105 | 87 |

全151セルで一致し、非空訳122セルの表外への流出はこの照合では認められなかった。両側とも縦結合0件のため、縦結合の実品質は今回検証していない。Wordの各表内drawingは0件であり、原本15ページの丸画像がセル外に出る既知問題は残る。原本PDFからInternal Documentへの抽出完全性、文面の意味品質、Wordのページレイアウトも別途検証が必要。

### 証拠の同一性と判定

| 対象 | SHA-256 |
| --- | --- |
| 先行Runのverify/document.json | `4f60482ab67ab6d6e593eee05747f7b49bdb77324bfd0371a89a8fe3eb28efff` |
| sample3-acceptance-v2/document.ja.docx | `02670602e0ac7f3edd65a9ee8a549a22f3bcb02dda29a52964124e606c0a6383` |
| sample3-acceptance-v2/document.ja.pdf | `c6ddeac815919742b20a95af5882832658261eed797a7732c0635fca543cbab4` |

欠落Captionのメモリ合成probeは再度2回とも「欠落を受理」で不合格になった。実成果物の存在確認を理由に不具合を閉じない。停止範囲は引き続き回答待ちで、製品コード・Testを変更していない。

Review session `12758`は同一handleへのpollで継続を確認した。06:42:54 JSTの中間directory更新も観測したが、更新時刻だけを生存根拠にはしていない。追加モデルの起動、Run/成果物の書換えは行わず、先行成果物を最新修正の正式E2E合格には流用しない。

追記後の文書/VALIDATE/TextUnitの既存Testは54 passed（2.48秒）、関連するrestore-docx-tables-and-indexesのOpenSpec strict検査はvalid、git diff --checkは指摘なし。本提案は未完成のため、そのstrict合格やapply準備完了を宣言しない。

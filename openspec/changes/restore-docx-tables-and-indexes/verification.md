<!-- markdownlint-disable MD013 MD041 -->

# Verification: restore-docx-tables-and-indexes

## 現在の判定

2026-09-25の追加修正後: **正式verify未完了・archive不可**。V-C2/V-W1/V-W2は回帰Testで修正を確認した。tasksは14/16で、4.3の利用者目視と5.5のtranslation→Word PDF化→review実行が未完了。以下の以前の正式verify失敗は履歴として保持し、追加修正だけで全指摘の解消とはしない。

## 追加Applyの回帰検証（2026-09-25）

- 承認済みの縦結合方針を設計/Scenario/tasksへ反映。header/body境界をまたぐ表だけ繰返し見出しを外し、位置と結合を保持。headerセルは太字とする。
- 空隅セル、複数見出し行、行見出し、セルとcaptionのLink/Code/6種marks/明示改行を既存PandocのASTへ対応付けた。HTMLや新parser、依存Package、共通実行Layerは追加していない。
- 修正前の追加5caseは全失敗。修正後は`tests/test_output_contract.py`が22 passed。列位置、w:vMerge、w:tblHeader、太字等のrun properties、hyperlink relationship、VerbatimChar、改行を実DOCXで確認。
- 対象2filesのRuff lint/formatとmarkdown.pyのtyは成功。全体pytestは292 passed, 1 skipped（25.32秒）。この成功は、別Changeで記録した診断I/Oの間欠失敗を解決した証拠ではない。
- 対象の既存7関数へ目的の説明を追加。関数コメントの全体監査は別記し、全件解消した扱いにしない。
- この節の自動Testは正式E2Eの代替ではない。実モデルtranslation、Microsoft WordによるPDF生成、入力PDFと生成PDFのreviewを順に実行してから正式verifyを更新する。

## 正式検証（2026-09-25）

対象実装commit: `afbd313`。検証では製品コードとtasksのチェック状態を変更していない。検証結果だけを追記する。

| 観点 | 結果 |
| --- | --- |
| Completeness | tasks 10/11。4.3の利用者目視確認が未完了 |
| Correctness | 4 Requirement中3件を確認、表・構造保持の1件に不一致。CRITICAL 2件、WARNING 2件 |
| Coherence | HTMLを経由しないgrid table、日本語静的一覧、一覧末尾改ページ、見出しnumPr除去は設計に対応。結合セルとheader保持には不一致 |

### CRITICAL（archive前に解決）

**V-C1: Task 4.3が未完了。** `tasks.md:24`の利用者によるWord/PDFの目視承認は得られていない。Word COMでPDFを生成できたことは利用者承認の代替ではない。推薦対応: 既知の品質問題を整理・修正し、利用者の確認結果を記録してから4.3を完了とする。

**V-C2: headerからbodyへまたがるrowspanでセルが別列へ移動する。** `translate/tasks/markdown.py:162`、`:176`、`:177`は先頭1行だけをTableHeadへ分離するため、その境界をまたぐrowspanを保持できない。次の有効な2列の表を製品rendererと実Pandocへ渡して再現した。

- 入力: `(row=0,column=0,rowspan=2,header=True,text=MERGED)`、`(0,1,header=True,text=H)`、`(1,1,text=BODY)`。
- 期待: MERGEDが第1列の2行を占有し、BODYは第2行・第2列。
- 実際: grid tableの第2行が`| BODY | |`となり、DOCXの`w:vMerge`は0個。BODYが第1列へ移動する。変換は例外なく成功する。
- 推薦対応: header/body境界をまたぐ結合を表現可能な構造として構築する。表現できない場合も、黙って列をずらして公開してはならない。行・列位置と結合範囲を照合する回帰Testを追加する。対応箇所は`_render_table`、`_table_row`と`tests/test_output_contract.py:378`。

### WARNING（修正推奨）

**V-W1: 表セル内のLink・Code・文字装飾を保持しない。** `translate/tasks/markdown.py:211`の`_table_inlines`は明示改行以外をStr/Spaceに変換し、`kind='link'`のhref、`kind='code'`、marksを参照しない。太字BOLD、href付きclick、Code `x = 1`を同じセルへ入れると、出力Markdownは`BOLDclickx = 1`のみ。DOCXの該当表に`w:b`と`w:hyperlink`がなく、relationshipsに指定URLもない。旧HTML処理でもInlineを平文化していたため、すべてを今回新規に生じた回帰とは扱わないが、構造・Link保持の要件に対する残存不具合である。推薦対応: Inlineのkind/marksを表の構文木へ対応付け、captionを含めて実DOCXで保持を検査する。

**V-W2: 一部だけheaderの行ではheader指定が失われる。** `translate/tasks/markdown.py:162`の`all(cell.header ...)`により、左上が空の通常セル・右上がheaderの表はTableHeadが空になる。row headerも通常セルとして出力される。空欄/HEADER、ROWHEADER/VALUEの2×2表で`w:tblHeader=0`を再現した。推薦対応: 空の左上セルを伴う列見出し、複数header行およびrow headerの扱いを明確にし、`TableCell.header`を失わない変換とTestを用意する。

### 要件・Scenarioとの対応

| Requirement / Scenario | 実装・検証証拠 | 判定 |
| --- | --- | --- |
| Markdown変換に成功する | `markdown.py:146`、`pandoc.py:120`。製品renderer経由でWord表、結合セル、captionを確認。ただしV-C2/V-W1/V-W2の境界ケースで不一致 | 部分適合 |
| 見出しと図表がある文書を変換する | `pandoc.py:345`、`:369`。実成果物で目次26/図一覧13/表一覧1項目、一覧直後の改ページ3個を確認 | 適合 |
| 対象がない一覧を変換する | `test_output_contract.py:191`および実Pandocの表のみのfixture。空一覧は見出しのみで、動的フィールドなし | 適合 |
| 番号付き見出しを変換する | `pandoc.py:306`、`test_output_contract.py:378`。Heading1～9のnumPr除去とoutlineLvl保持を確認 | 適合（同梱template） |
| テンプレートスタイル一覧を検証する | template XMLと`template-style.md`のstyle ID・種別・表示名・継承元の全4列を照合。110/110一致 | 適合 |

### 今回実行した検査

- `uv run pytest -q tests/test_output_contract.py`: **17 passed**。
- 対象3ファイルのRuff lint/format、および`ty check translate/adapters/pandoc.py translate/tasks/markdown.py`: **成功**。
- `openspec validate restore-docx-tables-and-indexes --strict`: **成功**。
- 追加の診断fixtureを一時directoryで実行し、V-C2/V-W1/V-W2を再現した。既存17テストはこれらのケースを含まない。
- 既存sample3成果物を読取り検証: 表3個、画像24個、dirty属性0、updateFieldsなし。PDFは28ページで、2ページ目に目次、3ページ目に図一覧、4ページ目に表一覧、5ページ目から本文。
- DOCX SHA-256: `5ba3c9f7a9443476c77732c6478384cfcb3877dc623792117d683fcfeaee76f4`。
- PDF SHA-256: `4eb486b411d573a5da596add6430bc35ad054080a7b635b78d3e68976df97d4d`。
- 本verifyでは実LLM/Embeddingへの要求、RunのResume、Word COMによる再生成は行わない。全体suiteの269 passed/1 skippedは直前のapply時の結果であり、本verifyの再実行件数には含めない。
- CLI/UIを含む新規RunのE2Eと利用者の目視確認は未実施。過去Runのメモリ内asset path補正による生成成功を、未補正の公開Resumeが成功した証拠として扱わない。

### 最終判定

**CRITICAL 2件・WARNING 2件。archiveは不可。** ARCH-001/ARCH-002、黄・緑の丸の配置、図採番、テンプレートの仮ヘッダーについては後述の既存積み残しとして引き続き未解決とする。

## Apply時の自動検証と実成果物（過去の証拠）

- `uv run pytest -q`: 269 passed, 1 skipped。
- DOCXに関する17件のTestで、実rendererからのWord表化、rowspan/colspan、明示改行、記号、日本語一覧、CodeとCaptionの目次除外、空一覧、改ページ、正規化の再実行、既存成果物のatomic公開を検証した。
- 変更対象のRuff lint/format、`ty check translate/adapters/pandoc.py translate/tasks/markdown.py`が成功。
- `openspec validate restore-docx-tables-and-indexes --strict`が成功。
- `template-style.md`はテンプレートXMLの110 style IDと一致し、欠落・重複なし。
- sample3 Run `01a0d080-2c51-7da5-a91b-700b9a21e7a9`のVERIFY結果から、LLMを再実行せずMarkdown/DOCXを生成した。旧Runの画像参照23件に旧prefixが残っていたため、検証用Documentをメモリ内で現在のasset相対pathへ対応付け、asset存在を検査した。元のRunとcheckpointは変更していない。
- 生成DOCX: `outputs/sample3-tablefix/document.ja.docx`。Word表3個、セル数28/18/105、計151セルの文字列が元の最終訳と一致（レイアウト上の空白を除いて照合）。画像24個（表紙を含む）、目次26項目、図一覧13項目、表一覧1項目。
- 目次の対象がない空見出しは出力項目に含めない。無題の表は表一覧の対象にしないため、実サンプルの表3個に対し表一覧は1項目となる。
- Microsoft WordのCOM操作で開き、`ExportAsFixedFormat`により`outputs/sample3-tablefix/document.ja.pdf`を生成。Wordが表3個、28ページとして認識することを確認。これは受入検証の利用者操作相当で、製品のPDF変換機能ではない。
- PDFの先頭は表紙→目次→図一覧→表一覧→本文の順で、各一覧が別ページにあることを抽出テキストと画像で確認した。
- 長い日本語セルによる極端な列幅の偏りを、総幅と結合位置を保持した最小列幅の保証で緩和した。
- PDF/DOCX/画像と入力サンプルはcommit対象外。

## 積み残し（2026-09-25 利用者指摘）

### ARCH-001: common/への責務集約と承認範囲の逸脱

**状態: 未解決。** 利用者が承認したcommonの範囲はlogger/settingsのみ。既存実装があることを設計承認済みの根拠にしてはならない。

追加対応: [reuse-installed-uuid7-generator](../reuse-installed-uuid7-generator/verification.md)でidentifiers.pyの独自生成器を廃止し、導入済みAPIへ直接委譲した。以下の一覧は監査時の棚卸しであり、identifiers.pyは現在の残存ファイルではない。他Moduleの整理と新実装の実E2Eは未完了。

以下は現在のファイル一覧と調査対象。役割名は入口の棚卸しであり、配置の妥当性や採用理由の説明完了を意味しない。

| ファイル | 現在の役割・説明が必要な対象 |
| --- | --- |
| `__init__.py` | パッケージ境界と公開範囲 |
| `logger.py` | ログ設定と機密値フィルタ（承認済みの配置） |
| `settings.py` | 設定読取り・検証（承認済みの配置） |
| `workspace.py` | 原子的保存、ディレクトリ公開、ハッシュ、排他ロック |
| `runs.py` | Run永続化、入力コピー、一覧・削除、入力manifest |
| `lifecycle.py` | Run準備、Resume判定、処理分岐、失敗情報、エクスポート |
| `fingerprint.py` | 設定・入力の互換性判定 |
| `identifiers.py` | UUIDv7生成 |
| `progress.py` | Task/Workflowの進捗通知と状態通知 |
| `redaction.py` | ログ・エラー・保存値の機密情報除去 |
| `terminal_evidence.py` | 診断証拠の永続化、子プロセス起動・監視・終了処理 |

- [ ] 全ファイルの責務、公開関数/class、呼出元、依存先、追加した背景、代替配置と採否理由を説明する。
- [ ] 特にlifecycle/terminal_evidenceの製品処理・実行制御・検証支援が混在していないかを整理し、adapters/tasks/workflowsとの境界を図示する。
- [ ] 不要な共通化、単一呼出元のhelper、重複責務を洗い出し、保持・移動・統合・削除案を別Changeで提案する。
- [ ] `CODING_RULES.md`へ、共通領域の許可責務、新規配置の説明要件、依存方向、汎用化の条件、設計変更の記録とレビュー手順を定める案を作る。
- [ ] 利用者が説明とルールを確認してから移行し、CLI/UIのRun共有、Resume、障害記録の回帰検証を行う。

### ARCH-002: Taskの共通構造と基底クラス継承の検討

**状態: 方針承認済み・実装/自動検証済み、実E2Eと利用者確認は未完了。** 2026-09-25、[unify-task-timing-with-base-task](../unify-task-timing-with-base-task/verification.md)で20 Taskへ具体classと既存関数入口を併用実装した。計測はBaseTaskへ集約し、Workflowの状態通知・Resume管理は移していない。47計測/転送Test、全体337 passed/1 skippedを確認。実translation→Word PDF→review前のためARCH-002の最終解決にはしない。

- [ ] 全Taskの入出力、実行順序、計時、atomic保存、retry、失敗通知、状態の有無を比較し、実際の重複を示す。
- [ ] 共通base class＋各Task class案と現行関数方式を、差分量、型の明確さ、テスト容易性、LangGraph/Resumeとの対応、継承しない例外Taskの扱いで比較する。
- [ ] 共通実行契約を定義し、基底クラスが担う責務と各Taskが担う責務を利用者へ具体例で説明する。
- [ ] 合意した方式を別Changeの仕様・設計・tasksへ反映し、共通化だけを目的とする無関係なLayer追加を防ぐ。

## 追加監査（2026-09-25）

### 更新goalの③-1・③-2・④

[coding-rules-audit.md](coding-rules-audit.md)に追跡Python全90 filesの関数説明欠落候補を全件記録した。表修正後のAST集計は912関数、docstringなし474件。関数先頭のコメントを持つ候補も含むため、内容と代替可否を個別確認する。lambda・実行文字列内関数・未追跡probeは別枠で、黙って合格にしない。

導入済みuuid-utils/tenacity/Pydanticと標準hashlibに置換可能な機構を確認。一方、portalocker.open_atomicは既存path更新を許さず、現行Artifact更新の代替にならない。既存依存の名前だけを理由に機械的置換しない。

④により、GraphStateの独自完了情報、WorkflowProgressの再集計、RunRecord.status/last_task、STRUCTURE page/REVIEW chunkの独自再開cacheも整理対象とする。LangGraph checkpointを唯一の再開正本とし、manifestに独立のTask進捗を持たせない。register/convertは現状Graph未使用なので移行設計に含める。document_processing/4file新設案は撤回した。③・④とも未解決である。

利用者の全件監査依頼を受け、common全11ファイル、Task全20件、残りの製品ソースと追跡Testを棚卸しした。責務・API・依存・追加背景・配置案・Task構造の比較・規則別判定は[architecture-audit.md](architecture-audit.md)に記録する。**ARCH-001/ARCH-002は説明を作成した段階で、利用者承認・移行・解決は未完了。**

- **ARCH-003（未解決）**: CODING_RULES全体への適合確認。全体Ruffは1件、tyは23 diagnosticsで失敗。formatは267 files成功。pytestは初回268 passed/1 failed/1 skipped、失敗Test単体は成功、全体再実行は269 passed/1 skipped。再現性の問題は未解決とし、後の成功で初回失敗を相殺しない。
- **DATA-001（未解決）**: 表セルの数値欠落がCHECKから抜け、表だけの英日DocumentがALIGNで空の対応群になることを再現。REVIEW/VERIFY/比較本文生成にもcell/captionが対象外になる実装を確認。レンダリング修正やBaseTask化だけで解消した扱いにしない。
- **RUN-001（未解決）**: 実行中Runのlockを保持したまま重複呼出を拒否すると、拒否された呼出がstatusをrunningからfailedに書換え、failure.jsonを作ることを一時Runで再現。所有者以外がRun状態を壊さないよう修正が必要。
- V-C2の列ずれには、表全体を同じbodyへ置く候補で位置/縦結合を保持できることを実Pandoc/DOCXで確認した。ただし見出し表示方針は確認中で、製品sourceの修正はまだ行っていない。
- この追加監査でも実LLM/Embedding要求、過去RunのResume、Word/PDF再生成、archive、main merge/pushは行っていない。既存のCRITICAL/WARNINGと利用者目視未完了は維持する。

## DOCX品質の残課題（継続）

### 配置案の再検討と方針承認（2026-09-25）

- ARCH-001は未承認・未解決。利用者の指示により、既存adapters/workflows/testsだけでなく、新設translate/cli/・translate/ui/と追加のRun専用directory候補を比較した。[具体案](architecture-audit.md)に現行関数との対応と採否理由を記録した。製品sourceは移動していない。
- ARCH-002の関数＋BaseTask併用案は承認済み。実装・回帰検証を別Changeへ反映する作業は残る。
- V-C2の見出し/本文をまたぐ縦結合は、セル位置・結合優先、当該表の繰返し見出し無効、見出しセル太字の方針を承認済み。修正・Word/PDF目視確認が終わるまで指摘を解決扱いにしない。

### 型検査項目の追跡更新（2026-09-25）

利用者回答: 縦結合が見出し/本文をまたぐ表は、位置・結合を優先し、繰返し見出しを無効化して見出しセルを太字にする方針を承認。Taskは関数/classの二者択一ではなく併用案を検討する。commonの配置は具体的な処理・移動先の説明が必要で、承認済みではない。[具体案](architecture-audit.md)を追記した。

ARCH-003の23 diagnosticsは`restore-typed-internal-call-contracts`で修正し、全体`uv run ty check`が成功した。STRUCTURE/Evidenceの転送・再送・context復元を含む関連29 Test、全体278 passed/1 skippedを確認。ARCH-003全体を解決済みにはしない（規約コメント、不要コード、未追跡probeのLint、配置、Test再現性等は残る）。

型修復Changeは正式verify成功後、[2026-09-25のarchive](../archive/2026-09-25-restore-typed-internal-call-contracts/verification.md)へ移した。Spec deltaはなく同期対象なし。main merge/pushは他の未解決事項とPR/CIゲートのため未実施。

診断runnerのTestでは、親のEvidenceStore.readがPath.read_textでPermissionErrorになるケースも再現した。前回のchild exit 2の直接原因と同一とは未確認。再実行成功で競合問題を閉じず、別途修正・回帰検証する。

2026-09-25 10:21 JSTに[診断I/Oの再検証](../serialize-detached-evidence-io/verification.md)を記録した。実親子の3 Testを20回逐次反復して60/60成功、その後の全体Testは656 passed / 1 skipped。ただし排他修正後に発生した過去のWinError 5の原因は未確定であり、競合の指摘・archive保留は維持する。モデル要求、製品Code変更、旧Run変更は行っていない。

続く同日の追加診断では、合成JSONだけの実親子I/OでWinError 5を3試行中2回再現した。OS一時領域の比較ではlock外のpath.resolveが2/2失敗、同じresolveを既存lockで囲むと2/2非再現となり、本文read/write以外のhandle操作も排他範囲へ含める必要性を確認した。ただしRepository内のwriter単独でも置換失敗があり、これを同一原因と断定しない。修正と追加切分けは未完了で、詳細は上記診断記録の最新節を参照。

- [ ] sample3のステータス表に含まれる黄・緑の丸は、既存Internal Documentでは独立したFigureになっている。セルへの関連付け・配置の保持は別途検証し、通常の表出力修正だけで解決としない。
- [ ] 表紙がPandocの図番号に数えられ、最初の本文図がFigure 2となる点を確認・修正する。表紙Captionの除去と本文図の採番は別の問題として追跡する。
- [ ] 利用者による再生成Word/PDFの目視確認（表、一覧、改ページ、見出し、起動時ダイアログ）。
- [ ] テンプレート由来のヘッダー・フッターに「○○システム」「○○株式会社」「SYS-DS-001」が残るため、製品成果物での扱いを確認する。

## 実装方針の訂正

### RUN-001の実装修正（2026-09-25）

[protect-active-run-from-rejected-execution](../protect-active-run-from-rejected-execution/verification.md)で開始準備から終了保存・log解放まで実lockを保持し、拒否側のmetadata/failure/log変更と古い失敗の誤表示を修正した。全4操作とfailure有無の修正前8失敗→修正後成功、追加17 Test、全体383 passed/1 skippedを確認。新Codeの実E2E・目視前のため最終解決は保留。削除時のlock解放後rmtree、通常失敗の再読込み、二重状態管理は別途残る。

### DATA-001の実装修正（2026-09-25）

[include-table-and-caption-content-in-review](../include-table-and-caption-content-in-review/verification.md)で本文/caption/cellの共通列挙をCHECK/REVIEW/VERIFY/ALIGNと比較Documentへ適用した。セル単位の欠落、空訳、候補検証、表/captionだけの比較と片側欠落の追加29 Test、全体366 passed/1 skippedを確認。新実装の実translation→Word PDF→reviewと目視が未完了のためDATA-001は未解決のまま。FIXの指摘対象限定とVERIFYページ単位採否も別途是正が必要であり、今回の対象列挙だけで仕様全体の適合を宣言しない。

### ARCH-001の再整理要求（2026-09-25）

利用者はcli/uiへの配置誘導ではなく、commonの過剰機能・整理不足そのものの是正を求めた。前のcli/ui新設推奨は今回の整理案から外し、[architecture-audit.mdの最新節](architecture-audit.md)に8moduleの保持・統合・削除候補と責務別配置を再記録した。重複hash、未使用API、製品の検証counter依存、二重の実行/失敗境界、暗黙callbackを縮小対象とする。要件上必要な排他・atomic保存・Resume判定・秘密保護は維持する。**配置・削減方針は未承認、製品変更と解決判定は行っていない。** Task併用と表の承認は維持する。

### Run保存layoutの追加要求（2026-09-25）

利用者がoutputs/<入力名>/<uuidv7>/.state/<task>とRun直下のinput.pdf・output.ja.docx・output.ja.pdf・manifest.jsonを指定した。[設計メモ](architecture-audit.md)にRun保存/再開/Artifact公開/診断の新規directory候補と、旧layoutからの仕様変更を記録した。root全体のatomic置換や再帰exportをそのまま流用しない。PDFは既存の手動操作方針を維持する。既存Run移行と翻訳以外の操作への適用範囲は確認待ち。ARCH-001は未解決、製品code/既存Runは未変更。

### 保存構成と命名の訂正（2026-09-25）

最新の利用者指定はoutputs/<file-basename>/<uuidv7>/.artifacts/{001-split,002-docling,...}と直下のinput.pdf・output.ja.docx・output.ja.pdf・manifest.json。.state案を置き換える。sourceのutils/artifacts.pyと検証機能のtests配下移管を反映し、意味が曖昧なrun/repository・compatibility・lifecycle、diagnostics/、workflows/progress、tests/supportは再提案した。[設計メモの最新節](architecture-audit.md)に元moduleとの対応と責務を記録。directory名変更だけでARCH-001を解決扱いにせず、機能削減と回帰検証は未完了のまま。製品code変更・既存成果物移動は未実施。

### HTMLを使わない表出力（既定方針）

利用者の指摘に従い、表をHTMLへ変換する既存処理と今回のHTML経由案を廃止する。Internal Documentの行・列・結合情報からPandocの表構造を直接構築し、既存Pandocでgrid tableを出力する。HTML readerやHTML中間成果物は使用しない。

一覧はMarkdownを正規表現で再解析せず、変換済みDOCXの見出し・図題・表題から静的な項目を作る。これによりCode内の見かけ上の見出しやCaptionが目次へ混入することを防ぐ。ページ番号は提案どおり含めない。

## 先行成果物のWord/PDFと表内画像の調査（2026-09-25）

Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`の実translationが終了コード0で完了した。生成DOCXを自分で起動した非表示Microsoft WordでPDF化し、`outputs/sample3-acceptance-v2/document.ja.docx`と`document.ja.pdf`を利用者へ提示した。hash、Word実行条件、起動時版の制約は[Checkpoint修正の先行成果物記録](../sanitize-workflow-checkpoint-errors/verification.md)を参照。ユーザ目視結果は未回答。先行processは後続修正を読み込んでいないため、最新Codeの実機Gateを完了にしない。

PDFは28ページ。表紙1ページ、目次2ページ、図一覧3〜4ページ、表一覧5ページで一覧は非空。25ページの評価表はWord表として出力される。一方、26ページのステータス表の黄・緑丸はセル内になく、27ページに10個縦並びで出力される。図一覧のFigure 2開始と仮ヘッダー/フッターも残り、既存指摘は未解決。

### 表内画像の対応が欠ける境界

- 調査対象は`.workspace/docling/part-0002/unpacked/document.json`の`tables[1]`、part内5ページ（原本15ページ）。Docling Schema JSONの時点で3行×6列の表に、文字のある`table_cells` 7個と`grid` 18個がある。丸の入る10空セルにbbox/画像参照はなく、10画像は親`#/body`の独立pictureとなっている。
- 表全体bbox、文字セルbbox、画像bboxはMERGE/POSITIONのJSONに残る。ページは612×792pt。表/画像はBOTTOMLEFT、文字セルはTOPLEFTなので、同じ原点へ変換して照合する必要がある。
- このサンプルでは全10画像が表bbox内に完全包含される。画像中心xは列見出しbboxのx区間へ1件、中心yは行見出しbboxのy区間へ1件だけ対応する。空セルbboxそのものへの包含判定ではない。行列は0始まりで、pictures 13/14→列1、19/20→列2、17/18→列3、21/22→列4、15/16→列5、各組の先頭→行1、後方→行2。距離閾値や最近傍推測を使わずこの10個は一意に対応できる。
- `load._table_cells()`はgridから18個のInternal TableCellを作るがbboxを保持せず、`TableCell`には画像表現もない。`load._block()`は画像を独立Figureにする。LOAD→STRUCTURE→VERIFYでも表と10 Figureが分離したままで、Markdownはそれを表の外へ描画する。WordによるPDF化だけの不具合ではない。
- 導入済みPandoc 3.11へ標準入力でgrid table内の画像を渡すと、Cell内のImageと寸法属性を認識した。HTMLや新規依存は不要。Docling画像は38〜40px、原本上は約19ptであり、単にpixel寸法で描画せず原本寸法を保持する必要がある。

### 次の提案へ向けた未決事項

LOADで既存の幾何情報からセルとの対応を確定し、Internal Documentに画像参照を保持して既存Pandocへ渡す案を調査した。割当済み画像の二重出力防止、asset参照検証、表示寸法も必要。commonや別保存Layer、別モデル要求の追加は前提にしない。

`grill-with-docs`の判断確認として、所属セルが一意に決まらない場合に停止・Resume可能とするか、警告して表外へ残すかを利用者へ質問した。**回答待ちのため、新Changeの正式作成・製品実装には進んでいない。** 推奨は誤った表の公開を防ぐ停止だが、承認済みの要求として扱わない。用語の新規合意や採用判断もないため、Glossary/ADRは追加していない。

## 実成果物Comparison Reviewの継続（2026-09-25）

openspec-verify-changeで本Changeのproposal/specs/design/tasksを読み直し、task 5.5の未実施だった公開比較Reviewを開始した。**正式verifyは未完了・archive不可**。過去の実行結果と最新Codeでの検証を混同せず、tasksのチェック状態は変更しない。

| 観点 | 現時点の結果 |
| --- | --- |
| Completeness | 14/16。4.3の利用者目視と5.5の実機連鎖完了が残る |
| Correctness | 4 Requirementの実装・既存Test対応を再点検。実DOCXの一覧・改ページ・見出しstyleと資料110 stylesは再確認済み。表内画像の既知不備と未完了Reviewを残す |
| Coherence | Markdown表は既存Pandocの構文木・writerへ委譲し、HTML・新依存なし。一覧は静的、ページ番号は生成しない。先行Word操作は製品機能を追加しない検証操作である |

### 入力の同一性と実行順

- 先行translation Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`のrun.jsonを読取り、status=completedを再確認した。実translationの終了コード0と非表示Microsoft WordでのPDF出力は先行節の記録を使用し、今回は再翻訳・再変換していない。
- 原本`inputs/sample3.pdf`: 16 pages、5,284,914 bytes、SHA-256 `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`。
- DOCX `outputs/sample3-acceptance-v2/document.ja.docx`: 3,657,145 bytes、SHA-256 `02670602e0ac7f3edd65a9ee8a549a22f3bcb02dda29a52964124e606c0a6383`、ZIP CRC正常。
- Word PDF `outputs/sample3-acceptance-v2/document.ja.pdf`: 28 pages、1,538,776 bytes、SHA-256 `c6ddeac815919742b20a95af5882832658261eed797a7732c0635fca543cbab4`。
- 三つのhashは先行記録と一致した。PDFは導入済みpypdfium2で開いてページ数を確認し、内容の再生成や上書きはしていない。
- HTTP 500の検索診断session 22682の終了コード0を取得し、ほかのCLI/診断childが実行中でないことを確認した後に比較Reviewを起動した。診断とReviewのモデル要求を並行させていない。

### 公開Review

- Command: `uv run python cli.py review inputs/sample3.pdf outputs/sample3-acceptance-v2/document.ja.pdf --output outputs/sample3-acceptance-v2/comparison-review-20260925.md`。
- 出力reportは起動前に存在しないことを確認した。既存DOCX/PDFやreportは上書きしていない。
- 新Run: `01a0d534-b9c9-7e60-9edf-7541d26b6e05`、追跡session `12758`。元PDFと今回検査した翻訳PDFの組を明示し、新規Runとして開始した。
- 基点commit `d59b9175effbffd74559aa5746ca33410ede2ac3`。既存未コミットの製品4 filesは維持し、起動前hashは[Checkpoint実機記録](../sanitize-workflow-checkpoint-errors/verification.md)のllm.py/lifecycle.py/terminal_evidence.py/review.pyの4値と一致した。HEADだけの実行証拠ではない。今回の製品Code編集は0件。
- context 30,208、request timeout 1,800秒、Task deadline 21,600秒。SOURCE/TARGETのSPLIT〜LOAD、ALIGN、CHECKの16/18 Taskまで完了し、REVIEWを継続中。SOURCE-DOCLING 26.806秒、TARGET-DOCLING 42.648秒。
- `ALIGN model fallback failed; using deterministic order`の警告を05:57:49に確認した。対応付け品質の確認事項として保持し、無警告成功と報告しない。Qdrantの非TLS接続警告も継続している。
- まだ終了コード・完成report・Finding照合は取得していない。5.5を完了にせず、最新翻訳がHTTP 500で失敗した事実もこの旧成果物の比較で相殺しない。

### DOCX・仕様対応の再点検

- 読取り専用XML検査で表3個、drawing 24個、field instruction/dirty属性/updateFieldsはいずれも0件。Heading1〜9のnumPrは9/9で除去、outlineLvlは9/9で保持されている。これは起動時ダイアログの利用者確認を代替しない。
- 日本語の目次26項目・図一覧13項目・表一覧2項目を確認し、三つすべての直後に明示改ページがある。古い別成果物の表一覧1項目という記録とは対象hashが異なる。
- `template.docx`のstyles.xmlと`template-style.md`のstyle ID・種別・表示名・継承元を全件比較し、110/110一致、資料内IDも110個で重複なし。
- 縦結合・空隅セル/複数見出し・Inlineの各Scenarioは、`markdown._render_table/_table_row/_table_inlines`と`test_header_to_body_rowspan_preserves_columns_without_repeated_header`、`test_empty_corner_multiple_headers_and_body_row_headers`、`test_table_inlines_keep_links_code_marks_and_breaks`に対応する。今回はsource/assertを読み直した確認であり、新しい実行件数を主張しない。
- 一覧・空一覧・番号のScenarioは`pandoc._index_entries/_populate_front_matter/_remove_heading_numbering`と既存`test_generated_table_and_indexes_survive_real_docx_conversion`等に対応する。既存TestはFigure 2開始を期待しており、本文図採番の残課題を検出するTestではない。

### 継続する指摘と判定

- CRITICAL: 4.3は利用者回答待ち、5.5は実Reviewの終端と内容確認待ち。両方の証拠が揃うまでarchiveしない。
- 表内画像のセル外配置、本文図採番、テンプレートの仮ヘッダー/フッター、ARCH-001/ARCH-002等の最終解決は保留。今回は機能修正を行っていない。
- Review結果が出た後、原本・DOCX・PDFとの代表Finding照合を行い、誤検出と実不具合を区別する。異なるrevisionの証拠だけで最新CodeのGateを完了にしない。
- 記録更新後の文書Testは21 passed（0.25秒）。本ChangeとCheckpoint ChangeのOpenSpec strict validationはvalid、git diff --checkは指摘なし。製品Code未変更のため全製品suiteは再実行せず、実Reviewは同じsession 12758のlive handleで継続を確認した。文書品質の合格を正式verifyの成功とは扱わない。

## 比較の意味的整合性と公開reportの追加検証（2026-09-25）

対象は同じReview Run `01a0d534-b9c9-7e60-9edf-7541d26b6e05`。session 12758を同じhandleでpollしてliveを確認し、外部要求を追加せず、完了済みALIGN Artifactと製品関数を読取り・メモリ内で検査した。終了コード・最終reportはまだ取得していない。以下は比較Capabilityの既存要求に対する不適合であり、表出力Changeの仕様を勝手に拡張して修正しない。

### COMPARE-ALIGN-001: 対応の意味が不正でも後続Reviewへ進む（CRITICAL・未解決）

- `comparison-review`の「文書要素を多対多で対応付ける」は順序だけでなく見出し・番号・URL・固有名詞・前後関係に基づく対応を要求する。IDの網羅性だけでは正しい対応の証拠にならない。
- 実Artifactは原文264単位、訳文289単位、291 Group。matched 262、source_only 2、target_only 27。confidence 0.95が96組、0.6が166組、1.0が29組。1対多・多対1は0組。全IDの一意・完全包含は`align._valid`でTrueだったが、次の内容照合では不一致を検出した。
- 先行translationの`verify/document.json`に保存された原文と最終採用訳を基準に、比較側sourceと原文が一致し、比較側targetに最終採用訳が一意に存在する組だけを抽出した。照合は空白文字だけを除去した完全一致で、双方40文字以上、先行原文・比較原文・比較訳文の三者で候補が一意という条件を使った。類似度推測やモデル要求は使用していない。
- この条件を満たす87組のうち51組で、実Groupのtargetが既知の最終採用訳とは別の要素だった。48組はconfidence 0.6、3組は0.95。残りの対象はこの照合方法では判定しておらず、全291 Groupの誤対応数とは報告しない。

| Group（0始まり） | 原文ID・page | 実target ID・page | 一意に一致する最終採用訳のID・page |
| --- | --- | --- | --- |
| 27 | `#/texts/30`・2 | `#/texts/87`・7 | `#/texts/99`・8 |
| 35 | `#/texts/34`・3 | `#/texts/115`・9 | `#/texts/107`・8 |
| 36 | `#/texts/39`・3 | `#/texts/116`・9 | `#/texts/112`・9 |

- 実行時にはALIGNのモデルfallback失敗警告があったが、原因分類が保存されていないため、その失敗原因は断定しない。`align.py`の広いexceptが失敗を警告だけに変え、順序による対応を公開することはsourceで確認した。
- メモリ内の別の合成試験で、アンカーを持たない各1 Blockの文書に対し、`structured`が`LLMError('text-invoke', TimeoutError(...))`を投げるよう注入した。既存AlignTaskは例外を伝播せず、confidence 0.6のGroupを返し、alignment保存を1回呼んだ。保存関数とatomic directoryをdoubleにしたため実Fileは作成していない。LLM adapterの有限retry自体を試験したものではなく、adapterからの終端例外をTaskが握りつぶす境界の再現である。
- この継続は`run-lifecycle`の「外部障害を分類して処理する」にある、回復しないLLM障害ではResume可能に停止する契約と不整合。推薦対応: 別Changeで安全な失敗伝播・原因分類を回復し、有限context内で1対多・多対1を含む正しい対応を得る実装と回帰Testを用意する。停止させるだけ、またはID数だけを検証する修正で意味的対応の指摘を解決済みにしない。
- `tests/test_align_contract.py`の多対多Testは正解Groupを返すmodel doubleを採用できることを確認する。実文書の長さ、モデル失敗、上記の誤対応を検出するTestではない。

#### 是正提案前の追加事実（2026-09-25 06:30 JST）

同じ保存済みsource/target LOAD Artifactから製品`align._items`を通し、現行と同じ`json.dumps(..., ensure_ascii=False)`の要求文字列をメモリ内で組み立てた。外部要求・File書込みは行っていない。Settingsも読取りのみとし、URL・Model名・秘密値・本文を出力していない。

| 測定対象 | 値 |
| --- | ---: |
| 原文 / 訳文 TextUnit数 | 264 / 289 |
| user payload文字数 | 99,815 |
| user payload UTF-8 bytes | 148,037 |
| PydanticOutputParserのschema指示文字数 | 1,086 |
| 設定context / output予約tokens | 30,208 / 16,384 |
| image / safety予約tokens | 2,048 / 1,024 |
| Settings.available_input_tokens | 10,752 |
| 最大単位文字数（原文 / 訳文） | 1,936 / 817 |

文字数をGemmaの実token数と同一視しない。現ALIGNはこの全文とschema指示を一要求にし、送信前budget検査を持たない。これは分割設計が必要な根拠だが、失敗応答の原因記録がないため、過去の実fallback原因をcontext超過と断定する証拠ではない。REQUEST timeoutを延長するだけでこの構造上の問題が解決するとは扱わない。

応答の構造検査にも不足がある。`AlignmentGroup`を通常のPydantic初期化で作り、`align._valid`へ渡すメモリ合成で、次の10条件がすべてTrueになった。

- matchedなのにsourceが空、またはtargetが空。
- source_onlyにtarget_idsがある、またはtarget_onlyにsource_idsがある。
- 正常Groupに両側空のGroupを追加する。
- confidenceが−1、2、NaN、正の無限大、負の無限大。

補助の読取り専用調査でも同じ結果を確認し、ID重複・未知IDはFalse、未定義kindはPydantic Literalで拒否されることを確認した。つまり現在の検査は全IDのpartitionであり、kindと両側の整合やconfidenceの有限性/範囲は保証しない。これらの決定的検査を加えるだけでも、意味的に正しい対応の証明にはならない。

`_items`はTextUnitのIDとsource文字列だけを渡す。走査順とcaption/cellのID suffixは残るが、page境界、見出しkind/level、bbox、Block.order値、セルheader/span、Inline href/marksは要求にない。これらの属性だけを変えても同じ`_items`結果になることをメモリ合成で確認した。次の設計では構造文脈を候補探索に利用し、単なる同番号・近い位置を正しい対応の根拠としない。

#### 導入済み機能の再利用範囲

| 既存機能 | 使える部分 / 不足する契約 |
| --- | --- |
| REVIEWの_review_chunks | 対応済みpairの件数/文字量分割。未対応文書の探索や境界をまたぐ多対多の調停はしない |
| TRANSLATEの_chunks | Inline列の分割。二言語対応はせず、巨大な単独Inlineは上限を超え得る |
| RecursiveCharacterTextSplitter | length_function/overlapによる文字列分割。両文書IDの一意被覆や対応確定はしない |
| TokenTextSplitter / from_tiktoken_encoder | 指定encodingの分割。ローカルGemmaのtokenizer一致は確認されておらず、意味対応機能ではない |
| MarkdownHeaderTextSplitter | Markdown見出し分割。Internal Documentの英日見出し対応を解決しない |
| llm.structured | 既存の単一要求・有限retry・応答解析へ委譲可能。ALIGN全体の分割と対応統合はしない |

調べた既存Codeと導入済み分割APIには、有限context分割と英日多対多対応・全IDの一意被覆をそのまま満たすAPIは見つからなかった。この限定調査を全Packageの不存在証明にはしない。既存部品で不足する対応の責務だけをTaskに置き、独立した再開Cacheや汎用frameworkは追加しない。片側だけを機械的に二分し、反対側の同じ位置と対応させる設計では既知の誤対応を解消できない。

#### 是正Changeの確定前に必要な利用者判断

LLM通信が回復しない場合に停止する方針は既承認であり、再質問しない。今回の未決事項は、通信と構造検証には成功したが意味的な対応先を確定できず、本当の訳抜けとも区別できない場合である。

- 推奨案: ALIGNで停止してResume可能な状態を保持し、誤った組で後続Reviewへ進まない。
- 代替案: 「対応未確定」の公開状態を新設して全対象を保持し、確定した組だけReviewする。この場合は現在のmatched/source_only/target_onlyと公開report契約を拡張する必要がある。

grill-with-docsの判断として利用者へ確認中。無回答を採用承認としない。新しい是正Changeはまだ作成せず、Code/Testも変更していない。どちらの案でも、適切に分割して既知の実対応を得ることが是正目標であり、巨大入力を停止させるだけでCOMPARE-ALIGN-001を解決済みにしない。改ページ差・多対多・順序が入れ替わる対応を、単純な同じ位置の窓に限定して切り捨てない。

実Review session 12758は同一handleのpollでliveを確認しており、追加のLLM/Embedding要求・停止・再起動は行っていない。前提が変わらない既存Artifactは読取りだけで保持する。

追記後の文書・ALIGN・比較Capabilityの既存Testは41 passed（2.33秒）、本Changeのstrict validationはvalid、git diff --checkは指摘なし。今回の構造不正を検出する製品Testはまだ追加しておらず、これらの既存Test成功を指摘の解消とは扱わない。

### COMPARE-REPORT-001: 公開MarkdownからFindingの対象・根拠・修正方針が落ちる（CRITICAL・未解決）

- `comparison-review`の「問題と根拠をReportする」は重大度・種別に加え、対象、根拠、修正方針を公開reportへ記載する契約である。
- `report.ReportTask.run`へ、target_ids・evidence・suggestionにそれぞれ異なる合成markerを持つFindingを渡した。atomic_write_text/jsonをメモリ内captureへ置換して製品REPORTを実行したところ、公開Markdownには三つのmarkerがすべてなく、内部JSONには全fieldが一致して保存されていた。
- 現実装はMarkdownの指摘行へseverity/kind/messageしか渡さない。CLIの`--output`はこのMarkdownをexportするため、内部JSONの保持を公開契約の充足とはみなせない。
- `test_comparison_capability_reports_findings_or_explicit_zero_without_mutation`は根拠・修正方針付きFindingを入力するが、Markdownの重大度/種別とJSON集計だけをassertし、三fieldの公開を検査していない。
- 推薦対応: 別Changeで、既存Findingの対象ID・根拠・修正方針を公開Markdownへ保持し、対応Groupを辿れる表示と欠落fieldの扱いを明示する。全field・複数Finding・指摘0件の公開report回帰Testを追加する。新たな進捗台帳や外部要求は不要。Findingの内容を生成し直して不足を隠さない。
- 是正Change: [preserve-public-review-finding-details](../preserve-public-review-finding-details/verification.md)。REPORT実装と公開経路の自動回帰Testを追加し、関連17件・全体587 passed/1 skippedを確認した。最新Translation→Word PDF→Reviewでの正式検証は未完了のため、本指摘の解決判定は保留する。

### 調査対象Artifactの同一性

先行sample3-acceptance-v2成果物について、[追加のセル照合](../require-translated-text-units-before-export/verification.md)でVERIFY Artifact→実DOCXの3表・151セルの行列位置、文字列、横結合幅の一致を確認した。非空訳は122セル。これは先行成果物での保持検査であり、原本からの抽出完全性・表内画像・翻訳品質・最新修正のE2E合格とは区別する。DATA-001および実受入の未完了判定は変更しない。

| Artifact | bytes | SHA-256 |
| --- | ---: | --- |
| Review/source/load/document.json | 295,054 | `b477679632211a310e8d6708cfb07136bc0bd52c16e6cf6abfb6dd268bd52722` |
| Review/target/load/document.json | 345,654 | `fe2473ada901875e77d77f320e895aee6d48e83b8dd5a9a55f669f26143134ec` |
| Review/align/alignment.json | 44,743 | `2c57dc94f1187045cedd7bb3f47b336fe7beb6670ab676b498e181f1dd640295` |
| Translation/verify/document.json | 600,814 | `4f60482ab67ab6d6e593eee05747f7b49bdb77324bfd0371a89a8fe3eb28efff` |

Translationは先行Run `01a0d44f-1efa-7597-9d1b-0be4c5748b85`、Reviewは本節冒頭のRun。Fileは読取りのみで、本文・raw応答・認証値はこの記録へ転載しない。

### 判定

比較受入は新規CRITICAL 2件により不合格。14/16 tasksは変更せず、利用者目視・既知の表品質・配置/再開管理などの指摘も継続する。実行中Reviewが後で終了コード0となっても、上記の誤対応に基づくFindingを翻訳不具合と即断せず、正式verify・archive・main merge・pushの成功条件とは扱わない。

記録後、`tests/test_documentation.py`・`tests/test_align_contract.py`・`tests/test_comparison_capability.py`は計26 passed（1.94秒）。本ChangeとCheckpoint Changeのstrict validationはvalid、git diff --checkは指摘なし。既存Testが新しい不適合を検出しないことは上記のassert点検と分けて記録する。全製品suiteと外部モデルの再実行はせず、session 12758の同一live handleでREVIEW継続を確認した。製品・Test Fileの編集、Runの停止・再起動・削除は行っていない。

### 先行Reviewの終端確認（2026-09-25 07:30 JST）

同じsession 12758は終了コード0、TOTAL 5615.091秒で終了し、公開Markdownと診断JSONを保存した。CHECK 247件＋REVIEW 170件の417 Findingがあるが、既知のALIGN誤対応に由来する指摘を含むため、そのまま翻訳欠陥数としない。旧REPORTの公開Markdownには根拠90件・修正方針98件の文字列が見当たらず、COMPARE-REPORT-001も実成果物で再現した。

詳細・hash・修正版REPORTへの実データ再投入結果は[後続Changeの検証記録](../preserve-public-review-finding-details/verification.md)を参照する。修正版の単独描画では417区画の項目欠落0件・生HTML token 0件だったが、最新E2Eを代替しない。

先行Review終了後、現在の入力/設定と互換な翻訳Run `01a0d520-15a4-74a2-9eaf-afafa726a03a`をsession 43282でResumeした。モデル実行は重複していない。14/16 tasksと不合格判定は維持し、最新Word/PDF・比較・利用者目視、表内画像、common/再開統合、ALIGN等の残課題が解消するまでarchiveしない。

### TRANSLATION-LATENCY-001: 実翻訳の長時間化を試行別に説明できない（WARNING・未解決）

2026-09-25 08:52 JST、翻訳Resume processは約80分経過してliveだった。第15ページの参照検索Artifactは08:51に生成されたが、DOCXは未生成であり、完全停止ではないことを翻訳成功と解釈しない。利用者は長時間自体を問題としておらず、その原因説明を求めている。所要時間の新たな合否条件は設定しない。

既存のLLM観測は再試行全体を一つにまとめ、試行ごとの経過時間・理由・対象Chunkを記録していない。通常の推論設定、出力検証や切断回復、通信再試行のいずれが時間を占めたかは取得済み出力から特定できない。`task_deadline_seconds`も各LLM要求の再試行判断用で、翻訳全体の総時間上限にはなっていない。詳細・根拠・是正案は[後続Changeの途中検証](../preserve-public-review-finding-details/verification.md)を参照する。診断不足を別Changeで是正し、根拠なしのtimeout短縮・並列化・推論設定変更や、独立したResume台帳の追加は行わない。

後続の既存Langfuse Provider観測との照合で原因を特定した。約84.3分の確認範囲でchat 22件が時間の97.79%を占め、生成tokenの89.80%が推論だった。high推論が出力枠16,384 tokensをほぼ使い切った2試行は計約16分、その直後のnone再送はそれぞれ約8秒/16秒で成功した。製品側観測だけでは不足していたが、既存Provider観測にtoken内訳があったため、追加機能を前提にせず説明できた。詳細は上記リンクの「原因の特定」を参照する。速度の不合格やnone時の品質同等性を宣言せず、実行設定は変更しない。

### 利用者指示後の実行切替（09:27 JST）

上記の「設定は変更しない」は原因診断時点の履歴である。その後、利用者の指示でsession `43282`を停止し、Checkpoint/Artifactを保持した。共通推論OFF設定を実装・自動検査した`11e8dd3`のworktreeから、新規Run `01a0d5f5-beb9-79d1-a1e4-f4300066b6b5`をsession `98497`で開始した。保存設定はoffで、export先は`outputs/sample3-acceptance-off`。進捗・Code同一性・実要求観測は[OFF検証記録](../configure-verification-reasoning-policy/verification.md)を参照する。未解決の表内画像・ALIGN・利用者目視を含む14/16 tasksの判定は維持し、設定追加だけで解決とはしない。

09:31:39 JSTに上記sessionはTRANSLATEのProtectedFragmentMissingでexit 1となった。新規DOCX/PDF/Reviewは未生成で、既存v2成果物を今回の合格証拠へ流用しない。直接原因は実応答から2つの保護断片が欠けたこと。読取り専用再現はリンク先のTRANSLATE-PROTECTED-OFF-001を参照し、本Changeの4.3/5.5と既存指摘は未完了のまま保持する。

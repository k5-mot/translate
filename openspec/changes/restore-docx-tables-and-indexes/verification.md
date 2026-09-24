<!-- markdownlint-disable MD013 MD041 -->

# Verification: restore-docx-tables-and-indexes

## 現在の判定

2026-09-25の正式verify結果: **検証失敗・archive不可**。既存Testは成功したが、追加の境界ケースで表の列位置とInline情報の欠落を再現した。tasksのチェックは10/11であり、チェック済みであることを全入力の正しさの証拠にはしない。利用者の目視確認も未完了。以下の積み残しは保持する。

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

**状態: 方針承認済み・実装と検証は未完了。** 2026-09-25、既存関数を入口として維持し、BaseTaskを継承する各Task classへ委譲する併用案を利用者が承認した。共通計測と固有処理を分離し、Workflowの状態通知・Resume管理はBaseTaskへ移さない。承認を実装完了として扱わない。

- [ ] 全Taskの入出力、実行順序、計時、atomic保存、retry、失敗通知、状態の有無を比較し、実際の重複を示す。
- [ ] 共通base class＋各Task class案と現行関数方式を、差分量、型の明確さ、テスト容易性、LangGraph/Resumeとの対応、継承しない例外Taskの扱いで比較する。
- [ ] 共通実行契約を定義し、基底クラスが担う責務と各Taskが担う責務を利用者へ具体例で説明する。
- [ ] 合意した方式を別Changeの仕様・設計・tasksへ反映し、共通化だけを目的とする無関係なLayer追加を防ぐ。

## 追加監査（2026-09-25）

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

- [ ] sample3のステータス表に含まれる黄・緑の丸は、既存Internal Documentでは独立したFigureになっている。セルへの関連付け・配置の保持は別途検証し、通常の表出力修正だけで解決としない。
- [ ] 表紙がPandocの図番号に数えられ、最初の本文図がFigure 2となる点を確認・修正する。表紙Captionの除去と本文図の採番は別の問題として追跡する。
- [ ] 利用者による再生成Word/PDFの目視確認（表、一覧、改ページ、見出し、起動時ダイアログ）。
- [ ] テンプレート由来のヘッダー・フッターに「○○システム」「○○株式会社」「SYS-DS-001」が残るため、製品成果物での扱いを確認する。

## 実装方針の訂正

利用者の指摘に従い、表をHTMLへ変換する既存処理と今回のHTML経由案を廃止する。Internal Documentの行・列・結合情報からPandocの表構造を直接構築し、既存Pandocでgrid tableを出力する。HTML readerやHTML中間成果物は使用しない。

一覧はMarkdownを正規表現で再解析せず、変換済みDOCXの見出し・図題・表題から静的な項目を作る。これによりCode内の見かけ上の見出しやCaptionが目次へ混入することを防ぐ。ページ番号は提案どおり含めない。

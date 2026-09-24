<!-- markdownlint-disable MD013 MD041 -->

# Verification: restore-docx-tables-and-indexes

## 現在の判定

実装と自動検証は完了（tasks 10/11）。利用者の目視確認は未完了。以下の積み残しは本Changeの実装修正だけで解消済みとしない。archive判定は保留する。

## 自動検証と実成果物

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

**状態: 未解決・設計未決定。** Taskが似た構造を持つためbase classを継承すべきではないか、という利用者の指摘を記録する。今回のDOCX修正でclass化を実施・決定した扱いにしない。

- [ ] 全Taskの入出力、実行順序、計時、atomic保存、retry、失敗通知、状態の有無を比較し、実際の重複を示す。
- [ ] 共通base class＋各Task class案と現行関数方式を、差分量、型の明確さ、テスト容易性、LangGraph/Resumeとの対応、継承しない例外Taskの扱いで比較する。
- [ ] 共通実行契約を定義し、基底クラスが担う責務と各Taskが担う責務を利用者へ具体例で説明する。
- [ ] 合意した方式を別Changeの仕様・設計・tasksへ反映し、共通化だけを目的とする無関係なLayer追加を防ぐ。

## DOCX品質の残課題

- [ ] sample3のステータス表に含まれる黄・緑の丸は、既存Internal Documentでは独立したFigureになっている。セルへの関連付け・配置の保持は別途検証し、通常の表出力修正だけで解決としない。
- [ ] 表紙がPandocの図番号に数えられ、最初の本文図がFigure 2となる点を確認・修正する。表紙Captionの除去と本文図の採番は別の問題として追跡する。
- [ ] 利用者による再生成Word/PDFの目視確認（表、一覧、改ページ、見出し、起動時ダイアログ）。
- [ ] テンプレート由来のヘッダー・フッターに「○○システム」「○○株式会社」「SYS-DS-001」が残るため、製品成果物での扱いを確認する。

## 実装方針の訂正

利用者の指摘に従い、表をHTMLへ変換する既存処理と今回のHTML経由案を廃止する。Internal Documentの行・列・結合情報からPandocの表構造を直接構築し、既存Pandocでgrid tableを出力する。HTML readerやHTML中間成果物は使用しない。

一覧はMarkdownを正規表現で再解析せず、変換済みDOCXの見出し・図題・表題から静的な項目を作る。これによりCode内の見かけ上の見出しやCaptionが目次へ混入することを防ぐ。ページ番号は提案どおり含めない。

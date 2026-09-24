<!-- markdownlint-disable MD041 -->

## 状態

実装と自動回帰検査まで完了（5/9 tasks）。正式verify・archive・main merge・pushは未実施。COMPARE-REPORT-001は実成果物での検証を残しており、[元の指摘](../restore-docx-tables-and-indexes/verification.md)を正式解決済みにしていない。

## 調査根拠

- `comparison-review`の全Requirement/ScenarioをCLIで確認した。「問題と根拠をReportする」が既に対象・根拠・修正方針の公開を要求するため、要求変更なしの実装修正としてdeltaを省略する。
- 修正前のreport.pyのMarkdown出力はseverity/kind/messageのみ。既存Testはevidence/suggestion付きFindingを入力するが、公開Markdownの全fieldを検査していなかった。
- 先行メモリ試験はREPORTの保存関数のみをcaptureへ差し替え、対象ID/根拠/修正方針のmarker欠落とJSON完全保持を示した。これはPDF/LLMを通す実受入試験ではない。
- 読取り専用の補助調査では、Group IDは比較Document側の`alignment/<index>`から導出可能、REVIEWの未知IDは現Modelで拒否されない、元PDFページ番号はREPORT入力だけでは解決できないと確認した。
- 導入済みmarkdown_it 4.2.0のメモリ試験では、既存markdown._escapeはHTML/実体参照のliteral保持を保証しなかった。既存code描画の動的fence方式は試験文字列をliteralとして保持した。製品にHTML中間変換を追加する提案ではない。

## 実行中Reviewの扱い

2026-09-25、既存session `12758`を同一handleでpollし、liveのままであることを確認した。Runは`01a0d534-b9c9-7e60-9edf-7541d26b6e05`。停止・再起動・並行モデル要求は行っていない。これは先行TranslationのWord PDFに対する旧REPORT実装のReviewであり、本Changeの検証証拠として流用しない。終端は未確認。

## 計画レビュー

grill-with-docsによる境界確認で、既存Finding情報の公開に限定し、未知ID拒否や元PDFページ解決を暗黙追加しない。None/空文字の区別、未知対象の明示、自由文のliteral表示はdesign.mdに示した表示案で、次のapply前のレビュー対象。用語変更や不可逆な設計判断はないためGlossary/ADRを新設しない。

未承認のcommon移管先・旧UUIDv7移行・表断片の曖昧な結合方針を本Changeで確定した扱いにしない。全体goalと元Changeの既存残課題は維持する。

## 文書検査

提案時点の検査:

- `openspec status`: proposal/design/tasksの3 Artifact complete、specsは明示skip。提案時点では実装Taskは全9件未着手。
- `openspec validate preserve-public-review-finding-details --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.25秒）。公開Findingの新規Testや製品全suiteは、この文書提案では未実行。
- `git diff --check`: 指摘なし。既存の無関係な変更を維持し、今回の文書と元指摘への参照だけをコミット対象とする。

これらの合格は計画文書の検査であり、製品不具合の解消・正式verify成功を意味しない。

## Applyの実装証拠（2026-09-25）

- 修正前、公開fieldを検査するassertを既存比較Testへ追加し、CHECK/REVIEW両経路の直接REPORT Testも追加した。`tests/test_comparison_capability.py`は3 failed / 1 passed（2.11秒）。`alignment/0`が公開Markdownにないため失敗し、既存Testの見落としを検出した。
- `translate/tasks/report.py`で対象ID・根拠・修正方針を全件表示し、対応一覧へ既存のalignment/indexラベルを付けた。未知対象は元IDを残して対応情報なし、空対象は対象未指定、None/空文字は別表示とする。元のFinding/Group Model、JSON全field、集計・順序は変更していない。
- 自由文は動的fenceでliteral表示する。既存code描画の小さな方法をREPORT内で使用し、Blockを偽造するadapterや新しい汎用描画moduleは作っていない。標準re以外の製品import追加はない。導入済みMarkdown parserはTestでのみ使用し、HTML成果物を作らない。
- 回帰Testは17 passed（2.12秒）。CHECK/REVIEWの全field、None/空文字/空白、複数/未知対象、caption/cell、多対多・片側未対応、順序/集計/JSON一致を検査した。6種類の特殊文字入力について、parserがraw HTML・リンク・画像tokenを作らず、内容をliteralとして保持することを確認した。
- 公開経路Testは外部解析とモデル処理をdoubleへ置換し、REPORT・CLIのRun準備/公開・export・UIのdownload関数は実実装を通した。実REPORTのbytesとCLI --output、export先、download_buttonへの受渡しの一致を指摘あり/0件の両方で確認し、入力hash不変と外部HTTP呼出0件も検査した。ブラウザの実ダウンロードや実PDF解析を代替するTestではない。
- `uv run ruff check .`: passed。`uv run ruff format --check .`: 328 files already formatted。`uv run ty check`: passed。`uv run pytest -q`: **587 passed, 1 skipped（39.84秒）**。
- SkipはWindowsで実行対象外のPOSIX PTY Test。個別の`pytest -q -rs`でも既定のskip理由を確認した。今回追加した公開REPORT Testにskipはない。
- `openspec validate preserve-public-review-finding-details --strict`: valid。`git diff --check`: 指摘なし。追加関数・入れ子のTest代替関数には目的説明を付与し、追加のmodule・依存・外部要求・再開台帳がないことを差分で確認した。group_idsは呼出中に既存groupsから導出する表示用集合で、永続化や再開判定には使用しない。

2026-09-24 21:25 UTC（JST 2026-09-25 06:25）、session 12758を同一handleでpollしliveを再確認した。旧processに読み込み済みのREPORTを今回の修正で置換・reloadしておらず、その終了結果を新実装の検証とみなさない。逐次実行のため、新しいTranslationはまだ開始していない。tasks 3.1〜3.4とCOMPARE-ALIGN-001、表品質、common/再開統合などの残課題は継続する。

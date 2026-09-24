<!-- markdownlint-disable MD041 -->

## 状態

提案段階。製品Code/Testの修正・正式verify・archive・main merge・pushは未実施。COMPARE-REPORT-001は未解決で、[元の指摘](../restore-docx-tables-and-indexes/verification.md)を解決済みにしていない。

## 調査根拠

- `comparison-review`の全Requirement/ScenarioをCLIで確認した。「問題と根拠をReportする」が既に対象・根拠・修正方針の公開を要求するため、要求変更なしの実装修正としてdeltaを省略する。
- report.pyのMarkdown出力はseverity/kind/messageのみ。既存Testはevidence/suggestion付きFindingを入力するが、公開Markdownの全fieldを検査していない。
- 先行メモリ試験はREPORTの保存関数のみをcaptureへ差し替え、対象ID/根拠/修正方針のmarker欠落とJSON完全保持を示した。これはPDF/LLMを通す実受入試験ではない。
- 読取り専用の補助調査では、Group IDは比較Document側の`alignment/<index>`から導出可能、REVIEWの未知IDは現Modelで拒否されない、元PDFページ番号はREPORT入力だけでは解決できないと確認した。
- 導入済みmarkdown_it 4.2.0のメモリ試験では、既存markdown._escapeはHTML/実体参照のliteral保持を保証しなかった。既存code描画の動的fence方式は試験文字列をliteralとして保持した。製品にHTML中間変換を追加する提案ではない。

## 実行中Reviewの扱い

2026-09-25、既存session `12758`を同一handleでpollし、liveのままであることを確認した。Runは`01a0d534-b9c9-7e60-9edf-7541d26b6e05`。停止・再起動・並行モデル要求は行っていない。これは先行TranslationのWord PDFに対する旧REPORT実装のReviewであり、本Changeの検証証拠として流用しない。終端は未確認。

## 計画レビュー

grill-with-docsによる境界確認で、既存Finding情報の公開に限定し、未知ID拒否や元PDFページ解決を暗黙追加しない。None/空文字の区別、未知対象の明示、自由文のliteral表示はdesign.mdに示した表示案で、次のapply前のレビュー対象。用語変更や不可逆な設計判断はないためGlossary/ADRを新設しない。

未承認のcommon移管先・旧UUIDv7移行・表断片の曖昧な結合方針を本Changeで確定した扱いにしない。全体goalと元Changeの既存残課題は維持する。

## 文書検査

- `openspec status`: proposal/design/tasksの3 Artifact complete、specsは明示skip。実装Taskは全9件未着手。
- `openspec validate preserve-public-review-finding-details --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.25秒）。公開Findingの新規Testや製品全suiteは、この文書提案では未実行。
- `git diff --check`: 指摘なし。既存の無関係な変更を維持し、今回の文書と元指摘への参照だけをコミット対象とする。

これらの合格は計画文書の検査であり、製品不具合の解消・正式verify成功を意味しない。

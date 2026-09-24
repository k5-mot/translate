<!-- markdownlint-disable MD013 MD041 -->

# 実装時検証: include-table-and-caption-content-in-review

## 判定

2026-09-25、実装と自動検証を実施。正式verifyは未完了。実translation→Microsoft Word PDF化→入力PDFと生成PDFのreview、および利用者目視が未実施のためarchive不可。DATA-001全体を解決済みとはしない。

## Completeness

Task 1.1〜1.3を実装した。新しい保存schema・Dependency・common Module・再開台帳は追加していない。

| 対象 | 実装と証拠 |
| --- | --- |
| 本文/caption/cellの列挙 | translate/document.pyのTextUnit/block_text_units。既存Inline参照を使い、本文IDを維持、caption/cellは起点IDで識別 |
| セル単位の欠落検出 | CHECKが各unitを個別検査しFinding.target_idsへIDを保存。他cellの同一数値で相殺しないTest |
| 空訳・空候補 | Noneの場合だけfallback。None/空配列/空文字/有内容の16組合せ、およびREVIEW/VERIFY実promptのTest |
| 修正候補の検証 | 本文/caption/cellのsource/before/candidateを送信し、採用・不承認・例外の3条件をTest |
| 表/captionだけの比較 | ALIGNから比較Document、CHECK、REPORTまで通し、両側一致/原文のみ/訳文のみの6条件をTest |

## Correctness

- 追加のtests/test_text_unit_review.py: 29 passed。
- 全体uv run pytest -q: 366 passed、1 skipped（24.91秒）。既存のskipを成功には数えない。
- 変更対象7 Python filesのRuff check、Format check: 成功。
- 全体uv run ty check: 成功。
- OpenSpec strict validation: 成功。
- git diff --check: 成功。
- 全体Testは既存の未commit差分を含むworktreeで実施した。本Changeのcommitへ無関係な差分を取り込まず、commit単独の実E2E成功を主張しない。

## Coherence

共通列挙は既存document.pyに限定し、5利用箇所で使用する。Documentの永続schemaは変えず、純粋画像へ文字を作らず、結合cellを範囲分展開しない。FIXのInline方式、既存の逐次REVIEW分割・障害処理を維持した。対象追加により既存Review cacheのpairs digestが変化するが、完了Graphの自動再計算はしない。

## 未完了・別指摘との境界

- CRITICAL: Task 2.2。新実装の実translation→Word PDF→reviewを新規Runで実施し、実Artifactの表/caption対象を照合する。
- CRITICAL: Task 2.3。利用者のWord/PDF目視結果を記録し、正式verifyとarchive判定を行う。
- 既存実翻訳session 40709、Run 01a0d44f-1efa-7597-9d1b-0be4c5748b85は旧Codeを読込んだProcess。今回の実装検証には流用しない。2026-09-25 02:25 JSTまでにpage-0007-chunk-0001の検索Artifact更新とsession継続を確認。重複Model実行・再起動はしていない。
- 既存FIXは指摘があるページの全Inlineを候補対象へ渡し、VERIFYの採否もページ単位である。仕様の「指摘がある翻訳単位だけ」の厳密な限定は本修正だけでは証明できず、未解決として保持する。unit IDとInline IDの対応を含む是正・Testが必要。
- LangGraph以外のPage/Chunk再開cache、common配置、全関数コメント、表内画像・図番号・Template残存文字等は別の指摘として残る。今回の成功で閉じない。

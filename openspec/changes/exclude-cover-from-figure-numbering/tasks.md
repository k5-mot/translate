<!-- markdownlint-disable MD013 MD041 -->

## 1. 表紙と本文図の採番境界

- [x] 1.1 tests/test_output_contract.pyのFigure 2を期待するTestを1開始へ変更し、表紙あり/なしの同一本文で番号差が生じることを先行Testで再現する。外部Modelは呼ばない。
- [x] 1.2 render_documentの表紙表現を標準escaped spaceで通常Imageにし、実Pandoc変換で表紙descr・幅・先頭配置・改ページ、本文と図一覧のFigure 1開始を確認する。本文Caption・表番号の文字列置換、新Module、依存追加を行わない。
- [x] 1.3 表紙だけ、複数本文図、Captionなし画像、表混在、元Caption内の番号、空白/日本語を含む画像pathを既存Test Fileで検査し、番号差0とCaption・画像保持を確認する（Q-FUNC/Q-COMP/Q-USE）。既存のatomic公開・外部参照拒否回帰も維持する。

## 2. 品質・実成果物・受入

- [x] 2.1 関連Test、全pytest、Ruff/format、ty、OpenSpec strict、diff検査を実行し、結果・Code版・適用範囲をverification.mdへ記録する。独自採番/追加依存0と関数説明、既存API再利用を確認する（Q-MNT/Q-REL/Q-SEC）。
- [ ] 2.2 修正後の新規sample3翻訳→Microsoft Word PDF→原本とのComparison Reviewをreasoning OFF・逐次で実行し、Run ID、hash、終了状態、本文と図一覧の番号を記録する。LLM障害中や修正前の成果物を合格へ読み替えない。
- [ ] 2.3 Word/PDFを利用者へ提示して目視結果を記録し、元の図採番指摘へ証拠を対応付けて正式verify・archive可否を判定する。旧成果物・Runの移行/削除なし、.agents/実生成物のcommit除外を確認する。他の図表・品質指摘も解消した場合だけ仕様同期・archive・PR/CI・main merge/pushへ進む。

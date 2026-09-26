<!-- markdownlint-disable MD013 MD041 -->

## Why

[既存の図採番指摘](../restore-docx-tables-and-indexes/verification.md)では、表紙がFigure 1を消費し、本文図と図一覧がFigure 2から始まる。表紙は画像だけを出力するという既決定の意味を、本文図の自動採番にも一貫して適用する。

## What Changes

- 表紙を本文図の自動採番・図一覧の対象から除外する。最初の採番対象の本文図は1とする。
- 表紙の代替説明・幅・先頭配置・改ページを維持し、本文Captionの内容と図・表の区別を変えない。
- 現状のFigure 2を期待するTestを修正し、表紙あり/なし・複数図・Captionなし画像・表だけの境界を検査する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `markdown-docx-conversion`: 表紙を本文図の採番から除外する観測可能な要件を追加する。既存の一般変換要件や先行Changeのレイアウト要件を置換しない。

## Impact

translate/tasks/markdown.pyの表紙表現とtests/test_output_contract.py。既存PandocとDOCX正規化を使用し、新Module・Dependency・採番器・HTML変換を導入しない。表内画像の所属、元Caption中の番号の書換え、仮ヘッダー、ALIGNの修正は含めない。

## Stakeholders and Lifecycle Impact

利用者は表紙による欠番のない図と図一覧を得る。保守者は既存変換器の採番を利用する。取得・供給は既存依存のまま、移行は新規生成分だけを対象とし、保存済みDOCX/PDFやRunを上書き・移行・削除しない。廃止するのは表紙を採番対象として渡す経路であり、データ廃棄はない。

## Quality Considerations

Q-FUNC/Q-USE: 本文図と図一覧の自動番号を一致させ、表紙による番号消費を0件にする。Q-REL/Q-COMP: 表紙なし・表紙だけ・複数図・表混在の実Pandoc変換と既存レイアウト回帰を検査する。Q-MNT: 新しい独自採番・文字列置換・依存追加を0件とする。Q-SECは既存の外部参照拒否とatomic公開を維持する。性能・可搬性・安全性に新しい処理系や外部通信は追加しない。正式verifyでは推論OFF・逐次のsample3翻訳→Microsoft Word PDF→原本とのReviewと利用者目視を別々に記録する。

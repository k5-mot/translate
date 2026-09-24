<!-- markdownlint-disable MD041 -->

## Context

`proposal.md`のWhyを参照。現状は`markdown.py`がHTMLの`<table>`を出力しているが、PandocのMarkdown入力ではRaw HTMLとして扱われ、DOCXでは段落へ分解される。また`--toc`系のDOCXは更新用フィールドだけを出力し、前回のポップアップ対策でdirty/updateFieldsを除去した結果、キャッシュ本文が空になる。

## Goals / Non-Goals

**Goals:**

- Pandocが認識するgrid tableを生成し、表題をPandoc Table captionとして保持する。
- 変換済みDOCXの見出し・図題・表題からエントリを作り、OOXMLの一覧SDTを静的な段落へ置換する。
- 表紙後の順序、一覧末尾の改ページ、日本語一覧見出し、Headingスタイルのアウトライン番号抑制を決定的にする。
- テンプレートのスタイルインベントリを再現可能なMarkdownとして納品する。

**Non-Goals:**

- Wordフィールドをユーザー環境で更新すること、またはページ番号を事前に推測すること。
- 新しいDOCX変換ライブラリや外部サービスの導入。
- 入力PDFの表認識アルゴリズムそのものの変更。

## Decisions

1. **HTMLを経由せずGrid tableを出力する。** Internal DocumentのセルをPandocの表構造へ直接対応付け、導入済みPandocのwriterでgrid tableを生成する。行・列位置、rowspan/colspan、空欄、明示改行を保持する。表のHTML直列化は削除する。Pandoc API versionは実行中のPandocから取得し、追加の変換ライブラリや共通Layerは導入しない。
2. **一覧は静的なOOXML段落にする。** WordのTOC/SEQフィールドはページレイアウト更新が必要で空欄・確認ダイアログを招くため、見出し名・図題・表題を`TOC1`～`TOC6`または`BodyText`段落としてキャッシュする。ページ番号は出力しない。
3. **一覧名は正規化処理で置換する。** Pandocが生成したSDTのgallery値を識別し、本文の見出しrunを日本語化する。空一覧も見出しと改ページを残す。
4. **改ページは一覧SDTの外側へ置く。** 各一覧をbody childとして正規化し、その直後に`w:br w:type="page"`段落を挿入することで、Word/PDFの両方で境界を保証する。
5. **HeadingスタイルのnumPrを除去する。** 参照テンプレートのHeading1～9にはnumId=1が定義されているため、生成DOCXの`styles.xml`から該当numPrのみを除去する。outlineLvlは残し、目次対象の階層は維持する。
6. **DOCXの確定した本文から一覧を作る。** Heading1～6、ImageCaption、TableCaptionの段落を対象とし、既存一覧を除外して項目を取得する。正規表現によるMarkdown再解析ではCode内の見出しや装飾を誤認識するため採用しない。生成済みの本文表示と一覧の文字列を一致させ、Captionは通常の目次へ含めない。

## Quality Attribute Design

- Q-FUNC: grid tableの`w:tbl`、非空一覧、改ページ、順序をXMLテストと実Pandocテストで検証する。
- Q-REL: normalize/validate/publishのatomic境界を維持し、正規化Errorでは一時DOCXだけを削除する。
- Q-USE: 日本語一覧名と重複しない見出し番号を実生成DOCXのplain text/XMLで検証する。
- Q-MNT: スタイル一覧生成スクリプトを一度実行した結果を固定文書としてレビューし、コードに依存しない。

## Lifecycle, Migration and Operations

実行時は従来のRun directoryと成果物契約を利用する。既存Runは再実行で新しいDOCXを生成でき、旧DOCXは自動上書きしない。運用時にWordのフィールド更新や外部参照を有効化する必要はない。テンプレートを更新した場合はスタイル一覧を再生成して差分レビューする。廃止時は通常のRun削除範囲に従う。

## Risks / Trade-offs

- [Risk] 静的一覧はWordの最終ページ番号・自動更新・項目から本文へのリンクを持たない → 生成時点の対象名一覧であることを明示し、ページ番号やリンクを生成したと報告しない。
- [Risk] grid tableのセル内改行・長文で幅が増える → セル内改行・結合セルを自動Testで検証し、長文セルの用紙内配置は実成果物でも確認する。
- [Risk] テンプレートのスタイルIDが将来変更される → `template-style.md`の更新を検証タスクに含める。

## Migration Plan

コードとテストを更新し、sample3のMarkdownからDOCXを再生成してXML/Word/PDFを確認する。問題がある場合は新しい一時成果物を破棄し、既存DOCXを保持するためロールバックはコード変更のrevertだけで完了する。

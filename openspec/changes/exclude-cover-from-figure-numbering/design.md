<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。render_documentは表紙を非空altを持つ単独画像段落として渡す。Pandoc 3.11のimplicit_figuresがこれをFigureへ変換し、DOCX生成後の_reorder_front_matterはCaptionだけを削除するため、本文側の採番は既に2から始まっている。_populate_front_matterは本文Captionを図一覧へ複写するので、一覧側だけの問題ではない。

## Goals / Non-Goals

表紙を変換器へ渡す表現だけで採番対象から除外し、既存の代替説明による表紙識別・DOCX正規化・一覧生成を保つ。番号を後処理で減算する採番器、HTML、独自Pandoc AST変換器は作らない。既存Captionに含まれる「Figure 7」等の文字列、本文図の翻訳、表内画像所属、仮ヘッダー、旧成果物の自動更新は対象外。

## Decisions

1. 表紙Markdown画像の直後だけにPandoc標準のescaped space（バックスラッシュと半角空白）を置く。段落が画像単独ではなくなるため通常Imageになり、本文のCaption付きFigureは維持される。導入済公式Guideのimplicit_figures節とstdin/stdout probeで確認した。表紙のalt「表紙」とwidth=100%、直後の既存OpenXML改ページは変えない。
2. 採番はPandocへ委譲する。implicit_figuresを全体で無効にすると本文Captionも失われる。空alt＋fig-altは通常Imageになるが、実DOCXのdescrが空となり現行表紙識別と整合しない。inline Spanでも識別と採番は維持できたが、標準の末尾空白方式で新しいclassや構造を足す必要がない。
3. 現在のtests/test_output_contract.pyはFigure 2を期待しているため、そのまま成功しても修正証拠にならない。本文Captionと図一覧の自動番号、表紙descr・画像数・先頭順序・改ページを実Pandoc出力で検査する。Captionなし画像、表紙なし、表紙だけ、複数図、表混在も含む。
4. 表紙の構文を生成する既存render_documentだけを変更する。一般の利用者Markdownからalt文字列だけで表紙を推測して書換える機構は追加しない。既存のDOCX正規化・atomic公開・外部File参照拒否は維持する。

### 判断枝の確認

grill-with-docsでは、表紙画像のみの出力、本文Caption保持、既存APIへの委譲、旧Run保全という既決定を前提に調査した。技術上の分岐（全体無効化・空alt・Span・末尾空白）は上記probeで比較した。本Changeは表紙に起因する自動採番差だけを扱い、表内画像の曖昧所属等の未回答事項を決めない。用語は既存の表紙/Caption/Figureで足り、実装語をCONTEXT.mdへ追加しない。不可逆な判断ではないためADRも追加しない。今回は計画のみ提示し、apply依頼で方針確認後に実装する。

## Quality Attribute Design

Q-FUNC/Q-USEは表紙による番号差0と本文/図一覧一致へ、Q-REL/Q-COMPは画像説明・幅・順序・改ページ・表番号・Caption内容の不変へ対応する。Q-MNTは既存構文と関数の最小変更で満たす。Q-SECは既存の外部参照拒否・公開失敗時の旧成果物保持を回帰検査する。Module・依存・外部Model要求・状態保存は増やさない。

## Lifecycle, Migration and Operations

新規生成に適用する。既存の完了RunをResumeして新しい結果に変わったと報告せず、受入は新規Runを使用する。旧Markdown/DOCX/PDF、Checkpoint、入力コピーを無断で再生成・変更・削除しない。PDF化は引き続きMicrosoft Wordによる手動相当の検証操作であり、製品機能には含めない。

## Risks / Trade-offs

- [Risk] 末尾空白が編集時に失われる → Pythonの文字列として明示生成し、文字列一致だけでなく実Pandoc変換で検出する。
- [Risk] 表紙識別を壊して一覧が先頭へ戻る → descr=表紙、先頭画像、一覧順、改ページを一括検査する。
- [Risk] 元Captionの番号を誤って書換える → Captionの本文を保持し、自動番号と区別するTestを追加する。
- [Risk] 小さい変換試験をE2E合格へ読み替える → 新規翻訳→Word PDF→原本Reviewと利用者目視を別Taskに残す。LLM接続障害が続く場合は未完了のままとする。

## Migration Plan

既存不具合を先行Testで失敗させ、表紙表現の最小差分を適用する。回帰・品質Gate後に実E2Eと目視を実施し、元指摘へ対応付ける。RollbackはCode差分だけで可能であり、保存形式移行はない。受入完了前にarchiveしない。

## 参考資料

導入済Pandoc 3.11の `C:/Users/merry/AppData/Local/Pandoc/Pandoc User's Guide.html`、implicit_figures節（6764行付近）。外部最新仕様への推測ではなく、導入版の説明と実行結果に基づく。

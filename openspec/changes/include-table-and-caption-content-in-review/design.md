<!-- markdownlint-disable MD013 MD041 -->

## Context

proposal.mdのWhyを参照。Internal DocumentはBlock.source/translated/final、captionの3層、TableCellの3層を既に持つが、CHECK/REVIEW/VERIFY/ALIGNと比較Document組立ては本文しか列挙していない。FIX/TRANSLATEは既にcaption/cellのInlineを扱える。

## Goals / Non-Goals

既存の全text layerを検査対象に含める。Table抽出・レイアウトの再設計、HTML、並列実行、新たなResume cache、独自tokenizerは追加しない。既存の全ページVERIFYの予算問題や修正単位の別の違反が見つかった場合は黙って解決扱いにしない。

## Decisions

1. document.pyに凍結dataclassのTextUnitとblock_text_unitsを置く。IDと既存の3層を参照する読み取りviewであり、Documentの保存schemaへ追加しない。5利用箇所で同じ列挙を使用し、commonや新しいpackageへ集めない。
2. 本文のunit IDは既存block.id、captionはblock.id/caption、cellはblock.id/cell/row/columnとする。結合cellはその起点を1回だけ列挙する。本文・caption・行列順のcellを区別し、別cellの数値が欠落を相殺しない。Inline自体のIDは変更しない。
3. TextUnit.textはsource/translated/finalの選択を受け、Noneの場合だけ前層へfallbackする。空配列または空文字は空のまま検査する。本文・caption・cellにいずれかの層があるunitを列挙し、内容のない純粋画像は新たな文字を作らない。
4. CHECKはunit別に決定的検査を行いtarget_idsへunit IDを設定する。REVIEWとVERIFYは同じID/層をpromptへ含める。FIXは既存のInline修正方式を維持する。
5. ALIGNは原文層の文字を持つunitを対象とし、比較Documentは同じunit IDでlookupする。既存本文だけの対応関係は維持し、表/captionだけの文書を空扱いしない。
6. 単なる描画修正や成功済み旧Runの検査を、新規対象の検証成功とみなさない。既存のchunk cacheはpairs内容変更でkeyが変わるが、Graph完了checkpointは自動再計算されないため正式E2Eは新規Runで実行する。二重Resume廃止は別タスクとして残す。

## Quality Attribute Design

Q-FUNC: 表セルとcaptionそれぞれの数値欠落、空訳、異なる層、結合cell、比較片側欠落をfixture化。Q-REL: VERIFYのpromptと不承認後のセル/captionを照合。Q-MNT: 同じviewを全利用箇所へ適用。Q-SEC: 原文の新しいログ出力は追加しない。

## Lifecycle, Migration and Operations

公開CLI/UI、永続Document schema、既存入力を変更しない。検査範囲の拡大でFindingが増えるのは意図した是正。新規Runで逐次E2Eを行い、利用者へWord/PDFを提示する。実行中の旧製品Processを停止・再起動せず、完了を待つ。

## Risks / Trade-offs

- [Risk] Tableを丸ごと結合するとcell間の欠落を相殺する → cell単位を維持。
- [Risk] 空訳をorで原文へ戻す → Noneと空を区別するTest。
- [Risk] REVIEWの既存未commit差分を巻き込む → 本Changeのprompt生成/import差分のみstage。
- [Risk] 対象追加でModel入力が増える → 既存の有限逐次chunk処理を維持し、実行証拠を確認する。

## Migration Plan

共通viewとfixtureを追加し、5か所を順次置換する。既存成果物やcheckpointを直接書き換えない。rollbackは本Code差分で可能。未実装Scenarioはtasksを開いたまま保持する。

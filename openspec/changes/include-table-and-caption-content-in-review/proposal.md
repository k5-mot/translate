<!-- markdownlint-disable MD013 MD041 -->

## Why

DATA-001で、表セルの数値欠落がCHECKから漏れ、表だけの文書がALIGNで対象0件になることを確認した。表の表示を修正しても検査対象が本文だけでは品質を保証できないため、captionとセルを一貫して検査・比較へ含める。

## What Changes

- 本文、caption、各表セルを文書モデルの共通列挙処理から取り出し、CHECK/REVIEW/VERIFY/ALIGNと比較本文生成へ渡す。
- 検査対象に安定した識別子を付け、セル同士の数値や訳文を混ぜて欠落を相殺しない。
- 未作成の訳（None）と空になった訳（空配列）を区別し、空訳を原文で隠さない。
- 表だけ/captionだけの比較、セル欠落、修正候補不合格、各層の検査網羅を回帰Testする。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 翻訳結果の検査を本文だけでなくcaptionと表セルへ明示的に適用する。
- `comparison-review`: captionと表セルを対応付け・欠落検出・意味Reviewの対象として保持する。

## Impact

translate/document.py、CHECK/REVIEW/VERIFY/ALIGN、comparison_reviewの比較Document組立てと関連Test。新Packageやcommon Module、永続化schema、別の再開台帳は追加しない。既存Reviewの有限逐次分割・予算・障害処理を利用する。

## Stakeholders and Lifecycle Impact

利用者が表の数値やcaption欠落をreportで認識できる。既存の本文IDと公開CLI/UIを維持し、検査対象拡張で追加Findingが生じ得る。取得・供給に新依存なし、既存成果物の削除なし。旧完了Runの検査結果を新しい網羅性の証拠に使用せず、新規Runで正式検証する。

## Quality Considerations

Q-FUNC: 本文/caption/セルの検査対象欠落0、各unitを1回、空訳の原文fallback0をfixtureで確認。Q-REL: VERIFY不承認時の修正前訳維持を確認。Q-MNT: 共通列挙は既存document.pyへ限定し、Taskごとに列挙条件を複製しない。Q-SEC: 内容の新しい公開log出力なし。Model要求は逐次で、性能向上は対象外。実translation→Word PDF→reviewと目視確認を省略しない。

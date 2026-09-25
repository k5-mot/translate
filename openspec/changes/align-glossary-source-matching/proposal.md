<!-- markdownlint-disable MD013 MD041 -->

## Why

sample3の実翻訳でCapital内のapiに用語APIが誤一致し、無関係な用語集指摘がFIX/VERIFYへ渡った。既存の用語選択とCHECKが異なる照合をしているため、承認済みの用語集検査を維持しながら適用対象を一貫させる。

## What Changes

- 原語が独立した語として現れない場合、単なる単語内の部分一致による用語集違反を作らない。
- 大小文字と連続空白の既存正規化を共有し、実際に存在する原語の指定訳欠落は従来どおり指摘する。
- 本文・Caption・表セルと、翻訳/比較の共通CHECKへ同じ判定を適用する。数値等の他検査は変更しない。
- 検査契約を既存Ruleとfingerprintへ反映し、旧結果を修正後の成功として再利用しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 用語集の原語が現れる範囲と、指定訳欠落の判定を明示する。
- `comparison-review`: 比較CHECKにも同じ用語適用範囲を要求する。

## Impact

tasks/check.pyの既存matching_glossaryの再利用、review Ruleと関連Testが対象。新Module・依存・並列化・LLM段階・独立再開台帳は追加しない。ALIGN、抽出時の負数欠落、表内画像、FIX/VERIFYのページ単位処理は別件として残す。

## Stakeholders and Lifecycle Impact

- 利用者/運用: 無関係な用語指摘を減らすが、無誤訳保証や性能向上率は約束しない。
- 保守/廃止: CHECKだけの単純部分一致を廃止し、導入済みの照合と回帰試験へ統合する。
- 移行/供給: CLI/UIと成果物形式は維持。旧Runを削除・上書きせず、Rule hashの互換性と新規実E2Eを検証する。
- 取得: 新しい外部サービス・依存の取得はない。

## Quality Considerations

| ID / 特性 | 測定可能な受入 |
| --- | --- |
| Q-FUNC 機能適合性 | Capital/APIの誤指摘0、実APIの指定訳欠落検出、大小文字/空白/句読点境界の合成Scenario全成功 |
| Q-REL 信頼性 | 数値/否定/条件/URL警告等の既存試験全成功、本文/Caption/セルで同じ結果 |
| Q-COMP 互換性 | 両翻訳Backend/比較の旧Rule Resume拒否、新Rule同士の互換性維持 |
| Q-PERF 性能効率 | 専用モデル要求追加0、実検証のLLM/Embedding逐次実行 |
| Q-USE 利用時の確認容易性 | 真の用語違反は対象ID・根拠を公開reportへ保持 |
| Q-SEC Security | 公開例外・ログへ本文や秘密を追加しない。既存安全性試験を維持 |
| Q-MAIN 保守性 | 既存APIへの委譲、新規Module/依存0、全Test/Ruff/ty成功 |
| Q-PORT 移植性 | Windowsで実翻訳→Word PDF→比較を検証。OS専用照合実装0 |

新用途・プラットフォーム対応・身体的安全性の保証は変更しないため追加要求の対象外。

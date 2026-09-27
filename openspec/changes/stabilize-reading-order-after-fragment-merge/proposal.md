<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

安全な断片結合の後でも、POSITIONを再適用すると本文の読み順が変わる（POSITION-ORDER-001）。結合によって段組推定の座標標本が減り、同じ元文書に対する段の判定基準が変わるため、結合前後で読み順を安定させる必要がある。

## What Changes

- 結合前後で保持される既存の出典座標を段組推定に利用し、断片数の変化だけで未結合要素の相対順が反転しないようにする。
- 同じ補正済み文書を再処理しても、内容・参照・読み順が変化しないことを検証する。
- 複数出典座標、ページ境界、欄外、同位置、欠損座標を回帰対象に含める。安全な同一ページ結合と、曖昧な候補の保持＋警告方針を維持する。
- 過去Runを変更せず、新しい処理結果で検証する。順序を固定する保存フラグや再開台帳は増やさない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 決定的な読み順について、断片結合と再適用での安定性を具体化する。

## Impact

対象は`translate/tasks/position.py`の段組推定・ページ境界確認と既存POSITION Test。共有前処理を利用するReview/登録の回帰も確認する。公開入口・Document Schema・Dependencyは変更しない。基礎となる[断片結合修正](../preserve-merged-fragment-content-on-load/proposal.md)を前提とする。

段組認識全体の刷新、LLMによる読み順推定、画像所属、ALIGN、保存構成再編は対象外。新しい移行処理や旧実装の並存は行わない。

## Stakeholders and Lifecycle Impact

- 利用者・運用: 同じ補正済み入力を再処理しただけで段落が前後する不安定性を除く。
- 取得・供給: 追加Package/サービスを取得せず既存PR/CIで供給する。`.agents`とPDF/DOCX・実行生成物を除外する。
- 移行・廃止: 古いArtifactのmigration、互換読込み、旧判定切替は追加しない。利用者の既存ファイルを無断削除しない。
- 保守: 小さな再現fixtureと保存済みsample3の読取り検証、新規推論OFF・逐次Translation→Word PDF→Review、利用者目視を分けて追跡する。

## Quality Considerations

- Q-FUNC/Q-REL: 再適用による順序反転、内容欠落・重複、参照破損を対象fixtureで0件とし、元文書の読み順保持と再実行安定性を検証する。
- Q-COMP/Q-MNT: 既存の座標変換、中央値、Task入口、参照整合・原子的保存を再利用する。新Module/Dependency/永続制御状態0件。
- Q-SEC/Q-INT: 診断へ本文や認証値を追加しない。変更理由は既存の参照列reportで追跡可能にする。
- 性能効率: 外部呼出追加0件。既存provの有限走査と既存sortで実現し、収束まで繰返す無制限loopは設けない。
- 柔軟性/移植性・安全性: 新規環境・配備方式・身体/環境リスクを導入しないため追加要求は適用しない。

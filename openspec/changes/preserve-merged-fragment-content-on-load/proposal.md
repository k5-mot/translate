<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

POSITIONで結合した元要素がcollectionに残り、LOADが再追加するため、訳文へ重複が持ち込まれる（CONTENT-MERGE-001）。実sample3でも17組の再出現を確認しており、結合した内容・参照・Captionを失わず、一度だけ後続へ渡す必要がある。

## What Changes

- 安全に結合した本文・コード・表について、結合元の再追加を防ぎ、正当な未参照要素と同じ文字列の別要素を保持する。
- 共有参照、Caption、子要素、表の複数表現などの保全を確定できない候補は、利用者の2026-09-27の承認に従い、結合せず内容を残して警告する。
- 表結合時の参照更新を構造上の参照に限定し、本文・URL等の一般文字列を変更しない。セルの位置・span・識別子と後続要素への参照を保つ。
- POSITION→NORMALIZE→LOADの統合回帰を追加し、collection補完を一律に廃止する修正や文字列一致による除重を行わない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 文書構造保持のうち、断片結合後の重複防止・内容保持・曖昧時の警告継続を具体化する。

## Impact

中心は`translate/tasks/position.py`と既存POSITION/LOADのTest。共有前処理を利用するComparison Reviewと参照登録にも影響するため回帰を確認するが、各操作の独立した公開契約は変更しない。LOADの正当な未参照内容補完は維持する。新しいDependency、Module、公開引数、再開台帳は追加しない。

保存先再編・LangGraphの再開整理・表内画像の所属判定・ALIGN・翻訳品質判定は別の是正であり、本Changeで完了としない。旧構成のmigration、互換loader、旧版並存は追加しない。既存利用者ファイルの削除は行わない。

## Stakeholders and Lifecycle Impact

- 利用者・運用: 二重出力を防ぎ、判定できない結合は内容を残した警告として追跡可能にする。
- 取得・供給: 既存依存だけを使い、PR/CIで供給する。`.agents`、入力PDF、Word/PDF成果物、実行生成物をコミットしない。
- 移行・廃止: 既存Artifactを書き換えるmigrationや旧版維持は行わない。不正な文字列置換と結合元の再出現経路を置き換える。保存構成全体の旧版廃止は別Changeに残す。
- 保守: 回帰fixtureと、推論OFF・逐次の新規Translation→Microsoft Word PDF→原本とのReviewで確認する。利用者目視と未完了指摘を追跡する。

## Quality Considerations

- Q-FUNC: 結合元の二重出力、正当な独立要素・Caption・セルの欠落、参照破損、一般文字列の書換えを回帰行列で0件にする。
- Q-REL: 連鎖結合とPOSITION再適用で重複・欠落を増やさず、曖昧な候補は入力を保ち警告する。
- Q-COMP/Q-MNT: 既存Task、Document変換、原子的保存を使う。新Dependency/永続状態/互換分岐0件。共通前処理の他操作も回帰する。
- Q-SEC/Q-INT: 診断に本文・Caption・秘密値を追加せず、対象参照と固定理由だけを記録する。曖昧時の理由を利用者が確認できる。
- 性能効率: 外部呼出追加0件。文書内の有限走査で処理し、参照調査を候補ごとの文書全探索にしない。
- 柔軟性/移植性・安全性: 新規環境、デプロイ方式、身体・環境リスクを導入しないため追加要求は適用しない。

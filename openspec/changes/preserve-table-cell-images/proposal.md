<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

sample3の黄・緑の丸10個が表セルから外れ、独立した図として縦に出力される。LOADでセルとの所属関係を失い、内部文書もセル内画像を表現できないため、Wordの見た目だけを補正せず入力から成果物まで所属を保持する必要がある。

## What Changes

- 表内画像のセル所属、元の寸法、画像参照と付随Captionを内部文書・Markdown・DOCXへ保持し、表外へ二重出力しない。
- 明示参照と座標による根拠を照合し、所属候補が曖昧・矛盾する場合は承認済み方針に従ってWorkflowを停止し、再開可能な状態を保持する。
- セルbboxがない場合も、原点を統一した行列見出しの位置が一意に交差するケースを扱う。最近傍や固定のsample位置で推測しない。
- 既存PandocのTable/Image表現とwriterを利用し、HTML、画像の別形式変換、新Dependency、追加LLM、別の再開台帳を導入しない。
- **BREAKING**: 従来の表外退避による成功は許容しない。旧Artifactの移行・互換読込み・旧実装の併存を追加しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `pdf-translation`: 表内画像の所属・寸法・一意出力と、所属不確定時の停止を具体化する。

## Impact

`document.py`、LOAD、セル/Captionを扱う翻訳・検査・描画境界と既存Testが対象。共通前処理を使う比較/登録も回帰対象とする。Pandoc変換の公開契約を変えず既存の画像/Table保持を利用する。common配置、保存構成再編、ALIGN、図採番全体やテンプレート修正は別残件とする。

## Stakeholders and Lifecycle Impact

- 利用者・運用: 表の位置が示す意味を維持し、所属を確定できない成果物を公開しない。失敗対象を安全なIDで示す。
- 取得・供給: 既存依存のみ。PR/CIの後に供給し、`.agents`、PDF/DOCX、入力・実行生成物をコミットしない。
- 移行・廃止: 新しい内部表現のみで処理する。旧形式移行や旧実装切替を作らず、既存利用者データを無断削除しない。
- 保守: 合成fixture、保存済み中間データの補助検査、新規実Translation→Word PDF→Reviewと利用者目視を区別する。

## Quality Considerations

- Q-FUNC/Q-REL: 既知10画像の行列一致、欠落/重複/表外出力0件、未確定時の公開0件を検査する。
- Q-INT: 原本pt寸法を保持し、DOCXのextentとの誤差を1 EMU以内で検査する。視覚品質は実Word PDFで別に確認する。
- Q-SEC: assetの存在・保存領域内参照を検査し、本文・秘密・画像bytesを例外へ出さない。
- Q-MNT/Q-COMP: 既存Schema、BaseTask、保存、Pandoc機能を利用し、通常の図、結合セル、両Backend、比較/登録を回帰する。
- 性能効率: 所属判定に外部要求を追加せず、有限な参照/座標照合のみ。任意の距離探索やモデル推測を導入しない。
- 柔軟性/移植性: 新しい配備環境を要求しない。身体・環境に関する安全性リスクは本変更の対象外である。

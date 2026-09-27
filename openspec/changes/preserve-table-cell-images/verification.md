<!-- markdownlint-disable MD013 MD041 -->

# 検証記録

## 2026-09-27 計画と環境確認

起点Commit `3090cf9`。今回は計画のみ、製品Code/Test未変更、Task 0/12。利用者の「表内画像の所属不明は停止・Resume保持」と「移行なし・新構成のみ・旧版を残さない」は[承認記録](../clarify-code-documentation-and-reuse-rules/verification.md)に従う。旧データの削除許可とは解釈しない。

`openspec-propose`と`grill-with-docs`を使用した。mainはLOAD/文書Model/Markdown/VALIDATE/STRUCTURE/翻訳/FIX/VERIFY、Pandoc adapter、既存Capabilityを確認した。スキルの事実調査として限定sub-agentが所属根拠、Schema伝播、Test位置を独立確認した。外部モデル、Embedding、Docling、Wordは呼んでいない。既存の無関係な作業差分は保持した。

### 再利用する実データ証拠

[元の画像調査とPandoc実験](../restore-docx-tables-and-indexes/verification.md)を再利用する。Run `01a0d8b6-c2ab-7c92-bed9-58403a8410b3`のMERGE SHA-256は現物確認でも`989b39b390a42e5a99a94c349ab02cf18fa6f12fa7817d284b44090b4d5c70d6`と一致した。

- 原本15ページ、tables[1]、3行×6列。10丸の親はbodyで、セル明示参照はない。空セルにはbboxがないが、列見出し5個と行見出し2個にTOPLEFT bboxがある。
- 表と画像はBOTTOMLEFT。ページ高さ792ptで原点を統一すると、全10画像が表内完全包含され、画像中心の行/列見出し区間が一意に交差する。
- 0始まりの対応はpictures 13/14→列1、19/20→列2、17/18→列3、21/22→列4、15/16→列5。各組は行1/2。これはTestの期待結果であり、製品へ固定indexを埋め込む設計ではない。
- 既存Pandoc実験は位置を手動指定して10セル内画像、表外0、pt→extent誤差1 EMU以内を確認した。自動所属や製品create_docx、Word PDF受入の証拠ではない。不要な再実験はせず、実装後の製品経路TestをTaskへ残した。

### Code照合で見つかった境界

| 観測 | 設計への反映 |
| --- | --- |
| TableCellは文字層のみ、LOADは全pictureを独立Figureへ変換 | 既存Model内に最小画像表現を加え、LOADで所属を確定 |
| grid優先でspanを1にするが、現物gridにもoffset/spanがある | 同じ論理セルへ正規化し、別表現の二重所有・span消失を防ぐ |
| POSITION座標処理はBOTTOMLEFTの符号反転だけ | 混在原点の所属判定には実ページ高さを使用。読み順全体は変更しない |
| body走査後にcollectionを補完する | 割当済み画像の独立出力を両経路で抑止し、正常な補完は残す |
| STRUCTUREはtableのkind変更が可能 | 画像付きcellsを描画不能にする変更を拒否し、最終検査も追加 |
| 文字層の翻訳/FIX/VERIFYには個別のcell走査がある | Captionも既存文字処理へ接続。deep copyだけで完了としない |
| Markdownはセルの文字だけを描画しasset検査は独立Figureだけ | 既存Pandoc Image ASTとasset検査をセル内へ適用 |
| VALIDATEの既存asset補正は旧checkpoint用 | セル画像向けの旧形式互換を増やさない |

既存`_resolve`、Pydanticの保存/再読込み、BaseTask、atomic保存、PandocのTable/Image writerを利用する。導入済み依存にローカルDocling APIはなく、HTTP側の出典から不足するセル所有契約だけをLOADで扱う。汎用geometry/コンテンツFrameworkや別保存Layerは追加しない。

通常図・複数画像・結合セル・Caption・原点混在・所有矛盾のScenarioを設計へ展開した。根本の停止方針は回答済みであり再質問しない。新しい業務用語の合意や独立Architectureは導入しないため、glossary/ADRは新設しない。

### 実受入の状態

LLMの直近接続確認は[読み順Changeの終端記録](../stabilize-reading-order-after-fragment-merge/verification.md)のとおりHTTP 500。現在進行中のモデル処理はなく、本Changeで新要求を送っていない。実Translation→Word PDF→Reviewと利用者目視は未実施。ALIGNの探索方式は別途回答待ち、common/保存構成とLangGraphの状態統合も別の未完了作業である。

### 計画の検査

- OpenSpec status: schema mysdd、proposal/specs/design/tasksの4/4が存在し、実装準備完了。実装Taskは0/12。
- `openspec validate preserve-table-cell-images --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、0.34秒。
- `git diff --check`: 指摘なし。製品Codeを変更していないため全製品Testは再実行していない。
- コミット対象は本Change文書と元指摘への対応付けのみ。無関係な既存差分、`.agents`、入力・PDF/DOCX・実行生成物を除外する。

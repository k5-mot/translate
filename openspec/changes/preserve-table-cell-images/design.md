<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。既存調査ではsample3の原本15ページ、3×6の表内画像10個について、表bboxへの完全包含と行列見出しの一意交差を確認済みである。空セルにbbox/画像参照がないため明示参照だけでは解決しない。内部TableCellは文字層だけで、LOADはpictureを独立Figureにする。

既存Pandocで、指定セル内画像10件とpt寸法をDOCXへ保持できることは検証済み。ただし自動所属判定、製品DOCX後処理、Word PDFの実受入はまだない。[調査記録](verification.md)で事実と未実装を区別する。

## Goals / Non-Goals

**Goals:** 所属をLOADで一度確定し、既存内部文書の中に保存して描画まで伝える。確定不能を成功扱いにしない。

**Non-Goals:** 画像認識/追加OCR/LLMによる所属推測、HTML変換、Wordの表レイアウト再実装、独立した所有台帳・再開Cache。common再編、保存root再編、ALIGNの探索方式は本Changeへ混ぜない。

## Decisions

### 1. LOADで参照と座標を照合し、論理セルへ一意に帰属させる

既存のref解決と画像URI正規化を使用する。tableのgrid/table_cellsは同一論理セルの別表現として扱い、行列offset・spanの起点を一度だけ正規化する。gridにもoffset/spanがある現物を確認しているため、gridを一律span=1へ落とさない。表現間で矛盾したshapeを一方の優先だけで隠さない。

有効な明示セル参照があれば第一の根拠にする。座標根拠が存在するときはそれとの整合も検査する。明示参照が不正・複数・別ページなら幾何fallbackで隠さず停止する。明示参照がない場合は、同じページの一つの表への画像全体包含を必要条件とし、セル領域bboxによる一意包含、または列見出しx区間と行見出しy区間の一意交差で所属を確定する。後者の中心は区間内部にあることを要求し、境界一致を任意に片側へ丸めない。

spanを持つ見出しが複数の論理行列を示す場合、そのまま一つを選ばない。交点が同じ結合セルの起点へ正規化される場合だけ単一候補とする。複数画像が同じセルに入ること自体は競合ではない。複数表、複数セル、上位と下位の根拠の矛盾、部分的な表境界重なりは曖昧として停止する。表と無関係な独立図を最近傍で吸収しない。座標不足で表との関係自体を判定できない同ページ画像は、明示的な独立所有を証明できなければ停止する。

所属表は呼出内の一時mappingとし、独立ファイル/進捗状態にしない。割当済み画像のrefをbody走査とcollection補完の両方で除外し、セル内の一箇所だけに残す。画像Captionも同じ所有に従い、正常な独立図のCaption補完を壊さない。

### 2. 混在する座標原点を実ページ寸法で統一する

TOPLEFT/BOTTOMLEFTをページ高さを使ってTOPLEFTのptへ揃える。有限数、正の幅/高さ、ページ一致を検査する。既存POSITIONの`_geometry`はBOTTOMLEFTのyの符号反転だけなので、混在原点を同じページ座標へ変換するAPIとしては使わない。LOAD内に必要な座標変換だけを置く。新しいgeometry Packageや全体の読み順変更は不要。

数値の距離閾値、等幅列の推測、sample画像indexの固定対応は採用しない。原本上の幅・高さをptで保持し、pixel数やDPIから別の大きさを推測しない。

### 3. 内部文書に必要最小のセル画像表現を加える

既存`document.py`内にセル画像の型を置き、TableCellがその配列を所有する。各画像は元画像ID、相対asset参照、有限で正のwidth/height(pt)、alt文字列、付随Captionの原文/翻訳/最終層を持つ。別Moduleや汎用コンテンツ木は作らない。画像自体は翻訳対象にせず、Captionは既存InlineのIDと文字層として既存の翻訳・CHECK/REVIEW・FIX/VERIFY・空訳検査へ接続する。

同セル内の画像順は既存文書の出現順を保持する。セル本文、画像、各付随Captionを失わず描画する。画像のみのセルは非空白原文がないため空訳拒否の対象にしない。Document/PageのJSON往復と各Taskのdeep copy後も画像参照・寸法・Captionが保たれることをTestする。

STRUCTUREは現在tableを任意kindへ変更できる。画像付きcellsを隠す変更は適用前に拒否し、最終検査でもcellsを持つ非table等の描画不能構造を成功扱いにしない。単にfieldが保存されているだけで保持を証明しない。

### 4. 既存Pandoc経路でセル内に出力する

`markdown._table_row`の既存Table ASTへImage要素とpt寸法を渡す。既存`table_to_markdown`→grid Markdown→`create_docx`のwriterを利用する。画像付きセルを文字が空という理由で空扱いせず、見出し行判定でも画像がある本文行をTableHeadへ誤吸収しない。結合セルと見出しから本文への縦結合で既承認の見出し太字/繰返し抑止を維持する。

セル内の状態画像を独立Figureとして図番号/図一覧へ再追加しない。独立図の番号や表紙・一覧の既存処理は回帰対象とし、その修正全体を本Changeへ広げない。HTMLや画像の変換、新しいDOCX描画器は使用しない。

### 5. 保存・公開・障害の境界は既存処理を使う

セル画像もassetの存在、許可root内の解決、寸法、重複所有を検証する。旧checkpointのURI補正をセル画像へ拡張しない。新規処理のMERGE相対URIを正規形とする。安全な失敗分類は本文・raw応答・画像bytesを含めず、既存Task通知とCheckpoint例外の保護へ渡す。

LOADの確定失敗では既存atomic_directoryを公開せず、GraphがLOADを未完了として再開する。VALIDATE/Markdownで破損が検出された場合も既存成果物を保持する。独自skipフラグや画像完成一覧は不要。共有LOADを使う比較/登録も同じ不正構造を黙って受け入れないことを回帰確認する。

## Quality Attribute Design

| ID | 実現手段・証拠 |
| --- | --- |
| Q-FUNC/Q-REL | 所属根拠の合成行列、実10画像、body/collection二重出力なし、失敗注入とGraph Resume |
| Q-INT | 元ptとDOCX XMLのextent照合、本文/Caption/結合領域の保存、Word PDFの目視 |
| Q-SEC | root外・欠損asset・非有限寸法拒否、診断marker試験、入力/既存公開物hash不変 |
| Q-MNT/Q-COMP | 既存Task/Pydantic/Pandocを使用。追加Dependency/Module/外部要求/独自再開状態0件 |

## Lifecycle, Migration and Operations

先に失敗fixtureを作り、所属・Schema・描画を接続する。保存済みMERGEを読取り専用にして一時領域で補助検証する。その後、新規推論OFF・逐次Translation→Microsoft WordでPDF→原本とのComparison Reviewを行い、利用者へWord/PDFを提示する。LLM障害と未修正ALIGNの影響は別残件として明示し、合成試験だけで受入を完了しない。

## Risks / Trade-offs

- [Risk] 座標だけで誤所属する → 明示根拠との矛盾、複数候補、原点/ページ不足は停止。近傍推測を使わない。
- [Risk] 厳格化で従来成功した入力が停止する → 画像を誤配置して成功するより、承認済みの停止・Resumeを優先し対象IDを示す。
- [Risk] Schema追加だけではSTRUCTUREや描画で消える → 中間往復と実writer、最終構造検査を必須にする。
- [Risk] 画像Captionを非翻訳扱いにする → 既存文字単位の検査・修正・最終採用訳へ組み込む。

## Migration Plan

旧Artifact移行、旧パス読込み、互換loader、旧実装切替を作らない。新しい文書表現で新規検証する。RollbackはCode版の切替のみで、利用者の過去Run/成果物を変換・削除しない。common/保存構成の旧実装廃止は別の未完了作業であり、本Change完了を全体移行完了とはしない。

<!-- markdownlint-disable MD013 MD041 -->

## 1. 所属と内部表現

- [ ] 1.1 既存LOAD/出力Testへ表内画像の失敗fixtureを追加し、文字だけのTableCellと独立Figure化による欠落/表外出力を再現する。混在原点、gridとtable_cells、結合セル、画像のみセル、Caption付き画像を含める（Q-FUNC）
- [ ] 1.2 既存document.pyへセル所有画像の最小型と配列を追加し、ID/asset/pt寸法/CaptionのJSON往復・deep copy保持と不正寸法拒否をTestする。新Module/Dependency/再開状態を作らない
- [ ] 1.3 LOADの行列offset/spanを論理セルへ正規化し、明示参照・セルbbox・行列見出しの一意交差で所属を確定する。両座標原点、複数表/所有、矛盾、境界重なり、座標不足、span起点、同セル複数画像の回帰を通す
- [ ] 1.4 bodyとcollection補完の両方から割当済み画像の独立出力を除き、Caption所有を維持する。通常の表外図、表紙、同一ref再出現、正当な未参照要素の保持と画像欠落/重複0件を確認する

## 2. 翻訳・描画・公開境界

- [ ] 2.1 画像Captionを既存の翻訳・CHECK/REVIEW・FIX/VERIFY・最終空訳検査へ接続し、両Backendの文字層採用/修正失敗時の復元と画像自体の不変をTestする。画像のみセルを未翻訳と誤判定しない
- [ ] 2.2 STRUCTUREが画像付きセルを隠すkind変更を拒否し、保存後の非table/cells不整合も最終検査で拒否する。既存内容が消えず公開されないことをTestする
- [ ] 2.3 既存Pandoc Table ASTへセル画像・pt寸法・Captionを出力し、実Markdown→DOCXでセル位置、結合領域、見出し判定、画像数とextent誤差1 EMU以内を確認する。HTMLなし、表外重複なし、図一覧への状態画像混入なしを確認する（Q-INT）
- [ ] 2.4 セル画像も欠損/許可領域外asset・重複所有・不正寸法を拒否する。LOAD/VALIDATE/保存失敗の実Graph試験で後続公開なし、元入力/旧成果物hash不変、CheckpointからのResume、診断marker非漏洩を確認する（Q-SEC/Q-REL）

## 3. 統合と実受入

- [ ] 3.1 保存済みsample3 MERGEを読取り専用で一時領域へ処理し、10画像の行列・寸法・画像hash・表外0件を検査する。製品create_docxまでの補助結果と原本hash不変を記録し、新規実E2Eとは区別する
- [ ] 3.2 Ruff check/format、ty、全pytest、OpenSpec strict、git diff --checkを実行する。比較/登録の共通LOAD、通常の図表、関数説明と既存API再利用、追加依存/旧形式互換/独自台帳0件を確認してCode hashと結果をverification.mdへ記録する（Q-MNT/Q-COMP）
- [ ] 3.3 サービス接続回復後にsample3の新規推論OFF・逐次Translation→Microsoft Word PDF→原本とのComparison Reviewを実行し、終了状態、設定、入出力hash、表内画像・Caption・一覧の品質を記録する。ALIGN等が未解決なら実受入は未完了に維持する
- [ ] 3.4 Word/PDFを利用者へ提示して目視確認を得る。全証拠と残件を正式verifyし、仕様同期/archive・PR/CI・main merge/pushの可否を判定する。`.agents`、入力、PDF/DOCX、実行生成物を除外し、旧形式の移行/並存や利用者データの無断削除を行わない（供給・運用・保守・廃止）

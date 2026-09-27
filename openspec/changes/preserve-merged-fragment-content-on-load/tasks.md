<!-- markdownlint-disable MD013 MD041 -->

## 1. 内容と参照を保持する結合

- [ ] 1.1 既存POSITION Testへ実POSITION→NORMALIZE→LOADのfixtureを追加し、本文/コード/表の結合元再出現、共有A/Bの二重結合、参照風セル本文の改変を修正前に再現する。正常な未参照要素と同文の別要素を残す期待値も固定する（Q-FUNC）
- [ ] 1.2 POSITIONで参照元fieldと所有関係を収集し、片側/両側共有・同一親の重複・同一ref・Caption/children・異なるformatting/hyperlinkを安全に扱えない候補を変更前に保持＋固定警告とする。再訪問による二重処理を防ぎ、各曖昧fixtureで内容/参照が保持されることを確認する（Q-REL/Q-INT）
- [ ] 1.3 安全な本文/コード結合の消費元をcollectionsから除き、残存indexと構造上の参照を一括対応付けする。連鎖A/B/C、後続index 1/10、同文別要素、未参照要素と再適用で欠落・重複・参照破損0件を確認する。既存reportは入力IDと出力IDを識別でき、LOAD用skip台帳を増やさないことを確認する
- [ ] 1.4 単一table_cells/cellsの安全な表結合で行・span・セルID・parent参照を保全し、一般文字列のreplaceを廃止する。複数行・rowspan/colspan・双方cell/0・参照風text/text_content/URLと、gridのみ/複数表現/空grid/外部cell参照/固有または共有Captionの保持＋警告を統合Testで確認する（Q-FUNC）

## 2. 統合回帰と規約・安全性

- [ ] 2.1 実NORMALIZE/LOADと後続Document描画で内容が一度だけ残ることを確認し、既存読み順/Caption/picture除外/Review/参照登録の回帰を実行する。LOADの正当なcollection補完を維持し、新Dependency/Module/保存台帳/旧版互換分岐がないことを差分で確認する（Q-COMP/Q-MNT）
- [ ] 2.2 合成本文・URL・認証markerで警告/reportへの追加転記0件を確認する。全関数の目的説明、既存API利用、入力不変、既存原子的保存を検査する。Ruff check/format、ty、全pytest、OpenSpec strict、git diff --checkの結果と版をverification.mdへ記録する（Q-SEC）

## 3. 実受入とリリース判定

- [ ] 3.1 LLM接続の回復確認後、sample3.pdfを新規に推論OFF・逐次でTranslationし、Microsoft WordでPDF化して入力PDFとComparison Reviewする。新しいID対応、結合/警告件数、後続文書と成果物の重複・欠落、入力/出力hashと終了状態を記録する。旧Runの読取り結果や合成Testを実受入の代替にしない
- [ ] 3.2 利用者へWord/PDFを提示して目視確認を記録し、全Requirement/Scenario/Taskの証拠で正式verify・仕様同期・archive可否を判定する。未完了ならarchiveせず、PR/CI→main merge/push時は`.agents`・入力・サンプルPDF/DOCX・実行生成物を除外する（供給・運用・保守・廃止）

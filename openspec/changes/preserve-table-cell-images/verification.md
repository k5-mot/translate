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

## 実装・補助検証と正式verify（2026-09-27）

計画基点`79e2f17`。`openspec-apply-change`でTask 1.1〜2.4と3.1を実装・検証し、`openspec-verify-change`でproposal/specs/design/tasksと照合した。**9/12完了、archive不可**。以下は新規Translation→Word PDF→Reviewの代替証拠ではない。

### 実装と失敗再現

- `document.py:52`のCellImageにID、assets参照、有限・正のpt寸法、Captionの原文/翻訳/最終層を保持する。最初の保存・寸法Testは11件失敗し、型定義後は成功した。
- `load.py:504`以降でgrid/table_cellsを論理セルへ統合し、offset/span・占有領域・見出し役割の矛盾を拒否する。明示参照、同ページの表包含、セルbbox、行列見出しの一意交差を照合する。BOTTOMLEFTはページ高さでTOPLEFTへ変換する。最初の6ケースで独立Figureが残る問題を再現し、修正後は正しいセルだけに保持された。
- `load.py:735`の呼出内mappingで所有を確定し、body/collection由来の重複Figureを取り除く。画像順・Caption・通常の独立図・結合セルを保持する。固定sample index、距離閾値、追加Model呼出しはない。
- `load.py:417`の所属例外はページと検証済み形式の対象IDだけを公開する。任意文字列IDは`unknown`とし、raw bbox/Caption/asset pathを例外文字列へ含めない。
- `block_text_units`と既存翻訳/FIX/VERIFY/VALIDATEへセル画像Captionを接続した。両BackendのCode/link保持、初回訳への復元、空訳停止、画像のみセルの通過を検査した。画像自体の翻訳や新しい検査Backendは追加していない。
- `markdown.py:234`で既存Pandoc Table/Image ASTへ画像・pt寸法・Captionを渡す。実DOCXで複数画像、画像だけの本文行、見出しから本文への縦結合、太字/繰返し抑止を確認した。CaptionをImageCaption styleへ昇格させず、状態画像を図一覧へ追加しない。HTMLを導入していない。
- STRUCTUREの非table化と、保存後のnon-table/cells不整合を拒否する。`markdown.py:502`の画像検査をVALIDATEとMarkdown公開前から使用し、欠損・assets領域外・root外・絶対path・重複所有・不正寸法・未解決Caption linkを拒否する。

### 障害・再開・安全性

- `tests/test_position_tables.py:344`の実Translation Graph＋SQLiteで、LOAD所属不明と保存失敗を注入した。旧LOAD Artifact、元入力、既存出力のhashを維持し、STRUCTUREへ進まないことを確認した。別SQLite接続から同じthreadを再開し、LOAD完了後のSTRUCTURE境界まで到達した。後続Modelを実行した証拠とはしていない。
- `tests/test_validate_contract.py:203`の公開操作＋実Graphでは、セル画像Caption欠落・asset欠損でVALIDATE停止し、Markdown/DOCXが未実行であることを検査した。合成入力を修復後、前段を再実行せず再開した。既存成果物・reportを失敗時に置き換えない。
- 本文・訳文・秘密値・保存例外のmarkerが診断、Checkpoint、failure記録へ漏れないことを検査した。合成試験の外部Networkを禁止し、画像所有専用の再開Cache/完了一覧/新Module/新Dependencyを作っていない。
- 既存図caption fixtureが非tableにdummy cellsを持っていたため、図ではcellsを作らないfixtureへ修正した。不正spanをLOADが丸める旧期待値も、POSITIONは原形保持・LOADは拒否の承認済み方針へ変更した。

### 保存済みsample3による製品DOCX補助検証

旧RunはResumeせず、MERGEを読取り専用で一時領域のPOSITION→NORMALIZE→LOAD→MARKDOWN→DOCXへ渡した。既存`docx.run`→`create_docx`の後処理を含む検査であり、手動のセル割当ではない。

- 入力MERGE SHA-256: `989b39b390a42e5a99a94c349ab02cf18fa6f12fa7817d284b44090b4d5c70d6`。処理前後で不変。
- 表3個。対象表の10画像は、原本15ページの期待行列すべてと一致。割当済み画像の独立Figure出力0件。
- DOCXの各セル位置をXMLで照合し、埋込み画像10件すべてのSHA-256が元assetと一致。寸法差は最大`0.9984130859375` EMUで1 EMU以内。対象表内のImageCaption styleは0件。
- 補助DOCX SHA-256: `f0bf295dc3b6735e79e5f78425452f5db54112d4b3675bf84bf43f726d634637`。一時生成物は検査後に削除済み。利用者の入力・旧Run・既存DOCX/PDFを変換・削除・上書きしていない。
- LLM/Embedding/Doclingサービス呼出し0件。Microsoft Word PDF化・新しい訳文の検査・利用者目視は未実施。

### 最終自動検査

- `uv run ruff check`: 成功。
- `uv run ruff format --check`: 391 files already formatted。
- `uv run ty check`: 成功。
- `uv run pytest -q --tb=short`: **1020 passed, 1 skipped、57.46秒**。Windowsで対象外のPOSIX PTY試験1件をskip。`PYTHONUTF8`の一括設定なし。
- `openspec validate preserve-table-cell-images --strict`: valid。
- `git diff --check`: 指摘なし。

最終Code/Test SHA-256（無関係な既存dirty差分は別管理）:

| File | SHA-256 |
| --- | --- |
| translate/document.py | d75b84693de9d39fbe84fae73ec3f6fcdfde1b4fadce0935184ff66b40d0ae36 |
| translate/tasks/load.py | 96636467fe9c17129f1e953d56b1d9f2cbaa9aeef8659cd1239006e6eda532f1 |
| translate/tasks/markdown.py | 9e66f05b743039cdedb5bc144ece5b55d623b0adf0c0d0f1dbaed748c4cfb567 |
| translate/tasks/structure.py | 7fd9164868548521e1730ca9ffe75b89f4dc8800045c8ab9152a47488bc57a2a |
| translate/tasks/translate.py | c6e34c2da08c3b90001b7f5eb5bde3f305ae10b5fe42dd693ea997aa31d20498 |
| translate/tasks/fix.py | 5369d2c57780b2add85b48cb129542ec768d945dd206ec8649edee102bb45fe6 |
| translate/tasks/verify.py | 4a2a27824cb65a41f90de621a7bde93d7888778decec5894e15eff7a5d3b74ce |
| translate/tasks/validate.py | 791557738f435578f2782e88b79408bd8860e1b45919e7f45309d782e23d2885 |
| tests/test_position_tables.py | cea7380ddaefd77d7717e440030fb488f0445e15a6b5566ee30e2e28379b1efb |
| tests/test_output_contract.py | 9604dd3288dee1dc63e1ffe5bf6698086731d706443b8cd770f0354daaf2fc53 |
| tests/test_pdf_translation_capability.py | 99e7c814a2af4f84d61588e17ea379c4ecf8a7fcfed43abb2840d5962d3ee110 |
| tests/test_validate_contract.py | 58c3f00a683a02badacf6ebd96728a708cdd0007b59ed3f75b18e9ee322595ef |

### Verify結果と停止理由

| 観点 | 判定 |
| --- | --- |
| Completeness | 9/12 Task完了。3.2、3.3、3.4は未完了 |
| Correctness | 2要求・6 Scenarioの実装と合成/保存データ試験を確認。新規実訳とWord PDFの受入は未確認 |
| Coherence | 既存Schema/Task/Pandoc/保存/Graphを利用。ただし登録経路の設計前提に誤りあり |

CRITICAL（archive前に解消）:

1. **3.2 / 登録経路の前提確認**: 設計とTaskが「比較/登録が共通LOADを使用」としているが、現物はComparison Reviewのみが`comparison_review.py:286`でLOADを呼ぶ。registerは`qdrant.py:245`以降のDocling文字抽出と`_register`を使い、LOADを通らない。全Test成功を登録への本機能適用の証拠にはできない。経路変更は責務・登録対象・障害契約へ影響するため、黙って追加も除外もせず利用者判断待ち。推奨は本Changeの前提を事実へ訂正し、登録の共通化は別Changeで設計すること。
2. **3.3 / 新規実E2E**: LLMの直近接続確認はHTTP 500。回復後、推論OFF・逐次の新規Translation→Word PDF→原本とのReviewを完走し、hash・品質・終了状態を記録する。未解決ALIGNも別途是正が必要。
3. **3.4 / 利用者受入と供給**: 最新Word/PDFの目視確認後に再verifyし、仕様同期/archive、PR/CI、main merge/pushの可否を判定する。現時点では実施しない。

WARNING: 登録経路の誤認はdesign.mdのDecision 5、tasks.mdの3.2と対応する。同じ問題を上のCRITICALに集約した。根拠のない計画完了や別処理の追加で隠さない。新しい保存root、common整理、LangGraphの二重再開状態廃止は別残件であり、この実装を全体完了とは扱わない。

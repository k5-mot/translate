<!-- markdownlint-disable MD013 MD041 -->

# 検証記録

## 最新状態

2026-09-27: 実装・自動回帰は6/8 Task完了。新規実Translation→Microsoft Word PDF→Comparison Reviewと利用者目視は未完了。正式verify/archive・main merge/pushは行っていない。保存済みsample3の前処理再実行で、別の読み順変化（POSITION-ORDER-001）も確認したため、全指摘解消とは判定しない。

## 2026-09-27 計画段階

提案時点の状態: 製品Code/Testは未変更、実装Taskは0/8。以下は計画時点の記録であり、実装後の結果は後節に記載する。

利用者は六つの判断を承認し、曖昧な結合は「結合せず内容保持＋警告で続行」と確定した。ただし保存構成についてはmigration不要・新構成のみ・旧版を残さないと指定した。[承認記録](../clarify-code-documentation-and-reuse-rules/verification.md)に従い、旧形式変換/読込み/並存を追加しない。利用者の既存ファイルを無指定で削除する許可とは解釈しない。

### 環境事実と既存機能の再利用

起点Code: `23bfc6f`。`position.py`、`load.py`、`normalize.py`、`merge.py`と既存POSITION Testを読取り確認した。grill-with-docsの限定した事実調査としてsub-agentも同じ参照経路と必要な回帰ケースを独立に確認した。新たなLLM/Embedding/Docling要求は実行していない。

| 観測 | 計画への反映 |
| --- | --- |
| POSITIONはchildrenから元参照だけを削除し、LOADはcollections全体を補完する | POSITION内で消費元の整理と参照整合を完結し、正常なLOAD補完は残す |
| 共有groupからの参照で同じA/Bを再結合し得る | 所有fieldを区別した事前判定と再訪問抑止を併用する |
| 表結合はcellsだけを変更し、LOADは空listを含むgridを優先する | 整合を証明できない表現は未結合で保持して警告する |
| Caption所有の収集は全tables/picturesを走査する | 元表だけを除外してCaptionを消さず、所有関係が不確かな候補を結合前に回避する |
| `_rewrite_ref`は一般文字列を部分一致置換する | self_ref/$refだけを完全なsegment/ID対応で更新する |
| MERGEの既存参照処理はcollection offset専用で、任意mappingやcell suffixを扱わない | 安全なfield限定の処理方針を再利用するが、APIをそのまま使えると仮定しない |
| セルself_refは実JSON pathと一致するとは限らない | cell ID対応とcollection pathの再採番を区別して検査する |

過去の合成再現と実sample3の証拠は[元のCONTENT-MERGE-001記録](../document-all-python-function-purposes/verification.md)を正本とする。実完了Run `01a0d8b6-c2ab-7c92-bed9-58403a8410b3` では本文結合19件のうちLOADで17組が再出現し、保存Markdownで13組の両側描画を確認した。表結合は0件であり、合成例のセル本文改変を実sample3でも起きたと主張しない。

### 判断と境界

新しい永続的な除外台帳、汎用編集基盤、Dependencyを増やさず、既存Task内の変換を整合させる。保守的な未結合判定は承認済みの内容保持＋警告方針に従う。保存構成再編、LangGraph再開管理、commonの具体的移管先は本Changeで実装/承認済みとは扱わない。新しいDomain用語や独立したArchitecture境界を導入しないため、glossary/ADRの追加は不要と判断した。

実行前提として直近のLLM接続確認はHTTP 500で終了しており、回復はまだ確認できていない。合成回帰を先に進められるが、実E2Eを成功とする根拠はない。

### 計画の検査

- OpenSpec status: proposal/specs/design/tasksの4/4が存在し、実装準備完了。実装完了を意味しない。
- `openspec validate preserve-merged-fragment-content-on-load --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、1.16秒。
- `git diff --check`: 指摘なし。製品Code/Testの新規差分なし。既存の無関係な作業差分を保持し、本計画の文書だけをコミット対象とする。

## 2026-09-27 実装と回帰

起点Commit `217be19`からPOSITIONと既存の二つのPOSITION Testだけを変更した。LOAD/NORMALIZE/MERGE/Workflow、Dependency、保存Schemaは変更していない。参照の所有判定、消費元のcollection整理、field限定の一括再採番をPOSITIONへ実装した。reportの`from`/`into`は入力ID、`output_ref`は出力IDであり、後続の制御には使わない。

曖昧な所有・属性・表表現は結合前に保持＋警告とする。セルのparent逆参照を別所有者と誤認せず、外部cell参照は保守的に結合対象外とした。表は同じ単一cells表現の範囲・寸法・IDを検査し、一般文字列へのreplaceを廃止した。本文のorig層も存在時は結合し、連鎖結合には末尾provの位置を使う。

### 自動Testと品質検査

- 修正前の追加Test: 6 failed, 4 passed、0.44秒。本文/paragraph/code/program_listingの再出現4件、共有本文の`A B B`化、参照風セル本文の改変を再現した。
- 修正後の対象Test: 35 passed、0.86秒。実POSITION→NORMALIZE→LOAD、本文描画、独立同文・未参照内容、片側/両側共有、同一ref、Caption/children、異なるformatting/hyperlink、連鎖結合、後続index、再適用、表のrowspan/colspan、セルID、複数表現の保持を含む。
- report保存失敗の合成Testで、入力と既存公開Artifactのbytes不変を確認した。本文/認証markerを診断へ追加しないことも確認した。
- 最終全体Test: **924 passed, 1 skipped、53.93秒**（session 88611、exit 0）。共通前処理利用元のReview/登録、Caption/picture、既存読み順等を含む。直前版923 passedの後、子要素の統合Testと参照形式guardを追加して全体を再実行した。
- `ruff check .`、`ruff format --check .`（381 files）、`ty check`、OpenSpec strict、`git diff --check`: すべて成功。
- 新Module/Dependency/独自永続状態/互換分岐0件。変更した全関数とTest helperに目的説明あり。既存BaseTask・原子的保存・Docling読込みを使用し、LLM/Embedding/Docling/Word呼出しは行っていない。

検査対象SHA-256:

- `translate/tasks/position.py`: `97707ea29f9cd2f07e1901a2f2d2f3787628da4242f64c887c5bdd2cf89af152`
- `tests/test_position_layout.py`: `ecdf073fe006ca856dc36f9e77c3d662b4a5b2395dbecd5380bcf398ed31bc92`
- `tests/test_position_tables.py`: `b5e5db524c9c326017994ed60b831679874ea8731b16e62ae1d6531975df8e03`

### 保存済みsample3の前処理による補助検証

完了Run `01a0d8b6-c2ab-7c92-bed9-58403a8410b3` の`.workspace/merge/document.json`を読取り、所有する一時領域だけにPOSITION→NORMALIZE→LOADを実行した。元ArtifactのSHA-256は前後とも`989b39b390a42e5a99a94c349ab02cf18fa6f12fa7817d284b44090b4d5c70d6`。一時領域は検査終了後に解放し、元Runや成果物を変更していない。

- 入力texts 188件、消費元23件、出力texts 165件、LOAD 135 Block、warning 0件。
- 入力配列とreportの結合対応から、結合先の本文と未結合の本文を別途照合し、payload不一致0件。単にBlock件数が減っただけで欠落なしと判断していない。
- 2回目のPOSITIONは追加結合0件。texts/tables/pictures/groupsの配列は1回目と完全一致した。
- POSITION出力hash `f01932467fefdb03913f9eacd38b3092021c0f079e920b11afad8a7750c100ae`、LOAD保存hash `7a33cecba7512b7f63831415ae6326cf8db032384cd0f2dbfa00b7f1a2e8551e`。
- 過去の19結合との差は末尾断片に連続する後続も結合する処理を含む。本検査は既存中間データの再処理であり、新規TranslationやDOCX/PDF品質の合格証拠ではない。

### POSITION-ORDER-001: 再適用時の読み順変化（未解決）

同じ補助検証で2回目のPOSITIONの`body.children`順が変化し、reordered reportは1件だった。その他の上記collectionsは不変、追加結合は0件。現時点で原因を段組許容幅や特定の位置判定と断定しない。読み順アルゴリズム全体の変更は本ChangeのNon-Goalであり、検査を緩めて全体を合格とはしない。別の調査・是正計画で扱い、実受入前の残件として維持する。

タスク3.1/3.2は未完了。LLMの直近確認は過去のHTTP 500で、その後の回復はこのターンでは未確認。現在も障害中と新たに測定した訳ではない。外部接続回復確認・新規実E2E・利用者目視が必要である。

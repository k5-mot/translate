<!-- markdownlint-disable MD013 MD041 -->

# 検証記録

## 2026-09-27 計画段階

状態: 提案のみ。製品Code/Testは未変更、実装Taskは0/8。CONTENT-MERGE-001は未解決であり、実Translation・Microsoft Word PDF・Comparison Review・利用者目視を未完了に維持する。

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

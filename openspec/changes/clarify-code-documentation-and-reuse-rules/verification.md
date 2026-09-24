<!-- markdownlint-disable MD013 MD041 -->

## 中間検証（2026-09-25）

正式verifyは未完了。実translation→Microsoft WordでPDF化→reviewの順の証拠が揃うまでarchiveしない。

| 観点 | 結果 |
| --- | --- |
| Completeness | 5/10 tasks完了。2.2は実処理の完了待ち、3.1〜3.4は仕様に対する未実装・未検証事項 |
| Correctness | 汎用規約と製品固有仕様の分類を確認。製品コードの適合を意味しない |
| Coherence | 利用者の訂正に合わせてskip_specsを解除しrun-lifecycle deltaを追加。製品module、依存、保存形式は変更なし |

## 要求対応

| 利用者要求 | 管理先と対応 |
| --- | --- |
| ③-1 全関数の説明 | コメント節で非公開・特殊Method・入れ子・Testを含む。Lambdaと実行文字列も点検対象。Docstring以外の説明を排除しない |
| ③-2 導入済み機能の再実装禁止 | 単純性節で既存APIの契約比較、同等機能への委譲、差分の根拠を必須化 |
| ④ Resume二重管理禁止 | run-lifecycle deltaで一元化を要求。LangGraphへの委譲はdesign.md。CODING_RULESの再開状態節は削除 |
| ① common整理・乱雑な共通化の抑制 | 汎用的な説明責任はCODING_RULESに残し、logger/settings限定という配置制約はdesign.mdへ移管 |
| 公開入口、対応Python版、各Taskの計測 | 公開契約はrun-lifecycle delta、time.perf_counterによる実現手段はdesign.mdへ移管 |
| 製品metadata/依存/除外Pathの参考例 | CODING_RULESから除去。実際の値はpyproject.toml/uv.lock、管理方針はOpenSpec設計とし、古い例を製品要件として転記しない |

## 実施した検査

- `uv run pytest -q tests/test_documentation.py`: 3 passed。
- `git diff --check`: 指摘なし。
- `openspec validate clarify-code-documentation-and-reuse-rules --strict`: valid。skip_specsを解除したdelta追加後も再実行して合格。
- 関数説明規則は目的・非自明な制約を対象とし、既存の「自明な行の言い換え禁止」と両立する。
- 独自の再開位置管理と、入力互換性検証・Artifact入出力・副作用の冪等性を区別した。
- CODING_RULES全文を点検し、design.mdの分類表にすべての節を対応付けた。Ruff/ty/pytestなどの品質規則、汎用Package選択指針、TypeScript/Java規則は製品の動作仕様ではないため維持した。
- `rg`でLangGraph、common/、cli.py、main.py、perf_counter、3.12、製品metadataと依存名の残存を確認し、CODING_RULES内の該当0件を確認した（検索終了コード1は該当なし）。

## 未完了・既存違反

- CRITICAL: task 2.2。実translationをRun `01a0d44f-1efa-7597-9d1b-0be4c5748b85`で実行中。入力は`inputs/sample3.pdf`、出力指定は`outputs/sample3-acceptance-v2`。STRUCTUREまで完了したが、Word PDF化とComparison Reviewはまだ開始していない。
- CRITICAL: tasks 3.1〜3.4。新たに明文化した再開要求に対し、移行設計、独立状態の廃止、common整理、障害/Resume検証が未完了。規約から仕様へ移したことだけで完了にしない。
- [追加監査](../restore-docx-tables-and-indexes/coding-rules-audit.md)にある説明欠落候補474件、導入済み機能の重複、独自Resume記録は未是正。本Changeによる規約整備で解消済みにしない。
- [配置監査](../restore-docx-tables-and-indexes/architecture-audit.md)のdocument_processing/4file新設案は撤回済み。utils/redaction.pyの独立性は未承認。今回は配置を変更しない。
- 診断I/Oの間欠障害、表を含む内容検証、Run排他の指摘も本Changeで修正していない。

## 判定

実処理の証拠不足につき正式verify・archive・mainへのマージは未実施。文書検査の合格を製品の検証合格へ読み替えない。

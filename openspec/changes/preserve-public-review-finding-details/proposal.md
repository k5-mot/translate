<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

公開Review MarkdownがFindingの対象・根拠・修正方針を捨てており、利用者が問題箇所と修正理由を確認できない（[COMPARE-REPORT-001](../restore-docx-tables-and-indexes/verification.md)）。診断JSONに情報が残っていても、既存のcomparison-review要求「問題と根拠をReportする」を満たさないため、公開成果物の欠落を修正する。

## What Changes

- 決定的検査と意味Reviewの既存Finding情報を公開Markdownへ保持する。情報を補うためのLLM呼出や入力文書の修正は行わない。
- 対象IDから既存の対応一覧を辿れるようにする。空・未知のIDや任意項目の未記載を捏造せず表示する。
- MarkdownやHTMLを含む自由文も文字列として表示し、レポートの構造へ混入させない。HTMLへの中間変換機能は追加しない。
- 公開経路と描画内容の回帰Testを追加する。対応精度の別指摘COMPARE-ALIGN-001は解決済みにしない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。既存[comparison-review仕様](../../specs/comparison-review/spec.md)の「問題と根拠をReportする」「任意の英日PDFを比較できる」への実装適合を回復する。要求自体は変更しないため`skip_specs: true`とし、検証のためだけのdeltaは作成しない。

## Impact

主対象は`translate/tasks/report.py`と比較・公開出力のTest。既存の関数入口とReportTask、診断JSON schema、集計・Finding順序、CLI/UIの入口を維持する。依存追加、commonへの機能追加、LangGraph/Resume変更、入力PDFの変更はない。Markdownの表示内容は増えるが、形式を解析する非公開の独自consumerまで互換性を保証しない。

## Stakeholders and Lifecycle Impact

- 利用者・保守者: 公開Markdownだけで保存済みFindingの全項目を確認可能にする。
- 取得: 新規依存・外部サービスの取得はない。供給: Code/Test/OpenSpecを既存PR/CIで供給し、実PDF・DOCXや秘密値はコミットしない。
- 移行: 過去のレポートを自動書換えしない。新しい処理結果から修正形式を生成する。
- 運用: 翻訳→利用者操作を模したMicrosoft Word PDF出力→原文とのReviewを逐次実行する。Word PDF出力を製品機能にしない。
- 保守: 欠落再現、境界ケース、公開成果物のTestを保持する。廃止: API/Artifact/旧成果物の廃止・削除は対象外。

## Quality Considerations

- Q-FUNC（機能適合性）: CHECK/REVIEW双方の全Finding項目の公開欠落0件。任意項目がない場合は未記載と区別し、内容の生成をしない。
- Q-INT（利用時の確認容易性）: fixtureの既知対象IDを対応一覧へ100%追跡でき、未知IDは誤ったGroupへ結び付けない。実成果物も利用者に提示する。
- Q-SEC（Security）: 自由文のHTML/Markdown構造への混入0件を導入済みparserで検査する。新たに設定・Prompt・Credentialを出力しない。
- Q-REL（信頼性）/Q-COMP（互換性）: 0件表示、順序、集計、診断JSON、入力hash、既存CLI/UI/exportの出力経路を回帰検査する。
- Q-MNT（保守性）: 必要最小限の描画変更と既存API再利用を行い、新規module・依存・再開台帳を追加しない。
- 性能効率: 外部呼出の追加0件を確認する。情報量に応じたMarkdown増加は必要な修正であり、独立した速度改善は対象外。
- 柔軟性/移植性・安全性: 配置/対応環境や身体・環境への影響を変えないため、新しい適応機能・安全性要求は適用しない。

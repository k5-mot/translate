<!-- markdownlint-disable MD041 -->

## 1. REPORTの契約回復

- [ ] 1.1 CHECK/REVIEW双方のtarget_ids・evidence・suggestionを公開Markdownに求める回帰Testを追加し、現実装で欠落により失敗することを記録する（Q-FUNC）。既存tests/test_comparison_capability.pyのJSONのみの検査を補う
- [ ] 1.2 ReportTaskに全Finding項目と対応一覧のalignment/indexラベルを描画し、空/複数/未知対象、None/空文字/空白のみ、caption/cell、多対多・片側未対応のTestを成功させる。順序・集計・JSON全fieldを変更しない（Q-FUNC/Q-INT/Q-COMP）
- [ ] 1.3 自由文とIDをliteralとして描画し、導入済みMarkdown parserで複数行・CRLF・長いbacktick列・HTML・実体参照・見出し/リンクを検査する。内容保持とraw HTML token 0件を確認し、既存APIとの契約差と小さな実装に限定した理由を残す（Q-SEC/Q-MNT）

## 2. 公開経路と回帰品質

- [ ] 2.1 実REPORTで生成したMarkdownをCLI --output、UI download、共通exportへ通す統合Testを追加し、全fieldを含むbytes同一性、指摘0件表示、入力hash不変を確認する。モデル/外部通信はdoubleとし、REPORTは置換しない（Q-REL/Q-COMP）
- [ ] 2.2 Ruff check/format、ty check、pytest全体、OpenSpec strict validation、git diff --checkを実行して結果をverification.mdへ記録する。関数説明と依存再利用を点検し、新しいmodule・依存・外部要求・再開台帳がないことを差分で確認する（Q-MNT）

## 3. 実成果物での正式検証

- [ ] 3.1 既存Review session 12758の終端を確認してから、最新製品Codeでinputs/sample3.pdfを実translationする。モデル/Embeddingは逐次、設定・Code同一性・Run ID・終了状態・成果物hashを秘密/本文なしで記録する。失敗時はResume状態を保持し未完了とする
- [ ] 3.2 3.1のDOCXをMicrosoft Wordでユーザ操作を模してPDFへ出力し、両成果物のhashと実行順を記録する。表・目次・表紙・番号・改ページを確認し、Word/PDFを利用者へ提示して目視結果を記録する。PDF生成を製品仕様/依存へ追加しない
- [ ] 3.3 3.2のPDFと入力sample3.pdfを実reviewし、公開Markdownと診断JSONのFinding全項目・対応ラベルを照合する。COMPARE-ALIGN-001に由来する誤判定を区別し、全体の品質不合格をREPORT修正だけで合格に変えない。外部障害や未確認は未完了のまま記録する
- [ ] 3.4 正式verifyで要求・Code・Test・実成果物を対応付け、COMPARE-REPORT-001の解消証拠を元verification.mdへ反映する。残る指摘は保持し、当該Changeの必要条件を満たしてからarchive、PR/CI、mainへのmerge、originへのpushを行い、その結果を記録する。サンプル・成果物・.agents・無関係な差分はコミットしない

<!-- markdownlint-disable MD041 -->

## 1. 内容の列挙と検査

- [x] 1.1 document.pyに本文/caption/cellの読取viewを設け、ID・順序・結合cell・3層・Noneと空の差をTestする
- [x] 1.2 CHECK/REVIEW/VERIFYを共通列挙へ移し、cell別の欠落検出と対象ID、prompt各層、不承認時の復元をTestする
- [x] 1.3 ALIGNと比較Document生成を同じ対象IDへ対応させ、表/captionだけの文書と片側欠落をTestする

## 2. 検証

- [x] 2.1 全体pytest、対象Ruff/Format、全体tyとOpenSpec strictを実行し、DATA-001への証拠と残課題をverification.mdへ記録する
- [ ] 2.2 新実装の実translation→Microsoft WordによるPDF生成→入力PDFと生成PDFのreviewを逐次実行し、表/captionの検査対象を実Artifactで照合する
- [ ] 2.3 Word/PDFを利用者へ提示し、目視結果と未解決事項を正式verifyへ記録してarchive可否を判定する

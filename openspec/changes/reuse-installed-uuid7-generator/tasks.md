<!-- markdownlint-disable MD041 -->

## 1. 導入済み生成器への委譲

- [ ] 1.1 uuid-utilsを明示依存にし、offline lock更新でPackage集合/versionが変わらないことを確認する
- [ ] 1.2 製品とTestをcompat.uuid7へ移し、identifiers.pyを廃止して残存importと独自生成器が0件であることを確認する
- [ ] 1.3 UUID型・version・variant・canonical・時刻・一意性と既存Run操作の回帰Testを通す

## 2. 検証

- [ ] 2.1 対象Lint/Format・全体型検査・pytest・OpenSpec strictの結果をverification.mdへ記録する
- [ ] 2.2 新実装で実translation→Microsoft WordによるPDF生成→入力PDFと生成PDFのreviewを逐次実行して正式verifyする

<!-- markdownlint-disable MD041 -->

## 1. 共通計測と具体Task

- [x] 1.1 BaseTaskの計測contextを追加し、成功/失敗で1回だけ時間を出力し元例外を保持するTestを通す
- [x] 1.2 全20 ModuleへBaseTaskを継承する具体Taskを設け、既存run関数のsignatureと転送引数を全件Testする
- [x] 1.3 手書き計測20か所を除去し、MERGE/STRUCTURE/MARKDOWNの公開完了後に計測終了することをTestする

## 2. 検証と引継ぎ

- [x] 2.1 全体pytest、対象Ruff lint/format、ty、OpenSpec strictを実行し、結果と既存の未解決指摘をverification.mdへ記録する
- [x] 2.2 class化後の実translation→Microsoft WordでPDF化→入力PDFと生成PDFのreviewを逐次実行し、実行順と成果物の証拠を記録する
- [ ] 2.3 Word/PDFを利用者へ提示して目視結果を記録し、既存入口・データを保持したことと旧重複計測の廃止を正式verifyする

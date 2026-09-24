<!-- markdownlint-disable MD041 -->

## 1. 規約の明文化

- [ ] 1.1 CODING_RULES.mdへ関数説明の対象・必要内容・lambda/実行文字列の扱いを記載し、③-1との対応を確認する
- [ ] 1.2 同等の導入済みAPI再利用と契約差の説明規則を具体化し、③-2および既存の最小実装規則と矛盾しないことを確認する
- [ ] 1.3 checkpointを唯一の再開正本とする規則と新規共通化の説明責任を追加し、④とcommon承認範囲に対応することを確認する

## 2. 検証と引継ぎ

- [ ] 2.1 git diff --check、tests/test_documentation.py、OpenSpec strict validationを実行し、文書の要求対応表と既存違反が未解決であることをverification.mdへ記録する
- [ ] 2.2 利用者指定の実translation→Microsoft WordでPDF化→reviewの証拠を確認し、実行順・成果物・残課題を記録して正式verifyを行う

<!-- markdownlint-disable MD041 -->

## 1. 規約の明文化

- [x] 1.1 CODING_RULES.mdへ関数説明の対象・必要内容・lambda/実行文字列の扱いを記載し、③-1との対応を確認する
- [x] 1.2 同等の導入済みAPI再利用と契約差の説明規則を具体化し、③-2および既存の最小実装規則と矛盾しないことを確認する
- [x] 1.3 汎用的な共通化の説明責任だけをCODING_RULESに残し、④の再開要求をrun-lifecycleのdelta、LangGraphへの委譲とcommon配置制約をdesign.mdへ移す
- [x] 1.4 CODING_RULES全体を分類し、対応Python版・公開entry point・Task計測をOpenSpecへ移管し、製品固有の設定例を実設定とOpenSpec設計へ整理する

## 2. 検証と引継ぎ

- [x] 2.1 git diff --check、tests/test_documentation.py、OpenSpec strict validationを実行し、文書の要求対応表と既存違反が未解決であることをverification.mdへ記録する
- [ ] 2.2 利用者指定の実translation→Microsoft WordでPDF化→reviewの証拠を確認し、実行順・成果物・残課題を記録して正式verifyを行う

## 3. 明文化した仕様に対する未実装事項

- [ ] 3.1 GraphStateの独自完了一覧、WorkflowProgressの再集計、RunRecord.status/last_taskの利用を棚卸しし、register/convertを含む新構成のみの設計を確定する。2026-09-27承認に従い、旧形式loader/Resume、移行機能、互換分岐、旧実装を残さない。削除対象未指定の既存利用者データは無断削除しない
- [ ] 3.2 再開位置・完了履歴・進捗表示をLangGraphの正本へ統合し、STRUCTURE Page/REVIEW Chunkの独自再開記録を既存の再開粒度を失わず置き換える
- [ ] 3.3 commonのlogger/settings以外を、具体的な利用元と責務を説明して確定した配置へ整理し、不要な機能を廃止する（未承認の4file新設案を採用しない）
- [ ] 3.4 障害注入、公開直後の中断、CLI/UI相互Resumeと副作用の重複防止を検証し、deltaの全Scenarioに実装証拠を対応付ける

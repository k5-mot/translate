<!-- markdownlint-disable MD041 -->

## 1. 説明の是正

- [ ] 1.1 公開入口とTaskの全関数を確認し、非公開・入れ子を含む目的説明を補い、説明以外のAST不変を確認する
- [ ] 1.2 Workflowの全関数を確認し、node接続・入出力・副作用の説明を補い、説明以外のAST不変を確認する
- [ ] 1.3 adapter/commonの全関数を確認し、目的・境界・失敗条件を説明して、未承認配置や二重状態を正当化していないことを確認する
- [ ] 1.4 全Testのfixture・double・入れ子・特殊methodを含め目的説明を補い、既存Testの意味と実行ロジックを維持する
- [ ] 1.5 lambda、実行Python文字列、未追跡probeを別途確認し、説明不足・不明な意図を0件にした証拠を記録する

## 2. 再発防止と検証

- [ ] 2.1 既存文書Testへ規約固有の説明存在検査とfixtureを追加し、全対象に欠落がないこと、標準parserへの委譲を確認する
- [ ] 2.2 全体Lint/Format/ty/pytest、strict validation、説明除去後のAST比較を実行し、対象一覧・Ruffとの契約差・意味確認をverification.mdへ記録する
- [ ] 2.3 実translation→Microsoft Word PDF化→reviewと利用者目視の証拠を対応付け、正式verifyとarchive可否を判定する

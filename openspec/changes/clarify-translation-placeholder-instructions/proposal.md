<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

推論OFFの実翻訳が第2ページで保護記号2件を欠落し、同じ指示による3試行とも停止した（[TRANSLATE-PROTECTED-OFF-001](../configure-verification-reasoning-policy/verification.md)）。現行の翻訳ルールには保護記号の保持方法が明記されておらず、既存の保護対象保持要求をLLMへの指示にも反映する必要がある。

## What Changes

- 既存の翻訳ルールに、targetの各IDに属する保護記号を同じIDの訳文へ、そのまま・過不足なく残す指示を追加する。
- 前後文脈と参照情報を翻訳対象から区別し、target全件の非空訳文を返す既存契約を明確にする。
- 配布ルールを実際に読み込むTestで、通常・retry・切断後分割の要求へ同じ指示が届くことと、欠落応答を依然拒否することを確認する。
- 推論OFFの新規sample3翻訳、Microsoft WordによるPDF化、原本とのReviewを逐次実施し、実成果物で判定する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。既存[pdf-translation](../../specs/pdf-translation/spec.md)の「文書構造と保護対象を保持する」「翻訳Backendを選択できる」を満たすための実装指示修正で、Spec Levelの契約は変えない。`skip_specs: true`を使用し、重複Deltaは作らない。既存[protect-all-translation-chunks](../protect-all-translation-chunks/specs/pdf-translation/spec.md)の保護・有限retry契約も弱めない。

## Impact

- 対象は`translate/templates/translation-rules.md`と既存の翻訳・fingerprint関連Test、検証記録。新規Module・Dependency・公開引数は不要。
- 復元・検証条件、retry回数、切断分割上限、逐次実行、通常の推論既定値は変更しない。
- ルールhashは既存の公開fingerprintとWorkflow識別へ反映される。変更前のRunをResumeせず、新規Runで検証する。旧入力・Checkpoint・成果物は保持する。
- ALIGN、表内画像、common整理等は別の未解決事項として残し、本Changeの成功で全体を合格にしない。

## Stakeholders and Lifecycle Impact

- 取得: 新規サービス・依存の取得は不要。既存ローカルLLMとWordを使用する。
- 供給: 修正ルールとTestを供給し、利用者に実DOCX/PDFを提示する。サンプル・生成物はコミットしない。
- 移行・運用: 検証プロセス限定OFFと未使用出力先を用いる。設定変更を無視するResumeや自動削除は行わない。
- 保守: 欠落・重複・未知記号・別IDへの移動の拒否を回帰検査し、原文や生応答を証跡へ転記しない。
- 廃止: 機能の廃止はない。Rollback時も旧Runを保持し、異なるルールの成果物を混用しない。

## Quality Considerations

- Q-FUNC: 配布指示の到達、全対象IDの訳と保護値の復元を自動Testと実成果物で確認する。指示文字列の存在だけを翻訳成功としない。
- Q-REL: 欠落等の不正応答は有限retry後に失敗し、公開成果物を出さず再開状態を保持する。
- Q-PERF: 新たな要求・再試行ループ・並列処理を加えない。実検証の所要時間と取得可能なtoken使用量を記録する。
- Q-COMP: 通常/OFFの両方で指示を適用し、ルール変更の非互換性とQdrant状態の非関与を維持する。
- Q-SEC: Testは合成データを用い、実証跡には本文・保護値・認証値・生応答を含めない。
- Q-USE: 利用手順は既存のまま。利用者目視の未確認を明示する。
- Q-MAINT/Q-PORT: 既存Rule loaderとTaskを再利用し、pytest・Ruff・tyで回帰を確認する。新たなOS固有製品処理は追加しない。
- Safety: 物理安全性に関わる新機能は対象外。誤った復元値を自動補完して公開しないことはQ-FUNC/Q-RELで検査する。

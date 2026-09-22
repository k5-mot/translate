<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

完了扱いの`resolve-translate-contract-verification-gaps`を現行worktreeで再検証すると、全pytestの比較Review・読取り不能な訳文PDFのcaseだけが`SOURCE-SPLIT`／対象なしとして失敗する。同caseは単独では通るため、公開Lifecycleの失敗帰属と検証Evidenceを安定させないままarchiveできない。

## What Changes

- 全suiteで再現する条件を小さなTestへ縮約し、失敗が入力検証、比較WorkflowのTask通知、Run metadata保存またはTest間の状態干渉のどこで発生するかを特定する。
- 確認した原因だけを修正し、英語側・日本語側のTask名と入力roleを実際に失敗したTaskへ一致させる。誤った直前Taskへのfallback記録を受入れない。
- 比較Workflowの逐次実行、有限retry、既完了TaskのResume、redactionおよびAtomic Artifactを維持し、単独・順序依存・全suiteの回帰Testで確認する。
- 公開CLI option、Failure schema、Run fingerprint、成果物形式、Model設定およびDependencyは変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`establish-translate-ja-contracts`の`comparison-review`には無効な入力PDFの対象を特定する契約、`run-lifecycle`には失敗Task／対象の安全な表示契約が既にある。本Changeはその実装と検証の不安定さを修正するだけなので、delta Specを作成しない。

## Impact

- 対象: `translate/workflows/comparison_review.py`、`translate/common/lifecycle.py`、必要と確認された境界のTest。
- Evidence: `tests/test_invalid_pdf_lifecycle.py`の順序依存失敗、`resolve-translate-contract-verification-gaps`のarchive再判定。
- 新しい外部Service、Package、Data migrationおよび公開interface変更はない。

## Stakeholders and Lifecycle Impact

- 利用者・運用・Support: 読取り不能な英日PDFを取り違えず、Run一覧と公開Errorに正しい失敗Task／roleを表示する。raw例外と文書本文は出さない。
- 取得・供給: 既存LangGraph、Pydantic、pypdfium2、pytestだけを使用し、Dependencyを増やさない。
- 移行: 旧Failureの読取り、既存Runとcheckpointを保持する。metadata一括書換えはしない。
- 保守: 再現条件と原因をTestへ固定し、検証結果が過去のPASS記録と異なる点を明示する。
- 廃止: Run、外部exportおよびQdrant Collectionを削除しない。本件で廃止操作は不要。

## Quality Considerations

- Q-FUNC／Q-USE: 英語側・日本語側の失敗注入で、Task名と`target_id`が期待roleに一致し、誤帰属0件となることを公開Lifecycle Testで確認する。
- Q-REL／Q-COMP: 単独、先行Testを含む順序、全pytestで同じ結果を得る。成功済みTask再実行0件、旧Failure読取り、途中成果物0件を確認する。
- Q-PERF: 比較Workflowの同時Model／Embedding request最大1件を維持し、新たな再試行または重い外部呼出しを増やさない。
- Q-SEC: Credential、endpoint、文書本文、raw response、tracebackおよび画像binaryのFailure／log漏えい0件をsentinel Testで確認する。
- Q-MAIN／Q-PORT: Ruff、Format、ty、全pytest、OpenSpec strict validationをWindowsで通し、POSIX固有処理を導入しない。
- Interaction capability以外のSafetyとFlexibilityは外部Action・拡張点を追加しないため新規評価対象外とする。

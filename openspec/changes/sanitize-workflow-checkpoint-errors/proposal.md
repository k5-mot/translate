<!-- markdownlint-disable MD013 MD041 -->

## Why

[SECURITY-CHECKPOINT-001](../clarify-code-documentation-and-reuse-rules/verification.md)で、Task例外に含まれる本文が公開診断では除外されても、LangGraphのSQLite `__error__`へ保存されることを確認した。既存の秘密・本文非保存契約を満たすため、再開機構を作り直さず保存境界を修正する。

## What Changes

- TranslationとComparison Reviewが使用するCheckpointの例外保存だけを、本文を含まない固定分類へ制限する。
- 導入済みSqliteSaverの公開serializer差し替え口を使い、通常の保存・復元・完了履歴・ResumeはLangGraphへ委譲する。
- 元の例外型、既存retry、公開FailureのTask・対象・許可済み診断値を維持する。例外を一律RuntimeErrorへ置換して制御を変えない。
- 実Workflowの失敗経路、別接続からのResume、独自reprと例外chainを含む非保存Testを追加する。既存の正常stateだけのTestを失敗時の安全性の証拠に使わない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。[run-lifecycle](../../specs/run-lifecycle/spec.md)の「Run情報から秘密と本文を保護する」「Task単位のCheckpointを保持する」は既にこの振る舞いを要求している。要求変更ではなく実装の契約違反を直すため、`skip_specs: true`とする。

## Impact

新設候補は`translate/adapters/checkpoint.py`一つ。実利用元は既存の`translation.py`と`comparison_review.py`で、現在両方が既定serializerのSqliteSaverを直接生成している。新moduleは既存Libraryの保存境界に対する製品固有の例外非保存方針に限定し、汎用実行wrapper、serializer全体、独立状態管理は実装しない。`common/`・公開CLI/UI・依存Package・保存layout・fingerprintは変更しない。Testは既存Workflow/Failure/Checkpoint検査を拡張する。

## Stakeholders and Lifecycle Impact

- 運用者: 修正後の失敗でも本文をCheckpointへ残さず、従来の安全な公開診断とResumeを利用できる。
- 保守者: Checkpoint内Errorは本文でなく固定分類となる。詳細は既存の許可済みFailure診断を参照する。
- 移行: DB schemaと通常値のserializationを維持する。既存UUIDv7や旧layoutの移行方針は確定しない。過去に保存された行を勝手に書換え・削除せず、過去分も浄化済みとは報告しない。
- 取得・供給: 新しいDependency・外部Serviceは不要。廃止: 利用者データの削除は対象外。

## Quality Considerations

- Q-SEC: 合成の秘密・本文・binary markerが修正後の例外保存行、DB/WAL、再読込したsnapshot、公開診断へ現れる件数0。既存のstate/metadataの非保存制約は弱めない。
- Q-REL/Q-FUNC/Q-COMP: 同一入力の障害後、失敗Taskだけが再実行され、成功済みTask再実行と新たな副作用重複0。例外型・有限retry回数・制御例外の意味を維持する。
- Q-MNT: LibraryのSQL・serializer・再開アルゴリズムを複製せず、commonの責務を増やさない。新規関数の目的説明と既存APIへ委譲する根拠を確認する。
- 正式verifyは修正を読み込んだprocessで実translation→Microsoft Wordによる手動相当PDF変換→原文PDFとのComparison Reviewを逐次実行し、Word/PDFを利用者へ提示する。実行中の旧process結果を新実装の証拠にしない。
- 速度改善・UI変更・新環境への移植は対象外のため、性能/操作性/移植性の新たな製品要求は追加しない。既存品質Gateは維持する。

<!-- markdownlint-disable MD013 MD041 -->

## 1. Safe output-failure contract

- [x] 1.1 `TranslationOutputError` と `TranslationIdMismatch`／`ProtectedFragmentMissing` の固定属性（`text-parse`、page、safe target）を実装し、例外へ本文・prompt・raw response・fragment 値を入れないことを Unit Test で確認する（ISO/IEC 25010 Security／Maintainability）
- [x] 1.2 翻訳 Task の ID集合検証と protected fragment 検証を共通の安全な validation helper へ移し、検証成功時だけ mapping を返すことを Test で確認する
- [x] 1.3 Lifecycle／Terminal Evidence の stage allow-list と Failure mapping が固定 cause、page、chunk を保持し、既存の redaction／Run schema を変更しないことを Regression Test で確認する

## 2. Finite sequential retry

- [x] 2.1 応答形状の検証失敗を既存 `settings.retry_attempts` の範囲で同一 chunk にだけ逐次 retry し、parallel Model／Embedding request を追加しないことを Test で確認する
- [x] 2.2 ID不一致が retry 内で回復した場合に後続 Task へ進み、部分 mapping／partial artifact を公開しないことを Integration Test で確認する
- [x] 2.3 ID不一致または protected fragment 欠落が exhaustion した場合に `TRANSLATE` を停止し、Resume 可能 Failure／checkpoint を保持することを Test で確認する
- [x] 2.4 retry 回数、backoff、既存の外部障害処理が回帰していないことを既存 LLM／workflow test suite で確認する

## 3. Security and diagnostics evidence

- [x] 3.1 failure、run metadata、log、Terminal Evidence に raw response、prompt、本文、endpoint、credential が出ないことを negative assertion で確認する
- [x] 3.2 `failure.json` と terminal evidence の status、task、stage、cause、page／target、heartbeat が公開 Resume 判定に必要な allow-list を満たすことを Test で確認する
- [ ] 3.3 既存 Run／fingerprint／Qdrant state／CLI／Streamlit contract と UUIDv7 validation の回帰 Test を実行し、変更がないことを記録する

## 4. Detached historical Gate

- [ ] 4.1 正本 UUIDv7 Run の一時 clone を使い、実Modelで同一 detached Gate を逐次実行して、成功または固定 cause の terminal Failure を外部 Evidence に保存する（ISO/IEC/IEEE 12207 Verification）
- [ ] 4.2 Gate 中に正本 SQLite の SHA-256 が変化せず、終了後に detached temp root が削除され、Evidence が terminal であることを確認する
- [ ] 4.3 Gate が成功し Evidence が公開 Resume を許可する場合のみ、同じ Run を明示 Resume して後続成果物と checkpoint を確認する。失敗／不確定時は Resume を行わず記録する
- [ ] 4.4 Gate 結果、source hash、Evidence path、cleanup、公開 Resume 判定を `verification.md` に記録し、OpenSpec 変更へ安全な JSON だけを追加する

## 5. Quality gate and handoff

- [ ] 5.1 変更対象の `pytest`、Ruff、format、ty を実行し、全結果と未解決警告を記録する
- [ ] 5.2 strict OpenSpec validation と artifact status を実行し、spec／design／tasks の整合性を確認する
- [ ] 5.3 tasks、verification、implementation の差分をレビューし、`.agents`、user-owned dirty files、秘密、raw PDF／LLM本文を commit 対象に含めないことを確認する
- [ ] 5.4 すべての実装・検証が完了したときだけ Change を archive し、archive 後の status と git diff を確認する

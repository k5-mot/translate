<!-- markdownlint-disable MD013 MD041 -->

## Context

`translate/tasks/translate.py` は Model 応答の ID 集合と protected fragment を検証するが、現在の検証失敗は一般の `ValueError` であり、Lifecycle が安全な `stage`、`cause_type`、page、chunk を抽出できない。LLM 呼出し自体の retry とは別に、応答形状を検査する境界にも有限 retry が必要である。Model と Embedding はローカルで逐次実行するという既存制約を保つ。

## Goals / Non-Goals

**Goals:**

- 応答検証失敗を固定された安全な例外型へ変換し、既存 Failure／Terminal Evidence に page、chunk、stage、cause を渡す。
- 同一 chunk の検証だけを既存設定回数まで逐次再実行し、成功時は既存の atomic artifact／checkpoint 境界を越えて後続処理へ進める。
- 上限到達時は裸の本文や raw response を保存せず、Resume 可能な停止として扱う。
- Unit、Lifecycle、detached Gate の証拠で ISO/IEC 25010 の reliability、security、maintainability と ISO/IEC/IEEE 12207 の verification／operation を確認する。

**Non-Goals:**

- 新しい retry 設定、外部 dependency、並列実行、Run schema、fingerprint、Qdrant 連携、CLI／Streamlit API の追加や変更。
- Model の prompt、翻訳品質、Token budget の再設計。
- 失敗した historical Gate に対する公開 Resume の強制実行。

## Decisions

1. `TranslationOutputError` を `ValueError` のサブクラスとして翻訳 Task 内に定義し、`cause_type` を `TranslationIdMismatch` または `ProtectedFragmentMissing`、`stage` を `text-parse`、`page` と安全な `target_id`（例: `page-8-chunk-2`）に限定する。例外メッセージと属性へ本文、prompt、raw response、missing fragment の値を入れない。既存の `TaskStatusEvent`／`FailureRecord` の属性コピーを利用するため、Lifecycle の公開契約を増やさない。

2. 応答取得と検証を同一 chunk の小さな境界にまとめ、検証に成功した mapping のみを返す。`settings.retry_attempts` を上限とし、各試行は前回の不完全な mapping を破棄する。検証以外の既存例外処理と backoff は既存実装へ委譲し、並列化は行わない。

3. `text-parse` を terminal diagnostics の許可 stage に追加し、固定 cause と target を既存の `evidence_from_failure` へ渡す。Terminal Evidence は既存の allow-list と redact 方針を保ち、raw LLM 応答を保存しない。

4. 検証テストは deterministic な `structured` stub を使い、(a) mismatch 後に成功、(b) mismatch exhaustion、(c) protected fragment 欠落、(d) raw 内容が error／failure／evidence に現れないことを確認する。実 Model はテストで偽装せず、別の detached historical Gate で一度だけ観測する。

5. detached Gate は UUIDv7 正本 Run を一時 clone へコピーして実行し、正本 SQLite の SHA-256 が不変、Terminal Evidence が確定、temp root が削除されることを記録する。Gate が失敗または Evidence が不確定なら公開 Resume を呼び出さず、次の診断 Change を提案する。

## Quality Attribute Design

| ISO/IEC 25010 | Design approach | Trade-off | Evidence |
| --- | --- | --- | --- |
| Reliability / recoverability | 同一 chunk の有限 retry と Resume 可能 Failure | 一時的に同じ Model request が増える | retry Unit、Lifecycle Test、detached Evidence |
| Security / confidentiality | 固定 cause と安全な識別子だけを exception／metadata へ渡す | 詳細な Model 応答は診断できない | raw 内容の非存在 assertion、Ruff／pytest |
| Maintainability / analyzability | `stage`、cause、page、chunk の共通属性を再利用 | 既存 diagnostics の allow-list を更新する必要 | Failure mapping Test、verification.md |
| Compatibility | Run layout、fingerprint、Qdrant、公開 API を変更しない | 旧裸 ValueError の詳細は復元しない | regression suite、strict validation |

## Lifecycle, Migration and Operations

- Transition: 実装前後で永続 schema migration は不要。旧 Run の裸 `ValueError` は既存 fallback で読み込み、新規失敗だけ固定分類する。
- Operation: Failure の `task=TRANSLATE`、page、target、cause、stage を確認し、Resume は CLI の明示 `--resume` または Streamlit の Run 選択からのみ行う。
- Support/Maintenance: retry 上限は既存 Settings を一元利用し、diagnostic allow-list とテストを同じ変更で保守する。
- Verification/Validation: synthetic tests と detached Gate の JSON、source hash、cleanup 結果を `verification.md` に記録する。公開 Resume は terminal evidence が `allows_public_resume` のときだけ実施する。
- Disposal: detached temp root と一時 artifact は終了時に削除し、外部 export と正本 Run は削除しない。

## Risks / Trade-offs

- [Risk] Model が恒久的に不正形状を返すと、有限 retry 分だけ処理時間が増える → 既存 retry 上限を共有し、各試行を逐次実行して上限を明示する。
- [Risk] 固定 cause だけでは原因調査が粗い → page、chunk、stage と安全な counter／checkpoint を併記し、本文は保存しない。
- [Risk] 大規模 PDF の Gate が長時間化する → detached process と heartbeat、temp clone、source hash を使い、Evidence 未確定時は Resume しない。

## Migration Plan

1. Change の Unit／Lifecycle tests を通過させる。
2. 同じ UUIDv7 正本 Run の clone で detached Gate を実行し、Evidence と source hash を保存する。
3. Gate 成功かつ Evidence が公開 Resume を許可する場合のみ、運用手順に従い同じ Run を明示 Resume する。失敗時は clone を廃棄し、正本を変更しない。
4. Rollback は新コードを revert するだけで、永続データ migration はない。


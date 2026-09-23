<!-- markdownlint-disable MD013 MD041 -->

## Context

前Changeのdetached Gateで、ローカルLLMの長い生成が既定300秒request timeoutに到達した。Settingsは環境変数で上書き可能で、LLM adapterは同じ値をChatOpenAIへ渡している。Model／EmbeddingはローカルHW制約のため逐次実行する。

## Goals / Non-Goals

**Goals:**

- 既定request timeoutを30分（1,800秒）へ延長し、長いローカル生成を許容する。
- 正の有限値検証、環境変数上書き、retry／task deadline、timeout Failureの安全な診断を維持する。
- 実Model Gateでtimeout解消またはterminal Failureを観測し、正本Run不変を確認する。

**Non-Goals:**

- 無制限timeout、並列実行、Model／prompt／token budget、外部dependency、永続schemaの変更。
- timeoutしたRunの自動Resumeや、Qdrant状態をfingerprintへ追加すること。

## Decisions

1. 既定値を`Settings.request_timeout_seconds`と環境変数fallbackの双方で1,800秒にする。既存の`_positive_float`検証を再利用し、ユーザー指定値を尊重する。既定値を長くすることでローカルModelの生成余地を増やす一方、task deadline 21,600秒と有限retryを上限として無制限化を防ぐ。
2. `ChatOpenAI(timeout=settings.request_timeout_seconds)`という既存経路を維持し、新しいHTTP clientや依存を導入しない。
3. `LLMError`のinvoke stageと例外型identifierだけをLifecycle／Terminal Evidenceへ渡す。Error本文、prompt、endpoint、credentialは保存しない。
4. synthetic timeout testではstubが`OpenAITimeoutError`相当の安全な例外を返し、settings／Failure／Evidenceの値だけを検証する。実Model Gateは別プローブで一度実施する。

## Quality Attribute Design

| ISO/IEC 25010 | Approach | Trade-off | Evidence |
| --- | --- | --- | --- |
| Reliability | 1,800秒の有限request timeout＋既存retry／deadline | 失敗検知が遅くなる | settings／adapter／Gate evidence |
| Maintainability | 既存Settingsとadapter経路を再利用 | default変更の回帰確認が必要 | pytest、strict validation |
| Security | 固定stage／causeのみ保存 | timeout詳細の粒度は限定 | Failure／Evidence negative test |

## Lifecycle, Migration and Operations

- Transition: 永続データmigrationなし。既存Runは新設定とfingerprintが互換でない場合、既存Resume判定に従う。
- Operation: 長い生成を待ち、timeout時はFailureのstage／causeを確認して明示Resumeする。
- Verification: synthetic Testと同一UUIDv7正本Run cloneのdetached Gateを記録する。Evidence未確定／failedなら公開Resumeしない。
- Disposal: detached temp rootだけをmarker検証後に削除し、正本Run／外部exportは保持する。

## Risks / Trade-offs

- [Risk] timeout延長で障害検知が遅延する → task deadlineとfinite retryを維持し、Evidence heartbeatを監視する。
- [Risk] 利用者の設定が過大になる → 正の有限値だけを受け付け、運用文書で推奨値を示す。

## Migration Plan

1. settings／adapter／Failure Testを通過させる。
2. detached Gateを同じ正本Run cloneで実行し、source hash、Evidence、cleanupを記録する。
3. Evidenceがcompletedかつ公開Resume許可の場合だけ、同じRunを明示Resumeする。失敗時はResumeしない。
4. Rollbackは既定値のrevertであり、schema migrationは不要。

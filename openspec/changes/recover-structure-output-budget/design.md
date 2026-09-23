<!-- markdownlint-disable MD041 -->

## Context

実装は、STRUCTUREのVision応答が失敗した場合にTextへ一度だけ逐次fallbackし、Text応答を`json-schema` modeで取得している。実PDF GateではこのText requestが16,384 output tokensを使い切り、既存の安全な`output-truncated` Failureへ到達した。入力とRun fingerprintは正しく、問題はローカルModelがjson-schema拘束下で応答を収束できない場合の最終経路がないことである。詳細な動機と受入れ境界はproposal.mdおよびspecs/pdf-translation/spec.mdを参照する。

## Goals / Non-Goals

**Goals:**

- Vision→Textの既存逐次fallbackを維持したまま、Text `output-truncated`だけを対象にprompt形式のstructured outputを最大1回試行する。
- 完全なPydantic応答だけを採用し、partial responseとraw本文を捨てる。
- 同一Run fingerprint、checkpoint、入力copyおよび公開Artifactのatomic境界を維持する。
- fallbackの呼出し回数、mode、stageおよび失敗時diagnosticsをunit／integration testで検証する。

**Non-Goals:**

- token context／outputのfingerprint値、無制限出力、並列LLM request、prompt本文への原文保存。
- 全LLM taskへのfallback拡張、Vision画像の再送回数増加、外部依存の追加。
- 既存Run metadataやcheckpointの移行、Qdrant revisionの判定。

## Decisions

1. **Text truncationだけをprompt modeへ切り替える。** Visionの失敗は既存どおりText json-schemaへ切り替える。Text側で`failure_kind=output-truncated`かつ`stage=text-output`の場合だけ、同じsystem/user入力を`schema_mode="prompt"`で一度だけ再要求する。これによりjson-schemaを解釈しないローカルProviderでもPydantic format instructionsを利用できる。
2. **fallbackは`structure.py`のpage境界で制御する。** Adapter全体のretry policyを変えるとTranslation／Reviewの再試行契約を壊すため、STRUCTURE pageだけで最終fallbackを明示する。既存の`LLMError`を再利用し、fallbackが失敗した場合は最後の安全なdiagnosticsを`StructurePageError`へ渡す。
3. **fingerprintを変更しない。** prompt modeは回復専用の実行経路であり、保存設定や成果物の意味を変えない。page checkpoint keyは既存の主経路設定を保持し、fallback成功後だけ同じkeyでatomicに保存する。これにより失敗Runを明示Resumeできる。
4. **成功判定はparse完了後だけにする。** `structured`がPydantic objectを返した場合のみ`_apply`、page JSON、auditおよびcheckpointを公開する。文字列、partial JSON、例外は公開せず、既存の一時directory cleanupに委譲する。

### Considered alternatives

- **最大output tokenをfingerprintごと増やす:** 旧Runとの互換性を失い、context内入力予算も減るため採用しない。
- **同じjson-schema requestをretryする:** v4で同一予算が枯渇しており回復根拠がなく、時間だけを消費するため採用しない。
- **STRUCTUREをLLMなしで常にno-opにする:** 見出し、code、captionの補正契約を失うため採用しない。

## Quality Attribute Design

- **Q-REL:** fallbackはText truncation後の最大1回、同時requestは1件以下、task deadline／request timeoutを共有する。Evidenceはcalls、mode、stageおよび終端statusで検証する。
- **Q-FUNC:** 完全なPydantic responseのみを適用し、成功時にpage artifactとcheckpointが存在することをmock testと実PDF Gateで確認する。
- **Q-COMP:** 主fingerprintとRun IDを変えず、保存済みpageを再利用し、失敗pageからResumeできることをLifecycle testで確認する。
- **Q-SEC:** raw response、prompt、本文、画像binaryおよびcredentialを例外・terminal evidenceへ渡さない。既存redaction assertionを維持する。

## Lifecycle, Migration and Operations

移行処理は不要である。デプロイ後の新しいSTRUCTURE実行と、同一fingerprintの失敗Runに対する明示Resumeだけが新経路を利用する。fallbackでも失敗したRunは`output-truncated`として保持し、入力copy、checkpointおよび外部export済み成果物を削除しない。運用者はterminal evidenceのstage、failure kindおよびtoken usageだけを参照する。

## Risks / Trade-offs

- [Risk] prompt modeでもModelがschemaを返さず失敗する → Pydantic parseを通過条件にし、既存の安全なResume可能Failureへ戻す。
- [Risk] fallbackにより実行時間が増える → 最大1回、逐次、同じ有限timeoutとtask deadlineを使用する。
- [Risk] fallback応答の意味が主経路と異なる → schema適合と既存`_apply`／保護対象検査を成功条件にする。

## Migration Plan

コードとtestを同一Changeで適用し、focused test、全pytest、strict validation後に実PDF detached Gateを実行する。Gate成功後、同じrun IDを明示Resumeして完了済みTask再利用とsource SQLite不変を確認する。fallback不成立時のrollbackは変更前コードへ戻すだけで、Run directoryやmetadataは変更しない。

## Open Questions

なし。fallback mode、回数、Resume境界およびfailure契約は本Designで確定している。

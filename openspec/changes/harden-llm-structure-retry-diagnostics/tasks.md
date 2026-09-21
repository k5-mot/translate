<!-- markdownlint-disable MD041 -->

## 1. Retry・診断契約の回帰Test

- [x] 1.1 LLM Adapterについて、`invoke`境界の一時的な`TypeError`と通信例外、および応答正規化・構造化parse境界の許可済み例外が有限回retry後に成功するCaseと、上限到達時に失敗するCaseを追加する。試行回数、backoff呼出し、既存上限、逐次実行および最終例外の安全なstage／cause typeを検証する（Q-REL、Q-PERF、Q-SEC）
- [x] 1.2 永続的なHTTP 4xx、Model／Client設定、prompt構築、TaskまたはApplication Code内の`TypeError`がretryされず即時失敗するCaseを追加し、広すぎる`TypeError`捕捉を防ぐ（Q-REL、Q-MAIN）
- [x] 1.3 STRUCTUREについて、Vision経路の有限retry失敗後にText経路へfallbackするCaseと、最終Text経路も失敗したときにpage、安定target ID `page/<n>`、stageおよびcause typeを通知するCaseを追加する。失敗時に途中Artifactを公開せず、prompt、raw応答および秘密値をEvent／Logへ含めないことを検証する（Q-FUNC、Q-REL、Q-SEC）
- [x] 1.4 Workflow／Lifecycleについて、`TaskStatusEvent`から`failure.json`、`run.log`およびCLI表示までstage／cause typeが保持されるCaseを追加する。既存Failure JSONの読取りとReference Registrationのstage診断を壊さないことも回帰Testで固定する（Q-REL、Q-COMP、Support Evidence）

## 2. LLM境界の有限Retry実装

- [x] 2.1 `translate/adapters/llm.py`へ、allowlist済みのstageとcause typeだけを公開する安全なLLM失敗表現を追加し、例外message、prompt、raw Model応答およびProvider固有識別子を上位層へ伝播しない（Q-SEC、Q-MAIN）
- [x] 2.2 1回の試行をClient `invoke`、応答内容の正規化およびPydantic構造化parseまでの境界として実装し、通信Error、408／429／5xx、境界内の一時的`TypeError`およびallowlist済みparse／validation Errorだけを既存の回数・backoff・期限でretryする（Q-REL、Q-PERF）
- [x] 2.3 永続的4xx、初期化／設定Error、prompt構築ErrorおよびLLM境界外のProgramming Errorをretry対象外に保ち、Model、Embedding、page、groupおよびWorkflowの処理をすべて逐次実行のままとする。新規Dependencyと公開CLI optionを追加しない（Q-COMP、Q-PERF、供給Evidence）

## 3. STRUCTUREからLifecycleまでの診断伝播

- [x] 3.1 STRUCTUREのpage単位処理へ診断wrapperを設け、VisionからTextへの既存fallbackを維持しつつ、最終失敗へpage、`page/<n>`、Vision／Textとinvoke／parseを組み合わせたstage、およびcause typeを付与する（Q-FUNC、Q-REL）
- [x] 3.2 `TaskStatusEvent`とWorkflowのfailed statusへoptionalなstage／cause typeを追加し、値がない既存Taskを互換に保つ。診断値は固定allowlistへ正規化し、任意の外部messageを保存しない（Q-COMP、Q-SEC）
- [x] 3.3 LifecycleでTask failure metadataを中央集約して`failure.json`とsafe logへ永続化し、Reference Registration固有の既存診断と旧形式Runの読取りを維持する（Q-REL、Q-COMP、Support Evidence）

## 4. 自動検証とSecurity確認

- [x] 4.1 追加したLLM、STRUCTURE、WorkflowおよびLifecycleのfocused Testを実行し、成功、retry上限、即時失敗、fallback、診断伝播および逐次実行の全CaseをPASSさせる（Q-FUNC、Q-REL）
- [x] 4.2 `uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`、`uv run pytest`および`npx --yes @fission-ai/openspec validate harden-llm-structure-retry-diagnostics --strict`を実行し、各command、exit code、Test件数および既知skipを`verification.md`へ記録する（Q-MAIN、保守Evidence）
- [x] 4.3 差分、Test出力、console、Run logおよびFailure Artifactをscanし、Credential、prompt、文書全文、raw LLM応答、Provider固有識別子および画像binaryの漏えい0件、新規Dependency 0件、並行実行導入0件を記録する（Q-SEC、Q-COMP、供給Evidence）

## 5. 同一Runの明示Resume検証

- [x] 5.1 Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`について、入力identity、設定fingerprint `4b41528d1e8b2af06b8154aeaf111f12f525e36d95888d5d2d7ba20bed366265`、STRUCTURE失敗状態、専用Qdrant Collection `translate-acceptance-sample-pdf`、外部export先、およびSPLITからLOADまでのfile数・SHA-256・mtime baselineをread-onlyで再確認する。他のModel／Embedding／Workflow processが0件であることも確認し、事前snapshotを`verification.md`へ記録する（Q-REL、Q-PERF、運用Evidence）
- [x] 5.2 公開CLIの明示的な`--resume 01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`を使用し、同じ入力、backend、Collectionおよび外部export先で同時実行数1のResumeを開始する。sanitized command、run ID、開始Task、進捗、wall time、retry、warningおよび診断を記録し、別Runを作成していないことを確認する（Q-FUNC、Q-PERF、Q-USE）
- [ ] 5.3 Resumeが再び失敗した場合は推測修正を行わず、page、target ID、stage、cause type、retry回数およびResume可能状態を記録して本Taskを未完了のまま停止する。成功した場合はSTRUCTURE以降が完了し、exit code 0、進捗100%、Run status `completed`および外部DOCX exportを確認する（Q-REL、Q-SEC、Support Evidence）
- [ ] 5.4 Resume前後でSPLIT、DOCLING、MERGE、POSITION、NORMALIZEおよびLOADのfile数・SHA-256・mtimeが不変であることを確認し、成功済みArtifactが再計算されていないことを記録する。最終結果と残作業を`complete-sample-pdf-acceptance-verification`へ引き継ぎ、このChange内ではWord→PDF変換、目視比較およびComparison Reviewを完了扱いにしない（Q-REL、Q-COMP、移行Evidence）

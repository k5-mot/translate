<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDF受入Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`は、STRUCTUREのLLM呼出しで`TypeError`となり、設定済み有限retryを行った証跡も、失敗page・呼出し段階を特定する診断情報も残さず停止した。既存`run-lifecycle`契約へ実装を一致させ、安全に同じRunをResumeできるようにする。

## What Changes

- LLM Adapterの外部呼出し境界と構造化応答解析境界で発生する一時的なprovider／SDK応答Errorを分類し、設定済み回数・backoff・deadlineの範囲で逐次retryする。
- 任意のTask内部で生じる`TypeError`を一律retryせず、LLM外部境界で捕捉したErrorだけを対象にする。恒久的な4xxと設定・Programming Errorは即時失敗のまま維持する。
- retry上限後のLLM Errorを、raw応答、prompt、本文、Credentialおよびendpointを含まない安全な例外へ正規化し、invoke／parseおよびvision／text fallbackを識別できるstageと下位例外型を保持する。
- STRUCTUREのpage処理で最終失敗したpageと安定した対象IDを付与し、公開CLI、`failure.json`および`run.log`へTask、page、target、stage、cause typeだけを記録する。
- Unit／Integration Testでretry回数、非retry Error、診断metadata、redaction、Atomic ArtifactおよびResumeを検証する。
- 修正適用後、同じUUIDv7 Runを公開CLIから明示Resumeし、STRUCTURE通過、既完了SPLIT〜LOAD Artifactのhash／mtime不変性、途中成果物0件および外部exportをEvidenceへ記録する。
- 公開CLI option、Run layout、fingerprint、成果物形式、既存RequirementおよびDependencyは変更しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`establish-translate-ja-contracts`で定義済みの`run-lifecycle`にある外部障害の有限retry、およびTask・Page／ID・安全な原因を含むError契約の未達実装を修正する。Spec Levelの振る舞いは変更しないため、`.openspec.yaml`で`skip_specs: true`を宣言する。

## Impact

- LLM境界: `translate/adapters/llm.py`のretry分類、構造化応答解析および安全なError正規化。
- STRUCTURE Task: `translate/tasks/structure.py`のpage単位Error contextとvision／text fallback診断。
- Run Lifecycle: `translate/common/lifecycle.py`、`progress.py`およびFailure stage型の後方互換な拡張。
- Workflow: `translate/workflows/translation.py`のTaskStatusEventへのpage、target、stage伝播。
- Test: `tests/test_adapter_retry.py`、`test_failure_contract.py`、`test_translation_workflow.py`および必要なfocused integration Test。
- 実受入Run: `runs/01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5/`を修正後に同じfingerprintでResumeする。外部export先は`C:\Users\merry\Desktop\translate-acceptance-output\complete-sample-pdf-acceptance-verification`とする。
- 新規Dependency、Data migrationおよび既存Runの一括書換えはない。

## Stakeholders and Lifecycle Impact

- 利用者: 同じrun IDを再指定して、完了済みTaskを再実行せずTranslationを続行できる。失敗時は秘密や本文を見ずにpageとstageを特定できる。
- 保守者: retry回数、最終stage、下位例外型、pageおよび対象IDから外部Service障害と製品Errorを切り分ける。
- 取得・供給: 新規Service／packageを取得しない。既存LangChain、OpenAI互換APIおよびPydantic境界だけを使用し、公開interfaceを変更しない。
- 移行: Failure metadataは既存optional fieldを後方互換に拡張し、旧`failure.json`を読取り可能なままにする。Run schema version変更や既存Fileの書換えは行わない。
- 運用: LLM requestは現在の`retry_attempts`、backoff、request timeoutおよびTask deadlineに従い、すべて逐次実行する。retry stormと並行requestを発生させない。
- 保守・Support: raw Errorを保存せず、allowlist済みのstageとcause typeだけを記録する。実Run ResumeでUnit Testだけでは分からないprovider互換性を確認する。
- 廃止: Runと外部成果物の削除境界は変更しない。修正失敗時も対象RunをResume可能な状態で保持し、自動削除しない。

## Quality Considerations

- Q-FUNC（機能適合性）: retryableなLLM invoke／parse Errorが設定回数内で回復し、上限後は安全なfailureへ変換されることを自動Testする。恒久4xxと境界外TypeErrorの誤retryを0件にする。
- Q-PERF（性能効率性）: 最大試行回数、指数backoff、request timeoutおよびTask deadlineを既存設定で制限し、同時LLM requestを1件以下にする。
- Q-COMP（互換性）: 既存Run fingerprint、checkpoint、CLI／Streamlit Failure読取りおよび旧failure JSONとの互換性を維持する。
- Q-USE（使用性）: CLI failureへrun ID、Task、page、target、stageおよびcause typeを表示し、今回と同型の障害で未特定項目を0件にする。
- Q-REL（信頼性）: 成功済みSPLIT〜LOAD ArtifactをResume前後でhash／mtime不変にし、失敗時の公開DOCXを0件にする。
- Q-SEC（セキュリティ）: Error、log、warningおよびTest出力へのCredential、endpoint、prompt、文書本文、raw LLM応答、画像binaryの混入を0件にする。
- Q-MAIN（保守性）: retry分類とFailure contextをfocused Testへ対応付け、Ruff、Format、ty、pytestおよびOpenSpec strict validationを全て成功させる。
- Q-PORT（移植性）: 標準Pythonと既存Dependencyだけを使用し、Windows／POSIX固有の新規処理を追加しない。
- Interaction capability、SafetyおよびFlexibilityは公開操作や利用環境を変更しないため新規評価対象とせず、既存Testの回帰で確認する。

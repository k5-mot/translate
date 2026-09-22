<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実PDFのSTRUCTURE page 3を安全に再現した結果、同じText requestは2回とも入力1,328 tokensに対して出力上限4,096 tokensを全て消費し、`finish_reason=length`、本文0文字で終了した。実Modelのcontext windowは30,208である一方、現実装は環境指定の有無にかかわらず16,384へ切り下げるため、Model能力とtoken予算を一致させ、出力枯渇を一時的なparse障害として同条件retryしない契約が必要である。

## What Changes

- `google/gemma4:12b`の実context window 30,208を設定上限と既定値へ反映し、入力、画像、安全余白および最大出力の合計がcontextを越えないよう検証する。
- STRUCTUREを含むLLM requestで、応答本文をparseする前に`finish_reason=length`とtoken usageを検査し、出力枯渇を安全な`output-truncated`診断へ分類する。
- 同一token予算で結果が変わらない出力枯渇は一時障害retryの対象外とし、未回復時はTask、page、target、mode、stage、finish reasonおよび数値token usageだけを保存してResume可能に停止する。STRUCTUREのvisionだけは異なるtext-only入力が完全に成功した場合に限り継続する。
- 30,208 context内でSTRUCTUREの小さいJSON応答を完了できる既定出力予算を設定し、page 3の逐次probeで非空かつschema適合することを確認する。新規Dependencyと並行Model requestは追加しない。
- ContextおよびToken設定は既存どおりfingerprint対象とする。修正前Run `01a0c138-0e5f-7e62-b0a8-8f9fd1e5bfa5`は書換えず、設定差分によるResume拒否を確認して、新設定では新しいUUIDv7 Runを作成する。
- Unit／Integration Testでcontext境界、token予算、truncation分類、非retry、redaction、fingerprint差分およびAtomic Artifactを検証する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: 実Model contextに整合するtoken予算、出力枯渇の非retry診断、およびtoken設定変更時の新規Run境界を追加する。

## Impact

- Settings: `translate/common/settings.py`のcontext上限、既定token予算および相互制約。
- LLM Adapter: `translate/adapters/llm.py`の応答metadata検査、truncation Errorおよびretry分類。
- Lifecycle: `translate/common/progress.py`、`lifecycle.py`およびFailureの安全なfinish reason／token count伝播。
- Fingerprint: 既存`tokens.context`、`tokens.output`および`tokens.image`を維持し、旧Runとの設定差分をResume拒否Evidenceにする。
- Tests: Settings、Adapter retry、Failure contract、fingerprintおよびSTRUCTUREのfocused Test。
- 実検証: page 3の単発逐次probeと、既存成功Artifactを破壊しない新規Translation Run。
- 公開CLI option、Run layout、成果物形式、Qdrant契約およびPython Dependencyは変更しない。

## Stakeholders and Lifecycle Impact

- 利用者: 空応答のparse失敗や不透明な`TypeError`ではなく、出力予算不足を特定できる。token設定変更後は誤Resumeせず新規Runを使用する。
- 保守者: page／mode、finish reason、input／output／total token countおよび設定値から、context不足とProvider障害を本文なしで切り分けられる。
- 取得・供給: 新規Packageや外部Serviceを取得しない。既存のOpenAI互換ServerとLangChain metadataだけを使用する。
- 移行: 既存Run metadataは変換しない。token fingerprintが異なる旧Runは契約どおりResume不可とし、入力copy、checkpointおよびFailure Evidenceを保持する。
- 運用: Model probeとWorkflowは同時実行数1に保つ。新しいtoken予算のwall time、finish reasonおよびusageを記録し、無制限生成を許可しない。
- 保守: context windowまたはModelを変更する場合は、上限、余白、既定出力予算およびfingerprint Testを同じ変更で更新する。
- 廃止: 旧Run、外部exportおよびQdrant Collectionは自動削除しない。新Run完了後も利用者の明示削除まで診断Evidenceとして保持する。

## Quality Considerations

- Q-FUNC（機能適合性）: page 3相当のSTRUCTURE requestが非空のschema適合応答を返し、truncated responseを成果物へ採用する件数を0件にする。
- Q-PERF（性能効率性）: context 30,208以内の有限出力予算、request timeoutおよびTask deadlineを維持し、同時Model requestを1件以下にする。probeと実Runのwall timeおよびtoken usageを記録する。
- Q-COMP（互換性）: Token設定差分をfingerprintで検出し、旧Runの誤Resumeを0件にする。旧Failure JSONはoptional診断fieldなしでも読取り可能にする。
- Q-USE（使用性）: 公開Failureへpage、target、stage、`finish_reason=length`および数値token usageを表示し、本文やraw responseを要求せず原因を識別できるようにする。
- Q-REL（信頼性）: 出力枯渇を同条件で反復せず、完全な代替応答を得られない場合はResume可能に停止し、途中STRUCTURE Artifactを0件にする。新設定の新規Runで正常完了を検証する。
- Q-SEC（セキュリティ）: prompt、文書本文、reasoning content、raw応答、Credential、endpointおよび画像binaryのlog／Failure／Evidence漏えいを0件にする。
- Q-MAIN（保守性）: context計算、truncation分類、retry判定、fingerprint境界をfocused Testへ一対一で対応付け、Ruff、Format、ty、pytestおよびOpenSpec strict validationを成功させる。
- Q-PORT（移植性）: 標準Pythonと既存Dependencyだけを使用し、OS固有のtoken処理を追加しない。
- Interaction capability、SafetyおよびFlexibilityは公開操作や自律的な外部Actionを増やさないため新規評価対象とせず、既存回帰Testで確認する。

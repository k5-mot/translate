<!-- markdownlint-disable MD013 MD041 -->

## Why

[SETTINGS-FINITE-001](../document-all-python-function-purposes/verification.md)により、timeout・retry待機・Task deadlineの環境変数がNaNや正の無限大を受理することが分かった。既存の有限時間制御の契約を満たし、不正設定を外部処理の開始前に拒否する。

## What Changes

- 4種類の秒数設定について、環境変数から正の有限数だけを受理する。非数値、0以下、NaN、Infinity、変換時overflowによる無限大は設定名を示して拒否し、既定値へ黙って置換しない。
- 内部Settingsの生成時にも非有限値を拒否する。Testが待機抑制に使う内部retryの0と、公開環境変数の0拒否は区別する。
- 既存Pydanticの数値制約を使い、独自の有限値検証器や新Dependencyを追加しない。
- 既定timeout 1,800秒、Task deadline 21,600秒、有限な利用者指定値、retry回数、逐次実行を維持する。新しい最大秒数や大小関係の規則を導入しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。[run-lifecycle](../../specs/run-lifecycle/spec.md)の有限retryと、既存Change [allow-long-local-llm-requestsの要求](../allow-long-local-llm-requests/specs/run-lifecycle/spec.md)に明示された正の有限timeout・有限backoff/deadlineを満たす実装修正である。未archiveの既存要求を別名で重複定義せず、`skip_specs: true`とする。元Changeの検証不足も本提案だけでは解消しない。

## Impact

主な対象は既存`translate/common/settings.py`とSettings/公開入口のTest。logger/settingsだけをcommonに残す方針と整合し、新moduleは作らない。接続adapter、Graph、Resumeの状態、保存layout、fingerprint、依存とlockfileは変更しない。既存の別Changeの未コミット差分は混入させない。

## Stakeholders and Lifecycle Impact

運用者は不正な時間設定を処理開始前に検出し、設定を修正できる。保守者は既存Libraryの制約と境界Testを使う。永続データの移行・削除、Serviceの取得/供給は不要。既に実行中のprocessへ設定を注入せず、停止・再起動しない。適用後の新processで検証する。

## Quality Considerations

- Q-REL/Q-FUNC: 4環境変数の非有限/非正数/非数値を受理する件数0、有効な分数秒・長時間値・既定値の意図しない書換え0。自動Testで確認する。
- Q-SEC/Q-USE: 設定Errorは対象設定名と固定理由を持ち、無効な入力自由文を公開表示や通常tracebackの原因表示へ露出しない。合成markerで確認する。
- Q-COMP/Q-MNT: 内部retry=0を使う既存Testと有限値の型変換を維持し、既存Pydanticへ委譲する。新規Dependency/共通module/独自状態台帳0。
- 正式verifyでは新Codeを読み込んだ実translation→Microsoft WordによるPDF化→元PDFとのComparison Reviewを逐次実行し、利用者へWord/PDFを提示する。単体Testだけではarchiveしない。
- 性能・移植性の新機能は対象外。待機既定値と対応環境を変えないため、新たな性能目標や環境要件を設けない。

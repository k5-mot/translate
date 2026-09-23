<!-- markdownlint-disable MD013 MD033 MD041 -->

## Why

実Modelのdetached GateはSTRUCTUREを完了してTRANSLATEへ進んだが、応答形状の検証失敗が裸の`ValueError`として記録され、`TRANSLATE`の失敗理由を「ID不一致」か「保護断片欠落」か判定できなかった。既存の有限retry設定がLLM呼出し境界にしか適用されず、同一chunkの一時的な不整合を再試行しないため、正本Runを安全にResumeする前に診断性とretry契約を補正する。

## What Changes

- 翻訳応答のID集合不一致と保護断片欠落を、本文やraw responseを含まない固定cause／stage／page／chunk identifier付きFailureへ分類する。
- 同一translation chunkの応答検証失敗を既存の有限retry設定内で逐次再試行し、並列Model requestや無制限retryを導入しない。
- retry exhausted時は`TRANSLATE`を停止し、`failure.json`、Run metadata、外部Terminal Evidenceへ安全なcauseを保存して、同じRunを明示Resume可能にする。
- 成功したretryでは後続Taskへ進み、既存のAtomic Artifact、checkpoint、fingerprint、Qdrant状態非依存、CLI／Streamlit公開interfaceを変更しない。
- detached Gateを同じUUIDv7正本Runのcloneで一度再検証し、成功時のみ公開Resumeへ進める。失敗またはEvidence未確定時は公開Resumeを行わない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: Task／Page／IDと秘密非含有の固定causeをFailureへ保存し、翻訳応答検証の有限retryとResume可能停止を明示する。

## Impact

- `translate/tasks/translate.py`の応答検証とsafe exception、`translate/common/lifecycle.py`のFailure mappingおよび既存Terminal Evidence mappingに影響する。
- 翻訳Task／LifecycleのUnit・Integration Test、detached historical Gate Evidenceおよびverification記録を更新する。
- Dependency、永続Run schema、fingerprint、Qdrant collection、CLI／Streamlit API、Model／Embedding並列数は変更しない。

## Stakeholders and Lifecycle Impact

- 利用者／運用: 失敗Page／chunkの固定causeを確認し、同じRunを安全にResumeできる。
- 取得・供給: 既存Settingsと標準Python／Pydanticを再利用し、新規Service／Packageを追加しない。
- 運用／保守: retry回数、cause、stageおよびcheckpointを用いて一時的応答不整合と恒久Failureを区別する。
- 移行: 既存Run／checkpoint schemaとUUIDv7を維持し、旧Failureは再利用時に既存の安全なfallbackを使う。
- 廃止: retry途中の一時ArtifactをAtomic boundaryで破棄し、外部exportと正本Runを削除しない。

## Quality Considerations

- Q-FUNC／Q-REL: 応答不整合を有限回だけ再試行し、成功時は後続Task、失敗時はResume可能停止を確認する。
- Q-USE: Failureへ`TRANSLATE`、page、chunkおよび固定causeを表示し、裸の`ValueError`を0件にする。
- Q-SEC: prompt、本文、raw response、reasoning、CredentialおよびendpointをFailure／Evidenceへ保存しない。
- Q-COMP／Q-PORT: 既存Run layout、fingerprint、Qdrant状態非依存、Windows／PowerShell動作を回帰Testする。
- Q-MAIN: Ruff、format、ty、pytestおよびstrict OpenSpec validationを実行する。
- ISO/IEC/IEEE 12207の検証・妥当性確認・運用・保守・廃止を、synthetic Failure Testとdetached historical Gateで記録する。

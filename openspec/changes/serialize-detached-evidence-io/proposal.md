## Why

検証用detached runnerのTestでEvidence読取り中のWindows PermissionErrorを再現した。writerだけがlockを取りreaderとheartbeatは排他されないため、原子的置換と開いた読取りhandleが競合し、検証対象の失敗と診断基盤の失敗を混同する。

## What Changes

- Evidenceとheartbeatの読取り/書込みを同じファイル別lockで直列化する。
- OS別に自作したlockを、導入済みportalockerによる有限待機へ置き換える。
- writerの読取り・終端保護・公開を一つのcritical sectionに保ち、二重lockを避ける。
- 未作成・壊れたEvidenceを成功扱いしない既存契約を維持し、未使用のheartbeat読取りhelperを除去する。
- モデルなしの再現Test、終端保護、lock解放、親子processの反復I/Oで検証する。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。`persist-detached-resume-terminal-evidence`と同じ検証専用Toolingの内部修正で、公開5 Capabilityの要求やRun形式は変えない。`skip_specs: true`。

## Impact

`terminal_evidence.py`とそのTest。新依存なし。実LLM/Embeddingの逐次実行、公開CLI/UI、common配置の利用者承認待ち、Task構造、表の修正は変更しない。既存の未commit FailureKind拡張は混ぜない。

## Stakeholders and Lifecycle Impact

保守者の検証結果回収を安定化する。調達/供給は既存portalocker再利用のみ。Run/checkpoint移行なし。heartbeat lockも所有するtemp root内でcleanupする。旧OS別lockと未使用helperを廃止し、rollbackはコード差分のrevert。

## Quality Considerations

- Q-REL: 読取りも排他されることを決定的Testで検査し、親子I/O競合によるPermissionErrorを防ぐ。
- Q-MNT/Q-PORT: 既存libraryへOS差異を委譲、全体tyと対象Ruff/format成功。
- Q-SEC/Q-FUNC: 未作成/不正JSON/不正schemaを成功へ昇格させず、古いrunning通知でterminalを上書きしない。
- Q-PERF: lock内は小さいJSONの読取り/検証/atomic公開のみ。モデル要求・sleep・process待機を置かず、取得待ちは有限。
- 互換性/操作性/柔軟性/安全性: 形式・公開操作・deployment・危険操作は変更しない。実モデル品質と全体受入をこのTestで代替しない。

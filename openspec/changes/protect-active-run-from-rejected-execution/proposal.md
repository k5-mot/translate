<!-- markdownlint-disable MD013 MD041 -->

## Why

RUN-001では排他で拒否された呼出が、所有者のrun metadataをfailedに変更し、failure.jsonと共有logを書き換える。実行中処理とResumeの診断を壊すため、排他取得から終了保存までの更新境界を修正する。

## What Changes

- 排他を取得した呼出だけが実行情報・診断・成果物を更新できる契約を明示する。
- 排他拒否は呼出元へ安全に通知し、既存の失敗記録を今回の原因として誤採用しない。
- 正常終了・障害記録・log解放まで排他を保持し、拒否側の外部呼出0件と所有者の保存内容不変をTestする。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `run-lifecycle`: 同一Runの排他拒否時に所有者の状態とArtifactを保全する要求を追加する。

## Impact

既存common/lifecycle.pyとworkspace.pyの実行・排他境界、関連Test。新しい共通Module、lock実装、保存状態、Dependencyは追加しない。common責務移管とLangGraph正本化を解決済みにはしない。

## Stakeholders and Lifecycle Impact

CLI/UIで誤って重複実行した利用者と、本来の実行所有者を対象とする。拒否された呼出は非成功を返すが、所有者の継続を妨げない。入力・保存schema・既存成果物の移行や削除なし、供給依存の変更なし。廃止対象はlock非所有者の状態更新経路。

## Quality Considerations

Q-REL: 拒否時の所有者metadata/failure/log/checkpoint/output変更0、外部処理呼出0を実lockで確認。Q-SEC: 公開拒否に秘密・原文・内部pathを露出しない。Q-MNT: 導入済みportalockerを再利用し、独自排他や進捗状態を作らない。CLI/UI共通境界でQ-COMPを維持する。性能向上・新UI・hardware対応は目的外。実translation→Word PDF→reviewと目視gateは維持する。

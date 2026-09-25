<!-- markdownlint-disable MD013 MD041 -->

## Why

診断JSONの原子的置換は、Repository内で標準APIだけの試験でもWinError 5を再現した。利用者が承認した「既存JSONへ直接上書きし、途中書込みで壊れた状態は成功扱いしない」方式へ変更し、診断保存を簡素化する。

## What Changes

- 検証用Evidence/heartbeatの保存だけを、同じlock内での既存Fileへの上書きへ変更する。
- **BREAKING（検証Tool内部保証）**: 書込み途中の中断時に前の診断JSONを保持する保証を廃止する。破損・欠落は状態不明であり、成功や自動再開の根拠にしない。
- 有限lock待機、正常な終端の古いrunning更新からの保護、flush/fsync、I/O障害の伝播、安全な保存項目を維持する。
- 以前の原子的保存設計との変更関係を記録する。Process Monitor導入・常駐ソフト停止・任意のPermissionError無視は実施しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。検証Tool内部の保存方式に限定するためskip_specs=trueとする。公開Run、入力・成果物、LangGraph Checkpoint、公開Resume条件は変更しない。

## Impact

translate/common/terminal_evidence.pyのEvidenceStore、tests/test_terminal_evidence.pyと関連検証記録。既存portalocker/Pydantic/標準I/Oを使い、新依存・新Module・新しい状態台帳は作らない。workspaceの汎用atomic writerと子process要求File保存は変更しない。

## Stakeholders and Lifecycle Impact

- 利用者・運用: 中断後に最後の診断状態を失い得るが、実Runは削除しない。process終了確認と既存成果物検証なしに成功を宣言しない。
- 移行・保守: Evidence schemaと既存JSONの読込みは維持する。保存方式の新旧混在を避け、対象診断processの停止後に更新する。
- 廃止: Evidence/heartbeatでの一時File置換だけを廃止し、所有一時領域のcleanup規則は維持する。
- 取得・供給: 外部製品取得や利用者向け形式変更はない。Word PDF化は従来どおり検証操作であり製品機能にはしない。

## Quality Considerations

| ID / 特性 | 目標・確認方法 |
| --- | --- |
| Q-FUNC 機能適合性 | 正常保存・再読・終端保護Test成功率100% |
| Q-REL 信頼性 | 空/部分JSONからの成功判定0、write/flush/fsync障害の握り潰し0、lock解放と実親子I/OをTest |
| Q-PERF 性能効率 | JSONの更新方式以外に処理・Model callを増やさない。実機反復の件数・時間・エラーを記録 |
| Q-COMP 互換性 | 既存Evidence読込み、公開Run/fingerprint/Checkpointの回帰Test成功 |
| Q-USE 利用時の分かりやすさ | 診断不能と処理成功を混同しない終端表示・判定をTest |
| Q-SEC Security | allowlistとtemp root外配置を維持、入力/成果物変更0 |
| Q-MAIN 保守性 | 新依存0、独自lock/retry追加0、Ruff・型検査・全Test成功 |
| Q-PORT 移植性 | WindowsのRepository内で実EvidenceStore親子反復を確認 |

電源断耐性やlock非協調readerへの完全版提供は保証しない。新たな安全性用途はない。

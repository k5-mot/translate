<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## ADDED Requirements

### Requirement: 対応環境と公開Entry Pointを限定する
SystemはPython 3.12以上を対応環境とし、製品として直接実行を保証するEntry Pointを`cli.py`と`main.py`に限定しなければならない（MUST）。内部ModuleのDebug入口を公開Interfaceとして扱ってはならない（MUST NOT）。

#### Scenario: 対応環境から公開入口を使用する
- **WHEN** 利用者が必要な依存を導入したPython 3.12以上の環境から公開入口を起動する
- **THEN** CLIはcli.py、Streamlit UIはmain.pyを入口として利用でき、内部Task Moduleの直接実行を必要としない

#### Scenario: 内部ModuleにDebug入口がある
- **WHEN** 開発者が内部ModuleのDebug入口を使用する
- **THEN** その入口は開発用途に限定され、製品が保証する公開操作には追加されない

### Requirement: 各Taskの経過時間を計測できる
Systemは、各Taskの経過時間を計測可能にしなければならない（MUST）。計測情報を再開位置やTask完了状態の独立した正本として使用してはならない（MUST NOT）。

#### Scenario: Taskを実行して計測する
- **WHEN** Taskを実行して経過時間を確認する
- **THEN** 対象Taskの経過時間を取得でき、計測処理は再開状態を別に管理しない

## MODIFIED Requirements

### Requirement: Task単位のCheckpointを保持する
Systemは、各Taskの成功、失敗および現在位置を識別できる単一のcheckpoint管理を再開状態の正本とし、再開位置と完了履歴を独立した台帳やCacheで二重管理してはならない（MUST NOT）。進捗表示は正本の実行情報から導出し、CLIとStreamlitで同じ完了状態と再開位置を使用しなければならない（MUST）。Task内部のPageまたはChunk単位の再開にも同じ原則を適用しなければならない（MUST）。checkpointにはArtifact path、状態、警告および小さい進捗metadataだけを保存し、文書本体と画像binaryを保存してはならない（MUST NOT）。入力・設定の互換性判定、Artifact入出力および外部副作用の冪等性確認は、独立したTask完了状態の正本として使用してはならない（MUST NOT）。Q-REL（ISO/IEC 25010）として、障害注入とCLI/UI相互Resume Testで、表示と再開位置の不整合および二重管理に起因する副作用の重複を0件とし、既存の再開粒度を維持しなければならない（MUST）。

#### Scenario: Task完了後に障害が発生する
- **WHEN** あるTaskのArtifact公開後、次のTaskでRunが失敗する
- **THEN** Resumeは公開済みArtifactをpathから読取り、成功済みTaskを再実行しない

#### Scenario: Checkpointを検査する
- **WHEN** 保守者が文書処理中のcheckpointを検査する
- **THEN** checkpointはArtifact pathと小さいmetadataだけを含み、文書本文と画像binaryを含まない

#### Scenario: CLIとStreamlitを切り替えて再開する
- **WHEN** 一方の入口で中断した同じRunを他方の入口から再開する
- **THEN** 両入口は同じ正本から完了状態と未完了位置を導出し、別の進捗記録によって成功済み処理を再実行したり未完了処理を省略したりしない

#### Scenario: PageまたはChunkの途中で停止する
- **WHEN** 細粒度の再開を提供するTaskが一部のPageまたはChunk完了後に停止する
- **THEN** Resumeは正本に記録された未完了単位から継続し、Task内部の独立した再開台帳を使用せず、既存の再開粒度を維持する

#### Scenario: Artifact公開後かつ完了記録前に中断する
- **WHEN** Artifactまたは外部副作用の公開とcheckpointへの完了記録の間に中断する
- **THEN** Resumeはcheckpointの未完了位置と必要な冪等性確認から処理を継続し、Artifactの存在だけでTask全体を完了扱いせず、副作用を重複させない

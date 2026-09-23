<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と対象Runは[proposal.md](proposal.md)を参照する。現在の正本Runは`.workspace/checkpoints.sqlite`に9 checkpoint／51 writes、LOADまでの公開Artifact、page 2のprivate STRUCTURE checkpointおよびpending STRUCTURE nodeを保持する。一方、成功したRun外probeは新規SQLiteへLOAD完了stateを一度だけ投入し、page 3だけのDocumentを使っていた。

`translation._run()`は`workflow.json`のfingerprintからthread IDを決定し、`SqliteSaver`の最新snapshotがあれば`compiled.stream(None, config)`で再開する。`execute_run()`はその外側でRun status、logging、`OutputLock`、task status／progress callbackおよび観測Contextを束縛する。historical checkpoint内のArtifact pathは正本Runの絶対pathを指すため、Database fileだけを複製して実行すると正本Artifactへ書き込む危険がある。

## Goals / Non-Goals

**Goals:** 正本を変更しない一貫したhistorical snapshotをRun外へ複製し、保存stateのpathだけを一時Runへ安全にrebaseする。fresh／historical state、single／full Document、page checkpoint、lock／logging／callback、公開Lifecycleの差を累積的なmatrixで比較し、TypeErrorを一つの境界へ再現する。原因限定修正後に正本複製の実Model Resumeと一度だけの正本公開Resumeを順番に通す。

**Non-Goals:** checkpoint formatの直接書換え、LangGraph／Langfuse／OpenAI SDKのupgrade、Model／prompt／schema／token予算変更、retry増加、並列化、raw診断追加、Run schema／fingerprint／checkpoint v4変更、Qdrant状態固定、Word-to-PDF変換、目視比較およびComparison Review受入。

## Decisions

### 1. 正本Runは読取り専用snapshotとして扱う

Preflightで実行processとModel queueがidleであること、Run lockを他processが保持していないこと、Run metadata／fingerprint／input SHA-256／SPLIT～LOAD baselineが保存値と一致することを確認する。SQLiteはread-only接続から標準`sqlite3.Connection.backup()`でOS一時directoryへ一貫したsnapshotを作り、Artifactはregular fileだけをtemp Runの同じ相対layoutへcopyする。symlink／junction、Run root外pathおよび外部exportは複製対象にしない。

`Copy-Item`だけでDatabaseを複製する案はWALまたは同時writeで不整合になり得るため採用しない。正本へ`OutputLock`を取得する案も`run.lock`を変更し得るため採用せず、idle確認後のread-only backupと前後hash／mtime比較で不変性を証明する。

### 2. Historical lineageを残したtemp forkでpathをrebaseする

複製したDatabaseを実`SqliteSaver`で開き、`workflow.json`の保存済みthread IDから最新snapshotとpending nodeを読み取る。Stateのpath-valued fieldをallowlistし、正本Run root配下の`source`、`output_dir`、`workspace_dir`およびArtifact pathだけをtemp Runの対応pathへ写像する。root外path、不明field、本文またはbinaryがcheckpointに含まれる場合は実行前に失敗させる。

LangGraph内部のSQLite blobを直接書き換えず、public `update_state()`で複製Databaseにだけrebased stateを追加し、元のcheckpoint lineage／writesを保持したtemp forkを作る。更新前後でpending nodeがSTRUCTUREだけであり、SPLIT～LOADが再実行されないことを検査する。直接blob置換はversion依存で移植性と整合性を損なうため採用しない。

### 3. Offline matrixは一要因ずつ累積する

同じstrict-schema responseを返す実ChatOpenAI／OpenAI SDK `MockTransport`と実Translation graphを用い、Network 0件で次の順に比較する。

1. fresh SQLite＋page 3だけのDocument（既知成功baseline）
2. fresh SQLite＋full LOAD Document＋page 2 private checkpoint
3. historical SQLite temp fork＋full Document／page checkpoint
4. 3に`OutputLock`、run logging、progress／task status callbackおよび観測Contextを追加
5. temp `RunRepository`／`PreparedRun`を使い`execute_run()`、続いて`execute_public_run()`を通す

各caseはModel build／bind／invoke、Provider call、response return、parse、node return、state update、checkpoint commit、logging handler、lock、task eventおよびContextVarをboolean／count／allowlist済み型だけで記録する。前段成功・次段失敗となる最初の追加要因を所有境界とする。全case成功なら製品Codeを変更せず、同じtemp forkを実Model Gateへ進める。

### 4. 修正は再現した所有境界だけへ限定する

- Historical state／checkpointが原因なら、公開APIで読めるstateの正規化またはResume時検証を最小修正し、成功済みTaskを再実行しない。
- Full Document／page checkpoint reuseが原因なら、現在pageの選択またはprivate checkpoint読取りを修正し、他pageの確定Artifactを変更しない。
- Logging、lock、callbackまたはContext束縛が原因なら、そのlifecycle境界の型／scope／cleanupだけを修正する。
- LLM／観測Adapterが原因なら、実際に再現したcall形または例外originだけを扱い、未知の`TypeError`一般を捕捉しない。

一意に再現できない場合、一般的な例外正規化、観測無効化、checkpoint破棄、新規Runへの置換またはretry増加を行わない。これらは正本Resume契約を満たした証拠にならないためである。

### 5. 実機Gateはtemp public Resumeから正本Resumeへ一方向に進める

Offline修正と全自動Gate後、LM Studioが対象Model、context 30,208、parallel 1、queued 0／idleであることを確認する。正本複製temp Runを`execute_public_run()`境界からSDK retry 0、Application retry 1、request timeout 900秒、同時request 1で一度Resumeする。STRUCTUREがschema-validに完了し、正本不変、temp ArtifactのAtomic性および秘密漏えい0件を満たした場合だけ、正本Runを公開CLIから一度Resumeする。

temp実Model Gateまたは正本Resumeが失敗した場合は、その段階で追加Model request／Resumeを行わず、Runを保持して次Changeへ引き渡す。

## Quality Attribute Design

| ID | Design approachとtrade-off | Evidence |
| --- | --- | --- |
| Q-FUNC | historical SQLite、full Document、page checkpointおよび公開Lifecycleを段階的に結合する | offline matrix、temp実Model Resume、正本公開Resume |
| Q-REL | read-only backup、path allowlist、pending node維持、一response一消費、Atomic公開を固定する | 前後hash／mtime、snapshot、call count、fault injection |
| Q-PERF | offline優先、実機はtimeout 900秒・parallel 1・一方向Gateとする | queue状態、attempt、wall time、最大同時request |
| Q-COMP | UUIDv7、fingerprint、checkpoint v4、CLI／UI共有layoutおよびQdrant非依存を維持する | Lifecycle／Resume／fingerprint回帰Test、正本差分 |
| Q-USE | 最初に失敗するmatrix要因と固定boundary／originをFailureへ縮約する | task event、safe diagnostics、Evidence inspection |
| Q-SEC | temp root限定、root containment、raw値非収集、終了時cleanupを要求する | path traversal Test、sentinel scan、残存temp 0件 |
| Q-MAIN／Q-PORT | LangGraph public APIと標準SQLite backupを使い、原因限定修正だけを行う | Ruff、Format、ty、全pytest、Dependency／OS分岐差分 |

## Lifecycle, Migration and Operations

- 移行: 永続Data migrationはない。正本RunのcheckpointとArtifactは変更せず、temp forkだけにpath rebase checkpointを追加する。
- 運用: 全Model／Embedding呼出しを逐次実行する。各実機Gate前にModel、context、parallel、queue、fingerprint、input hashおよびService healthを再確認する。
- 保守／Support: offline matrixをhistorical Resumeの回帰契約とし、失敗要因、境界、型および回数だけをEvidenceへ残す。
- Rollback: 原因限定のCode／Test commitを通常のGit操作で戻す。Run、外部export、Qdrant Collectionおよび利用者Dataは削除しない。
- 廃止: 一時cloneは検査終了後に明示削除する。新規Service、Dependency、公開optionおよび永続fieldがないため追加の廃止手順はない。

## Risks / Trade-offs

- [Risk] Path rebase用`update_state()`が最新checkpointを一つ増やし、完全に同一のlatest checkpointではなくなる → 元lineage／writesを保持し、rebase前snapshotでもpending STRUCTUREとstate shapeを記録する。temp fork以外は変更しない。
- [Risk] Historical Databaseに文書本文または正本外pathが含まれる → allowlist／containment検査で実行前に失敗し、値そのものをEvidenceへ保存しない。
- [Risk] Offline responseではlocal runtime固有のTypeErrorを再現できない → offline全case成功時だけtemp forkの実Model Resumeへ進み、正本Resumeはさらにその成功後へ限定する。
- [Risk] full DocumentのTest fixtureが大きくCIを不安定にする → 正本Dataをrepositoryへcommitせず、fixtureは一時copyまたは構造を保つ最小synthetic Documentとし、正本複製probeは手動実機Gateに限定する。
- [Risk] 公開Lifecycle Testがglobal logging stateを残す → 各case後にhandler、ContextVar、lockおよびtemp directoryのcleanupを検査し、次caseへの汚染をFailureにする。
- [Risk] 正本公開Resumeが再び失敗する → 一回限り制約を維持し、成功済みArtifact不変、部分Artifact非公開およびResume可能状態を実測して次Changeへ渡す。

## Migration Plan

1. 正本baselineを読取り専用で記録し、SQLite backup／Artifact copy／path rebaseをtemp forkとして構築するTestを追加する。
2. Offline matrixをfresh baselineから公開Lifecycleまで順に実行し、最初の失敗要因を確定する。
3. 原因を一意に再現した場合だけ失敗Testを固定して最小修正し、matrixと既存fault injectionを成功させる。
4. 全品質／Security Gate後、正本複製temp Runを実Modelで一度Resumeする。
5. Temp Gate成功時だけ正本Runを公開CLIから一度Resumeし、成功なら成果物、失敗なら保存状態を検査する。
6. Rollback時はCodeとTestだけを戻し、正本Runおよび外部状態を保持する。

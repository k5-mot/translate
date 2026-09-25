## Context

proposal.mdのWhyを参照。EvidenceStore.writeはlock内でread/replaceするがreadは無排他。heartbeatは直接load_json/atomic_write_jsonを呼ぶ。Windowsでは開いた読取りhandleとreplaceが競合し得る。既存portalockerのLock APIをインストール済みsourceで確認した。

## Goals / Non-Goals

**Goals:** 全Evidence/heartbeat I/Oをファイル別に直列化し、終端判定と不正Evidenceの扱いを維持する。

**Non-Goals:** 製品モデルの並列化、Run排他の修正、診断基盤の配置移動、検証専用機能の公開化、任意のPermissionErrorの握り潰し。

## Decisions

1. `_evidence_lock`はportalocker.Lockをappend-binary、取得待ち最大10秒/再試行間隔0.01秒で使用する。10秒は従来Windows lockが最大約10秒待つ境界を維持し、短いJSON I/Oで永続的な競合を待ち続けないため。モデルtimeoutとは別物。独自OS分岐とlock前のbyte書込みを除去する。
2. public readは存在しない場合だけNoneを返し、存在する場合は同じlock内で内部readを行う。writeはlockを取得済みなので内部readを直接呼ぶ。内部readはこの2か所だけで使い、再入lockや二重取得を避ける。
3. 内部readはJSON parseとschema validationのValueErrorをNoneへ変換する。OSError/PermissionErrorは隠さない。未知・不正を成功扱いしない既存契約の実装漏れを補う。
4. heartbeatもEvidenceStore経由で読書きする。終端Evidenceとheartbeatのlockを同時に保持せず、deadlockを避ける。未使用の_run_id_from_heartbeatは廃止する。
5. grill-with-docsの判断木では「既存依存を再利用」「不正なEvidenceで成功にしない」「モデルは逐次」は確定済み要求。新しい配置/公開仕様/用語の判断はないため、CONTEXT/ADRの追加は不要。前回の設計質問は未回答のまま別途保持。
6. 実機診断でconstructorのpath.resolveもFile handleを開くことが分かったため、指定pathの既存File別lockを取得してから正規化し、readの存在確認もlock内へ移す。標準Path.resolveへの委譲とtemp root外の判定を維持し、文字列だけの絶対path変換へ弱めない。constructorもlock Fileと親directoryを作る場合があるので、未作成EvidenceのTestも所有するtmp_path内で実行する。異なるFile symlink名から同じtargetへ入る場合のlock identityは、この修正だけで統一したと扱わない。
7. 排他の追加は協調する診断処理間の競合を防ぐもので、Repository内のwriter単独でも起きた置換失敗まで直す証拠にはならない。外部handle等の未確定要因を追跡し、全体受入では残件を明示する。任意のPermissionErrorをretry/無視する修正は追加しない。

## Quality Attribute Design

Q-REL/Q-FUNC: read/replace時にlockをちょうど一つ持つ決定的Test、古いrunning更新の終端保護、実親子の高頻度I/O。Q-SEC: 不正JSON/schemaが成功にならず本文が保存されない既存Test。Q-MNT/Q-PORT: library再利用、Ruff/ty/全体Test。Q-PERF: critical section内に外部サービス待機を入れない。

## Lifecycle, Migration and Operations

Evidence schema不変、既存JSONを読取り可能。新しいheartbeat lockは既存の所有temp root内でcleanupされる。外部Evidenceとそのlockは保存先に保持。モデルや過去Runは起動/変更しない。古い子processが実行中なら終了を確認してから新旧writerを混在させない。

## Risks / Trade-offs

- [Risk] public readをwriteから呼ぶと二重lock → 内部readへ分離し取得回数を検査。
- [Risk] lock待機で監視deadlineの観測が遅れる → I/O取得は最大10秒、lock内で待機しない。watchdog timeoutそのものの値や意味は変更しない。
- [Risk] stress成功だけでは競合不存在を証明できない → 排他境界の決定的Testと組み合わせる。
- [Risk] 原因未特定の過去child exit 2を同一原因と断定する → PermissionErrorの再現と区別し、全体Testの結果を記録する。

## Migration Plan

Testで現行の無排他を再現し、lock/heartbeatを修正。対象と全体検査後、未commit機能差分を除外してcommitする。問題時はコード/Testのrevertで戻せる。

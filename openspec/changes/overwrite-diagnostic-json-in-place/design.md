<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)を参照。[既存検証記録](../serialize-detached-evidence-io/verification.md)には標準API置換の失敗と直接上書き3984回の事前成功がある。これは実EvidenceStore親子試験の代用ではない。現行EvidenceStoreは読書き・resolve・existsを既存portalockerで排他する。

## Goals / Non-Goals

**Goals:** Evidence/heartbeatだけを標準File I/Oへ簡素化し、破損診断で成功を誤認しない。

**Non-Goals:** 公開Runの状態機構、汎用Artifact保存、入力/成果物/Checkpointの直接上書き、common移動、新backup/journal/checksum、追加retryやOS監視Tool。過去のWinError 5の原因process特定を採用条件にしない。

## Decisions

1. **保存前にserializeし、同じlock内で直接更新する。** Pydanticの既存JSON出力を使って完全な文字列を作り、既存の旧状態読取り・終端保護の後にopen("w", encoding="utf-8")、write、flush、os.fsync、closeする。serialize失敗はtruncate前に発生させる。新しい汎用writerやModuleは不要。workspace.atomic_write_jsonは他用途で残す。
2. **前の診断状態の保持を保証しない。** truncate後の中断では空/部分JSONを許容する。既存schemaで読めない場合はNone/unknownとしてGateを通さず、write/flush/fsync等のOSErrorはそのまま伝播する。完全なcompleted JSONだけでもwriterのfsync成功を証明できるわけではないため、watchdogは既存のprocess exit・Run/成果物検証と組み合わせて判断する。新しい成功台帳を追加しない。
3. **協調I/Oの排他は維持する。** 読取り、constructorのresolve、exists、旧終端判定からcloseまで同じsidecar lockを使う。未作成Fileは初回に作成する。正常な終端がある場合は古いrunningを無視するが、破損前の終端を復元する機能は作らない。lock非協調readerや別名symlinkの統一を新たに保証しない。
4. **設計変更を明示する。** persist-detached-resume-terminal-evidence/design.mdの原子的Evidence/heartbeat保存と、serialize-detached-evidence-ioの無条件旧版保持を本Changeが置き換える。過去の実測と失敗判定は保持する。診断JSONの上書きと中断時unknownは利用者承認済み。新たな業務用語も不可逆な構成変更もないためCONTEXT/ADRは追加しない。

## Quality Attribute Design

Q-FUNC/Q-REL: 新規/既存/短いJSON、単一lock、終端保護、serialize前失敗、truncate後失敗、flush/fsync失敗、強制終了後の破損をTestする。破損からのGate通過は0件。Q-PERF/Q-PORT: Repository内の実EvidenceStore親子I/Oを固定回数・有限時間で確認する。Q-COMP: 既存JSON/schemaと公開convert経路を回帰。Q-USE/Q-SEC: 不明と成功の区別、safe項目、temp root外配置を維持。Q-MAIN: 標準I/Oと既存lockへ委譲し、例外握り潰し・新依存は0。

## Lifecycle, Migration and Operations

既存の対象診断processが終了してから切り替える。旧Fileのmigrationは不要。破損診断があっても利用者Runを消さず、processと既存Run/成果物の情報を確認して次の操作を決める。原因不明の共有障害が残る場合は失敗記録を残し、retryで合格へ塗り替えない。Process Monitorは導入しない。

## Risks / Trade-offs

- [Risk] 前の終端まで失われる → 承認済み。unknownを成功扱いせず、新backupや再開状態を追加しない。
- [Risk] 上書きでも共有拒否が起きる → 実親子反復で測定し、再現時はエラーを報告する。事前試験の非再現で安全を断定しない。
- [Risk] atomic writerをspyする既存Testが無効になる → 実open/write/closeとlock保持の境界を観測するTestへ替える。
- [Risk] 保存完了JSONがあるがfsyncが失敗する → 呼出しを失敗として扱い、保存値の存在だけで成功としない経路をTestする。

## Migration Plan

1. 対象Test先行で保存境界と失敗分類を確認し、EvidenceStoreのみ変更する。
2. 既存親子I/O TestとRepository内の反復を逐次実行し、終了handle・件数・エラーを記録する。所有する合成一時領域だけをcleanupする。
3. 品質command後、翻訳簡素化Changeと同じreasoning OFFのsample3翻訳→Microsoft Word PDF→比較Reviewに診断保存を接続し、実終端を確認する。試験用Runの追加再実行を検証件数のためだけに増やさない。
4. 後継関係を旧verificationへ追記し、受入後に正式verify/archiveへ進む。RollbackはEvidenceStore実装だけを戻し、利用者Runを変更しない。

<!-- markdownlint-disable MD041 -->

## Context

動機は[proposal.md](proposal.md)のWhyを参照する。現在のRun modelはcanonical UUIDv4だけを許可し、新規IDも`uuid4()`で生成する。Python 3.12の標準`uuid` moduleには`uuid7()`がないため、Dependency追加か小さいRFC準拠実装の選択が必要である。

参照登録はsource hashを`read_bytes()`で計算し、binary文書全体を一つのDocling jobへ送信した後、全Chunkをmemoryへ保持して一括書込み・一括確認する。`inputs/sample.pdf`はこの経路で約25分後に失敗した。Adapterはstageを含むError messageを生成するが、Lifecycleの安全化境界が例外型だけを保存するため、永続Evidenceからstageを復元できない。

既存のPDF splitter、streaming SHA-256、atomic directory、有限retry、stable source keyおよびrevision確認後削除は再利用できる。新規Dependency、公開CLI option、Word→PDF変換およびQdrant状態のfingerprint追加は不要である。

## Goals / Non-Goals

**Goals:**

- Python 3.12と既存DependencyだけでRFC 9562 UUIDv7を生成し、UUIDv4 Runを後方互換に扱う。
- PDF抽出とQdrant I/Oの一回あたりの処理量を固定上限へ抑え、途中失敗後の同一Run再実行を決定的にする。
- 登録stageと下位例外型だけを信頼済み診断値として永続化し、raw例外内容を公開境界へ渡さない。
- Chunk方式の変更時に、同じsource hashを持つ旧方式Pointが残らないrevision identityを導入する。

**Non-Goals:**

- Run一覧をrun IDの辞書順で並べること、または同一millisecond内のID順序を厳密に単調化すること。
- UUIDv4 Run directoryの改名、Run schema versionの更新または保存済みmetadataの一括書換え。
- Qdrant transaction、Collection snapshot、登録取消APIまたはRun削除とQdrant削除の連動。
- DOCX／PPTXのpage分割、Docling Server自体の性能改善またはWord→PDF変換。
- 失敗した登録の各Docling partをCheckpointとして再利用すること。Resumeは既存の分割Artifactと決定的Point IDを利用するが、未完了抽出を安全に再実行する。

## Decisions

### 1. UUIDv7を標準型と暗号学的乱数から構成する

`translate/common/identifiers.py`に、Unix epoch millisecondの48 bit、version 7、12 bitの`rand_a`、RFC variantおよび62 bitの`rand_b`を組み立てて`uuid.UUID`を返す小さい生成関数を置く。時刻は`time.time_ns() // 1_000_000`、74 bitの乱数は`secrets.randbits()`から取得する。追加Packageは導入しない。

Run Repositoryは新規作成時だけUUIDv7を生成する。Run ID validatorはcanonical lower-case文字列、RFC variantおよびversion 4または7を許可し、それ以外をpath構築前に拒否する。UUIDv7のtimestampが生成前後のUTC時刻範囲に入ること、固定clock／randomでbit layoutが一致すること、多数生成で衝突がないことをTestする。

時刻逆行や同一millisecond内の厳密なsortを補正するprocess-global counter案は、複数process間で同じ保証を提供できず、永続lockもID生成を重くするため採用しない。表示順は従来どおり`updated_at`を正とし、UUIDv7は時刻を含む一意識別子として使用する。

### 2. 登録全体で一つのdeadlineを共有する

登録開始時に絶対deadlineを一度計算し、PDF partのDocling変換とQdrantの各retryへ残時間を渡す。partごと、batchごとにTask deadlineを作り直さない。残時間が0になった時点で現在stageの`TimeoutError`として失敗し、Runをfailed状態へ保存する。

これにより358 pageの処理が設定済みTask deadlineを超えて際限なく継続することを防ぐ。外部APIの一回のrequest timeoutと登録全体のdeadlineは別の制約として維持する。

### 3. PDF分割ArtifactをRun workspaceへAtomic保存して再利用する

Lifecycleは登録Adapterへ`.workspace/registration/`を渡す。PDFごとにsource keyとsource hashで識別するdirectoryを作り、既存PDF splitterで`PDF_SPLIT_PAGES`以下のpartとmanifestをatomic publishする。complete marker、source hash、分割設定およびpage範囲が一致する場合だけResume時に再利用し、不一致または不完全directoryは作り直す。

各partはmanifest順に一つずつDoclingへ渡し、抽出したtextをChunk化した後に次のpartへ進む。原PDFのhashは共通streaming関数で計算し、原PDF全体、全Docling payloadまたは全Chunkを同時にmemoryへ保持しない。Text、DOCXおよびPPTXの既存抽出契約は維持する。

OS temporary directoryだけを使う案は再実行時に分割を繰り返すため採用しない。Docling JSON全文をCheckpointへ永続化する案は本文保持量とschemaを増やすため、本Changeでは採用しない。

### 4. Chunkを64件ずつupsertして同じbatchを確認する

抽出順にglobal chunk indexを割り当て、最大64件の`Document`とPoint IDをbufferする。bufferが上限へ達するかsource末尾になった時点でupsertし、同じID集合を有限retryでretrieveして全件確認する。初回batchだけCollectionを作成し、以降は既存Collectionへupsertする。64は内部定数としてTestで固定し、新しい環境変数やCLI optionは増やさない。

失敗済みRunの再実行は確認済みPointも同じIDでupsertするため重複しない。全sourceの全batchを確認するまでは旧revision削除を開始しない。途中で失敗した新revision Pointは残り得るが成功報告せず、Resumeまたは後続revisionの成功時に決定的に収束させる。全登録をmemoryへ保持する現方式と一括retrieveは、大規模入力でmemoryとrequest sizeが入力全体に比例するため廃止する。

### 5. Chunk schemaをregistration revisionへ含める

PDF分割導入により同じsource hashでもChunk境界が変わるため、`registration-v2` schema識別子、source hash、分割page数、OCR設定、Chunk sizeおよびoverlapからcanonicalなregistration revisionを作る。Point IDは`source_key + registration revision + global chunk index`からUUIDv5で決定的に生成し、metadataへ`registration_revision`と`chunk_schema`を追加する。

全新Point確認後、同じsource keyかつ現在のregistration revisionと一致しないPointを削除する。これにより旧実装の`source_hash + index` Point、設定違いのPointおよび失敗した過去revisionをまとめて旧revisionとして扱う。source keyと表示用logical pathは変更しない。Qdrant状態は引き続きRun fingerprintへ含めない。

Chunk schemaをPoint IDへ含めず余剰indexだけを検索・削除する案は、旧metadataに総Chunk数がなく、同一hashの旧Chunkを安全に識別できないため採用しない。

### 6. 登録Errorをallowlist済みfieldで構造化する

登録Adapterは`collect`、`hash`、`split`、`extract`、`write`、`verify`、`replace`の固定stageと、`type(cause).__name__`だけを持つ`RegistrationError`へ失敗を変換する。入力収集前の利用者Errorは従来どおり`ValueError`とし、外部Errorのmessage、response、Credential、本文、pathおよびDocling job IDは`RegistrationError`へcopyしない。

`FailureRecord`へoptionalな`stage`と`cause_type`を追加し、既存failure JSONをdefault値で読めるようにする。Lifecycleは信頼済み属性だけを転記し、共通formatterが`task=REGISTER stage=<stage> cause=<cause-type>`をCLI、StreamlitおよびRun logへ出す。`error_type`は公開境界の`RegistrationError`、`reason`は後方互換な安全要約として保持する。一般例外の既存表示は変更しない。

raw例外messageを共通redactionへ通して保存する案は、未知形式の本文や外部IDを完全に分類できないため採用しない。

## Quality Attribute Design

| 品質ID | Design Approach | Trade-off | 検証Evidence |
| --- | --- | --- | --- |
| Q-FUNC | UUIDv7 bit layout、順序付きPDF part、global chunk index、version付きrevision | Chunk schema移行時にPoint IDが変わる | RFC field Unit Test、固定受入PDF、再登録件数照合 |
| Q-PERF | streaming hash、10 page既定のpart、64件batch、登録全体deadline | 外部request回数は増える | 全量読込み禁止Test、最大part page数／batch件数spy、wall time |
| Q-COMP | UUIDv4／v7両対応validator、optional failure field、stable source key | ID形式は新規Runから変わる | CLI↔UI新旧Run Lifecycle Test、旧failure読込みTest |
| Q-USE | allowlist stageと下位例外型を共通formatterで表示 | raw messageを使った詳細診断はできない | stage別CLI／AppTest、Run log／failure JSON検査 |
| Q-REL | 絶対deadline、決定的upsert、batch確認後の全体置換 | 失敗中は新旧Pointが一時共存する | Docling／write／verify／replace障害注入、Resume Test |
| Q-SEC | 例外型と固定stageだけを永続化 | Support情報を意図的に限定する | Credential、本文、raw応答、job ID sentinel Test |
| Q-MAIN | ID生成、revision計算、batch処理、診断抽出を分離 | 小さい内部componentが増える | Ruff、Format、ty、pytest、OpenSpec strict validation |
| Q-PORT | Python 3.12標準library、既存pypdfium2、canonical path前検証 | 標準`uuid7()`へ直ちに委譲できない | Windows／POSIX CI、固定clock／random Test |

## Lifecycle, Migration and Operations

- **Transition**: readerをUUIDv4／v7両対応にしてからgeneratorをv7へ切り替える。次に登録diagnostic、workspace分割、batch処理、version付きrevisionの順に導入する。
- **Rollback**: UUIDv7を読めるvalidatorは維持する。旧Codeへ戻す必要がある場合もUUIDv7 Runを改名・削除せず、新規Run作成を停止する。`registration-v2` Pointは既存metadata fieldを追加するだけであり、自動削除しない。
- **Operation**: 登録失敗時はrun ID、`REGISTER`、stage、cause type、deadlineおよび外部Service healthを確認し、原因修復後に同じrun IDを明示Resumeする。raw応答の収集は要求しない。
- **Support**: `extract`はDocling、`write`はEmbedding／Qdrant upsert、`verify`はPoint確認、`replace`は旧revision削除として切り分ける。固定受入PDFのRun Evidenceを回帰基準にする。
- **Maintenance**: Chunk size、overlap、分割または抽出結果へ影響する規則を変える場合はchunk schemaを更新し、registration revisionのmigration Testを追加する。
- **Disposal**: Runの明示削除はworkspaceのsplit Artifactを含めて削除する。Qdrant Pointと外部exportは既存どおり別Lifecycleとし、自動削除しない。

## Risks / Trade-offs

- [Docling part境界で段落または表が分断され、Chunk品質が変わる] → page順とpage範囲を保持し、固定PDFの代表箇所を検索して抽出欠落を確認する。
- [有限batchによりEmbedding／Qdrant request回数が増える] → 64件を初期上限とし、wall timeとrate-limit retryをEvidenceへ記録する。
- [登録失敗後に新revisionの部分Pointが残る] → 旧revisionを全確認前に削除せず、決定的upsertと後続成功時のrevision cleanupで収束させる。
- [UUIDv7は生成時刻を公開する] → run IDは既に利用者が参照する運用識別子であり、秘密として扱わない。入力内容、利用者Identityまたはhost情報は埋め込まない。
- [OS clockが逆行するとUUIDv7の辞書順が生成順と一致しない] → Run表示順と新旧判定には`updated_at`とfingerprintを使用し、ID順へ依存しない。
- [Qdrantの欠落fieldに対する`must_not`挙動がVersionで異なる] → legacy Pointを含むIntegration Testで削除条件を検証し、必要なら旧schema用filterを分ける。

## Migration Plan

1. UUIDv7 helperとUUIDv4／v7 validatorを追加し、既存UUIDv4 fixtureを維持したまま新規Run Testをv7へ変更する。
2. `RegistrationError`と`FailureRecord`のoptional診断fieldを追加し、全stageと秘密sentinelの障害注入Testを通す。
3. registration revision v2とlegacy cleanup Testを追加し、既存Qdrant revision置換を維持する。
4. Lifecycleから登録workspaceを渡し、streaming hash、atomic PDF split、64件write／verify batchおよび全体deadlineを接続する。
5. Unit、Integration、CLI／UI、Windows／POSIXの品質Gateを実行する。
6. `inputs/sample.pdf`を検証専用Collectionへ登録し、deadline、Chunk件数、重複、旧Point、診断情報および秘密漏えいを記録する。
7. 問題時は新規登録を停止し、既存UUIDv4／v7 Runと旧Qdrant revisionを保持してCodeを直前Versionへ戻す。自動migrationや自動削除は行わない。

<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。現行`_positive_float`は標準`float()`で変換し`value <= 0`を検査する。NaNとの比較はfalse、正のInfinityは0より大きいため受理される。Settingsの4 fieldも制約なしのfloatである。Docling/LLM/LibreTranslate/Qdrantはその値をtimeout、deadline計算、backoffへ渡す。

導入済みPydanticは2.13.5。メモリ内試験でFiniteFloatがNaN/±Infinityを拒否し、`Annotated[FiniteFloat, Field(gt=0)]`を使うTypeAdapterが正数と有限性を同時に検証できた。PositiveFloatだけでは正のInfinityが通るため不十分。既存Test多数は内部Settingsのretry_base_seconds=0で実待機を抑制している。

## Goals / Non-Goals

**Goals:** 既存の4秒数設定で非有限値を外部呼出前に拒否し、公開env契約と内部Testの互換性を維持する。検証自体は既存Libraryへ委譲する。

**Non-Goals:** retryの再設計、秒数上限の新設、backoff base/maxやtimeout/deadlineの大小関係の強制、既存長時間値の短縮、設定frameworkの新設、CLI/UIの一般的なError表示の全面改修、Settingsのunsafe構築APIの再実装。他の未解決指摘は解消扱いにしない。

## Decisions

### 1. 検証境界を既存契約に合わせる

| 境界 | 採用する既存機能 | 維持する契約 |
| --- | --- | --- |
| Settingsの4秒数field | Pydantic FiniteFloat | 通常構築で非有限値を拒否。内部Testのretry=0を壊さない |
| 環境変数の秒数変換 | 標準floatとTypeAdapterの正のFiniteFloat制約 | 従来どおり0以下を拒否し、NaN/Infinityも拒否 |
| 環境設定Error | 設定名と固定理由のValueError | 元入力文字列やPydantic詳細を公開せず、呼出側の既存ValueError処理を維持 |

共通の型/Adapterはsettings.py内で4設定に再利用する。別module・抽象framework・独自のfinite判定関数は作らない。正数境界は公開envの制約であり、Test内部の0を公開設定で許容する変更ではない。内部の他の有限値に新しい制約を追加することも本修正の目的にしない。

### 2. 数値表記と診断を不用意に変えない

環境変数の生文字列を直接TypeAdapterへ渡さず、従来の`float()`変換結果を渡す。Pydanticへ生文字列を渡すと、これまでfloatが受理した全角数字やArabic数字を拒否する差がある。空白、符号、指数、underscoreを含む有効値も回帰Testする。

変換不能または制約違反は、設定名と「正の有限数が必要」という固定理由へ変換し、既定値へ補正しない。通常tracebackで元例外を表示しないよう`from None`を使う。これは`__context__`そのものを消す機構ではなく、例外オブジェクトの任意属性の非保持を保証するものでもない。raw例外や`.errors()`を新たに保存・表示しない。

隔離した実CLI（.env無効、合成Credentialのみ）で変換不能文字列を指定すると、現行は終了コード1となり、原因例外に合成の無効設定値が表示された。修正後は外側Errorだけでなく実CLIのstdout/stderrでもmarker不在を確認する。CLI全体の設定例外処理を新設する前提にはしないが、既存表示境界でなお露出する場合は正式verifyを不合格にし、必要差分を再提示する。

### 3. 実行制御・Resumeへ波及させない

retry回数、timeoutの既定値、Task deadline、逐次実行を変更しない。新Dependencyは不要。今回の4秒数は現行fingerprintに含まれておらず、追加しない。正の有限値で生成される設定とResume互換性は変わらない。不正設定の拒否はRun作成・外部要求より前に行う。

Pydanticの`model_construct`や`model_copy(update=...)`は検証を迂回する公開APIである。現在の製品にSettingsをこれらで作る経路は見つからない。これを防ぐ独自BaseModelやcopy wrapperは追加しない。Testでもそれらで検証を迂回して合格を作らない。

### 4. grill-with-docsの判断整理

既決定の枝は、待機を有限にする、長いローカル生成を許容する、モデルを逐次実行する、不正設定を暗黙補正しない、導入済みPackageへ委譲する、の5点。本提案はその範囲の契約違反を修正し、上限値変更・並列化・再開機構追加という新しい枝を作らない。内部0の維持は現存するTestと公開env契約の境界を保つ技術的選択である。適用は本提案提示後のapply依頼で確認する。

表内画像の曖昧時の扱い、common最終配置、旧保存形式の移行という回答待ちの判断から独立している。本Changeをそれらへの同意に読み替えない。新しいDomain用語や不可逆なArchitecture判断はないためGlossary/ADRは追加しない。

## Quality Attribute Design

- Q-REL/Q-FUNC: 4 envそれぞれのNaN/±Infinity/overflow/0/負数/非数値、正の分数・長時間・既定値を表形式のparameterized Testで検査する。直接Settings構築の非有限拒否も別に確認する。
- Q-SEC/Q-USE: 合成markerで例外の通常表示・CLI/UIの表示を検査し、不正設定では外部呼出とRun作成0件を確認する。Testに実Credentialや実Serviceを使わない。
- Q-COMP/Q-MNT: 内部retry=0の既存Testと通常値のfingerprint不変を確認する。手書きのfinite判定、新module、不要なhelper、依存追加がないことを差分で検査する。
- 自動検査の後、新しいprocessで実translation→Word PDF化→原文とのComparison Reviewを実行し、成果物を利用者へ提示する。先行するsession 58094はこの修正を含まないため証拠を区別する。

## Lifecycle, Migration and Operations

運用では設定Errorに示された環境変数を修正して再実行する。既存データと実行中processは変更せず、無断Resume・再起動をしない。保守では境界TestとLibrary版を記録する。新たな取得・供給・廃止手続きは不要。

## Risks / Trade-offs

- [Risk] 生文字列の型変換を全面置換すると数値表記の受理範囲が変わる → 標準floatを維持し、その結果へ既存制約を適用する。
- [Risk] 内部Testの0拒否へ広げると修正と無関係な待機やTest改変が増える → Modelの有限性とenvの正数制約を区別する。
- [Risk] from Noneだけであらゆる秘密の保持を防げると誤認する → 診断表示に限定した保証とし、任意の例外属性やPydantic errorsを公開しない。
- [Risk] 極端に大きい有限秒数も許容される → 現行の有限値の受理範囲を維持し、新たな運用上限を未承認で導入しない。全HTTP実装が任意の巨大秒数を扱える保証とは区別する。

## Migration Plan

既存不具合の再現Testを先に作り、settingsの既存境界を修正する。自動/実機Gateの後に指摘を更新する。DB migrationやArtifact削除は不要。Rollbackはcode差分の取消で可能だが、非有限値の受理が再発するため安全性回復とは報告しない。

## 調査資料

導入済み`pydantic/types.py`、`type_adapter.py`、`main.py`とPydantic 2.13.5のメモリ内probe、製品`settings.py`、`fingerprint.py`、`tests/test_settings.py`、既存adapter Testを確認した。外部Web資料や未導入Packageの仕様には依存していない。

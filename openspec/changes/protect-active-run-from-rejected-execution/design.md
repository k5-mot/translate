<!-- markdownlint-disable MD013 MD041 -->

## Context

proposal.mdのWhyを参照。execute_runはlock前にstatus/logを更新し、lock解放後に失敗・成功を保存している。execute_public_runは例外時に保存済みfailureを再読込みするため、排他拒否と過去の所有者失敗を混同する。既存のcontext-exceeded診断の未commit差分は保持する。

## Goals / Non-Goals

既存の排他範囲とError分類を直す。新規状態機械や永続フラグ、独自lock、common配下Moduleを作らない。common移管、LangGraphの再開正本統合、削除時のlock解放後rmtreeの競合は別の未解決事項であり、本修正で追認しない。

## Decisions

1. execute_runの最外周で既存OutputLockを取得し、その内側で最新record読込み、running保存、logging設定、操作、成功/失敗保存、logging解除を行う。呼出前に読んだPreparedRun.recordだけから更新すると最新warnings等を消すので、取得後のrecordを使う。lockの有無を新しい保存フラグでは表さない。
2. workspace.py内にOutputInUseErrorを定義し、導入済みportalockerのAlreadyLockedを既存RuntimeError互換の専用型へ変換する。同期的な非blocking取得は維持し、独自のOS別排他やretryを追加しない。待機queueや暗黙Resumeへ変更しない。
3. 公開境界はOutputInUseErrorの場合だけ既存failureを再読込みせず、今回の操作に対する一時的な安全なFailureRecordを例外へ載せる。Runへは保存しない。所有者が実行中のTaskを今回の失敗Taskとして転用しない。通常の所有者失敗は従来の構造化診断を維持する。
4. 実portalockerを保持した同期的な再入試行で拒否を検証する。全操作translate/review/register/convertへ共通の境界をTestし、Model呼出は不要。記録済みfailureの有無、所有者の成功/失敗、終端保存中の拒否、log解除を含む保持範囲、拒否後のResumeを確認する。
5. ユーザーの既存要求は同期処理・排他・状態保全であり、その修復に新しい製品選択は不要。保存layoutの移行判断とは独立して進める。一般概念の排他を製品用語としてGlossaryへ追加せず、既存境界の修正にADRも新設しない。

## Quality Attribute Design

Q-RELはbyte比較と書込み時の実lock再取得失敗で証明する。Q-SECは内部path・秘密を公開Errorへ転記しないTest、Q-MNTは既存関数とportalocker再利用で確認する。単体Testを実E2Eの代替にはしない。

## Lifecycle, Migration and Operations

既存Processや保存データを変更しない。修正後に新規Runでtranslation→Word PDF→reviewを逐次実行する。既存UUIDv7のlayout移行、Run削除操作、外部exportは変更しない。

## Risks / Trade-offs

- [Risk] 部分的なlock範囲修正では終了保存に競合が残る → 状態保存・失敗保存・log設定解除のすべてを保持範囲でTest。
- [Risk] 拒否を旧failureで表示する → failureがある/ない両方のTest。
- [Risk] dirtyな診断差分の混入 → lifecycleの本Change分だけを選択stage。
- [Risk] 本修復を二重状態管理の承認と誤認する → 既存RunRecord/GraphState等の統合課題を未解決として維持。

## Migration Plan

失敗する再現Testを追加してから境界を修正する。公開署名・保存schema・依存を変えず、Code差分のrevertで戻せる。実行中Processは新Codeの検証証拠には数えない。

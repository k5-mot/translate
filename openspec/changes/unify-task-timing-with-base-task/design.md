<!-- markdownlint-disable MD013 MD041 -->

## Context

proposal.mdのWhyを参照。[Task監査](../restore-docx-tables-and-indexes/architecture-audit.md)で20件の入出力と保存境界を確認済み。関数維持と継承の併用は利用者承認済みで、commonの配置未決定とは切り離せる。

## Goals / Non-Goals

Goalは型付き関数入口と具体Taskクラスを併用し、計測だけをBaseTaskに集約すること。Non-GoalはTask順序、Graph、進捗正本、retry、保存形式の再実装。独自Page/Chunk再開の既存違反は別途追跡する。

## Decisions

1. 20 ModuleそれぞれにSplitTask、DoclingTask等の具体クラスを置く。既存module.runは同じsignatureのままTask().runへ委譲する。既存呼出元・monkeypatch・公開型を壊さずに関数とclassを併用できるため、入力DTOや汎用引数dictは作らない。
2. BaseTaskは標準contextlib.contextmanagerによるmeasure()だけを持つ。固定Task名をクラス属性として参照し、time.perf_counterの開始とfinallyの計測終了を共有する。各具体runはwith self.measure()内で既存処理を行う。metaclass、decorator自動登録、汎用execute/retry frameworkを導入しない。
3. 計測はTask全体のatomic公開を含む。MERGE/STRUCTURE/MARKDOWNの内側_run_intoから計測を除き、外側の具体runで計測する。失敗でも時間を通知するが、成功通知やcheckpoint更新は一切行わず、元例外を伝播する。既存のTIME行形式と固定page/group表記を維持する。
4. BaseTaskはWorkflow/common/progressやArtifact保存に依存しない。Task instance、計測時刻、結果を永続化しない。新しい状態管理を追加しないことをsource依存と実行Testで確認する。
5. 全Taskの旧関数と具体classの引数・既定値・keyword-only・戻り値型の対応を検証する。失敗・成功計測は動的Testを主とし、旧Testの「各fileにperf_counter文字列がある」を継承と委譲の実行検証へ置き換える。

## Quality Attribute Design

Q-MNT: 20 Moduleのclass化と共通計測1か所を検証。Q-COMP: モデルを呼ばないstubで20関数の引数転送と例外/戻り値を照合し、既存suite・Ruff・tyで回帰を検出する。Q-REL: 成果物公開後の計測終了、失敗時1回、例外identityの保持を確認する。Q-SEC: 時間と固定名以外を出力せず、失敗本文を計測へ追加しない。

## Lifecycle, Migration and Operations

既存Run、入力、成果物を変更しない。既存関数を維持するのでCLI/UIの呼出変更は不要。実行中E2Eの証拠をclass化後の製品検証へ流用しない。完了後、class化後の実translation→Microsoft WordでPDF化→入力PDFとのreviewを逐次実行する。

## Risks / Trade-offs

- [Risk] 転送時に任意引数を落とす → 全20signature/引数転送Test。
- [Risk] Task完了と時間通知を混同する → BaseTaskに状態更新APIを持たせず、失敗でも計測のみ行う。
- [Risk] class化で大量の固有処理まで変更する → 既存処理を保持し、移動・計測除去・説明追加に限定。
- [Risk] REVIEW等に既存の未commit差分がある → 既存差分を保存し、本変更の移動・計測差分だけをcommitする。

## Migration Plan

共通baseとTestを追加し、20 Taskを移行する。旧重複計測は除去する。失敗時は本ChangeのCode差分を戻せばよく、データrollbackは不要。利用者の最終Word/PDF確認と未解決監査項目を他Changeの完了として相殺しない。

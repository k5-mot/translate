<!-- markdownlint-disable MD013 MD041 -->

## Context

[proposal.md](proposal.md)のWhyを参照。導入版はLangGraph 1.2.11、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1。既存のTranslationとComparison Reviewは`SqliteSaver.from_conn_string()`を使用し、Task wrapperは例外を通知後、そのまま再送出する。公開Failureの安全化はGraphによる例外保存より外側にある。

現行Testの`test_workflow_state.py`は正常なpath中心stateを持つ最小Graphを検査するが、製品Graphの例外保存を検査していない。`test_failure_contract.py`の多くもWorkflow全体をdoubleへ置き換えるため、SQLite経路を通らない。

## Goals / Non-Goals

**Goals:** 現行の`__error__`保存経路を安全化し、既存の例外伝播・公開診断・有限retry・CheckpointによるResumeを保持する。

**Non-Goals:** 新しい再開機構、汎用redactor、全serializerの再実装、Graph stateへの本文保存の許可、過去DBの無断改変、旧UUIDv7移行、common配置の最終決定。既存の二重進捗・Page/Chunk Cacheの問題をこの変更で解決済みにしない。

## Decisions

### 1. LangGraphの公開serializer境界へ委譲する

`adapters/checkpoint.py`に、既存`JsonPlusSerializer`を継承して直接渡された`BaseException`だけを固定文字列`TaskError`へ変換するserializerと、SQLite接続寿命を管理する小さい入口を置く。例外の`str`、`repr`、`args`、型名、任意属性、cause/context、notesを直列化へ渡さない。通常値の保存と全値の復元は既存serializerへ委譲する。pickle fallbackや追加の型許可は有効にしない。

Checkpointが持つnode名/Task IDは従来どおり維持する。Page、対象ID、LLM stage、原因分類、token数などの既存の許可済み公開診断は、元の例外を受ける現在のFailure通知から取得する。本文保存の代わりにもう一つの診断台帳を作らない。固定分類の採用はSQLiteの内部失敗表現だけを変え、公開FailureRecordを一律`TaskError`へ置換するものではない。

利用元は2 WorkflowのCheckpoint生成箇所。`from_conn_string()`にserde引数はないため、標準`sqlite3.connect(..., check_same_thread=False)`と`contextlib.closing`で管理した接続を`SqliteSaver(conn, serde=...)`へ渡す。SQL、DB schema、transaction、lock、pending writes、thread ID、Graphの実行・復元は実装しない。新しいsaverを自作・継承する必要もない。

### 2. この配置にする理由と代替案

- `adapters/`は既存Libraryとの境界を置く承認済み区分であり、2 Workflowの実利用がある。新moduleの責務は「Checkpoint serializerへ製品の例外非保存方針を適用する」に限る。
- `common/`や`utils/redaction.py`へ追加しない。文書Artifactのloader/saverへ混ぜると本文を保存すべき経路まで変質するため、`utils/artifacts.py`の責務とも分ける。
- 2 Workflowにserializerと接続処理を複製すると一方だけが無保護になり得る。既存Workflow間の逆importや、Langfuse adapterへの混在も避ける。
- nodeで全例外をRuntimeErrorへ置換する案は、例外型を使うretry/呼出側の判定を変える。導入済みのGraph error handlerはエラー保存後に動くため漏えい防止境界として遅い。
- Checkpointer自作、Libraryのprivate関数patch、保存後のSQL書換え、例外自由文の正規表現maskは採用しない。最後の案では既知秘密以外の本文を除去できない。

### 3. 調査で確認した適用範囲

`SqliteSaver.put_writes()`は各writeの値を個別に`serde.dumps_typed()`へ渡す。標準serializerは通常例外を`repr()`で保存するが、dataclass例外の属性など、先行する型分岐で保存される場合もある。入口でBaseExceptionを判定することで両方を抑止できる。

ただし、dict/listの内側へ任意に入れた例外、文書本文を含むGraph state、config metadataは、この直接例外の変換だけでは保護されない。特にmetadataはSqliteSaver内の`json.dumps()`を使いserdeを通らない。現行state/configはpath/小metadataのみという既存要求を維持し、製品経路のTestで混入しないことを別途確認する。汎用recursive redactorを追加してその検査を代替しない。

Graphのtask/debug streamは元例外を含み得る。今回の製品はそのpayloadをそのまま公開しておらず、新しいstream公開も追加しない。今後の進捗正本化では、安全な値だけを抽出し、payloadやreprを丸ごと表示・保存しないことが必要である。Graph Retryのlogも別境界であり、本変更はその安全性を保証しない。現在の2 WorkflowはGraph RetryPolicyを指定していない。

### 4. 制御と互換性

serializerは例外をcatch/raiseし直さず、実行時の元オブジェクトを変更しない。GraphBubbleUp、GraphInterrupt、取消、KeyboardInterrupt、SystemExitの処理は既存Libraryへ委譲する。GraphInterruptのpayloadは例外でなくSequenceとして保存されるため、本対策では変更されない。製品は現在動的interruptを使用しない。将来導入時にも安全なID/分類だけを渡す必要がある。

通常state、成功結果、既存DBの復元を変更しない。旧serializerが書いた本文を含まない合成DBを開き、失敗nodeだけを再実行できることを確認する。過去行の自由文まで自動消去したとは報告しない。

### 5. 計画の判断整理（grill-with-docs）

既決定の枝は、本文/秘密を保存しない、再開管理はLangGraphへ委譲する、commonを増やさない、全モデル処理を逐次実行する、実成果物でverifyする、の5点。未決の旧保存形式移行・全操作layout・common最終配置は別Changeの枝であり、本修正では判断しない。

本設計は既存契約を満たす実装案として提示する。新adapterの責務と理由を上記に限定し、実装開始は計画提示後のapply依頼で確認する。新しいDomain用語はなく、serializerは一般の実装概念なのでCONTEXT.mdへ追加しない。容易に差し替え可能なLibrary境界であり、採用済みの新ADRも作成しない。

## Quality Attribute Design

- Q-SEC: 実製品Graphの通常例外/custom repr/dataclass例外/例外chainを含む障害注入で、DBとWAL、pending writes、再読込snapshot、公開Failureの合成marker不在を検査する。serializer単体合格だけを統合の証拠にしない。
- Q-REL/Q-COMP: 接続を閉じて開き直したResumeで成功済みTask呼出数不変、失敗Taskのみ追加1回。既定serializerとの通常値の往復互換性、例外型とretry回数、制御例外の意味を確認する。
- Q-MNT: 呼出元2件と小さいadapterだけに修正を限定し、既存SQL/serialization/再開処理を複製しない。全関数に目的説明を付ける。
- Q-FUNC: 自動Gate後に新コードを読み込んだ実translation→Word PDF→Comparison Reviewを逐次実行し、ユーザ目視の対象DOCX/PDFを特定する。旧processと新コードの証拠を混同しない。

## Lifecycle, Migration and Operations

現行の実translation session 40709を停止・再起動しない。終了をlive handleで確認してから、修正後の逐次実機Gateへ進む。失敗時はCheckpointとArtifactを保持し、原因を追跡して勝手に新Runや追加モデル要求を繰り返さない。

過去DBは無断で変更・削除しない。採用時に既存失敗行を読取り専用で調べる場合も本文を表示せず、影響の有無・件数と対象IDだけを報告する。漏えいの疑いが残ればverificationへ記録し、権限が必要な消去をこのChangeの副作用として行わない。

## Risks / Trade-offs

- [Risk] 固定分類でCheckpointだけの診断情報が減る → node/Task IDを保持し、既存の安全な公開Failure診断が維持されるTestを必須にする。
- [Risk] 将来nested例外やmetadataへ本文を保存してしまう → 直接例外変換の適用範囲を明記し、Graph入出力はpath/小metadataに限定する既存契約を検査する。
- [Risk] 過去のunsafe行が残る → 新規書込み防止と過去データの浄化を区別して報告し、疑いを未解決事項として保持する。
- [Risk] 接続のclose漏れ・Windowsでのlock保持 → 成功/失敗双方のclose後にDB再接続と一時Test directoryの後始末を検査する。

## Migration Plan

新たなschema移行は不要。既存APIへの接続箇所だけを切り替え、自動Gateと実機Gateを実行する。RollbackでもDB形式の変換は不要だが、旧コードへ戻すと例外本文保存が再発するため、安全性を回復したとは扱わない。

## 参考資料

- [SqliteSaverの公開API](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver): `serde`注入と標準SQLite接続の使用。
- [JsonPlusSerializer](https://reference.langchain.com/python/langgraph.checkpoint/serde/jsonplus): 型付きserializerの公開境界。
- 導入済み実装: `langgraph/checkpoint/sqlite/__init__.py`の85/99/421/478行付近、`checkpoint/serde/jsonplus.py`の258/531行付近、`pregel/_runner.py`の579〜603行、`pregel/_retry.py`の618〜676行、`pregel/debug.py`の118行付近を確認。行番号は上記導入版の調査時点。

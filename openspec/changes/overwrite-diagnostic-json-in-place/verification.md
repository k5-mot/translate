<!-- markdownlint-disable MD013 MD041 -->

# Verification: overwrite-diagnostic-json-in-place

## Apply中間結果（2026-09-25）

利用者の承認に基づき、EvidenceStoreの保存だけを直接上書きへ変更した。既存PydanticでJSON生成後、既存portalocker内で旧終端保護、open/write/flush/fsync/closeを行う。workspaceのatomic writer、子process要求保存、入力・成果物・Checkpointは変更していない。依存・Module・retry・成功台帳は追加していない。

### Test先行と障害注入

- 旧実装に対し、新しい保存境界のTestは7 failed / 1 passed。直接保存非使用、serialize境界、truncate/部分write/flush境界が旧動作と異なることを確認した。
- 変更後は対象8 Testが成功。追加の実子process強制終了と最終fsync失敗を含め、tests/test_terminal_evidence.pyは37 passed、7.00秒。
- serialize/open前の失敗では旧JSONを保持する。truncate/部分write後は旧状態を保証せず、空/不正JSONをNoneとしてGateを拒否する。flush/fsync失敗もそのまま伝播し、各障害後にlockを取得して再更新できる。
- 実EvidenceStoreのwriteを途中で停止させた所有childは、親がhandleのlive状態を確認してkill/waitした。不完全JSONの拒否、次の保存、隣接する合成入力の不変を確認。利用者のRun/processを停止していない。
- 完全なcompleted JSONがあっても、watchdogの最終fsyncを失敗させたTestでは成功結果を返さずOSErrorを伝播した。File内容だけでfsync成功を検出できると主張しない。既存allows_public_resumeは内容検査であり、process終了と保存呼出しの成功を別途確認する必要がある。
- lock Testは旧atomic writerのspyを廃止し、実File open/closeとfsyncの単一lock保持を検査する。無関係なFile保存APIをstubして合格にしていない。

### Repository内の実親子I/O

所有TemporaryDirectoryで親がEvidenceStore.writeを繰り返し、childが同じFileのEvidenceStore構築/readを繰り返した。各試行は12秒上限、3回逐次。childのstdoutは合成read件数だけを回収し、モデル・外部サービスは使用していない。

| 試行 | write件数 | read件数 | child exit | I/Oエラー |
| --- | --- | --- | --- | --- |
| 1 | 2382 | 1803 | 0 | なし |
| 2 | 2323 | 2522 | 0 | なし |
| 3 | 2334 | 1782 | 0 | なし |

session 17073はexit 0、合計7039 write / 6107 read。全child handleを回収し、所有一時領域のみ自動cleanupした。以前の原子的置換の失敗は取り消さず、新方式について今回の条件で非再現と判定する。任意の共有環境・電源断・lock非協調readerへの保証ではない。

### 残る受入

全体pytestは668 passed / 1 skipped、46.18秒（session 12357 exit 0）。全体Ruff check、format（348 files）、ty、対象OpenSpec strictとgit diff --checkは成功。文書更新後のdocumentation Testも21 passed。Testの初回Lint指摘（未使用import/引数、長いTest、例外match不足）は今回のTest内で修正し、規則緩和なしで再検査を通した。

検査対象はHEAD 31f2851に既存未commit差分と今回の修正を含むworktreeであり、commit単独の検証ではない。SHA-256はterminal_evidence.pyが6464434b7de49c983c42793c453a9e102973c020a2d014266b90591321863738、Testがda0395515c0def54f4f1834afa93de6664ce64444c8701860af37f791369e6c6。製品Fileのhashには別件のFailureKind/context-exceededも含むが、その1行は今回のcommitから除外しworktreeへ保持する。他のLLM/Review/Lifecycle差分、.agents、サンプル、outputs/runsも含めない。

7/8 Tasks完了。reasoning OFFのsample3翻訳→Microsoft Word PDF→比較Reviewは、simplify-translation-literal-checksの実装後に同じ実行で検証する。Task 2.4は未完了であり、正式verify成功・archive可能とは判定しない。

### 共通実E2Eの進捗（2026-09-25更新）

[文字列検査簡素化の実検証記録](../simplify-translation-literal-checks/verification.md)に、翻訳Run 01a0d8b6-c2ab-7c92-bed9-58403a8410b3のexit 0（2366.730秒）、実LLM要求97件のreasoning OFF、DOCXとWord PDFのhashを記録した。翻訳は通常CLIであり、この保存境界の実親子検査は後続比較へ接続している。

最初の比較起動は検証側の入力role誤りで、Run 01a0d8df-90fc-7eb1-a686-cb8a59c2ab77がKeyError・child exit 1で終了した。comparison-terminal.jsonへ安全なfailed終端と各外部呼出し0を保存し、所有tempのみcleanupできた。これを成功のE2Eとしない。

公開CLIと同じroleへ訂正した新規比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2は、別名comparison-terminal-corrected.jsonへ既存lock下でheartbeatを直接保存しながら実行中。14:14 UTC時点で共有I/O障害は観測していないが、終了・最終counter・cleanup・成果物整合は未確認。Task 2.4は未完了のままとし、途中保存の成功を終端回収の成功へ読み替えない。ALIGN誤対応などの品質問題も共通記録で保持する。

### 終端回収とcounter不整合（2026-09-26）

上記比較Runはcompleted・child exit 0・finished_at=2026-09-25 14:25:52.669267 UTCを保存し、対象親子Processは終了、所有tempもcleanup済みだった。共有I/O例外の記録はない。公開reportと入力hashの確認は[共通E2E記録](../simplify-translation-literal-checks/verification.md)へ記載した。元toolの親handleが失われたため、親の終了コードを直接取得したとはしない。

終端Evidenceのllm_calls/embedding_calls/qdrant_callsはすべて0だったが、同じRunのLangfuseにはLLM要求39件がある。したがって、終端保存そのものと計測値の正しさは区別し、Task 2.4は未完了のまま保持する。

コードではdebug childをpython -m translate.common.terminal_evidenceとして実行する一方、adapterは同Moduleを通常名でimportする。外部通信なしのrunpy切分けでは、同じFileを別Module名でロードすると_CALL_COUNTSは別objectとなり、別名側でbindして通常名側でcountすると0、同じ通常名側でbind/countすると1だった。これはmodule identityによるcounter分離を再現する合成証拠であり、実childの全計測経路を修正検証したものではない。新しい独立counterや再開台帳を追加する対処は行っておらず、別Changeまたは責務整理で既存の状態共有境界を是正する必要がある。

### 計数入口の修正（2026-09-26）

[reuse-canonical-detached-child-module](../reuse-canonical-detached-child-module/verification.md)で実-m childの成功/公開失敗時の0件を再現し、通常importした既存mainへの委譲で既知hook回数が保存されることを確認した。新規状態管理は追加していない。旧JSONは未変更。LLMはinvoke試行数、Embedding/QdrantはClient生成等の異なる粒度であり、timeout途中値も完全な計数ではない。物理通信回数の正確性まで解決したとはしない。修正後の新規実E2Eが必要であり、本ChangeのTask 2.4は未完了のまま保持する。

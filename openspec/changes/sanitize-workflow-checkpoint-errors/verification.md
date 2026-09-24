<!-- markdownlint-disable MD013 MD041 -->

## 計画時点の状態（2026-09-25）

本Changeは提案のみ。製品実装0/11 tasks、正式verify・archive・merge・pushは未実施。[元の指摘](../clarify-code-documentation-and-reuse-rules/verification.md)のSECURITY-CHECKPOINT-001は未解決のまま。

## 再現と導入済みAPIの証拠

- 実製品`translation.build_graph()`のSPLITだけを合成例外へ置換し、network禁止・メモリSQLiteで調査した。既定の保存では`__error__`とsnapshotに本文markerが残る。
- 同じ実Graphへ公開`SqliteSaver(conn, serde=...)`から、直接BaseExceptionだけを固定文字列へ変換する実験用serializerを渡すと、SQLite内本文marker=false、custom repr marker=false、再読込のtasks.error=`TaskError`となった。呼出元へは元のRawError型が伝播した。
- 標準serializerでは、普通の例外のcause/context/notes/任意属性は直接保存されなかったが、dataclass例外のfieldとcustom reprが参照する属性は保存された。通常例外一種類のTestだけでは不十分。
- 直接例外だけの変換ではnested dict/list内例外とconfig metadataの文字列は保護されなかった。後者はSqliteSaverのjson.dumpsでserdeを迂回する。製品Graphのstate/configへの本文持込み禁止を緩めない。
- Graph task/debug event formatterは元errorオブジェクトを保持した。永続化の対策をstream/ログの安全化と同一視しない。
- 同期・逐次の実Graph合成試験で、GraphBubbleUpは同型伝播しerror保存なし、GraphInterruptはLibraryが処理してinterrupt payloadを保存、asyncio.CancelledErrorはNodeCancelledErrorへ変換、KeyboardInterrupt/SystemExitは同型伝播し当該経路でerror保存なし。製品wrapperはこれらもfailed通知するため、将来interruptを製品へ導入するときの扱いは別途検討が必要。
- 上記はすべて外部Service・利用者文書を使わない調査用試験で終了コード0。製品ファイルとTestファイルは未編集。提案の有効性を示すが、正式な回帰Test・製品への接続・別接続Resume・実機検証の代わりにはならない。

## 既存実翻訳

session 40709へwrite_stdinを行い、同じlive sessionが返ることを確認した。初回は追加出力なし、再確認時には`FIX 1440.792 s`と`[12/17] FIX`の完了通知が得られた。終端結果はまだ得ていない。沈黙を失敗と判定せず、停止・再起動や追加モデル処理を行っていない。このprocessは本Changeの未実装コードを読み込んでいないため、完了しても修正検証の証拠にはしない。

## 残課題と判定

- CRITICAL: 本Changeの全実装・統合・実成果物Taskは未完了。メモリ試験のみで安全性を達成したと判定しない。
- 過去に保存された例外情報は未調査・未変更。新規保存を防ぐ修正で過去分も消えたとは主張しない。
- common最終配置、旧UUIDv7移行、全操作の新layoutの未回答事項は、独立した既存の確認事項として保持する。本提案をそれらの承認に読み替えない。
- 正式verifyには修正後translation→Word PDF化→原文/生成PDFのComparison Reviewとユーザ目視が必要。新たな指摘があれば保持し、archiveへ進めない。

## 計画文書の検査

- `openspec status --change sanitize-workflow-checkpoint-errors --json`: proposal/design/tasksがdone、specsは既存要求の不具合修正のためskip_specsでskipped。これは計画Artifactの存在確認であって、実装完了を意味しない。
- `openspec validate sanitize-workflow-checkpoint-errors --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed（0.24秒）。
- `git diff --check`: 指摘なし。
- 製品Codeを編集していないため、全製品Test・Ruff・型検査・実機Gateは本提案ターンでは未実行。tasks.mdに残す。

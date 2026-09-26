<!-- markdownlint-disable MD013 MD041 -->

## Apply結果（2026-09-26）

Task 1.1〜1.3と2.1を完了し、4/6。実PDFの新規E2Eと利用者目視は未完了。製品実装はcli.py、main.py、translate/tasks/base.pyの計測printのみをcontextlib.suppress(OSError, ValueError)で保護した。新Module・依存・設定・保存状態は追加していない。

- 先行回帰Test: 48 failed / 47 passed、2.59秒。成功結果、元例外、SystemExit、中断、必須保存の例外が計測stream障害へ置換されることを修正前に再現した。
- 修正後の最終関連Test: tests/test_timing_contract.pyは114 passed、2.54秒。既存47件を保持し、67件を追加した。
- 全体pytest: session 31997、799 passed / 1 skipped、47.49秒、exit 0。WindowsでPOSIX PTYの既存Testをskip。PYTHONUTF8を追加せず実行した。
- 全体Ruff check、format check（367 files）、ty、OpenSpec strict、git diff --checkが成功した。追加Testの初回Lint指摘は行整形・例外match・raises内の単一呼出しへ修正し、規則を無効化して回避していない。

Q-REL/Q-FUNC: Task/CLI/UIそれぞれでBrokenPipe、閉じたStringIO、通常OSErrorを注入した。戻り値または元例外identity、SystemExitのcode、本体1回、計測出力1回を確認した。公開入口は実Moduleをimportし、その実__main__節のASTを動的に実行した。本体とstreamだけをstub化し、境界の制御をTest側へ複製していない。OS process終了時の遅延flushの検証ではない。

Q-COMP/Q-MNT: Taskのclass/関数入口、引数転送、成果物公開後までの計測範囲、正常時のstdout形式を維持した。製品の3境界に標準Libraryを直接使用し、新しいHelperや共通Moduleを設けていない。時計読取り・本体・保存は抑制範囲外であり、OSError/ValueErrorの必須保存失敗とKeyboardInterrupt/SystemExit/RuntimeErrorの表示失敗は伝播する。

Q-SEC: 計測要求が従来のTask名・時間だけで、失敗本文・credential-sentinelを含まないこと、stdout/stderrへのfallback出力がないことを確認した。Testは外部Model/Embeddingを呼ばず、既存の秘密情報・保存・入力保護の全体回帰も成功した。

実装前には[直前の実検証](../reuse-canonical-detached-child-module/verification.md)のfailed終端・所有Process終了を確認した。そのRunは本修正前のCodeであり、本Changeの実E2E証拠へ流用しない。Run入力・Checkpoint・既存成果物を削除せず、今回の変更による移行も不要。既存未commit変更、.agents、サンプルPDF/DOCX、outputs/runsはcommit対象に含めない。

## 残る受入

Task 2.2の適用後の新規translation→Microsoft Word PDF→原本とのreviewと、Task 2.3の利用者目視は未完了。直前の実翻訳はLLM接続関連HTTP 500で停止しているため、接続復旧を確認してから逐次検証する。自動Testの成功をE2E・最終品質の合格へ読み替えない。

12:41:22.967494 UTC、文書を含まない「OKのみ返す」短い要求を同じSTRUCTURE Modelへ1回だけ送った。reasoning_effort=none、thinking無効、最大32 tokens、retryなし。診断要求だけの30秒timeoutに対し30.219秒でReadTimeoutとなり、復旧は未確認。製品の1800秒timeoutを変更したわけではなく、これだけでModelが停止したとも判定しない。新規Run・Resumeを開始せず、LLM/接続先サービスの確認待ちとする。

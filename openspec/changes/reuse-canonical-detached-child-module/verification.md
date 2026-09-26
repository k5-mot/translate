<!-- markdownlint-disable MD013 MD041 -->

## Apply検証（2026-09-26）

4/5 tasks完了。実Modelの新規E2Eと正式verify・archiveは未完了。

- 実装前にWindowsのProcess一覧でPython/uvが存在しないことを確認した。
- 本番`run_public_run_detached()`の実`python -m`起動へ、Test専用sitecustomizeで設定と公開処理fixtureを注入した。socket接続を禁止し、Run入力と終端JSONは実際に保存する。製品処理全体の実E2Eではない。
- 修正前: 成功/公開失敗の2ケースとも、status・exit・実行1回・cleanup検査を通過した後、期待2/1/3に対してLLM/Embedding/Qdrant計数が0/0/0で失敗。2 failed、7.55秒。
- 修正後: `__main__`入口を通常importした既存`main()`へ委譲し、同2ケースが期待値を保存。2 passed、7.96秒。新Module・依存・計数台帳・設定・Schema変更なし。
- 実LLM Adapterと応答stubによる検査では、一時接続失敗→成功は2試行、有限retry終了の失敗は3試行。各ケースを連続2回束縛して値の混入がないこと、束縛解除後のhookが以前の値を変更しないこと、外部socket呼出し0を確認した。
- 関連Testは41 passed、11.55秒。既存context入れ子・例外復元、実convert child、watchdog、JSON排他/直接書込み、cleanupを含む。秘密sentinelをFailure理由へ入力しても終端JSONに含まれないことを確認した。
- 最初のself関数importはtyが解決できなかったため、module importと属性呼出しへ調整した。`__main__`と通常moduleの区別が目的のため、当該1行だけRuff PLW0406を説明コメント付きで抑止した。全体の規則は変更しない。
- 最終版の全体検査: Ruff check成功、format 362 files、ty成功。pytest session 76689は732 passed / 1 skipped、47.58秒、exit 0。WindowsでPOSIX PTY試験をskip。前のsuite session 92440も732 passed / 1 skipped、48.91秒で終了したが、途中のimport調整後に開始した76689を最終証拠とする。二つの自動Test実行は一部重なった。実Model/Embedding処理は起動していない。
- OpenSpec strict validationとgit diff --check成功。

検査基点はa8f17c9と既存未commit差分を含むworktree。製品File SHA-256はac595e2e298bc2cdc62ebe82e53586fe63131e9c6fdf1b6ff9bcc83f175470f1、Testは88e115a36f176d0639b746793be940a4e372a3af0e2fdb21b49760d50d97412b。製品hashには既存FailureKind/context-exceeded差分も含むが、その1行を本commitに含めない。他の既存差分・.agents・サンプル・outputs/runsも含めない。

## 計測の限界と残る指摘

- 旧比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2の0値は計測不成立。原記録を保持し、未呼出しの証拠として使わない。
- LLMはAdapterのinvoke試行数。Langfuse spanはretryを内包するため、件数は無条件には一致しない。
- EmbeddingはClient生成試行数、Qdrantは登録Client生成と検索retry外のhook回数。物理通信回数や同時実行数の証拠にはならない。この粒度の課題は本修正では未解決。
- 途中heartbeatは計数を更新しないため、強制終了/timeoutの0値も未呼出しを証明しない。今回確認した終端保存は成功とPublicRunErrorの経路。
- Task 2.2はreasoning OFF・逐次のsample3新規Translation→Word PDF→Comparison Reviewで検査する。旧結果は修正後の実E2E証拠に流用しない。用語集Changeの受入と共有し、ALIGN/表内画像/利用者目視などの未解決指摘を保持する。

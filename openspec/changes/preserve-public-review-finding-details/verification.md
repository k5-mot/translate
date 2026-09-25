<!-- markdownlint-disable MD041 -->

## 状態

実装と自動回帰検査まで完了（5/9 tasks）。正式verify・archive・main merge・pushは未実施。COMPARE-REPORT-001は実成果物での検証を残しており、[元の指摘](../restore-docx-tables-and-indexes/verification.md)を正式解決済みにしていない。

## 調査根拠

- `comparison-review`の全Requirement/ScenarioをCLIで確認した。「問題と根拠をReportする」が既に対象・根拠・修正方針の公開を要求するため、要求変更なしの実装修正としてdeltaを省略する。
- 修正前のreport.pyのMarkdown出力はseverity/kind/messageのみ。既存Testはevidence/suggestion付きFindingを入力するが、公開Markdownの全fieldを検査していなかった。
- 先行メモリ試験はREPORTの保存関数のみをcaptureへ差し替え、対象ID/根拠/修正方針のmarker欠落とJSON完全保持を示した。これはPDF/LLMを通す実受入試験ではない。
- 読取り専用の補助調査では、Group IDは比較Document側の`alignment/<index>`から導出可能、REVIEWの未知IDは現Modelで拒否されない、元PDFページ番号はREPORT入力だけでは解決できないと確認した。
- 導入済みmarkdown_it 4.2.0のメモリ試験では、既存markdown._escapeはHTML/実体参照のliteral保持を保証しなかった。既存code描画の動的fence方式は試験文字列をliteralとして保持した。製品にHTML中間変換を追加する提案ではない。

## 実行中Reviewの扱い

2026-09-25、既存session `12758`を同一handleでpollし、liveのままであることを確認した。Runは`01a0d534-b9c9-7e60-9edf-7541d26b6e05`。停止・再起動・並行モデル要求は行っていない。これは先行TranslationのWord PDFに対する旧REPORT実装のReviewであり、本Changeの検証証拠として流用しない。終端は未確認。

## 計画レビュー

grill-with-docsによる境界確認で、既存Finding情報の公開に限定し、未知ID拒否や元PDFページ解決を暗黙追加しない。None/空文字の区別、未知対象の明示、自由文のliteral表示はdesign.mdに示した表示案で、次のapply前のレビュー対象。用語変更や不可逆な設計判断はないためGlossary/ADRを新設しない。

未承認のcommon移管先・旧UUIDv7移行・表断片の曖昧な結合方針を本Changeで確定した扱いにしない。全体goalと元Changeの既存残課題は維持する。

## 文書検査

提案時点の検査:

- `openspec status`: proposal/design/tasksの3 Artifact complete、specsは明示skip。提案時点では実装Taskは全9件未着手。
- `openspec validate preserve-public-review-finding-details --strict`: valid。
- `uv run pytest -q tests/test_documentation.py`: 21 passed（0.25秒）。公開Findingの新規Testや製品全suiteは、この文書提案では未実行。
- `git diff --check`: 指摘なし。既存の無関係な変更を維持し、今回の文書と元指摘への参照だけをコミット対象とする。

これらの合格は計画文書の検査であり、製品不具合の解消・正式verify成功を意味しない。

## Applyの実装証拠（2026-09-25）

- 修正前、公開fieldを検査するassertを既存比較Testへ追加し、CHECK/REVIEW両経路の直接REPORT Testも追加した。`tests/test_comparison_capability.py`は3 failed / 1 passed（2.11秒）。`alignment/0`が公開Markdownにないため失敗し、既存Testの見落としを検出した。
- `translate/tasks/report.py`で対象ID・根拠・修正方針を全件表示し、対応一覧へ既存のalignment/indexラベルを付けた。未知対象は元IDを残して対応情報なし、空対象は対象未指定、None/空文字は別表示とする。元のFinding/Group Model、JSON全field、集計・順序は変更していない。
- 自由文は動的fenceでliteral表示する。既存code描画の小さな方法をREPORT内で使用し、Blockを偽造するadapterや新しい汎用描画moduleは作っていない。標準re以外の製品import追加はない。導入済みMarkdown parserはTestでのみ使用し、HTML成果物を作らない。
- 回帰Testは17 passed（2.12秒）。CHECK/REVIEWの全field、None/空文字/空白、複数/未知対象、caption/cell、多対多・片側未対応、順序/集計/JSON一致を検査した。6種類の特殊文字入力について、parserがraw HTML・リンク・画像tokenを作らず、内容をliteralとして保持することを確認した。
- 公開経路Testは外部解析とモデル処理をdoubleへ置換し、REPORT・CLIのRun準備/公開・export・UIのdownload関数は実実装を通した。実REPORTのbytesとCLI --output、export先、download_buttonへの受渡しの一致を指摘あり/0件の両方で確認し、入力hash不変と外部HTTP呼出0件も検査した。ブラウザの実ダウンロードや実PDF解析を代替するTestではない。
- `uv run ruff check .`: passed。`uv run ruff format --check .`: 328 files already formatted。`uv run ty check`: passed。`uv run pytest -q`: **587 passed, 1 skipped（39.84秒）**。
- SkipはWindowsで実行対象外のPOSIX PTY Test。個別の`pytest -q -rs`でも既定のskip理由を確認した。今回追加した公開REPORT Testにskipはない。
- `openspec validate preserve-public-review-finding-details --strict`: valid。`git diff --check`: 指摘なし。追加関数・入れ子のTest代替関数には目的説明を付与し、追加のmodule・依存・外部要求・再開台帳がないことを差分で確認した。group_idsは呼出中に既存groupsから導出する表示用集合で、永続化や再開判定には使用しない。

2026-09-24 21:25 UTC（JST 2026-09-25 06:25）、session 12758を同一handleでpollしliveを再確認した。旧processに読み込み済みのREPORTを今回の修正で置換・reloadしておらず、その終了結果を新実装の検証とみなさない。逐次実行のため、新しいTranslationはまだ開始していない。tasks 3.1〜3.4とCOMPARE-ALIGN-001、表品質、common/再開統合などの残課題は継続する。

## 先行Reviewの終了と最新翻訳のResume（2026-09-25 07:30 JST以降）

### 先行Reviewの終端

同一session `12758`から終了コード0を取得した。REVIEWは5543.097秒、REPORTは0.013秒、TOTALは5615.091秒。Run `01a0d534-b9c9-7e60-9edf-7541d26b6e05`の保存状態もcompleted / REPORT、updated_atは2026-09-24T22:30:12.733634Zだった。途中で停止・再起動せず、モデル実行を重ねていない。

診断JSONには291対応Groupと417 Finding（CHECK 247、REVIEW 170）があり、重大度はerror 320 / warning 97。417 Findingすべてに対象IDがあり、この実データの未知対象参照は0件だった。根拠を持つ299件中90件、修正方針を持つ117件中98件の文字列が公開Markdown内に存在せず、根拠/修正方針の独立ラベルも0件だった。これは大文字小文字を区別する文字列存在検査による欠落件数であり、他の箇所で偶然同じ文言が見つかった値まで正しいFindingへ関連付けられたとするものではない。

先行processが読込み済みだった旧REPORTの欠落を実データでも確認した。COMPARE-ALIGN-001の誤対応があるため、417を実際の翻訳欠陥数と解釈しない。終了コード0でも比較受入は不合格であり、本Changeの修正後E2E完了を意味しない。

| Artifact | SHA-256 |
| --- | --- |
| Run outputs/review.md と export先 sample3-acceptance-v2/comparison-review-20260925.md | `88d1f3d5ca0934d6fa5a7b962f9a10cebca564741645122b59e5a6ca25176928`（両者一致） |
| Run .workspace/report/review.json | `a2ad8915b5119ab3794721d5e1e0b3f65432961d575970938280acdaed432bf4` |
| 入力 inputs/sample3.pdf | `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`（不変） |
| 比較先 sample3-acceptance-v2/document.ja.pdf | `c6ddeac815919742b20a95af5882832658261eed797a7732c0635fca543cbab4`（不変） |

### 修正版REPORTへ実データを渡した追加検査

上記JSONを既存AlignmentGroup/Findingとして検証し、CHECK 247件とREVIEW 170件を現在のReportTaskへ渡した。置換したのはatomic_write_text/jsonの保存先captureだけで、実描画処理をメモリ内で実行した。過去のMarkdown/JSONは書き換えていない。LLM・Embedding呼出、HTML成果物の生成はない。

導入済みmarkdown_itのtokenを指摘見出しごとに区切り、各Findingの重大度/種別・message・全対象ID・非空のevidence/suggestionがそれぞれの区画のliteralに出現する回数まで比較した。417区画、項目欠落0件、生HTML token 0件、出力JSONと入力診断JSONの完全一致を確認した。本文はログへ出していない。None/空文字の表示は既存回帰Testの対象で、この追加検査では非空fieldの実データ保持を検査した。

これは実データによるREPORT単独の検査であり、最新translation→Word PDF→reviewおよび公開exportの代替にはしない。tasks 3.1〜3.4は未完了のまま維持する。

### 最新コードでの翻訳Resume

先行Reviewの終端を確認した後、07:32 JSTまでに以下を開始した。sessionは`43282`。再開前にfingerprintの互換性True・差分0件を確認し、CLIも同じIDとmode=resumeを出力した。保存状態はrunning / TRANSLATE。新しいRunを暗黙生成していない。

```powershell
# 先行Reviewの終了後、互換性確認済みの失敗Runを逐次再開する。
uv run python cli.py translate inputs/sample3.pdf --output-dir outputs/sample3-acceptance-latest --resume 01a0d520-15a4-74a2-9eaf-afafa726a03a
```

起動HEADは`8e28198d6e1473e37dd97381f9d757424448605a`。既存未コミットの製品差分4 filesも含むworktreeを実行しており、commit単独の検証とは表現しない。起動前のSHA-256は以下のとおり。

| File | SHA-256 |
| --- | --- |
| translate/adapters/llm.py | `d75bef0d3baea485a9d3b6510cd0aef8badfb0f45fcfdd77ec9aef0951186014` |
| translate/common/lifecycle.py | `d15eb3dff4782da13cc747f695e9731b8f4da1b3103e3a5ba73e5214499ddc8a` |
| translate/common/terminal_evidence.py | `881339c47e68857e782f21b4d7c2e2609c65ab4e6458584c3a5e6c1cd565b6f8` |
| translate/tasks/review.py | `b968b2ac43d23032f435c7a8486901c07334cf0a3c76f4899a9b7f4f01e54c14` |
| translate/tasks/report.py（commit済み修正版） | `41eea6764f6b61efa86884eae9a9f366e6f9bf0da25715f67770b1c4ccbf263b` |

request timeout=1800秒、Task期限=21600秒、retry=3、available_input_tokens=10752を維持した。接続先・Credential・本文は記録しない。export先は起動前に未存在を確認し、先行Word/PDFを上書きしない。

07:33 JSTに同一session `43282`の実行継続をpollで確認した。翻訳成功、最新DOCX、Word PDF化、最新PDF比較、利用者目視はまだ未確認。進捗は5/9のままで、正式verify/archive/main merge/pushは行わない。

記録更新後の文書・公開比較Testは38 passed（2.43秒）、本Changeとrestore-docx-tables-and-indexesのOpenSpec strict検査はvalid、git diff --checkは指摘なし。製品Codeは今回変更していない。先行Reviewの受入不合格をこれらの局所検査で合格へ変更しない。

## 実翻訳の長時間化と診断情報の不足（2026-09-25 08:52 JST確認）

利用者からセッションの長さについて質問されたため、実行と実装の事実を確認した。その後、利用者は「処理が重く長いこと自体はよく、原因を知りたい」と明確化した。長時間そのものを不合格条件としない。これは途中検証であり、tasks 3.1〜3.4は未完了のままである。

| 観点 | 判定 |
| --- | --- |
| Completeness | 5/9。実翻訳、Word PDF、最新比較、正式検証の4項目が未完了（CRITICAL） |
| Correctness | REPORTの局所回帰証拠は上記のとおり。最新実成果物による合格は未確認 |
| Coherence | 製品Code・設定は実行中に変更せず、逐次実行を維持。下記の診断不足を別途追跡 |

### TRANSLATION-LATENCY-001（WARNING・未解決）

- 実行processのCreationDateは07:31:50 JST。08:52時点で約80分が経過し、同一session `43282`はpollでliveを確認した。Run保存状態はrunning / TRANSLATEで、最新export先のDOCXはまだ存在しなかった。
- 参照検索Artifactの更新は第6ページ07:53:12、第7ページ08:03:40、第11ページの第2 Chunk 08:23:04、第12ページ08:31:03、第14ページの第2 Chunk 08:42:37、第15ページ08:51:12だった。これらは検索結果の保存時刻であり、翻訳完了時刻、LLM要求数、推論速度の証拠ではない。完全停止ではないことと、翻訳の成否・品質を区別する。
- `translate/tasks/translate.py`の`_translate_page.translate_chunk`は通常要求に`reasoning="high"`を渡す。出力切断後の推論無効化・分割、翻訳応答の検証失敗後の再試行もある。ただしProviderがこの指定をどう処理したか、今回どの回復経路を通ったかは取得済み出力から特定できない。高推論設定やHardwareを原因と断定しない。
- `translate/adapters/llm.py`の`structured`は`_invoke_with_retry`全体を一つの`llm.request`観測で囲む。明示metadataはreasoning/response_typeで、各試行の開始・終了・所要時間・再試行理由・Page/Chunk IDを記録していない。成功応答のtoken情報は解析するが、成功時の観測更新へ渡していない。Langfuseが有効でも、この実装だけで試行別の時間内訳を復元できるとは限らない。今回、LangfuseまたはLM Studioのserver側記録の取得はしていない。
- 同Fileの`_invoke_with_retry`は呼出しごとに`task_deadline_seconds`からdeadlineを作り、例外後の再試行可否を判定する。実行中のcallをdeadlineで中断する処理ではなく、全Pageを含むTRANSLATE Taskの総時間をこの値で制限する実装でもない。前節の「Task期限=21600秒」は設定値を指し、翻訳全体が6時間以内に終了する保証ではない。
- 対応案: 別Changeで既存の観測・Logger境界を再利用し、本文・秘密を含まない要求単位/試行番号/経過時間/結果分類と、出力切断・検証再試行を対応付ける。診断情報をResumeの判定や完了一覧に使用せず、新しい進捗台帳・並列実行・依存は追加しない。性能改善方針と受入時間は計測根拠を得て提案し、単なるtimeout短縮や推論設定の変更で品質問題を隠さない。

今回の調査・記録で製品Code、実行設定、既存Artifactは変更していない。停止・再起動・追加LLM要求も行っていない。所要時間の合否基準を新たに決めたものではなく、診断不足と利用者の懸念を未解決事項として保持する。正式verify/archive/main merge/pushは引き続き未実施。

### 原因の特定: 既存LangfuseのProvider観測との照合

先の「取得済み出力だけでは特定できない」はCLI出力と製品側観測の実装だけを調べた時点の判断である。その後、導入済みLangfuse SDKのAPIを確認し、既存サーバーのv2 observationsを読取り専用で取得した。v1は404だったためv2を使用した。新たなLLM要求・計測Code・依存は追加せず、本文/Prompt/応答本文/認証値は取得対象のfieldsから除外した。

製品の`llm.request`に加えて、接続先側の`chat google/gemma-4-12b`観測にtoken内訳が既に存在した。製品trace `9dc342e45844a60a6780d95dcb0f8777`の22要求とProvider側の22 chatを、開始・終了時刻とも0.1秒未満の差で一対一に照合できた。両者のtrace IDは異なるため、IDで直接紐づいたものとは表現しない。要求と子処理を二重加算せず、Providerのchatだけを集計した。取得結果の次cursorはnull。

| 07:31:50〜08:56:10.333 JSTの確認済み範囲 | 実測 |
| --- | ---: |
| 経過時間 | 5060.333秒（約84.3分） |
| 終了済みchat 22件の時間合計 | 4948.543秒（経過時間の97.79%） |
| 同期間内に終了したEmbedding 39件 | 103.687秒 |
| high / none要求 | 20 / 2件 |
| 推論token | 151,655 |
| 通常出力token | 17,229 |
| 生成tokenに占める推論 | 89.80% |
| 推論＋通常出力token / chat時間 | 約34.13 tokens/秒 |
| chat入力tokenの範囲 | 3,541〜5,052 |

この範囲は途中のsnapshotであり、進行中の第16ページや後続Taskの総時間を含まない。39件のEmbeddingは期間境界で区切った件数であり、一律にPage数や製品検索回数と同一視しない。token/秒は要求全体の時間で割った値で、純粋なdecode速度や推論部分だけの秒数ではない。

具体例は以下。Providerの通常出力と推論の合計が設定上限16,384に達し、製品側のhigh要求はLLMError、直後のnone要求は成功している。`translate_chunk`のnoneへの回復条件は出力切断であるため、単なるtimeout待ちではなく、推論による出力枯渇と再送が発生したと判断できる。

| 対象（検索Artifactの時刻と照合） | high時の時間 / 推論 / 通常出力 | 直後のnone時の時間 / 通常出力 |
| --- | --- | --- |
| 第11ページChunk 2、08:23:04開始 | 469.134秒 / 16,381 / 3 tokens | 8.440秒 / 309 tokens |
| 第14ページChunk 2、08:42:37開始 | 491.915秒 / 16,381 / 3 tokens | 15.561秒 / 548 tokens |

したがって確認範囲の主因は、各Chunkのhigh要求で翻訳本文より大量の推論tokenを逐次生成していることと、一部要求で出力枯渇後に再送していることである。上記2件の枯渇試行だけで計961.049秒（約16分）を占める。別の第15ページ要求も298.174秒、推論9,339 / 通常出力905 tokensだった。入力context超過を示す証拠はなく、上限を伸ばす提案の根拠とはしない。CPU使用時間は08:55時点で9.5625秒、稼働中の接続はLLM endpointへ向いており、ローカル文書整形やWord変換の処理時間が支配している状況ではなかった。

原因説明はここまで既存観測で可能だったため、「新たな診断機能を実装しなければ原因が分からない」という結論へ進めない。製品側でPage/Chunkとの直接対応や回復理由を提示する不足は残るが、改善案は既存Provider観測の再利用も比較してから扱う。利用者は速度改善や品質を変える設定変更を今回要求していないため、reasoning、timeout、実行順を変更しない。none応答の短時間成功を翻訳品質の同等性保証ともみなさない。

原因調査の記録後、文書Testは21 passed（0.26秒）、本Changeとrestore-docx-tables-and-indexesのstrict validationはvalid、git diff --checkは指摘なし。製品Testの再実行や新たなモデル比較実験はしていない。実成果物検証4項目が未完了のため、正式verifyは未合格として保持する。

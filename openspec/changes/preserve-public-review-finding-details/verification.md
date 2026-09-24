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

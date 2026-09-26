<!-- markdownlint-disable MD013 MD041 -->

## Apply結果（2026-09-26）

**4/6 tasks完了。製品修正と自動回帰は成功。新規sample3 E2E・利用者目視・正式verifyは未完了で、archive不可。** 以下の計画時点の「未変更」は過去記録として保持する。

### 変更と再現証拠

- 基点Commitは64200f7。製品差分はtranslate/tasks/markdown.pyのrender_documentの表紙構文1行と目的Commentだけ。画像の直後に標準escaped spaceを付け、本文Captionや番号を後処理で変更しない。新Module・Dependency・HTML・採番器は追加していない。
- 修正後markdown.pyのSHA-256: `7a70ae4bbb47df8c25c1eb3c6639bd06006070994cf92d1f20e7f380ee32f9a1`。この記録とCodeを同じCommitへ含める。
- 既存一覧TestのFigure 2期待値を1へ変更し、新規12ケースを追加した先行実行は **9 failed / 4 passed / 21 deselected（4.07秒）**。本文図がある全8ケースと既存一覧Testが、実出力Figure 2と期待Figure 1の差で失敗した。表紙なし変換は先に成功する。LLM等の外部Modelは呼ばない。
- 最小修正後、tests/test_output_contract.pyは **34 passed（4.56秒）**。12ケースそれぞれで同じ本文を表紙なし/ありの2回実Pandoc変換する。採番対象図0/1/2、Captionなし画像と表の有無、ASCIIまたは空白を含む日本語画像pathを組み合わせる。
- 本文Captionと図一覧が同じ1開始、表紙の有無による番号差0、元Caption中の`Figure 7`保持、表一覧のTable 1保持、期待画像数、表紙descr=表紙、先頭配置、直後改ページを確認した。表紙だけでは図一覧に表紙項目を作らない。
- 幅指定`width=100%`を維持し、同じ10 px合成画像の実DOCX幅が修正前後とも127000 EMUであることを確認、最終Testへ固定した。これは前後不変の確認であり、実PDFのページ幅を目視で受け入れたという意味ではない。

### 品質Gate

| 検査 | 結果 |
| --- | --- |
| uv run pytest -q（最終Code、session 22334） | 811 passed / 1 skipped、50.59秒、exit 0 |
| uv run ruff check . | 成功 |
| uv run ruff format --check . | 373 files already formatted |
| uv run ty check | 成功 |
| OpenSpec validate exclude-cover-from-figure-numbering --strict | valid |
| git diff --check | 成功 |

初回Lintの複合assert 1件を分離し、上表は修正後の結果。全pytestは既存未commit変更を保持した作業Tree上の検査であり、それらを本Changeの実装・Commitへ含めない。既存のatomic公開、外部参照拒否、表紙Page除外等の回帰も全体Testに含む。追加関数はTest 1個で目的Docstringあり、製品の既存関数とPandocに委譲する。

### 残る実検証・受入

Task 2.2/2.3は未完了。直近の別Changeでの新規Run `01a0dd7f-a0a9-75f0-bc80-4693ee212389` はSTRUCTUREで失敗し、その後2026-09-26 12:41:22 UTCの診断用単発要求も30.219秒でReadTimeoutだった（詳細は[preserve-results-on-timing-output-failure](../preserve-results-on-timing-output-failure/verification.md)）。その事実だけで現在も停止中と断定せず、接続回復確認後に本修正後の新規翻訳→Microsoft Word PDF→原本Reviewをreasoning OFF・逐次で行う。本ターンは推論・Word・実PDF生成を行っていない。

旧Run・成果物は変更/移行/削除せず、旧PDFを修正後の証拠へ読み替えない。表内画像・負数抽出・仮ヘッダー・ALIGN等も本Changeでは解決していない。Commitは今回のCode/TestとOpenSpec記録だけを指定し、.agents、inputs、outputs、runs、PDF/DOCXを含めない。正式verify・同期・archive・PR/CI・main merge/pushは実検証と最終受入が揃うまで実施しない。

## 計画時点（2026-09-26）

製品Code/Testは未変更、0/6 tasks。これは提案前の読取り診断であり、正式verify・受入・archiveは未実施。

### 原因の確認

markdown.render_documentは表紙を非空altの単独画像段落として描画し、Pandoc 3.11のmarkdown-smart readerはFigure ASTへ変換する。DOCX正規化は後から表紙Captionを除くが、本文番号を戻さない。図一覧は残った本文Captionをコピーする。既存の実変換TestもFigure 2を期待しており、この不備を検出できていなかった。

grillingの事実調査では限定した読取りsub-agentがASTを確認し、main agentも現行Code/Test・導入済Guideと実DOCX出力を照合した。新しい仕様判断をagentへ委任していない。

### メモリ上の実DOCX比較

既存Runのcover.pngを読取り参照し、合成Caption「Body caption」を持つ本文図1個を後ろへ置いた。Pandocのstdin入力→stdout binary出力をBytesIO/ZIP/標準XMLで検査し、利用者Fileへ書込み・新規File生成はしていない。LLM/Embedding/Wordは呼ばない。最初のprobeはbinary stdout指定なしでexit 4となり、--output=-を明示して再実行した。

| 表紙表現 | 表紙descr | 出力されたCaption |
| --- | --- | --- |
| 現状の単独画像 | 表紙 | Figure 1: 表紙、Figure 2: Body caption |
| 空alt＋fig-alt | 空 | Figure 1: Body caption |
| inline Span | 表紙 | Figure 1: Body caption |
| 画像直後のescaped space | 表紙 | Figure 1: Body caption |

後二者は表紙識別を保持して本文図を1開始にできる。最小の標準構文で済むescaped spaceを計画へ採用した。上表は正規化前の合成出力であり、製品rendererを修正した回帰Test、正式なtemplate/list生成、Word PDF、実新規翻訳/Reviewの証拠ではない。実装Taskでそれぞれ検査する。

既存の表内画像の所属・負数抽出・仮ヘッダー・ALIGN・LangGraph二重管理等は別件として残す。既存Runや成果物を変更・削除せず、今後のapply承認後に実装する。

計画4/4 Artifactの存在、OpenSpec strict valid、文書Test 21 passed（0.32秒）、git diff --check成功を確認した。製品未変更のため全製品Test・実E2Eをこの計画ターンで実施したとはしない。計画と元指摘への参照だけをcommitし、.agents・サンプル・outputs/runs・既存未commit変更は含めない。

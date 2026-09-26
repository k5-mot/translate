<!-- markdownlint-disable MD013 MD041 -->

## 正式Verify（2026-09-26、Code 05c7a80）

**検証失敗（受入未完了）：CRITICAL 2、WARNING 0、SUGGESTION 0。archive不可。** 仕様の実装不足を新たに検出したという意味ではなく、必須の実E2E・目視受入が未完了である。製品差分を追加せず、Codeと記録を照合した。

| 観点 | 判定 |
| --- | --- |
| Completeness | 4/6 tasks。追加Requirement 1件の実装あり、必須受入2項目が未完了 |
| Correctness | 1/1 Requirement、4/4 ScenarioにCodeと実Pandoc回帰Testの対応あり。新規sample3・Word表示の証拠なし |
| Coherence | 標準escaped space、既存Pandoc採番・正規化再利用、最小差分という設計に一致。新規依存/Module/採番後処理なし |

### Requirement・Scenario対応

Requirement「表紙を本文図の採番へ含めない」はtranslate/tasks/markdown.py:486のrender_document、同:507の表紙画像構文に対応する。translate/adapters/pandoc.py:68のcreate_docxはdocx+native_numberingを使用し、同:407の_is_cover_paragraphはdescr=表紙を維持した通常画像を識別、同:436の_reorder_front_matterは先頭と改ページを保持する。採番済み本文Captionを同:353の_index_entriesで図・表別に取り出し、同:377の_populate_front_matterへ渡す。これらの既存Adapterを変更していないこともgit diffで確認した。

| Scenario | 検証Code |
| --- | --- |
| 表紙に続いて本文図を出力する | tests/test_output_contract.py:390の実変換Testが本文図に対応する図一覧Figure 1を確認。同:495では本文ImageCaptionと図一覧を両方照合 |
| 表紙の有無を比較する | 同:495で同一Documentを表紙なし/ありで変換し、Caption/一覧の完全一致、先頭descr、改ページ、画像数・幅を確認 |
| 複数図と表を含む | 同Testのfigure_count=2かつextras=TrueでFigure 1/2、元Caption文字列、表一覧Table 1を確認。表一覧は本文TableCaptionから生成される |
| 採番対象の本文図がない | 同Testのfigure_count=0で表紙だけ、Captionなし画像＋表の場合を確認。本文ImageCaptionと図一覧項目は空、画像は保持 |

### 必須残件

1. **CRITICAL COVER-NUMBER-E2E-001 — tasks.md:12（2.2）未完了。** 接続回復確認後、05c7a80以降の新規sample3翻訳→Microsoft Word PDF→原本Reviewを推論OFF・逐次で完了し、Run ID・hash・終端と採番を記録する。修正前の完成Runを代用しない。
2. **CRITICAL COVER-NUMBER-ACCEPTANCE-001 — tasks.md:13（2.3）未完了。** そのWord/PDFを利用者へ提示し、実表示の目視結果を得て元指摘へ紐付ける。本Verifyを実施したことだけで複合Task全体を完了扱いにしない。

### 外部状態の再確認と検査範囲

2026-09-26 13:06:30.316558 UTC、稼働中のローカルPython/uvプロセスがないことを確認して、設定済STRUCTURE Modelへ合成の「OKのみ返す」要求を1回だけ送信した。製品の既存_modelを利用し、reasoning=none、thinking=disabled、max_tokens=32、SDK retry=0。診断要求だけのtimeout=30秒で **30.032秒後にOpenAITimeoutError（cause: APITimeoutError）** となり、session 67763はexit 0で診断終了した。exit 0は例外種類を安全に記録できたことを示し、生成成功ではない。製品の1800秒timeoutは変更していない。

続く読取りGET /modelsは **HTTP 200、0.218秒、7モデル、設定済STRUCTURE Modelの掲載あり**。接続先APIの到達性は確認できるが、推論遅延・内部障害・モデル実行状態を区別する根拠にはならない。短いtimeoutだけでモデル停止とは断定しない。タイムアウトした要求がサーバー内でも終了したとは確認できないため、生成要求を重ねず、新しい製品Runも開始しなかった。

Code 05c7a80の対象Code/TestはHEADから未変更、markdown.py hashは下記Apply記録と一致。関連Test＋文書Testを再実行し **55 passed（4.57秒）**。全811 passed / 1 skipped、Ruff/format/tyは直前Applyの実行結果を参照し、本ターンに再実行したとはしない。秘密値・入力本文・応答本文は診断出力していない。実PDF・Word・利用者目視は未実施と明記し、全体目標は未達のまま維持する。

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

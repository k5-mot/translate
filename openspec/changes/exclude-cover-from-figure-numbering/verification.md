<!-- markdownlint-disable MD013 MD041 -->

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

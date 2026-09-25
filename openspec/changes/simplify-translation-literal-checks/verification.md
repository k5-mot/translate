<!-- markdownlint-disable MD013 MD041 -->

## 状態

2026-09-25、applyの静的・合成回帰と新規実翻訳を完了。tasks 1.1〜3.1は完了、3.2の比較Reviewは実行中、3.3の利用者目視は未完了。後述の途中記録は履歴であり、最新状態は末尾の完了記録を正とする。正式verify、仕様同期、archive、main merge/pushの完了を意味しない。

## 実装と検査証拠

- LLM/LibreTranslateの本文marker生成・復元・専用prompt fieldを削除。LLMの対象ID・空応答検査、有限retry、reasoning OFF、逐次切断分割は維持した。新依存・新製品Module・再開台帳を追加していない。
- CHECKの対象は明示http/https/www URLと小さい既知拡張子集合（pdf/docx/xlsx/pptx/txt/md/csv/json/yaml/yml）。固有名詞・略語・camelCase・underscore識別子を形だけで判定しない。変更はliteral-reference/warningとして対象IDと根拠を保存する。数値/単位・否定・条件・比較・用語集の検査は維持する。
- 構造化Inline Codeは翻訳とFIXの送信対象から外し、出力層へ原文を保持する。Linkはhrefを維持して表示ラベルを翻訳・修正する。通常textからCodeを推測しない。
- REVIEWはCHECKの参照warningを応答と併合し、モデルが追加指摘なしでもFIX/VERIFYへ渡す。比較reportではこの引継ぎwarningを二重集計せず、対象と根拠を残す。専用の検査LLM段階は追加しない。
- 公開fingerprintはLLM/LibreTranslateともtranslation/review Rule hashを既に含み、比較はreview Rule hashを含む。両Ruleの変更で旧契約を区別できたため、新version項目や互換性機構は不要。Workflow threadも既存Rule hashを使用する。入力やQdrant状態の扱いは変更しない。

| 試験 | 結果と範囲 |
| --- | --- |
| test_translation_output_failures | 24 passed。実装前の配布Rule/通常・retry・分割試験は9 failed。実装後はU.S.→米国、ID/空応答拒否、有限切断回復、安全な原因分類、失敗時の旧Artifact/入力保持が成功 |
| test_finding_contract | U.S./U.K./U.S.A./固有名詞/camelCase/underscoreの誤指摘0。URL、拡張子大小文字、句読点、未知拡張子の境界と既存検査を確認 |
| test_pdf_translation_capability | 12 passed。両Backend×本文/表題/表セルの6ケースで翻訳→CHECK→REVIEW→FIX→VERIFY→実Pandoc DOCXを実行。Code内容とhref保持、ラベル翻訳・修正、warning根拠保存、比較report集計を確認。各ケースは翻訳サービス1、REVIEW 1、FIX 1、VERIFY 1の既存呼出しのみ。LibreTranslateの件数不足/過剰/サービス例外で旧Artifactと入力を保持 |
| test_fingerprint | 17 passed。LLM/LibreTranslateの通常/OFFでRule変更が別threadとなる。公開translate両Backendとreviewが旧RuleのResumeを拒否し、旧manifestを変更しない |
| 全体品質 | 最終pytest: 675 passed, 1 skipped（43.70秒、session 38602、exit 0）。skipはWindows上のPOSIX PTY試験。Ruff check、format（351 files）、ty成功。OpenSpec strict成功。git diff --checkで空白不正なし |

合成試験のLLM/検索/LibreTranslateは固定応答であり、実モデルの翻訳品質や実PDFの受入を証明しない。DOCX試験のPandocは実実行した。URLの推測・未知拡張子の網羅・固有表現認識は提供しない。

## 廃止と後継

旧4 Changesのverificationへ後継と廃止対象を記録した。preserve-protected-fragments-after-split、harden-protected-fragment-restoration、protect-all-translation-chunksのmarker Deltaは再同期せず、後継要求との統合確認後に仕様同期を省略してarchiveする。clarify-translation-placeholder-instructionsは既存skip_specsを維持する。旧marker専用Testは削除したが、対象ID/空応答、逐次切断回復、既存成果物保持、安全な失敗診断のTestは残した。過去の失敗・旧Runを削除せず、旧未完了受入を合格へ書き換えていない。

## 実行時の差分境界

基点commitは38604ee（診断JSON直接上書き）。本Change以外に既存のAGENTS.md、openspec/config.yaml、review context/latency関連Code・Test、lifecycle/terminal_evidenceのcontext-exceeded対応、過去検証記録、未追跡Change/診断Script/outputsの差分がある。全体Testはそれらを含むworktreeで実行した。本Changeのcommitには本件の差分だけを入れ、review.pyはwarning引継ぎhunkのみを選択する。.agents、PDF/DOCX、outputs/runs、秘密値を含めない。

## 残る受入

1. 新規Runの翻訳とMicrosoft WordによるPDF作成は完了した。旧失敗Runは再利用していない。
2. 原本PDFと生成PDFの比較Reviewの終了と指摘根拠を確認する。診断保存Changeと証拠を共有する。
3. 利用者へDOCX/PDFを提示して目視を確認する。既知の表内画像・ALIGN・Template等の別件を合格扱いにしない。

## 実検証の開始記録

実装commit 17ebaf2と上記既存差分を含むworktreeで、新規公開CLI翻訳を2026-09-25 13:17:31 UTCに開始した。入力SHA-256は5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f。旧Runや既存exportは上書きしていない。

- Run: 01a0d8b6-c2ab-7c92-bed9-58403a8410b3、tool session: 75952。
- 入力: inputs/sample3.pdf。export先: outputs/sample3-acceptance-off-literals。
- LLM_REASONING_MODE=off。保存snapshotもoff。context/output/image=30208/16384/2048、request timeout=1800秒、Task deadline=21600秒、retry=3。
- 起動系列: uv PID 49236 → Python launcher PID 41572 → Python PID 19172。プロセス数はModel並行数を意味しない。
- SPLIT〜LOAD完了、DOCLING=26.987秒、STRUCTURE=104.580秒。前回失敗した第2ページを通過し、第4ページのTRANSLATEまで進行中。この途中記録はWorkflow成功証拠ではない。終了handleと最新結果を確認するまで再起動・Resumeしない。
- この翻訳は通常CLIで起動したためdetached childの呼出しcounterは未接続。未取得の呼出し数を0と記録しない。後続の実比較は既存診断runnerを使用し、診断保存Changeとの共通証拠を得る。
- 読取り専用Langfuse v2 observations照会で、trace 56e4ac20ce055e2988a2f42e599bb1b6の終了済み18 llm.request（STRUCTURE 15、TRANSLATE 3）のmetadataが全てreasoning=none / thinking=disabledであることを確認した。取得時点の件数であり最終件数ではない。Provider内部の推論token実測0は主張しない。旧trace一覧APIはv4 events_only環境の404を返したため、導入済みSDKのv2 observationsへ切り替えた。診断照会はModel要求を追加していない。
- QdrantClientからAPI keyを暗号化されていない接続で使用する旨の警告が出た。処理停止は起きていない。接続設定を無断変更せず、Security受入の残確認として保持する。

### TRANSLATE/CHECK完了時点（Workflow継続中）

同じsession 75952のlive handleからTRANSLATE=805.803秒、CHECK=0.098秒の完了通知を取得した。旧失敗の第2ページを含む全本文ページを処理し、REVIEWへ進んだ。DOCX生成・Workflow終了はまだ確認していないためtask 3.1は未完了のままとする。

- 翻訳Artifactの非空原文Inline 245件に対して、同じIDの訳文欠落0、空白だけの訳文0。構造化Codeの変更検出0（このsampleの検出範囲であり、全Code形式の保証ではない）。
- U.S.を含む6単位中5単位で米国の表記を確認。略語の自然な訳による停止は起きなかった。
- TRANSLATEは基本Chunk 24に対して完了llm.request 24件。観測された生成区間の合計639.689秒、最長40.898秒。Task全体との差166.114秒には検索・I/O等が含まれ、その個別内訳は未計測。構造推定15件と開始済みReview 4件を含む取得済み43件は全てnone/disabled、v2 cursorなし。
- CHECKは85指摘（warning/untranslated 15、error/number-unit 60、error/glossary 6、error/negation 2、error/comparison 1、error/condition 1）。literal-reference警告はこのsampleでは0であり、URL/ファイル名warningの実発生例を得たとはしない。警告経路は合成統合Testで別途確認済み。数値等の指摘は未判定で、品質合格を意味しない。
- 中間構造には主要3表（7×4、3×6、21×5セル）がある。表内画像・Word上の配置の合格証拠には使用しない。

### REVIEW完了とFIX待機

同じsession 75952からREVIEW=397.029秒の完了を取得した。保存Findingは34件（error 11、warning 2、info 21）。Langfuseの完了ReviewResponseは38件、生成区間の合計198.283秒、最長34.046秒。差分約198.746秒の個別内訳は未計測である。

CHECKの数値指摘は確定誤訳数ではない。原本第3ページの`#/texts/33`では「$7.4 billion」に対応して「74億ドル」があり、文字列7.4の欠落という指摘は換算表記による誤検出だった。同ページの意味Review結果は0件で、既存の意味確認がこの例を誤訳として残していない。他の数値指摘まで一括して誤検出と扱わない。

最新確認時はFIX継続中。完了FixResponse 6件（合計37.264秒、最長20.695秒）を観測し、次の要求の完了を待っている。Python PID 19172とsession 75952のlive handleを確認済み。約3分の未完了期間をtimeout/停止とは判定せず、1800秒の要求timeout内で待機している。中断・再起動・同じRunの重複実行は行っていない。生成DOCX、Word PDF、比較Review、目視確認は依然未完了。

### 翻訳完了・Word PDF作成（上記途中記録の更新）

Run 01a0d8b6-c2ab-7c92-bed9-58403a8410b3はsession 75952のexit 0で完了した。TOTALは2366.730秒（約39分27秒）、FIX=1000.784秒、VERIFY=29.461秒、DOCX=0.406秒。起動したプロセスの終了も確認した。

- Langfuse trace 56e4ac20ce055e2988a2f42e599bb1b6の最終llm.requestは97件（STRUCTURE 15、TRANSLATE 24、REVIEW 38、FIX 10、VERIFY 10）、全件終了済み、cursorなし。全97件のmetadataはreasoning=none / thinking=disabled。開始・終了区間の最大重なりは1だった。これは製品のLLM要求spanの計測であり、Provider内部retryやEmbeddingの実呼出し数まで97に含めたとはしない。通常CLIの外部呼出しcounterは未接続のため、その未計測値は不明のまま保持する。
- Provider側でもreasoning_effort=none、temperature=0、max_completion_tokens=16384を確認した。推論token数は提供されておらず、実推論tokenが0という断定はしない。FIXの製品span最長は476.335秒。Provider observation 180a85d7c5961a3cは約472.856秒、入力1417・出力16384 tokenであり、少なくともこの長時間待機は出力上限までの生成を伴っていた。単にプロセスが固まったとは判定しない。
- 最終単位状態はfixed 58、unchanged 123、skipped 64。VALIDATEはvalid=trueだがfix-skipped警告64件がある。第7・10・12・14ページでは修正候補の不採用があり、誤字・品質指摘が残る。exit 0を無誤訳や品質合格と同一視しない。
- DOCXは3表・24画像。OOXMLのdirty field、instrText、外部relationshipは各0。表セルへの画像配置、表の意味的再現、Wordで警告ダイアログが一切ないことまでは、この静的検査だけで保証しない。
- 原本とRun内入力コピーのSHA-256はともに5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f。
- outputs/sample3-acceptance-off-literals/document.ja.docx: 3,656,615 bytes、SHA-256 78aeb3c5e50f8785e4a9b5dca1f64776355f9a96470ed090b357263764ca4d7d。
- 同じDOCXをMicrosoft Word 16.0でread-onlyで開き、RepaginateとExportAsFixedFormatを実行した。28ページのdocument.ja.pdf: 1,541,242 bytes、SHA-256 57a19cc835e8cb637f9ac027b3b6f27458a1f21c191c213ade4f1950309ac21a。変換後DOCX hashは不変。製品の変換機能・依存は追加していない。
- 最初のWord操作はApplication.Hwndの誤使用で文書を開く前に失敗した。新規作成した空Word PID 25540だけを所有確認後に終了した。Window.Hwndへ訂正した操作は所有PID 9484で成功し、そのWordも終了した。既存の利用者Word PID 9348は保持した。
- DOCX/PDFのリンクを利用者へ提示し、表・図・表紙・一覧・見出しのページ別目視を依頼済み。返答前なのでtask 3.3を完了にしない。

### 比較Reviewの実行記録

最初の診断起動は補助コードの入力roleをsource/targetと誤ったため、Run 01a0d8df-90fc-7eb1-a686-cb8a59c2ab77がWorkflow開始前にKeyError・exit 1で終了した。これは検証側の呼出し誤りであり、製品回帰としない。comparison-terminal.jsonにはfailed・child PID 24760・exit 1・LLM/Embedding/Qdrant各0を保存できた。所有temp outputs/.sample3-review-ioed52ycは既存cleanupで削除済み。失敗Runと診断記録は保持した。同じ誤ったroleを使っていたfingerprint試験fixtureも公開CLIと同じ名前へ訂正する。

訂正後は公開CLIと同じsource_en/translation_jaで、Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2を新規作成した。reasoning OFF、既存run_public_run_detachedで2026-09-25 14:03:05 UTCに開始。原本と上記Word PDFを入力とし、旧RunをResumeしていない。診断先は別名comparison-terminal-corrected.json、所有tempはoutputs/.sample3-review-h_pnez6s、監視対象child PID 53980（実Python PID 56052）。CHECK通知まで進み、14:07 UTC時点はrunning。途中のcounter=0は最終呼出し数を意味しない。Task 3.2と診断保存ChangeのE2E受入は、終了状態と報告内容を確認するまで未完了とする。

### 最新成果物の読取り・目視（AIによる検査、利用者受入ではない）

PDF全28ページを導入済みpypdfium2で読み、1・2・3・5・25・26・27・28ページを描画して確認した。検査用画像はoutputs/sample3-visual-n2xq2h91にのみ保存し、成果物とcommitへ混入させない。未導入のpymupdfは追加せず、既存Packageを使用した。

- 表紙画像はPDF第1ページ、目次は第2ページで順序を確認。目次・図一覧・表一覧は日本語見出しで非空。図一覧は第3〜4ページ、表一覧は第5ページ、本文は第6ページからで、次の区分への改ページが確認できる。
- 第25ページには4列表があり、以前の「表の全セルが縦に本文化する」状態とは異なる。ただしこれで全表を合格としない。
- 第26ページのStatus/Progress表は枠と見出しがあるが、色丸を含む10セルが空。第27ページに黄・緑の丸10個が表外で縦に並ぶ。既知の表内画像の問題は未解消。
- 図一覧の先頭はFigure 2で、本文側の図番号とCaption対応にもずれがある。図一覧へ長い本文がCaptionとして混入している箇所がある。目次にはCaptionはないが、本文由来と考えられる長い項目があり、STRUCTURE結果の別確認が必要。
- 表一覧にはTable 1の1件だけがある。3表の存在だけで一覧の網羅を保証しない。第27〜28ページの金額表は表として出力されるが、原本の負数符号との照合が必要。
- テンプレートの「○○システム」「SYS-DS-001」「社外秘 / ○○株式会社」がヘッダー・フッターに残る。既知のTemplate問題を解消済みとしない。
- FIX Artifactでは第10・14ページにLLMErrorのskip理由があり、後続VERIFYで別の不採用理由へ置換される。最終Artifactだけでは最初のFIX障害理由を読み取れない。VERIFYは第7・10・12・14ページを戻している。全層を再帰集計すると同じInlineが重複するため、その数を64警告に加算しない。

公開reviewの入力roleを訂正した後のtests/test_fingerprint.pyは17 passed（2.21秒）。対象Ruff check/format、全体ty、OpenSpec strict、git diff --check成功。文書Testは21 passed（0.90秒）。この試験fixtureの訂正で進行中の製品コードは変更していない。

### 実データで再確認した別件（本Changeへ無断で取り込まない）

1. **金額表の負数符号欠落（未解決）**: 原本第16ページの画像には−766、−1,796、−749などの負数があるが、生成PDF第28ページでは正数表示となる。原本第16ページも同じ描画器で目視した。Docling part-0002/unpacked/document.json内の該当text/origは既に766、1,796であり、MERGE、POSITION、NORMALIZE、LOAD、STRUCTURE、TRANSLATE、FIX、VERIFYでも同値を確認した。翻訳モデルがマイナスを消したと断定せず、Docling応答と原PDFからの数値保持を別Changeで診断・修正する必要がある。欠落符号が別要素へ分離された可能性を含め、発生原因の確定は未完了。
2. **用語集の部分一致による誤指摘（未解決）**: 原文「Complete a Capital Asset Management Plan and certify the Earned Value Management System.」に用語API→APIを適用すると、deterministic_findingsはglossary/APIを返すが、既存matching_glossaryは0件を返す。Capital内のapiへの部分一致であり、単語境界を考慮する既存APIとの不一致を外部呼出しなしで再現した。実データの第14ページでもAPI指摘をVERIFYが無関係と判定している。今回の文字列保護廃止とは別の用語集検査問題である。
3. **比較ALIGNの誤対応（既知問題の再現）**: 訂正後の比較Runは290 Groupを生成した。logs/run.logに2026-09-25 23:04:17 JSTの「ALIGN model fallback failed; using deterministic order」があり、LangfuseのAlignmentResponseは0.741秒でERROR/LLMError。原因の詳細はこの安全な観測値だけでは確定できない。alignment/14はDepartment of Energy→図一覧、alignment/18はOVERVIEW→大統領によるクリーンな石炭へのコミットメントとなり、別内容同士を比較している。後続reportの総件数を誤訳数・品質合格の根拠にしない。

14:14 UTCの比較trace fe87686a81b37a939449aaa97b608a4eでは完了要求12件（ALIGN 1、REVIEW 11）、すべてreasoning=none。比較Runはrunning、親のheartbeatは更新されている。Evidenceのtask=CHECKは最後の完了通知であり、run.jsonのlast_task=REVIEWと区別する。途中counter=0も実呼出し0を意味しない。既存の進捗表示・再開状態整理の課題として残し、比較の二重起動・中断は行わない。

### 負数欠落の追加切り分け（同日14:17 UTC）

導入済みpypdfium2で原本第16ページのテキストを直接抽出したところ、画像上の−766、−1,796、−749に対応する文字列にも負数符号がなかった。Docling part-0002のtable_cellsでもrow 17/19、column 1/2のtextは766、1,796だった。したがって、現時点の証拠から本アプリのTRANSLATEまたはDocling単独の不具合とは断定できない。原PDFの表示と抽出テキストの差が少なくとも入口から存在する。

現行Docling adapterはdo_ocr=true、force_ocrは既存設定（既定false）を送る。強制OCRで画像上の符号を取得できるかは未検証であり、実行中Reviewとは並行して外部解析を起動していない。PDF内の符号の表現方法とOCR結果を確認する前に、金額や周辺行から負数を推測して書き換える対処は行わない。既存の設定/APIを用いた単一ページ検証を次の診断候補とする。

14:18 UTC時点で比較child PID 53980/56052と親PID 55584の生存を確認。完了ReviewResponseは14件、対応する既存Chunk Artifactも14件へ増加している。未知の終了コードや中間counter値を成功扱いせず、同じ実行を継続する。

### 参考文献

- [Microsoft Word Window.Hwnd](https://learn.microsoft.com/en-us/office/vba/api/word.window.hwnd): Automation対象のWindowから所有Processを確認するために使用。

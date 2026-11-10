# 📈 進捗

スクラッチ実装の削減と実機検証の進捗を記録する。不具合は[BUG.md](BUG.md)へ記録する。

## 🧭 現在の状況

- 2026-11-05の現行差分検証: `uv run pytest tests/unit tests/regression -q`は372件成功、`uv run ruff check .`、`uv run ruff format --check .`（103 files）、`uv run ty check`、`git diff --check`も成功。
- sample／sample2の保存Reviewにある表紙findingをPDF画像で確認。どちらも原文・訳文の先頭ページは同じ表紙だが、Doclingが異なるロゴ由来の文字を抽出し、sample2では文字列類似度が0.855となって旧閾値0.90を下回っていた。短い表紙も検出できるよう複製ページ判定を100文字以上・類似度0.85へ調整。保存LOAD文書に適用するとsampleは14unit、sample2は3unitを新たに認識し、sample1は非該当、既知のsample3〜5も認識した（`.tmp/matching-audit/copied-front-page-v68/check.json`）。Agent経由でOCR差を無視して原文を比較基準にするunit testを追加し、front-page関連test 2件成功。
- sample2 source335/336→translation365の訳抜け見逃しに対し、Reviewの対応付け契約を修正し「一部の対応があれば、訳抜けがあってもmatchedとして品質評価へ送る」と明記。新しい出力先でLLMを再実行すると、以前はsource335だけだったgroupがsource335・336→365へ変わり、実Review評価が省略された後半を検出した（`.tmp/matching-audit/sample2-agreement_continuation-prompt-v69/check.json`、全group評価`.tmp/matching-audit/sample2-agreement_continuation-full-group-eval-v70/check.json`）。初回のprompt再試行は同じ出力先を使って保存済み旧応答が返っており、検証として無効だったため、v69でやり直した。Naval C4Iでは「unit内すべての文・節を調べ、最初の一致だけで止めない」指示を加えたfresh Callでsource632〜635→translation736のgroup化に成功（`.tmp/matching-audit/sample2-naval-sentence-scan-v74/check.json`）。直後のReview評価も訳文の一部が原文内容から不自然に抜き出された問題を指摘した（同`evaluation.json`）。この例の分割・並び替え対応は改善したが、他PDFや全文再実行での精度は未確認。
- sample2保存Reviewの16 findingを再監査すると、6件は誤groupによる誤指摘だった。source97→115、439→465、632〜635→736、900→1105、1062→1252、58・62→83のfocused照合で正しい対応を確認。source341→482はDOD Directive 4630.5の引用を含む部分対応で、NOTEだけへの訳抜けfindingは有効と分類した。source335・336→365では新しい照合契約により後半の訳抜けもReview評価へ渡せた。証跡と個別再照合の限界は[対応付け精度検証](docs/MATCHING_VALIDATION.md)に記録。全文Reviewの再実行とfinding再監査は未完了。
- sample5の保存Review17件を対応groupと突き合わせると、11件が原文と同一の英語表紙ページ内のOCR差・式記号差に対する指摘だった。現行複製ページ判定はsample5表紙の14unit全てを検出し、該当groupは原文を比較基準に使いspanなしで評価するため、この11件の誤指摘と不適切な修正候補を抑制できる（分類`.tmp/matching-audit/copied-front-page-v68/check.json`）。残る6件は日本語訳ページで、数式誤記等の実指摘が含まれる。以前確認したmatched誤group3件（式8、式9前の導入、式12係数）も引き続き候補検索で修正可能なことを確認済み。

- sample1全文Review v61は423成功call後、次のReview制御応答が固定1024 output tokenを超えて失敗した。`choose_action()`が設定値4096を1024に制限していたため、Review／Upgrade共通制御枠を最大4096まで使うよう修正し、上限別unit testを追加。v61のcallとEmbedding cacheを引き継いだv62（`.tmp/matching-audit/sample1-full-current-v62/`）は2026-11-06 00:10時点で747成功call／round689、88件の評価chunkを保存。LOAD JSONを`Document.text_units()`の対象条件で数えるとsourceは3,526、translationは2,878件の非空TextUnit。既存callのmatched group 473件をkindで監査したところ、table cell／headingと別kindを結ぶ構造不一致はなかった。一方、PDF目視でTOCのsource table1 row1 `Planning Teams / Ill-1`に対し、旧groupがtranslation table3 row11 `作戦設計の概要 / IV-1`を選んでいた誤対応を発見。source page 8とtranslation page 9をレンダーして確認し、箇条書きセル`•`をrow labelに選んでいたのが原因と特定した。`Document.unit_contexts()`で文字を含まない記号だけのセルをrow labelから除外し、回帰testを追加。current codeのfocused候補検索＋実LLMは正しいtranslation row1 `計画チーム / 図-1`を選択（`.tmp/matching-audit/sample1-toc-page-number-row-label-v1/check.json`）。ただし、正しい行での評価はpage reference差を正しく指摘できず、原文OCR `Ill-1`とPDF上の`III-1`の曖昧さに関する未解決点が残る。v62 workerは修正前コードをメモリへロードして稼働中であり、全文成果物・最終finding監査は未完了。再開後にsample1表K-13・K-14行と`Intentionally Blank`の正しい対応、旧E-4のfocused修正も確認済み。1024 output上限エラーは再発していない。
- 実行中に見つけた上限不整合を修正。`max_reference_ids`は全role合計の上限だが、Reviewのschemaは各roleへ上限値を個別適用し、Agent system promptも常に32件まで選べると指示していた。roleごとに合計上限を分配し、promptも動的上限へ変更。再現unit testを追加し、`uv run pytest tests/unit/test_agents.py -q`は89件成功。全unit／regressionは366件成功。
- sample2保存Reviewでsource482はsource-only、translation523はtranslation-onlyだった。翻訳側の「19 支援および調整」見出しと本文を原文の「2. Assistance and Coordination」と照合し、現行`MatchingCandidates`＋実`ReviewTask`／LLMでsource475・479・481・482→translation523の結合を確認した。結合groupの実ReviewTask評価はfinding／revisionなし（`.tmp/matching-audit/sample2-source482-focused/check.json`、`evaluation.json`）。source482の文意はtranslation523末尾の「軍事部門および国防総省機関は…地理的または機能的な責任範囲内…調整する」に対応する。unit同士の粒度差が保存結果の未対応・誤groupにつながる具体例で、複数source対1translation照合が復元できた。全682翻訳unitのEmbedding検索はbatch応答待ちが長く、144 vector生成後に停止したため、節から絞った候補集合の結果を全文順位検証とは扱わない。
- sampleの保存Reviewで日付`2026/08/20`が`2026/0820`へ誤抽出され、スラッシュ欠落と指摘されたfindingを目視監査。原文・訳文PDFの該当表は両方とも`2026/08/20`だった。日付行で暦日が等しいLLM findingを正しい判定へ正規化し、誤検知と再試行を同時に除く。実ReviewTask＋LLMは1 callで指摘・Revisionなし、確認済みになった。証跡は`.tmp/matching-audit/sample-date-inspect/`、`.tmp/matching-audit/sample-date-recheck-v2/check.json`。
- sample1 v55（`.tmp/matching-audit/sample1-full-current-v55/`）はv53の161callとEmbedding cacheを引き継ぎ、237call／186round後に先頭ページの複製原文をOCR比較から除外する修正のため停止。訳文`#/tables/41/cell-r0004-c0000/content`（`ISR`）は23回の旧履歴を超えて再照合されていない。全文Review成果物は未生成。call/cacheは再開用に保持している。
- Review制御出力枠修正後、`uv run pytest tests/unit tests/regression -q`は369件成功。Ruff lint、format、ty、`git diff --check`も成功。
- 保存済みsample Reviewを追加監査し、長表の誤groupの原因を発見。`Document.unit_contexts()`が各セル行の最初の非空セルをrow_labelにしていたため、説明列自身の本文や値を行キーとして誤用していた。先行列のラベルセルから行キーを取るよう修正し、同一行の説明列・値列が共通キーを持つunitテストを追加。さらに同一行候補内で同じ列位置を優先する。保存済みsample長表40セルの新Embedding候補検索は40/40で正しい行・列を1位に選択し、現行ReviewTask＋実LLMのmatched groupも40/40期待値と一致（`.tmp/matching-audit/sample-longtable-rowlabel-v44/check.json`）。
- sample4の保存Reviewでsource88→translation164という誤対応を確認。現行節補正はsource87・88→translation176を検索し、ReviewTask＋実LLMも正しい結合を返した。source80・83→translation164の別の結合例も、EmbeddingGemma（`text-embedding-embeddinggemma-300m-qat`）を用いた現行検索＋実LLMで期待groupに一致（`.tmp/matching-audit/sample4-merged-embeddinggemma-v47/check.json`）。Nomicは同じsample4全文候補で誤候補を上位にしたため、モデル依存は残る。品質検査359件成功、Ruff、format、ty成功。全PDFのfinding監査、sample1全文Review、他PDF Upgradeの現行版再検証は継続中。
- 同じEmbeddingGemma／LLM設定で既知の誤groupを全文候補から再確認: sample2 source97→translation115、sample3 source43・45→translation45、sample5 source102→translation53・source113→translation66。source101の式(8)は訳LOAD内に式の相手が見つからずsource-onlyとし、誤候補translation61を避けた。証跡は`.tmp/matching-audit/sample2-source97-v48/check.json`、`sample3-source45-v50/check.json`、`sample5-known-false-v49/check.json`。
- sample3保存Reviewのsource23→translation70は再監査で部分対応に分類を訂正。translation70には「114 sites」の訳がある一方、24施設・4管理局は訳出されていないため、source23を未対応とするfocused結果だけではfindingの妥当性を否定できない。
- sample4の保存誤group source83→Figure 2 captionも再照合し、source80・83→本文translation164を実LLMで確認。別節source85はsource-onlyとなった（`.tmp/matching-audit/sample4-controller-overhead-current/check.json`）。
- sample4表の行1にある原文数値3セルが訳文行0の列見出しへ誤対応していた。現行候補検索は同じ行・列を選び、ReviewTask＋実LLMも3/3期待対応（`.tmp/matching-audit/sample4-table-candidates-v56/check.json`）。sample3・4・5の訳文先頭に原文とほぼ同一の英語ページがあり、そこでのOCR差が保存findingに含まれることを確認。評価では原文LOAD本文を比較基準にし、翻訳有無は引き続き評価、編集spanは与えない。sample5の実LLM focused再評価は未翻訳指摘のみで数式OCR差を指摘せず、修正提案もなし（`.tmp/matching-audit/sample5-duplicate-frontpage-v59/check.json`）。実LOAD上ではsample3/4/5が検出、sample/sample1/2は対象外（`.tmp/matching-audit/copied-front-page-v58/check.json`）。
- sample4の表で、原文行1の数値3セルが訳文の行0列見出しへ誤対応し、誤検知となっていた。現行候補検索は同じ行・列の訳文セルを3件とも選び、ReviewTask＋実LLMも3組すべて期待対応（`.tmp/matching-audit/sample4-table-candidates-v56/check.json`）。同じPDFの「空白欠落」指摘はfocused再評価で空白差でなく英語見出しの未翻訳を検出したため、旧理由は不正確だがunit全体の誤検知ではない（`.tmp/matching-audit/sample4-ocr-whitespace-v57/check.json`）。
- sample2の旧誤対応対象source439を現行候補検索で再照合し、本文が一致するtranslation465を検索・実LLMで確認（`.tmp/matching-audit/sample2-mobile-current/check.json`）。
- sample2 source482の初回照合では16件batch／4件batch／単独要求がReadTimeoutし、本文299文字・候補unit最大430文字でもEmbedding負荷が課題となった。その後、該当節に候補を絞った実LLM照合で複数source unit→translation523を確認した。全候補順位の検証は未完了。
- sample1現行全文Review v53は161件の成功call後に中断。訳文`#/tables/41/cell-r0004-c0000/content`（`ISR`）を原文の異なる表セル23件と照合し、23件すべてsource-only／translation-onlyだった。同一scopeだけを見る既存停滞検出では候補相手が毎回変わると止まらない。Reviewは1unitあたり3回の不成立後に候補から外し、Upgradeは同じ英文unitへの3回のmatch失敗を未確認として記録する修正を追加。
- sample2 Upgradeの保存callでは同じ原文v1/v2セルが各13回登場し、そのうち12件は5回の応答再試行後に失敗していた。Upgradeも失敗履歴からunit別回数を復元し、同じ対象を延々と再送しない回帰テストを追加。
- 上記の回帰テスト追加後、`uv run pytest tests/unit tests/regression -q`は360件成功。Ruff lint・format、ty、`git diff --check`も成功。
- sample1全文Review v52（`.tmp/matching-audit/sample1-full-current-v52/`）は78件のcall保存後にLLMTimeoutErrorで失敗。v53（`.tmp/matching-audit/sample1-full-current-v53/`）はv52のcallとEmbedding cacheを引き継いだが、161件のcall中に同一訳文unitの反復を発見したため中断。call/cacheはv54再開用に保持。全文Review成果物とfinding監査は未完了。
- マッチング精度の追加監査: sample保存Reviewの長表誤group由来finding10件を検出し、現行検索66セルが66/66正しく選ぶことを確認。sample5の誤group由来Review false positive3件を検出し、現行検索＋実LLMで正しいsource106→translation61、source108→translation63、source113→translation66を確認。sample2の既知誤groupも限定候補再照合で正解候補を返した。sample1全文ReviewはEmbedding要求待ちで停止・cache保管中。sample3・4の分割/結合例とsample Upgradeの差分4件は現行検索＋実LLMで正解を確認。sample2／5全findings、sample1全文、他PDFの現行Upgrade検証は未完了。詳細は[MATCHING_VALIDATION](docs/MATCHING_VALIDATION.md)
- sample1全文Reviewのv38はEmbedding要求待ち、v51は出力上限超過、v52はLLM timeoutで失敗。v53では同一訳文unitを別候補で23回照合しすべて不成立になる挙動を確認。unit別の失敗上限をReview／Upgradeへ追加し、v54再検証は未実施。
- 保存済みsample Reviewの長表で別レコード間の誤対応を10件確認。現行検索は順位付けと近傍確認に使うベクトルだけを段階取得し、実sample1では1,204セルから2候補へ削減。現行ReviewTask／実LLMへ保存済み失敗範囲を再送し、正しい行だけmatched・候補外行はtranslation-onlyとなることを確認。unit／regression357件、Ruff、ty成功。
- sample5のReview入力PDFを画像で再照合: 原文はカゴメ格子論文。訳文PDFは8ページで、1ページ目に同論文の英語原文、2〜8ページに日本語訳がある一方、`SYS-DD-001`の表紙・ヘッダー・フッターが混入。以前の「2ページ目以降は別文書」という判定は誤りと訂正。保存済みReviewの誤対応を本文で監査し、式周辺2 findingは誤group由来と確認
- 作業ブランチ: `feature/review-matching-audit`（`main`の`11146bc`から分岐。未push）
- 実装: Review／Upgradeの候補選択と照合に構造情報を追加し、照合時のIDを文書ごとに短縮
- 品質検査: 表行のEmbedding前フィルターを含む最新実装でunit／regressionテスト356件、候補検索テスト16件、Ruff、ty成功
- 精度検証: sample／sample1〜5の保存済み結果から誤対応を確認。sample5の正解データにも式前後の取り違え1組を検出し訂正。候補の全列挙を避ける方式と、Upgradeの重複した網羅性出力の削減を追加検証中

修正版ではsampleの既知の3組、sample5の既知の2組と追加候補を含む4組、sample1〜4の正解8組／1組／2組／1組に実LLMで一致した。
sample1〜4の再送はすべて1試行で成功。全文Reviewの再実行と、成果物に残る指摘の監査は継続する。

- sample1の既知誤group source「Planning Products」(p.7)→translation本文表「計画機能」(p.38)を追加監査。表セルの候補検索文に同じ行の隣接セル本文を加え、限定候補の実LOAD検索が同じ目次行「計画成果物」(p.7)を選択し、ReviewTask＋実LLMも期待groupを返した（`.tmp/matching-audit/sample1-planning-products-real-review-v1/check.json`）。回帰テストを追加。`uv run pytest tests/unit tests/regression -q`: 375 passed、Ruff lint／format、ty、`git diff --check`成功。
- sample1全文Review v62は820 callで6時間の全体期限に達し、`LLMTimeoutError: LLM Task deadline exceeded`となった。保存済みcallとEmbedding cacheを保持し、現行コードをロードしたv63（PID 48036）へ引き継いで再開した。v63のReview成果物・finding監査は未完了。
- v63はv62の820件の保存済み照合callを再利用しているため、最終全文結果は修正前後のコードが混在する。既知誤groupはfocused Reviewで新コードを別途検証し、全文auditではcall時刻・groupを区別する。
- v63は2026-11-06 01:42 JSTに1000 callへ到達し処理継続中。LLM・Embeddingとも直近要求は成功、Review成果物は未完成。
- sample1の保存済みfinding 9件を元のmatched groupへ再構築。誤group由来は「Planning Products」→本文の「計画機能」と「Ill-1」→別行「IV-1」の2件で、いずれも現行コードのfocused Reviewが正しいgroupを返すことを確認。PDF画像で「5 第III章」の指摘は翻訳に実在し、CICS指摘も原文画像がCJCS・訳文がCICSで正当な指摘と確認。全文結果の監査は未完了。

監査した結果、採用した修正と再検証の証跡は[対応付け精度検証](docs/MATCHING_VALIDATION.md)へ記録する。

## 🧪 実機検証

今回の対象順序はsample2、sample1。各文書をRegister→Translate→Review→Upgradeの順で検証する。起動は`scripts/real_acceptance.ps1 -StartAt sample2`とし、実行記録のパスは完了後に追記する。

Reviewの訳文はTranslateのDOCXをWordでPDF化したものを使う。Upgradeは英文v1に元PDF、英文v2に最終ページを削除したPDF、日本語v1に訳文PDFを指定し、差分処理も検証する。

| 文書 | Register | Translate | Review | Upgrade |
|---|---|---|---|---|
| sample | 成功 (`01a19c62-8e22-7122-8466-6223fc7bc637`) | 成功 (`01a19c64-60a7-7cc2-a9a4-f2b7234ff37b`) | 成功 (`01a19c6e-5408-7722-a481-343979864921`) | 成功 (`01a19c9d-067a-7e81-a505-931a0d770ea4`) |
| sample5 | 成功 (`01a19ca0-2f7f-7cd3-8ae1-8b1c0fbadc46`) | 成功 (`01a19cc6-99de-7441-9c48-f0bce42649cb`) | 成功 (`01a19cf1-bc56-7be0-8049-5b34d11b211a`) | 成功 (`01a19d2e-8f8a-79f2-9616-4a7d66f60b09`) |
| sample4 | 成功 (`01a19d75-7293-7281-a82a-53c5b5f69c70`) | 成功 (`01a19d7e-7d4e-7600-b001-4b4efd8b8979`) | 成功 (`01a19d9a-a44d-7d73-980e-61ede59e59bb`) | 成功 (`01a19de8-a4ba-7b80-8e27-37e629478037`) |
| sample3 | 成功 (`01a19ded-1c63-7382-a00f-9efa86f6b2bd`) | 成功 (`01a19df6-d813-7fa1-832d-0e89ea9ed911`) | 成功 (`01a19e1a-96b2-7f73-835e-6adaf2252131`) | 成功 (`01a19e38-0950-7641-9c93-077cc9e0d421`) |
| sample2 | 処理中 (`01a19f9d-ef80-7c83-a096-3637c23f8bfc`) | 実行待ち | 実行待ち | 実行待ち |
| sample1 | 実行待ち | 実行待ち | 実行待ち | 実行待ち |

## ✅ 実装済みの修正

- Upgrade: 同一英文を`difflib`で事前照合し、LLMへ送らない
- LLM入力上限: LiteLLMの`/utils/token_counter`で判定し、未対応のendpointでは`LLM_INPUT_BYTES_PER_TOKEN`で換算する
- Embedding: 再試行をOpenAI SDKへ委譲する
- MERGE: `docling-core`の`concatenate`へ置換する（既存6文書のLOAD結果と本文が一致）
- 文分割: `pysbd`へ統一する
- OOXML: `python-docx`へ置換する
- JSON Schema: STRUCTUREとTRANSLATEをPydanticの生成へ統一する
- Docling: 断線を最大30分待機し、変換済みpartを再利用する。到達しないOffice対応と未公開の状態値を削除する
- LLM応答: HTTP 200の非JSONを応答不正として再試行する。Schema深度の検査で`$ref`を展開する
- 小規模な整理: `hashlib.file_digest`、用語集の正規表現、Pandoc ASTのキャッシュ、`python-dotenv`の削除、未使用コードとコメントアウトの削除、重複処理の共通化、Docstringの`Returns`修正

## ⏸️ 見送りと未対応

- LOADの`dict`処理は`docling-core`へ移していない。適用範囲はMERGEだけとした
- STRUCTUREとTRANSLATEのLLM Call保存処理は統一していない。分割と`partial`の扱いがREVIEW・DIFFと異なるため
- `.env.sample`へ`LLM_INPUT_BYTES_PER_TOKEN`を追記していない。権限でファイルを読めなかったため

- sample1全文Review v63は1,517 call後、2026-11-06 04:57 JSTにEmbedding要求timeoutで失敗。finding成果物は未生成、diagnosticsは空。利用者のEmbeddingサービス再起動後、単発疎通（1入力→1 vector）成功。v63のcallと候補vector cacheをv64へ引き継ぎ、Reviewを再開。v64は旧call再生後、新規照合を処理中。
- 2026-11-06 06:01 JST時点でv64は1,679 call、status=processing。再開後約59分、Embedding/LLM要求は継続成功。全Review成果物は未生成のためfinding全件監査・最終精度判定・commitは保留。
- 2026-11-06 06:08 JSTにsample5 v75保存findingを再照合。17件中11件は複製された英語先頭ページのOCR/数式差、現行処理で比較基準を原文にするため誤指摘抑制の対象。残り6件は日本語ページ上のfindingで内容確認が必要。v64 sample1全文Reviewは1,698 call・processing、最終監査未完了。

- 2026-11-06 06:51 JST: sample2保存済みReviewでsource #/texts/294が誤候補 #/texts/229にgroupされ、正しい本文は42-spanのtranslation #/texts/325へ結合されている事例を確認。現行Embeddingでspan coverageは正候補0.734／誤候補0.508、unit cosineは誤候補0.692／正候補0.641。構造種別フィルターを緩和し、長いcross-kind候補をspan再順位付けする変更と回帰テストを追加。unit/regression 375 pass、docstring修正後の関連26 pass、Ruff／ty pass。全候補PDF検索と実Review検証はEmbedding要求待ちで未完了。詳細は[対応付け精度検証](docs/MATCHING_VALIDATION.md)。

- 2026-11-06 06:55 JST: sample2 source294の限定候補現行検索が正訳325を選び、実ReviewTask＋LLMも294→325を`matched`と判定。PDF由来の同一モデルspan cache／実測cosineを利用した候補2件のreplayで、全訳文書順位検索の完了とは区別する。全候補検索v78はEmbedding要求待ちで停止。sample1全文Review v64は再開後1,757 call、processing。

- 2026-11-06 06:57 JST: 最新コードで`.venv/Scripts/python.exe -m pytest tests/unit tests/regression -q`で376 passed。全体Ruff check／format、tyもpass。sample1全文Review v64は1,762 call、processing継続。

- 2026-11-06 06:58 JST: sample2保存Reviewのsource97/632/900/1062/62の誤groupを既存focused実LLM結果で再点検し、正候補115/736/1105/1252・分割訳362〜368を確認。source341→translation482はDOD引用のみの部分対応で、本文訳漏れfindingは妥当。証跡はMATCHING_VALIDATION.mdに追記。

- 2026-11-06 07:06 JST: span再順位付けの上限を同kind long unit上位8件とcross-kind long unit上位16件へ分離。最新コードでunit/regression 376 passed、Ruff check／format、ty check、git diff --check成功。sample1全文Review v64は1,786 callでprocessing継続。

- 2026-11-06 07:07 JST: sample5 PDF画像で式(10)/(12)のf_{8ν}は正しく、LOAD OCRの`86`/`□`起因のfalse positiveと確認。訳PDFの式(18)相当は番号(13)の実誤記だが、source LOADに式(17)/(18)unitが欠け、正groupに直すとtranslation-only target78はmatched対象評価から外れる。マッチング修正だけでは再検出できない残課題としてMATCHING_VALIDATION.mdに記録。
- 2026-11-06 07:16 JST: 利用者によるEmbeddingサービス再起動後、sample1全文Review v64の同一PID 25660が処理を継続。ログ上Embedding要求266件を開始し266件すべて完了、LLM要求も成功。Review成果物は未生成で全文finding監査は未完了。既存Upgrade実行記録は現行コードではないため、現行コードでのUpgrade検証はsample1完了後に実施する。

- 2026-11-06 07:22 JST: 現行コード（指紋`883ad05a…`）で保存済みsample Upgradeを再実行し成功、変更4件を検出。原文v1のAppendix見出し2件・節見出し1件・本文1件が原文v2で削除され、それぞれの翻訳unitも削除と判定した結果は入力差分どおり。LLMのmatch参照制約違反1件は再試行で回復。成果物・照合証跡は`.tmp/matching-audit/upgrade-sample-current-v80/`、詳細は[MATCHING_VALIDATION.md](docs/MATCHING_VALIDATION.md)。sample1全文Review v64は同じPIDで処理継続中。

- 2026-11-06 07:25 JST: sample1全文Review v64はPID 25660でprocessing継続、ログ2,048行。Embedding開始293件／完了293件、直近LLM要求中で最終成果物なし。sample Upgrade v80はstatus=succeeded、4件の削除変更は原文v1にのみ存在し、原文v2（13ページ、v1は14ページ）に4文字列すべて不在と確認。

- 2026-11-06 07:37 JST: sample5保存Review v75の残り6findingを再分類。Figure 4は許容スタイル差、source102→target63とsource113→target78は現行focused Reviewで誤groupを解消、式(10)/(12)はPDF画像上正しくOCR false positive。式(18)相当の番号誤記は実在するが原文LOADに式17/18がなくmatched-only Reviewでは未検出。証拠と限界をMATCHING_VALIDATION.mdに記録。
- 同日sample5全文Review v81を現行コードで開始。sample1全文Review v64とEmbedding要求が競合し両方80秒以上pendingとなったためv81のみinterrupted、入力とcall/cacheは保持。sample1の同じPID 25660を優先し、その後Embedding 323/323完了、processing継続。tests/unit/test_matching.py: 25 passed。
- 2026-11-06 07:39 JST: sample1全文Review v64は同一PID 25660でprocessing継続。Embedding要求329件すべて完了、Review成果物は未生成。v64は今回の最新コード変更前に起動したため、全文結果は現行コードの受け入れ証拠として扱わない。現行コードで既知範囲をfocused再照合し、sample5全文とsample1全文の最新コード検証は別途必要。

- 2026-11-06 07:46 JST: sample3のKey Components findingは再監査で部分対応（114 sitesは翻訳、24施設・4管理局は未訳）の可能性が高いと訂正し、false positiveと断定しない。sample4の誤groupは保存結果source83→Figure 2 captionに対し、focused検証v47でsource80/83→translation164、source87/88→translation176の段落結合を確認。sample1全文Review v64はPID 25660で継続中。

- 2026-11-06 JST: sample3の保存Reviewで別のfalse positiveを確認。原文「Environmental Management」行の7,434（`#/tables/2/cell-r0009-c0004/content`）が、別行「Legislative Proposal」の749（`#/tables/2/cell-r0013-c0004/content`）へ誤対応。正しい訳は同じ行の「環境管理」7,43 4。現行MatchingCandidatesの行ラベル・兄弟セル検索と関連unit/regression test 376件passを確認。sample1 v64はPID 25660でprocessing継続、ログEmbedding 372件／LLM 902件。現行コードでの実データ再照合は未完了。
- 2026-11-06 07:52 JST: 現行コードでtests/unitとtests/regressionを再実行し376 passed（53.10s）。sample1全文Review v64はPID 25660でprocessing継続、Embedding 385件・LLM 933件完了。v64は旧コードhashのため最終現行精度の判定には未使用。sample3の7,434→749実データ再照合はEmbedding cacheに行・兄弟セルcontextのvectorがなく、sample1実行中の同時要求はtimeoutしたため保留。

- 2026-11-06: sample3 PDFのp.16／訳p.22を画像確認。保存Reviewのgross→net指摘はsource gross row12が別のnet row15と誤groupされたfalse positive（正しい訳 row12には「総額」あり）。1,796/1,357の空白指摘もPDF上のセル折り返しで誤検知。ただしsource画像の負号はLOADで欠落し、訳画像は正数表示のため、符号差はLOADレビューから判定不能という別残課題。証拠・未検証範囲を[MATCHING_VALIDATION.md](docs/MATCHING_VALIDATION.md)へ追記。

- 2026-11-06: sample3の保存Reviewで表のページ跨ぎ誤groupを追加確認。source table2 row12「gross」→同表row15「net」、row13「Legislative Proposal: Reclassify...」→次表row0「立法提案」、row17「Existing law」→次表row1「総計、義務的支出」。各々同じ表の同じ行に正しい訳がある。PDF画像でsource p.16／translation p.22を比較し、数値の改行はfalse positiveだがsource負号はLOADで欠落する別課題も判明。詳細はMATCHING_VALIDATION.md。

- 2026-11-06: sample3表の追加誤groupを確認。EWGPP source `#/tables/0/cell-r0006-c0000/content`が別表のNNSA行へ対応し「未翻訳」とfindingされたが、訳PDF page 20の同じ表・行に兵器級プルトニウム生産廃止の訳が存在する。false positiveとしてMATCHING_VALIDATION.mdへ記録。

- 2026-11-06 08:06 JST: sample1全文Review v64はPID 25660でprocessing継続、Embedding 412件／LLM 999件完了、review.json未生成。旧コード実行のため現行コード精度証拠にはしない。sample3表・EWGPPの実データ誤groupをMATCHING_VALIDATION.mdへ追記し、現行コードの実PDF再照合はEmbedding負荷が解消してから行う。unit/regressionは376 passed。

- 2026-11-06: sample3表誤groupを受け、候補Embedding用の表セル数値を正規化。`7,43 4`を`7,434`として扱い、空白を含む任意の隣接数値は結合しない。新規回帰テスト込みunit/regression 377 passed、focused matching 26 passed、Ruff check／format・ty passed。現行コードでsample3 PDFの候補再照合はEmbedding cache missのため未完了。

- 2026-11-06 08:12 JST: sample1全文Review v64はPID 25660でprocessing継続、Embedding 433件／LLM 1,055件完了。review.json未生成。候補数値正規化の追加後、focused matching 26件pass、全unit/regression 377件pass、Ruff check／formatおよびty passを確認済み。

- 2026-11-06: sample3表の現行コード候補検索v82で既知6件すべて正しい訳候補を選択。隣接行ラベル文脈を追加した後、実LLMのfocused照合v84では6件すべてを正しい同一行へ単独matchedとし、gross/net行の取り違えと提案見出しの重複対応を解消（`.tmp/matching-audit/sample3-table-cells-review-current-v84/check.json`）。関連unit 120 passed、unit/regression全体377 passed、Ruff check/formatとty checkもpass。sample1全文Reviewは旧v64の処理を停止し保存Call/cacheを保持済み。Embedding service再起動完了を受け、現行コードで全文Reviewを別出力先から再開する。

- 2026-11-06: Embedding service再起動完了後、sample1全文Reviewを現行コードhashでv85として再開。旧v64の2,004 Callと130.3 MiB candidate-vector cacheを複製して引き継いだ。v85はprocessing中で、成果物生成・全finding監査・最終精度確認は未完了。旧v64はinterruptedのまま保持。

- 2026-11-06: 同じ表文脈を使うUpgradeのDIFF promptにも隣接行ラベルを説明し、Review／Upgrade共通テストで前後行ラベルがpayloadに渡ることを確認。関連context test 4 passed、unit/regression 377 passed、Ruff check/format・ty check passed。sample1 v85はLLMとEmbedding要求（1件）を実処理で成功しprocessing継続。

- 2026-11-06: sample1現行Review再開で、再照合結果の変化により旧evaluate targetが消えた後、旧match Callもすでにmatchedのunitを再指定して停止する問題を再現。保存操作の再生時、現行groupに存在しないevaluate/recheckと、既にmatched済みunitを含むmatchをskipし、残りを現在stateで再処理するよう修正。回帰テストは修正前に失敗し修正後に成功。unit/regression 378 passed、Ruff/format/ty/diff-check passed。sample1 v87は2 stale evaluate・3 stale matchをskipしてprocessing継続、最終Review監査は未完了。

- 2026-11-06 08:52 JST: sample1 v87はstale evaluate 2件・stale match 3件をskip後、LLM照合を継続。LLM 189件完了、status=processing、review.json未生成。Embedding cache再利用中。

- 2026-11-06 08:55 JST: stale evaluateのうち、現在のgroupにはあるが別の保存Callですでに確認済みのtargetを再評価しようとするケースも回帰テストで再現。再生時に重複evaluateもskipする条件を追加、focused regression passed。sample1 v87（追加guard適用前に起動）はprocessing継続、LLM 309件完了、stale evaluate 2件・match 5件をskip。

- 2026-11-06 08:57 JST: 重複evaluateを含む保存Call再生修正後、全unit/regression 378 passed（60.16s）、Ruff check/format、ty、git diff --check passed。sample1 v87はprocessing継続。

- 2026-11-06 09:08 JST: sample1 v87のEmbedding再計算は16件batchを20回完了し、cacheは137.0 MiB。各batch成功、LLM 323件完了後もprocessing継続。サービス再起動後のEmbedding応答に再停止はない。

- 2026-11-06 09:13 JST: Upgradeでも既存の確認済みsource unitを古いsaved matchが再指定して`Use recheck to revisit confirmed changes`となるケースを再現。Review／Upgrade両方のresume loopで、現在stateに適用できない保存操作の`InputError`を捕捉してskipし、未確認対象を現行Agentへ残すよう統一。Review stale eval/matchおよびUpgrade stale matchの回帰test 2件を含めunit/regression 379 passed、Ruff/format/ty/diff-check passed。sample1 v87は旧guard版でprocessing中、Embedding 28 batch完了。

- 2026-11-06 09:16 JST: sample1 v87 status=processing、Embedding 32 batch成功、candidate-vector cache 142.3 MiB。LLM 323件完了、stale-operation skip後の追加エラーなし。

- 2026-11-06 09:28 JST: v87はEmbedding要求開始後にworker不在となり、statusをinterruptedへ記録。cache/callsをv89へ引き継ぎ、最新コードでforeground監視sessionから再開した。stale evaluate 2件・match 5件をskipして復帰。LLM 3件・Embedding 4 batch（最後は2件）成功しprocessing継続。v89のstdout/stderrを保存中。

- 2026-11-06 09:42 JST: sample3 v84 focused照合artifactにpass判定を付与し、6 expected pairと6 actual match pairが完全一致。sample1 v89はlatest codeでprocessing継続し、LLM 9件・Embedding 29 batch完了、cache 152.8 MiB、API/worker errorなし。

- 2026-11-06 09:45 JST: sample1 v89はprocessing継続、LLM 11件・Embedding 37 batch完了（最後は4件）。stale操作skipは7件のまま、Review/Embeddingエラーなし。

- 2026-11-06 09:49 JST: sample1 v89はLLM 17件・Embedding 45 batch完了、stale operation skip 7件。API/Review errorなし、processing継続。

- 2026-11-06 09:54 JST: sample1 v89はLLM 34件・Embedding 57 batch完了、worker alive（約436 MiB）、ログ上の失敗なし。

- 2026-11-06 09:59 JST: sample1 v89はLLM 48件・Embedding 69 batch完了、candidate-vector cache 162.8 MiB。stale operation skip 7件、1件の不正Action応答は再試行で回復。Review processing中。

- 2026-11-06 10:05 JST: sample1 v89 LLM 67件・Embedding 83 batch完了、stale skip 7件。1回の不正Actionは再試行で回復済み。その他の失敗なくprocessing継続。

- 2026-11-06 11:01 JST: sample1 v89はworker稼働中、LLM 394件・Embedding 253 batch完了。保存された新しい照合では、translation `#/texts/3711/content`が前roundでtranslation-onlyになった後、次roundにsource `#/texts/4530/content`へ正しく再対応し、隣接する別文source `#/texts/4531/content`はtranslation `#/texts/3712/content`へ独立して対応した。複数roundでの候補再探索が文境界・粒度差を回収した実例。成果物と全文finding監査は未完了。

- 2026-11-06 11:25 JST: sample1 v89はLLM 458件・Embedding 281 batch完了、PID 19684でprocessing継続。11:22時点の直近match roundは2131で、表のsource table10／translation table20を処理。Review成果物はまだなく、全文finding監査は未完了。

- 2026-11-06 11:34 JST: sample1 v89はLLM 507件・Embedding 299 batch完了、worker processing。保存callは2,211、Review評価chunkは72件。成果物未生成。これらの再生済み旧callを含む全文結果はコード世代が混在するため、既知誤groupはfocused現行コードの証跡と分けて監査する。

- 2026-11-06 11:56 JST: Embedding endpointはTCP/API到達可能で、認証なしの`/models`は401を返す。sample1 v89（PID 19684）はReviewを継続中だが、本コードの照合世代filter追加前に起動したため、結果は監査用で現行resume検証として扱わない。Review/Upgradeの成功Call復元と失敗match回数復元にmatching versionを追加し、versionをfingerprintとcall ID lineageへ含めて旧Callとの再利用・衝突を防止。旧世代を除外する回帰テストを追加。`uv run pytest tests/unit/test_agents.py -q`は97 passed、Ruffとty checkはpass。PDF全体の再実行・finding監査は未完了。

- 2026-11-06 12:05 JST: 全384 testのうち383 pass、1 regressionでReview分割親Call IDのversion不一致を発見。親ID計算にも同じmatching version lineageを使う修正を追加し、該当testを単独再実行してpass。全suiteを再実行して384 passed。`ruff check translate tests`、`ruff format --check translate tests`、`ty check`、`git diff --check`もpass。Review/UpgradeのPDF全体検証・成果物監査は継続中。

- 2026-11-06 12:10 JST: 既存sample2 Upgrade失敗記録`01a190b1-157a-7131-9b8f-71543b87efc3`のsource v1/v2および日本語v1 PDFを特定し、同じ3入力で現行UIから新規Upgrade `01a1aed5-1b6c-78c0-9199-0065584226be`を開始。SPLIT成功、DOCLING処理中。旧記録の同一unit再試行12回を、新しい保存callと成果物で比較する。

- 2026-11-06 12:16 JST: `llm_call_id`へ明示的な`matching_version`を渡す形に整理し、世代差によるID分離testを追加。`uv run pytest -q`は385 passed。`ty check`、format、diff-checkはpass。Ruffはmatching.pyの新規commentに含まれた曖昧なen dashを指摘したため、ASCII hyphenへ修正して再検査する。

- 2026-11-06 12:18 JST: sample2の過去失敗Upgradeと同じsource v1/v2・translation v1を現行UIで実行したID `01a1aed5-1b6c-78c0-9199-0065584226be` が成功。変更0件、旧planのmodified 2件は再現せず。source v1/v2の859 TextUnit本文列は完全一致し、824 unitずつ未変更確認。UI成果物検査成功（`.tmp/matching-audit/sample2-upgrade-current.png`）。完全一致による早期確定でDIFF callは0件のため、再試行抑制はunit testで確認し、実PDFでは過去false positive解消を確認。詳細を`docs/MATCHING_VALIDATION.md`へ記録。

- 2026-11-06 12:22 JST: sample1 v89はworker稼働中、保存Call 2,316（11:34時点から+105）、Review成果物なし。旧matching callを含むため最終現行コード検証ではないが、既知誤対応の発見・全文finding監査用として処理を継続。

- 2026-11-06 12:25 JST: v89（PID 19684）を停止。2,316 call／ログ／cacheは保存し、legacy成功Callを再生するため現行結果として扱わない。既存baselineの同一sample1 LOAD文書とv89候補Embedding cacheを用い、`MATCHING_VERSION=1`のクリーンReview v90（PID 38780）を開始。`validation.json`を保存。初期Agent判断中で、新規保存Callはまだなし。

- 2026-11-06 12:30 JST: v90はPID alive／応答可能で、候補cacheを読み込み後に更新（192.6→195.2 MB）した。初期候補探索は進行中で、保存Review Callはまだ生成されていない。
- 2026-11-06 12:35 JST: v90はCPU・memory使用が増え、candidate-vectors cacheは198.0 MBまで更新。Review Callはまだ0件。LLM `/v1/models`とDocling `/health`は応答するため、processを維持して進行を監視する。
- 2026-11-06 12:36 JST: v90で現行世代Callが初めて保存され、round 0 matchが`matching_version=1`・status succeeded。source／translation冒頭の`Joint Publication 5-0`を実LLMが対応付けた。legacy Callを再適用せず新規matchから開始した証拠。
- sample1 v90の保存Callを監査中、表紙のsource `Joint Planning`が本文62ページのtranslation見出しへ誤対応していることを検出。訳文PDF表紙には同じ見出しがある一方、Docling LOADからは欠落していた。ページ位置を候補順位に使う修正と回帰testを追加し、source表紙見出しに対するsample1実候補検索は遠い本文見出しから先頭ページ候補へ変更。ただし訳見出しの抽出漏れは続いており、Review全文での判定は未確認。v90は誤group保存後に停止済み。現行全体Review v91の起動試行はWindows subprocessのimport環境を継承できず失敗したため、Call 0件・Embedding cacheのみ保存して停止した（`.tmp/matching-audit/sample1-full-current-v91/`）。このためfocused実データ検索と単体検証までを完了し、PDF全体検証は未完了として扱う。
- 2026-11-06 14:15 JST: sample1表紙見出し誤対応を再調査。source `#/texts/1/content`「Joint Planning」対translation全403見出し（保存Embedding cache）では、最高候補が本文p.19の「7.1.5 Planning Process」、cosine 0.705／ページ位置補正後0.561。遠い表紙見出しの補正後scoreが0.60未満なら候補追加しないルールを追加し、全403見出し検索でtranslation候補なしを確認。現行実`ReviewTask`＋LLMもsource-onlyを返し、文書全体に訳がないとは断定しなかった（`.tmp/matching-audit/sample1-full-cover-candidate-check.py`、`.tmp/matching-audit/sample1-cover-heading-review-v2/`）。ページ位置はReview／Upgradeのプロンプトpayloadから除外し候補順位に限定。matching version 4、関連test 38 passed、Ruff／format／ty passed。現行全文Review v93は開始済みだが、14:15時点でCall未保存・成果物未生成。全文finding監査、sample／sample2-5の残りfinding監査、他PDFの現行Upgrade検証は未完了。

- 2026-11-06 14:27 JST: sample1全文Review v94をEmbedding再起動後に再開したが、初期化後にEmbedding要求が192.168.1.100:31000へ確立したまま応答せず、保存Call・成果物なしで停止。設定上のLLM endpoint 192.168.1.183:1234/v1/modelsはHTTP 200、Embedding endpoint /modelsはHTTP 401（認証なしの確認要求）を返した。worker状態は.tmp/matching-audit/sample1-full-current-v94/validation.jsonに記録。外部要求を伴わないsample3表セル6件の既存focused実Review結果はすべて期待pairどおり。現branch全体のpytest 389 passed、Ruff check/format、ty、diff-checkもpass。sample1全文Reviewとsample/sample2-5の残りfinding監査、各PDFの現行Upgrade再検証は継続中。

- 2026-11-06 14:30 JST: Embedding復旧を短時間で確認するため、現行設定を使いHTTP timeout 12秒・再試行なしで1件要求したが、APITimeoutError相当のEmbeddingErrorで失敗した。したがってsample1 v94の全文Reviewは未再開。sample長表の保存Embedding cacheも現在設定のendpoint/model fingerprintと不一致で、現行候補検索の再演には利用できない（過去の40/40結果は当時の設定・コードの検証証跡として保持）。

- 2026-11-06 14:48 JST: sample3表の最新LLM照合を追加検証。6 source／12 translationを一括すると5/6正解で、EWGPP pairをsource_only＋translation_onlyへ落とした。残ったsource 1件とtranslation 7件の照合ではEWGPPを正しく回復。sourceを1件ずつ、translation 12件の候補と照合した場合も5/6で、Legislative Proposalを同じ行の数値cell #/tables/2/cell-r0013-c0004/contentへ誤対応（期待は説明cell c0000）。これはmatch_documentsへ候補を直渡ししたfocused実験で、Embedding候補filterを通すReviewAgent全体の受入確認ではない。現行候補検索の同一行・列filter関連unit test 4件はpass。ReviewAgent部分実行v97は5 matched後の品質評価Callがprocessingのまま停止し、最終成果物なし。現行Embeddingは短時間疎通もtimeoutのため、RAG込み再検証待ち。
- 2026-11-06: Reviewの未matched source/translationが両方残る場合に、未matched unitだけで再照合し、3回失敗後は停止する修正を追加。現行matching versionを5へ更新して旧Call再利用を分離。追加回帰を含む全pytestは391 passed（90.46s）、Ruff check/format、ty check、git diff --checkも成功。Embedding再起動後に1件要求を再試行したが12秒でtimeoutし、PDF全文の実処理検証は再開できていない。sample3 focused結果など既存の実データ証跡は保持し、全文PDF受け入れ確認は未完了。
- 2026-11-06: 最新の保存Review（sample1 run `01a1a1fe-c9fa-77b0-bc92-5bc68e83de36`、226 findings）を走査し、`TPFDD`（`#/texts/332/content`）と`WARNORD`（`#/texts/333/content`）の2件で誤検知を確認。どちらもsource・translation・spanが同一略語なのに、保存responseは「その略語が訳文に含まれない」と指摘し、同じ略語を修正案として返していた。原文と訳文が一致し、reasonが同じ引用文字列の不在を主張する場合だけ評価を`correct`へ正規化するReview検証を追加。未訳見出し`GLOSSARY`のfindingを残す回帰ケースも含め3件pass。これはgroup誤対応ではなく品質評価の矛盾。全PDFの最新版再実行はEmbedding timeoutのため未確認。
- 2026-11-06: 略語誤検知修正後の全pytestは394 passed（98.83s）。`ruff check translate tests`、`ruff format --check translate tests`、`ty check`、`git diff --check`も成功。再起動連絡後のEmbedding 1件スモーク要求を再実行したが再びHTTP要求timeout。sample1全文など、現行コードによるsample群PDFの再Review・Upgrade受け入れ確認は未完了。
- 2026-11-06: sample4の最新保存Reviewも監査し、`#/tables/1/cell-r0004-c0000/content`「Spec. dec.」が原文・訳文で一致しているのに「そのまま保持すべき」と説明するFindingを確認。修正案はセル全体を最初のspanへ返しており、適用時に重複を作る内容だった。同一文面の正常性を理由自体が示す場合も評価をcorrectへ正規化するよう拡張。略語2件・Spec. dec.を抑制し、英語見出しGLOSSARYの未訳指摘を残す回帰4ケースが成功。最終全pytestは395 passed（95.13s）。Ruff check／format、ty、diff-checkも成功。Embedding 1件要求は12秒timeoutし、現行PDF全文の再Review・Upgradeは未確認。
- 2026-11-06: sample1目次の保存Reviewで、`III-1 5`/`III-15`、`III-1 8`/`III-18`、`III-1 9`/`III-19`、`IV-1 1`/`IV-11`、`IV-3 1`/`IV-31`の5件が空白差を誤指摘。source p.10、訳p.12–13のPDF画像とtargetを確認し、source側抽出空白を訳文欠落と逆に説明していた。ローマ数字形式のページ参照だけ数字間空白を正規化し、ページ番号差と英単語区切りは保持する検証・回帰を追加。直近全pytest 398 passed（94.06s）、Ruff／format／ty／diff-check成功。現行Embedding要求はtimeoutのためPDF全文の再実行は未完了。
- 2026-11-06: sample1／sample4の保存済みLLM Call responseを現行ReviewTask検証へローカルreplayし、TPFDD、WARNORD、Spec. dec.と目次page reference 5件の計8 assessmentが`correct`に正規化されることを確認。外部APIは使わず保存target・responseを直接使用。PDF全文の再生成・ReviewはEmbeddingが引き続きtimeoutするため未実施。
- 2026-11-06: sample2の`NCTS Naval Computer and Telecommunications Stations`はNCTSが実際には存在する一方で名称全体が未訳のため、有効findingとして維持する確認ケースを追加。略語欠落の矛盾だけで翻訳不備全体を消さない。回帰8ケースpass、全pytest 399 passed（88.38s）。Ruff check／format、ty、diff-checkも成功。Embeddingスモーク要求は再度timeout。
- 2026-11-06: 既存FIX成果物まで確認し、sample1目次の5件は正しい`III-15`等をsource抽出空白付き表記に戻す編集、sample4の`Spec. dec.`は1st spanをセル全文にして2nd spanの`dec.`と重複し、FIX後PDFに`Spec. dec.dec.`を出していたと確定。現行Review validationの8件ローカルreplayで全てcorrect化し、不要修正を抑止。sample最新3 findingはsource／FIX後PDF画像で見直し、誤検知と断定できず。Embedding 1件要求は今回もtimeoutし全文検証は再開できない。

- 2026-11-06 16:15 JST: 最新worktreeの全pytest 400件、Ruff check／format、ty、`git diff --check`を再実行して成功。sample2の保存Review後続Runを比較し、run `01a19e5e...`では表「Interface standards」のsource #/texts/414〜420に対して翻訳のunit順序が入れ替わり、Review findingのtargetも誤った文章を含む例を確認。後続run `01a19fc3...`では同じID範囲がsource順の対応へ戻っていることを保存target本文で確認した。これはunit粒度差・分割文脈の誤照合がReview誤検知に直結した事例と、後続翻訳Runで修正された証拠だが、現行MatchingCandidates＋ReviewAgentの再現試験ではない。sample1全文Reviewおよびsample群の現行PDF再実行・全finding監査は未完了。Embedding 1件要求は再び12秒timeoutした。

- 2026-11-06 16:24 JST: 保存済みsample2 Reviewの別runを再比較し、#/texts/414〜420の行対応についてrun `01a19e5e...`のsource/translationが入れ替わっていた一方、run `01a19fc3...`では各target本文が正しい順に揃っていることを確認。最新matching変更に関連するunit／regression抽出31件はpass。Embedding 1件スモークは再度12秒timeout。過去結果比較は現行コードの全文PDF検証ではなく、残るfindingとsample群のUpgradeを含む受入確認は未完了。
- 2026-11-06: 利用者からEmbedding再起動完了の連絡を受け、1件のみ・timeout 12秒・再試行なしで疎通確認したが、要求は再度timeout。全文Review／UpgradeのPDF受入検証は再開できていない。保存済みsample2 run `01a19fc3...`ではsource `#/texts/821/content`「...major regional」と訳unit 821「...主要な地域的」の続きが、それぞれ次の本文unit 825「conflict...」「紛争...」にある一方、間にheading 824「Chapter VI」が挟まることを確認。単独unitの評価が誤検知した可能性はあるが、heading越しの隣接文脈追加は誤抑制リスクがあり、今回の変更には含めず、二文書境界を使う再現試験と実LLM確認を次段階へ保留。既存Matching変更の全pytest 400 passed（89.75s）、Ruff check／format、ty、`git diff --check`成功。変更はfeature branchに残し、commit・main merge・pushは未実施。
- 2026-11-06: 現行ReviewTask＋実LLMでsample5既知失敗範囲4組（本文2組・式周辺1組・caption1組）を再照合し、期待対応どおりで数式と説明文の誤対応は再現しなかった。sample1 E-2は広い候補を直渡しすると別行・別列の同名セルへ誤対応する一方、現行候補検索相当の同列候補へ絞ると正しい訳セルを選択した。sample Upgrade保存結果v80は旧146／新版142 unitから末尾4件の削除のみだが、候補Embedding cacheは35件で現行UpgradeAgent全文の再実行には不足。Embedding単発要求もtimeout。全文PDF受け入れ・全finding監査は未完了。
- 2026-11-06: sample1全文Reviewの現行candidate rerankで、source `PREFACE`がtranslationの正しい`1 序文`ではなく長文候補を選び、source-only／translation-onlyとなる失敗を発見。短い見出しのspan rerankを止め、近い見出し候補2件をLLMへ渡す変更を追加。続いてsource「Expands discussion on global campaigning…」では、長い候補内の単一spanが正解unitより高評価となる別の取りこぼしを確認し、sourceが複数spanのときだけ長い候補をspan再順位付けするよう変更した。matching version 8。現行候補検索＋実LLMのsample1 focused検証は`PREFACE`→`#/texts/13/content`およびcampaign summary→`#/texts/41/content`が正解（`.tmp/matching-audit/sample1-preface-v6/check.json`、`.tmp/matching-audit/sample1-campaign-v8/check.json`）。全pytest 402 passed、Ruff check／format、ty、diff-check成功。現行sample1全文Review v8は継続中（`.tmp/matching-audit/sample1-full-current-v108/`）。
- 2026-11-06: 現行UpgradeAgent（matching version 8）でsampleの異なるsource PDF二版を再検証。146／142 unitを網羅し、削除4件は`Appendix A`、`Chapter Title`、`Section Title`、`Appendix body text sample.`と期待どおりで、日本語v1の各訳unitを正しく参照した（`.tmp/matching-audit/upgrade-sample-current-v108/validation.json`、`21-diff/plan.json`）。成果物の4変更と確認済みIDを監査済み。sample1全文Reviewはまだ処理中で、sample2〜5の現行PDF受け入れ・全finding監査、commit／main merge／pushは未完了。
- 2026-11-06: sample3の現行表候補検索で、行ラベルのないsource表セルが別表の別行を選ぶケースを追加検出。候補行の数値兄弟セルが順序まで一致する場合に順位を補正する matching v9 と回帰testを追加し、sample3既知セル6件を現行候補検索＋実LLMで再検証して6/6正しくmatched。全pytest 403 passed、Ruff check／format、ty、diff-check成功。sample1全文Review v108はmatching v8で起動した古いrunのままprocessingであり、v9全文の証拠とはしない。sample1成果物・finding監査、sample2〜5の現行PDF受け入れは未完了。feature branchに変更を保持し、commit／merge／pushはしていない。
- 2026-11-06: matching v9の副作用確認としてsample4の既知表セル3件を現行候補検索に通し、全て期待する同じ行・列セルだけが選択されることを確認。sample4の既存実LLM検証v56でも3組ともmatched。sample3 row12の正答候補はEmbedding単独0.565で誤候補0.6205を下回るが、順序付き数値列一致の補正後0.765となり実データ期待結果と一致。sample1全文Review v108は処理継続中でmatching v8のため、version9受け入れ証拠とfinding監査には使わない。
- 2026-11-06: sample5の数式source #/texts/113/contentを現行matching v9候補検索＋実LLMで再検証。候補translation 66／62のうちtranslation 66のみと正しくmatched（.tmp/matching-audit/sample5-candidate-review-v9/check.json）。これは既知数式誤対応のfocused確認で、全文Review受け入れではない。sample1全文Review v108は依然処理中、現在のmatching v9ではなくv8で起動したrun。
- 2026-11-06: sample1全文Review v108の保存CallでTOCの連鎖誤対応を発見。Planning is Commander's Businessが計画機能へ誤matchedし、正しい訳row0が消費された後、Planning Functionsが別rowの概要へmatchedしていた。兄弟cellのページ番号数字列を照合し、同一ページ・同スコアの近接候補を2つLLMへ渡すmatching v11を追加。focused現行検索＋実LLMでsource row0→translation row0、Planning Functions→計画機能row5を確認。回帰test追加後、matching unit test 34件pass。PDF画像では別のsource IV-9／translation IV-19不一致が両方IV-19の印刷に対するsource OCR欠落と判明。現行sample1全文v8 runはprocessing継続中で、v11全文成果物・finding監査は未完了。
- 2026-11-06: matching v11を含む現行全pytest 405 passed（88.27s）。Ruff check／format、ty、git diff --check成功。sample1全文Review v108はmatching v8で起動したままprocessing中、152 call保存済みだがReview artifactなし。
- 2026-11-06: sample1 TOCではsourceのpage refs V-12/V-15がLOADでV-1 2/V-1 5へ空白分割され、translation側は通常表記でも対応行は正しいと保存Call＋PDF画像で確認。Roman numeral付きページ参照だけ数字間空白を詰め、一般数値の空白は保つ正規化を追加しmatching v12。関連unit test 35 passed。sample2 Naval候補検索v11はcurrent cacheへ追加入力を処理中。sample1全文Review v108は引き続きmatching v8でprocessing。
- 2026-11-06: matching v12を含む全pytest 406 passed（86.18s）、Ruff check／format・ty・git diff --check成功。sample1全文v108およびsample2 Naval v11のcandidate検証は実プロセスとして継続中。いずれも出力未完了で、成功扱いにはしていない。
- 2026-11-06: sample1全文Review v108（matching v8）は保存Call 160件／cacheを保持したままinterruptedとして終了。現行matching v12の全文Reviewを別のsample1-full-current-v12へ開始し、v8の234 MB候補cacheをseedとして再利用。初回Callがmatching_version 12で保存され、processing継続を確認。sample2 Naval focused v11はEmbedding pendingのためinterruptedし、current fingerprintの297 vector cacheを保持（source候補484件分は未計算）。v12全文・sample2再検証と全finding監査は未完了。
- 2026-11-06: sample3既知表false-positive 6件をmatching v12の現行候補検索＋実LLMで再確認し、期待pair 6/6 matched（.tmp/matching-audit/sample3-candidate-review-v12/check.json）。sample1全文v12はcacheを使ってprocessing中、version12のCalls 9件保存、Review artifact未生成。
- 2026-11-06 20:25 JST: sample2 Navalのv12候補検索でsource #/texts/632〜635に対し誤候補 #/texts/901だけを選び、期待する結合訳 #/texts/736を外す再現を確認。訳unit 736は6spanで、隣接source 633〜635との本文類似度が0.782／0.792／0.716ある一方、736の開始位置補正後はsource 632の順位を落としていた。matching v13で、単一spanのparagraph/list_itemにも同節の隣接source文脈を使って6span以上の同種候補を順位補助する処理と回帰testを追加。sample2 v13候補検索＋実LLMはsource 632〜635→translation 736をmatched、sample1のcampaign source 20→translation 41もv13で維持（.tmp/matching-audit/sample2-naval-candidate-v13/check.json、sample1-campaign-v13/check.json）。全pytest 407 passed、Ruff check／format、ty check成功。sample1全文Review v12は変更前に起動したまま20:23時点で144 Calls・processing、全文artifactなし。Embedding単発疎通は再起動連絡後に9秒で成功。feature branchに未commit差分を保持し、v13全文受け入れ・sample2以外の全PDF／finding監査、commit・merge・pushは未完了。
- 2026-11-06 20:31 JST: sample1全文Review v12は保存Call 168件でprocessing継続、artifact未生成。完了済みmatch結果のsnapshotではmatched group 167件／table-cell source 143件、sourceまたはtranslation IDの重複割当なし。数値兄弟cell列の差2件は同一行「Overarching Elements of Operational Design」のsource OCR IV-9とtranslation IV-19で、PDF画像では両方IV-19印字を確認済み。v12全文結果はv13コードの受け入れとは分けて記録。
- 2026-11-06 20:40 JST: v13のUpgradeAgentを保存済みsampleのsource v1/v2・Japanese translationで再実行。146／142unitを確認し、前回v8と同じ4件（`Chapter Title`、`Appendix A`、`Section Title`、`Appendix body text sample.`）の削除のみを計画。source／translation参照ID集合もv8と一致（`.tmp/matching-audit/upgrade-sample-current-v13/validation.json`、`21-diff/plan.json`、`audit.json`）。構造化LLMの初回不正応答は再試行で回復し、Upgrade自体は成功。sample1全文Review v12はCall 192件でprocessing、artifact未生成。v13全文Review・sample2以外の全PDFとfinding監査は未完了。
- 2026-11-06: 利用者からEmbeddingサービス再起動完了の連絡を受け、単発Embeddingは成功した。一方、sample2 Mobile v13 focused候補検索は既存cache外Embedding要求から約2時間進まず、結果未生成のため中断。sample1全文Review v12もCall 200件まで進んだ後、約50分Call数に変化なくartifact未生成のため停止した。両runの保存Callとcandidate vector cacheは保持。Embedding待ちを伴う全文Reviewとこのfocusedケースの現行実処理検証は未完了。feature branchの変更は未commitで、merge／pushも未実施。
- 2026-11-07: sample2 Mobileの既知誤groupを現行matching v13で再検証。source `#/texts/294/content`の候補検索は旧誤候補 `#/texts/229/content`を除き、translation `#/texts/325/content`のみを選択した。LOADと過去cacheを用い、必要だったunit vector 476件とspan vector 228件を取得・保存後、現行ReviewTask／実LLMの照合でsource 294→translation 325がmatchedとなった。結果は`.tmp/matching-audit/sample2-mobile-current-v13-cache/check.json`、`real-review.json`。単発Embeddingは成功するが複数batchの取得には長時間を要した。sample1全文Reviewとsample1〜5全findingの包括的な最終監査は未完了。
- 2026-11-07: 保存済みReviewをtargetの`target_ids`経由で正しく走査し直した。sample4のtable 3にある`Tree`／`Forest`はPolicy列のアルゴリズム名だが、従来Reviewは英語未訳として指摘していた。評価規則に表内のモデル・アルゴリズム・手法名は周辺列文脈から識別子として評価する指示を加え、現行ReviewTask／実LLMで`Tree`・`Forest`を再評価し、finding／revisionなしを確認（`.tmp/matching-audit/sample4-policy-labels-v2/check.json`）。全pytest 407 passed、Ruff check／format、ty、`git diff --check`成功。sample1全文成果物とsample1〜5すべてのfinding目視監査は未完了。
- 2026-11-07: sample3 Reviewのsource `#/tables/2/cell-r0010-c0000/content`は「Nuclear Waste Disposal」の後に点線があり、訳文にも同じ点線が残るのに、旧Reviewは不要なドットと報告していた。source PDF p.132は点線が項目名と数値を結ぶドットリーダーの表であると確認。Review規則へ表・目次のドットリーダーをレイアウト要素として扱う指示を追加し、現行ReviewTask／実LLMでこのcellとsample4のTree／Forestをまとめて再評価、finding／revisionなし（`.tmp/matching-audit/sample3-leader-and-sample4-policy-v2/check.json`）。sample3 source `#/texts/91/content`の`$43 million`も一時false positive候補と見たが、訳文は`4,300万ドリン`（正しい「ドル」でなく誤字）であり、再評価でも指摘・修正案が出たため有効findingとして維持した。確認済み誤検知3件は修正規則とfocused確認済み。sample1〜5すべてのfinding監査は未完了。
- 2026-11-07: sample1の参考文献付録で公式出版物名`JP 3-60, Joint Targeting`、`AFDA 3-12, Cyberspace Operations`、`ADP 5-0, The Operations Process`を未訳としていた保存findingを確認。各項目はpublication number付きの正規タイトルであり、識別可能な引用として英語保持を許容するReview規則を追加。現行ReviewTask／実LLMで3項目を再評価し、これらへのfinding／revisionなし（`.tmp/matching-audit/sample1-publication-citations-v1/check.json`）。参考文献一覧の他の同種finding全件と全文結果は未監査。
- 2026-11-07: sample3 `#/texts/129/content`の「Lawrence Livermore」を「リバーモア」と訳したfindingは、固有施設名を特定できる許容音訳の差だった。固有名詞の確立済み公式訳と許容表記揺れを区別する規則を追加。実LLMの再評価で`#/texts/129/content`はfindingなし、対照対象`#/texts/91/content`は`4,300万ドリン`の「ドリン」誤字をfindingとして維持（`.tmp/matching-audit/sample3-livermore-transliteration-v1/check.json`）。

# 🧪 Review／Upgradeの対応付け精度検証

## 🔎 保存済み結果の監査

2026-11-04、[進捗](../PROGRESS.md)に記載されたReviewと、その後に完了したsample2 Reviewを確認した。
sample1は完了済みReviewが存在しないため、失敗したReviewの成功済みcallを確認した。
処理の成功は対応付けの正しさを保証しない。指摘数の減少だけも改善の根拠にしない。

2026-11-05更新: sample1全文Review v61は423成功call後に制御Actionの出力上限1024 tokenで失敗した。共有`choose_action()`が設定値4096を1024に制限していたため最大4096へ修正し、現行差分のunit／regressionは374件成功、Ruff lint／formatとtyも成功。v61のcallとEmbedding cacheを引き継いだv62は2026-11-06 00:10時点で747call／round689、88件の評価chunkを保存し、workerは継続中。sourceは3,526、translationは2,878件の非空TextUnit。既存callのmatched group 473件でkind不一致はなかったが、TOC source row「Planning Teams / Ill-1」がtranslationの別row「作戦設計の概要 / IV-1」へ結び付いた誤groupをPDF目視で検出した。source page 8・translation page 9のレンダーで、箇条書き記号をrow labelとしていたことを確認。記号だけのセルをrow labelから除く修正後、focused candidate search＋実LLMは正しいtranslation row「計画チーム / 図-1」を選択した（`.tmp/matching-audit/sample1-toc-page-number-row-label-v1/check.json`）。一方でこの正しい行の評価はpage reference差を検知できず、原文OCR `Ill-1`と視覚上の`III-1`の曖昧さは未解決。full v62は修正前コードで実行中のため、最終成果物とfinding監査は未完了。sample1目次の見出し・番号は両PDFで一律一致するとした先の確認は、このpage-reference差により訂正する。

| PDF | Review ID | 確認した誤対応例 |
|---|---|---|
| sample | `01a19c6e-5408-7722-a481-343979864921` | `alignment-000093`で原文の表の行05と訳文の行07を対応付け。「番号の誤訳」として誤検知。長表で異なる行番号の対応が6組ある |
| sample1 | `01a1956c-0f32-7a40-a128-a08f86f2354a` | 旧call round114で原文E-4「Examples of Requested Military Flexible Deterrent Options」と訳文E-1「要求された外交的柔軟な抑止選択肢の例」を誤対応。PDF画像ではE-1はDiplomatic同士、E-4はMilitary同士と確認。現行候補検索＋実LLMはE-4相互をmatchedにし、実Review評価はfinding／revisionなし（`.tmp/matching-audit/sample1-military-title-focused/`）。最終ReviewはTimeoutErrorで失敗しており、旧誤groupは部分結果での確認 |
| sample2 | `01a1a043-6246-76b0-9fcb-a743005bb887` | `alignment-000250`で「What the Warrior Needs」の引用を、別の目的・要約の段落へ対応付け |
| sample3 | `01a19e1a-96b2-7f73-835e-6adaf2252131` | `alignment-000438`でKey Componentsを含む原文unitを環境管理の段落へ対応付け。訳文には「114 sites」はあるが、24施設・4管理局がなく、部分的な対応と訳抜けを分けて評価する必要がある |
| sample4 | `01a19d9a-a44d-7d73-980e-61ede59e59bb` | `alignment-000177`でcontroller overheadの本文をFigure 2のcaptionへ対応付け |
| sample5 | `01a19cf1-bc56-7be0-8049-5b34d11b211a` | `alignment-000040`で式(8)を「重み(8)は自由フェルミオン条件を満たす」という説明文へ対応付け |

sample3の`alignment-000438`は再監査で分類を訂正する。translation70には「114 sites」の訳がありsource23（Key Components）の一部と対応する一方、24施設・4管理局は省かれている。したがって旧findingは明白な無関係groupとは断定できず、部分対応と訳抜けを含む可能性が高い。focused候補検索がsource23をsource-only、隣接source31→translation70とした結果だけでは、source23の評価が不要とは言えない。これをfalse positive扱いせず、全文評価でどのgroupを評価するか確認する。

一方、sample3保存Reviewで原文表cell `#/tables/2/cell-r0009-c0004/content`（Environmental Management、7,434）が訳文の別行 `#/tables/2/cell-r0013-c0004/content`（Legislative Proposal、749）へ対応付けられたfindingはfalse positive。訳文の正しい対応は同じ行 `#/tables/2/cell-r0009-c0004/content`（環境管理、`7,43 4`）であり、PDF/LOADの行・数値が一致する。現行`MatchingCandidates`は行見出し・同じ行の他セルを検索文へ含める。回帰テスト`test_matching_uses_sibling_cells_to_disambiguate_table_rows`を含むunit/regression 376件はpass。実PDFでのこのcellの現行コード再照合は未完了（sample1全文ReviewとEmbeddingを共有しており、focused要求はtimeout）。

2026-11-05追加: sample2の保存Reviewにある16 findingを、対象訳unitを含むmatched groupとLOAD本文へ突き合わせた。source97→translation151（正しい訳は115）、source439→translation294（正しい訳は465）、source632→translation977（旧matched groupは別組織MCEBの訳文、現行の候補検索はNaval C4Iのtranslation736を選択）、source900→translation1248（NMCS段落を用語見出しへ誤対応、正しい本文訳は1105）、source1062→translation317（正しいRSI用語訳は1252）、source62→translation362（6原則の訳は83）の6件を誤対応由来の誤指摘と確認した。別のsource341→translation482は「DOD Directive 4630.5」の引用が重なる部分対応で、訳文にあるのはNOTEだけだった。対応自体は有効で、本文の大半の訳抜けを示すfindingも有効なため、false positiveには数えない。保存Review全体の監査分類と本文は`.tmp/matching-audit/sample2-finding-group-audit-v75/check.json`に記録した。

現行ReviewTask／LLMのfocused再照合では、source97→115、source439→465、source632〜635→736、source900→1105、source1062→1252、source58・62→83を確認した。source335・336→365では省略箇所の指摘も再現できた。証跡は`.tmp/matching-audit/sample2-source97-v48/check.json`、`.tmp/matching-audit/sample2-source439-current/`、`.tmp/matching-audit/sample2-naval-sentence-scan-v74/`、`.tmp/matching-audit/sample2-saved-false-positive-followup-v64/nmcs/check.json`、`.tmp/matching-audit/sample2-glossary_rsi-recheck-v67/check.json`、`.tmp/matching-audit/sample2-principles_overview-recheck-v67/check.json`、`.tmp/matching-audit/sample2-agreement_continuation-prompt-v69/`。これは失敗例と正解候補を使った個別再照合であり、全文候補検索後の再Reviewは未実施。

同じsample2の表紙findingは原文・訳文PDFの1ページ目をレンダーして確認した。ページは視覚上同一だがDocling抽出文字列は異なり、表紙unitにロゴ画像由来の文字が混入していた。既存の複製ページ条件（500文字以上・類似度0.90）では、sample／sample2の短い表紙が候補外だった。条件を100文字以上・類似度0.85に変更し、保存済みLOAD文書でsample 14unit、sample2 3unit、sample3 14unit、sample4 11unit、sample5 14unitを検出し、sample1は非該当となることを確認した。OCR差のある短い表紙をReviewAgentへ通す回帰テストも追加した（画像`.tmp/matching-audit/sample2-review-pages/`、`.tmp/matching-audit/sample-review-pages/`、全6件`.tmp/matching-audit/copied-front-page-v68/check.json`）。

同監査でfalse negativeも判明した。source335（Agreement in Advance of War）と続きのsource336（括弧内の詳細要件）に対し、訳文translation365は前半しか訳していない。旧matchはsource335→365だけをmatchedにし、source336を除外したため保存Reviewに訳抜けfindingがない。両sourceを強制的にtranslation365と一緒に品質評価すると後半の大部分の訳抜けが検出された（`.tmp/matching-audit/sample2-alignment-complete-v65/detailed_principles/check.json`、`.tmp/matching-audit/sample2-complete-groups-evaluate-v66/agreements/check.json`）。

照合契約を「一部に識別可能な対応があれば訳抜け・追加があってもgroupに含め、品質評価へ委ねる」と更新し、fresh output directoryで実LLMを再実行した。source332〜339とtranslation362〜368を渡すと、初めてsource335・336→translation365をmatchedにし、実Review評価が実際の訳抜けを検出した（`.tmp/matching-audit/sample2-agreement_continuation-prompt-v69/check.json`、`.tmp/matching-audit/sample2-agreement_continuation-full-group-eval-v70/check.json`）。前回のprompt試行は同じCall保存先だったため、input-only fingerprintにより旧応答を再利用していた。fresh実行でない結果をLLMの反応として誤って報告していたため訂正する。

Naval C4I段落では、source632〜635の複数unitの内容が順序を変えてtranslation736一unit内に入る。初回の新契約ではsource632→736だけで、source633〜635を同じgroupへ入れられなかった（`.tmp/matching-audit/sample2-naval-reordered-v72/check.json`）。「一unit内のすべての文・節を確認し、最初の一致だけで止めない」という照合手順を追加し、新しい出力先で再照合するとsource632〜635→translation736の1groupを返した。group理由も訳文の各断片を各原文unitへ対応付けている。実Review評価は文章の不自然な抜き出しを検出した（`.tmp/matching-audit/sample2-naval-sentence-scan-v74/check.json`、`evaluation.json`）。そのうえでsource633〜635だけをtranslation736と照合した試行ではsource633だけmatchedとなっている（`.tmp/matching-audit/sample2-naval-subset-v71/check.json`）。候補を全体として渡し各fragmentを走査する手順がこの具体例を改善したが、subset検証との結果差と他PDFへの一般化は未確認。unitを一文へ全面分割する変更はしていない。

sample4の保存誤group source83→Figure 2 captionも現行候補検索＋実LLMで再検証した。source80・83→本文translation164となり、別節のsource85はsource-onlyに残った（`.tmp/matching-audit/sample4-controller-overhead-current/check.json`）。

同じ保存済みsample4で、原文表`#/tables/2`の行1にある数値`1.00×`・`1.00×`・`0.2%`が、訳文表の行0にある列見出し「加速率」「エネルギー」「一致」へ対応していた。この3つは誤group由来の誤検知だった。現行候補検索は各原文セルについて同じ行・列の訳文セルを選び、ReviewTask＋実LLMも3組すべて期待どおり対応した（`.tmp/matching-audit/sample4-table-candidates-v56/check.json`）。

sample3・4・5では訳文PDFの先頭に原文の英語ページがほぼそのまま含まれていた。Doclingのわずかな抽出差を実際の翻訳誤りと誤認する例を防ぐため、原文・訳文の先頭ページが500文字以上あり、訳文に日本語がほぼなく、casefold後の本文類似度が90%以上の場合、そのmatched groupは訳文側の品質評価文を原文LOAD本文で置き換える。未翻訳の指摘は続け、編集spanは渡さないためOCR差から誤った修正案を作れない。実LOADではsample3（14unit）、sample4（11unit）、sample5（14unit）を検出し、sample／sample1／sample2は除外されなかった。sample5の`#/texts/3/content`を実ReviewTask＋LLMへこの方法で再評価した結果、未翻訳の指摘は残り、OCR由来の変数差指摘とRevisionは出なかった（`.tmp/matching-audit/sample5-duplicate-frontpage-v59/check.json`、検出一覧は`.tmp/matching-audit/copied-front-page-v58/check.json`）。sample1全文Review v55は237call／186roundで中断。v60を255callまで実行した後、候補上限の指示不整合による32回の拒否を確認して停止。v61は423成功call後に出力token上限で失敗し、その上限修正を含むv62を再実行中。全文Review成果物とfinding監査は継続中。

sample2の保存Reviewで誤った相手と比較されていたsource439（軍事作戦の情報支援）は、現行候補検索でtranslation465を選び、実LLMもsource439→translation465を確認した。Figure 2／Mobileなど近接unit番号に引きずられた過去の対応を本文の一致で修正できた（`.tmp/matching-audit/sample2-mobile-current/check.json`）。

sample2のsource482も追加検証した。保存Reviewではsource482がsource-only、translation523がtranslation-onlyだった。別に、訳文の短い「NOTE: DOD指令 4630.5」translation482は原文source341の引用末尾と対応していたが、source341本文の大半が訳出されていないため、そのfindingは誤検知ではなく訳抜け指摘に分類した。原文の見出し「2. Assistance and Coordination」に対応する翻訳側「19 支援および調整」節の本文translation523を候補に含め、現行`MatchingCandidates`と実`ReviewTask`／LLMでsource475・479・481・482→translation523のmatched groupを確認した（`.tmp/matching-audit/sample2-source482-focused/check.json`）。translation523末尾は、source482の軍種・DOD機関が責任範囲内のC4計画等を適切な戦闘軍司令官と調整する内容に対応する。単一unit同士ではなく複数source unitを1 translation unitへ対応させることで復元できた実例である。全682翻訳unitをEmbedding検索する試行は144 vector生成後もbatch応答待ちが続いたため停止した。よってこの実LLM照合は、文書見出しから特定した候補範囲での検証であり、全文候補順位が正しいことの証拠には数えない。

sample1再開中、`max_reference_ids`が全role合計8件へ縮小した後も、system promptは32件を許容し、JSON schemaはsource／translation各roleへ8件ずつ許可していた。このため、実行時上限検証で同じactionがLLM応答5回分拒否される事象を確認した。role別`maxItems`を合計上限から計算し、system promptにも動的な合計・role別上限を明記した。再現unit test追加後、`uv run pytest tests/unit/test_agents.py -q`は89件成功。修正後のv61では8件制約に起因する反復拒否は見られない。一方、最大32件制約を超える初回actionが2件あり、各々LLMの1回再試行で回復した。v61は処理中である。

保存先は各IDの`outputs/document.ja-office/<ID>/tasks/41-review/`。
sample1以外は`review.json`、sample1は`calls/*/response.json`と`call.json`を照合した。

2026-11-05の追加確認では、sampleの長表で行05の説明文が行07と対応する誤groupを再確認し、候補検索へ渡す行文脈の生成不具合を特定した。`Document.unit_contexts()`は各セルについて同じ行の最初の非空セルを`row_label`にしていたため、説明列セル自身の文章、数値列セル自身の値が行キーとして使われていた。保存済みReviewの`alignment-000093`では原文の行05説明が訳文行07説明へ結び付いている。`alignment-000094`では値5が値7へ結び付いていた。

sample4の保存済み指摘には、原文`Background andMotivation`、訳文`Background and Motivation`について訳文の空白欠落を主張するものがあった。focused再評価では空白差を指摘せず、対象見出しが英語のままである点を指摘した。空白の向きを誤った旧理由は不正確だが、未翻訳という別の欠陥は残るため、unit全体を誤検知とは数えない（`.tmp/matching-audit/sample4-ocr-whitespace-v57/check.json`）。

sampleの保存Reviewには、表の日付`2026/08/20`が訳文で`2026/0820`となり、区切り文字の欠落とするfindingがあった。PDFの該当表を画像で確認すると原文・訳文とも`2026/08/20`であり、LOAD時の抽出差による誤検知だった。`Date`行で双方の日付値が同じ場合、LLMが返したissueを検証境界でcorrectへ正規化する。修正後の実ReviewTask＋LLMは1 callでfinding／Revisionなしとなった（画像`.tmp/matching-audit/sample-date-inspect/`、結果`.tmp/matching-audit/sample-date-recheck-v2/check.json`）。

## 🛠️ 修正の判断

### 英日間のunit粒度

`TextUnit`は一文ではなく、LOADされた段落・見出し・caption・表セルを保持する。保存済み6組のReview LOADを`split_sentences()`で数えると、英語／日本語unit数はsample 146/144、sample1 3526/2878、sample2 824/682、sample3 245/227、sample4 147/151、sample5 88/55だった。1 unitあたりの文数平均もsample1で2.24/2.87、sample5で2.42/3.60となり、unitと文の境界が常に一対一ではないことが確認できる。

この集計は言語別の正解対応表ではなく、`split_sentences()`による粗い診断値である。unit数の差だけで誤対応とは判定しない。一文への全面分割も、表セル・見出し・複数文をまとめた翻訳を壊し、分割片を元unitへ戻す処理が必要になるため現時点では採用しない。まず失敗PDFの誤groupを監査し、候補範囲の追加・隣接unitの結合が実際の正しいgroupを回復するかで改善を評価する。

現行の`TextUnit`はDocling由来の本文Block・Caption・表セルであり、文分割された`TextSpan`を内包する。
Agentの対応付けはunit全体の文字列を使う。

確認した誤対応は、文境界のずれだけでは説明できない。
sampleのmatch round 12では原文の行05の相手が候補集合になく、残った行07へ誤対応した。
また、LLMに渡す情報は本文と長い参照IDだけで、表の行・列の意味や数式・captionの種別がなかった。

このため、まず次の変更を選ぶ。

- 要素種別・節見出し・表の行見出しと列見出しを、候補選択と対応付けの両方へ渡す。
- 構造情報を比較対象の本文と分け、表番号やページ位置の一致を対応の根拠にしない。
- 照合入力には文書ごとに異なる短いIDを使い、応答Schemaを選択したIDへ限定する。保存時は元IDへ戻す。
- 段落の分割・結合には複数unitの対応を使い、翻訳上の追加・省略と対応箇所の特定を区別する。

一文ずつへの全面変更は加えていない。再検証で段落境界が原因の誤対応が残る場合に、次の修正候補として評価する。

## 📋 検証記録

既存PDFのSHA-256と保存済みLOAD ArtifactのSHA-256を元の処理記録と照合したうえで、現在のAgent／Taskを実LLMへ接続して再実行する。
Docling変換の繰り返しは行わず、同一PDFから得た文書表現を使って照合の変更を比較する。
実行結果とコードのSHA-256は`.tmp/matching-audit/`配下へ保存する。

| 検証 | 結果 |
|---|---|
| sample長表のrow_label生成を修正 | 行キーを同じ行の先行列から取るよう変更。説明列と値列が同じ識別子（例:`page_split_05`）を共有し、識別子列自体には行キーを設定しない。さらに同じ行の候補内で同じ列位置を優先する。単体テストを追加 |
| 修正後sample長表の候補検索 | `192.168.1.183:1234`のNomic Embeddingで保存済みLOADの対象40セルを再検索。40/40で正しい行・列の訳セルが1位になった。詳細は`.tmp/matching-audit/sample-longtable-rowlabel-v44/candidate-audit.json` |
| 修正後sample長表のReview照合 | 現行`ReviewTask.match_documents`と実LLM（Gemma 4 12B）で40組を5回に分けて照合。matched groupは40/40で期待対応と一致（`.tmp/matching-audit/sample-longtable-rowlabel-v44/check.json`） |
| sample4の節番号が離れた誤group | 保存済みsource88→translation164は誤り。節距離ペナルティを強めた現行検索ではsource87・88→translation176となり、実LLMもこのgroupを返した（`.tmp/matching-audit/sample4-source88-v45/check-current.json`） |
| sample4の分割・結合を全文候補から再検索 | Nomic Embeddingでは誤候補が上位となり、単独unit検索は不合格。EmbeddingGemmaではsource80・83→translation164、source87・88→translation176を現行候補検索＋実LLMで両方正しく照合（`.tmp/matching-audit/sample4-merged-embeddinggemma-v47/check.json`）。モデルにより順位が変わるため一般化はしない |
| sample2 source482の分割・結合と評価 | 保存Reviewではsource482がsource-only、translation523がtranslation-only。対応節の本文に候補を絞った現行検索＋実LLMではsource475・479・481・482→translation523となり、source482の内容を含む結合を回復した。続く実ReviewTask評価はfinding／revisionなし（`.tmp/matching-audit/sample2-source482-focused/check.json`、`evaluation.json`）。全翻訳unitを対象にした候補順位は未確認 |
| sample2保存Reviewのsource97誤group | 全文候補から現行検索がtranslation115を選択し、実LLMもsource97→115を返した。旧誤候補translation151は選ばれない（`.tmp/matching-audit/sample2-source97-v48/check.json`） |
| sample3保存Reviewの分割・結合 | 全文候補から現行検索がsource43・45とtranslation45を集め、実LLMが両sourceの結合を返した。誤候補translation63は選ばれない（`.tmp/matching-audit/sample3-source45-v50/check.json`） |
| sample5保存Reviewの式周辺3unit | source102→translation53、source113→translation66を照合。source101の式(8)は訳文LOADで対応unitが見つからずsource-onlyとし、誤候補translation61へ結び付けない。旧期待値source101→translation60は本文に対応する式がなく誤りと訂正（`.tmp/matching-audit/sample5-known-false-v49/check.json`） |
| 全文候補のEmbeddingモデル比較 | sample4でNomicは不正候補を上位にした一方、EmbeddingGemmaでは期待groupを回復した。利用モデルによる品質差があるため、他のEmbeddingモデルにも同等の精度があるとは結論しない |
| 旧候補cache再利用の試行 | 旧文脈のEmbeddingを修正後の別入力へ流用した試行は無効として破棄し、上記検証では新しいEmbeddingを使用 |
| Review制御出力枠 | sample1全文Review v61は423成功call後、`choose_action()`固定1024 output tokenを超過して停止。設定上限4096を使えるよう修正し、unit／regression 369件とRuff、format、tyを再確認。成功call/cacheを引き継いだv62で再検証中 |
| 2026-11-05品質確認 | `uv run pytest tests/unit tests/regression -q`（369件成功）、`uv run ruff check .`、`uv run ruff format --check .`、`uv run ty check`成功 |
| 保存済みsampleの長表検査 | 異なる行番号の対応6組を検出し、検査は失敗。再現できることを確認 |
| sampleのmatch round 12の16候補 | 構造情報追加後は正しい3組だけがmatchedとなり、候補内に相手がいない残りは未対応。期待結果と一致 |
| sample5のmatch round 4の16候補 | 数式・本文の誤対応は解消。初期の正解データには原文102と訳文63の取り違えが1組あり、式の前後を確認して訂正した。訳文63の実際の相手は原文108で、元の候補には入っていない |
| 同じsample5候補で短いIDを追加 | 初回は3組を返したが、訂正後の正解に照らすと原文102と訳文63の1組が誤対応。短いIDだけで精度改善完了とは判定しない |
| 対応が確認できた組だけをLLMから返す方式 | sampleの正しい3組、sample5の正しい2組に一致。候補に実際の相手を加えた検証も継続中 |
| sample全文Review、構造情報のみの途中版 | 同じIDの重複出力による再試行を確認。ログを保存して停止し、短いIDを含む版で再検証する |
| sample1〜4の既知の誤対応に実在する正しい相手を追加 | 短いID版でそれぞれ8組・1組・2組・1組の正解に一致。sample4は英語2段落と日本語1unitの対応を確認 |
| sample5で原文106・108を候補に追加 | 対応が確認できた組だけを返す方式で、正しい説明文2組を含む計4組に一致。似た表現の原文102へは誤対応しない |
| sample5 Upgrade全文（旧5ページ・新4ページ） | `de6d32d`で旧88unit／新81unitを確認し、末尾ページの7unitだけを削除と判定。誤った追加・変更・訳文参照はなし。ただし冗長な確認済みID配列の省略で再試行が発生 |
| 同じUpgradeの失敗callを応答保存付きで再現 | LLMは削除7件を正しく返していたが、確認済みID配列の省略で失敗したことを確認。確認範囲をchange一覧から導出する修正後、1回で7件を正しく処理 |
| sample1〜4の同じ正解集合を応答形式の修正版で再検証 | 全ケースが1試行で正解8組・1組・2組・1組に一致。`.tmp/matching-audit/other-pdfs-v4/*/check.json`に入力IDと正解・実結果を保存 |
| sample全文Review、候補検索追加版 v11 | 不合格。正解141group中78一致、29誤対応、34未対応。多数の長表行で同じ値の別行を対応付けた。検索結果を広く混ぜるだけでは精度が下がることを確認 |
| sample5全文Review、候補検索追加版 v11 | 処理は成功したがfinding24件の内容監査が未完了。対応と指摘を正解箇所へ照合する必要がある |
| sample長表の失敗範囲を行見出しで絞った再試験 | 正しい3組だけをmatchedにし、残りは相手なしではなく候補内で未確認として残した。LLMは正しい同一行の値・説明を選択。`.tmp/matching-audit/table-row-key-v12/`に保存 |
| 異なる節見出しの失敗例を候補検索で調査 | source `2 Lists`では訳文`2 リスト`が類似度1位だったが、複数unitを一度に候補へ混ぜた照合では別見出しを選択した。検索起点を1unitに制限し、段落境界への対応は前後断片で保つ修正を追加 |

2回目の修正では、Reviewの残余候補をアプリ側で未確認として補い、LLMへ全候補の列挙を要求しない。
不明ID・重複IDの拒否は維持する。Upgradeはchange一覧による全英文IDの一度限りの網羅を引き続き検証し、
同じIDを繰り返す確認済み配列だけをアプリ側で導出する。
`de6d32d`の全文Reviewはこの応答形式の再試行を記録して停止し、修正版でやり直す。

実行した検査は`.venv/Scripts/python.exe -m pytest tests/unit tests/regression -q`（329件成功）、
`.venv/Scripts/python.exe -m pytest tests/unit/test_agents.py -q`（73件成功）、
`.venv/Scripts/ruff.exe check translate tests/unit/test_agents.py`、`.venv/Scripts/ty.exe check`。

### 🔬 全文監査と追加の修正

`f6b7e73`の全文Reviewはsample／sample5とも処理が成功したが、精度監査は不合格だった。
sampleは正解141groupのうち137groupが一致し、誤対応1group・未対応3groupが残った。
旧結果は同じ正解集合で49group一致・誤対応12group・未対応80group。長表の69組は修正版ですべて一致した。
残る誤対応は、英語4unitの定義を日本語1unitへ対応させる際に英語3unitが欠落するものだった。
sample5にも自由フェルミオンの説明・式を別の導入文へ対応付ける誤りが残った。

sampleの正解集合は原文144unit・訳文141unitを含む。PDFの見た目と抽出結果を比較し、
社名が`cot`になった箇所と、式が訳文のTextUnitから消えた箇所は信頼できる本文照合から除外した。
追加生成された図目次・表目次も原文に対応する要素はない。これらを翻訳の誤りと決めつけない。

sample5の保存済みReview入力PDFもページ画像で確認した。原文PDFはカゴメ格子論文だが、訳文PDFの1ページ目は同論文の英語原文、
2ページ目は`SYS-DD-001`の別文書である。したがってsample5の24指摘は、英語のままの箇所が実際に存在する証拠にはなる一方、
同文書ペアとしての誤訳判定の正解集合には使えない。異なる文書内容が対応groupに入る場合はマッチング誤りとして扱う。

この結果から、構造情報だけでは足りず、未確定の相手文書全体からEmbeddingで候補を検索する修正を追加した。
段落の分割・結合に対応するため近傍も候補へ含め、対応そのものはLLMへ判定させる。
sample5の既知の失敗範囲では、この検索後に説明・数式8組すべてが正解と一致した
（`.tmp/matching-audit/retrieval-science-v7/check.json`）。

品質確認には、略語・固有名詞の任意の補足、抽出空白、日付の区切り差を不備とする指摘もあった。
対応groupごとの評価、訳文入力名の明確化、空白だけの修正と同じ暦日の指摘を再判定する検証を追加している。
正しい保持5例と、本当の未翻訳・数値不一致2例を同時に検証し、指摘数を減らすだけの修正にしない。

`f6b7e73`のUpgradeは、同一PDFではなく実際に末尾ページを削除した入力で再検証した。
sampleは旧146／新142unitを網羅して末尾4unitだけを削除、sample5は旧88／新81unitを網羅して末尾7unitだけを削除と判定した。
追加・変更や無関係な日本語への対応はなかった。新しい候補検索を含む版でも再検証する。

行見出しを使った絞り込みを取り入れたsample全文Reviewを再実行中（`.tmp/matching-audit/full-sample-rowkey-v12/`）。sample5全文の指摘監査、失敗範囲の再検証、sample1〜4の候補検索版およびUpgradeの再実行は未完了。現段階では誤検知がなくなったとは判定していない。


### 🔬 sample長表候補監査の再開

作業ブランチ`feature/review-matching-audit`では、旧候補キャッシュを使いsampleの2表に含まれる66セルを再監査した。
行見出し優先だけでは60/66件、列位置も優先すると62/66件が正しい候補になった。残る4件は表ヘッダーの候補で、ページ分割された同一表の見出しと別表の見出しが重複している。

ヘッダーセルのEmbedding入力へ同列の隣接行ラベルを追加し、ページ分割後の表片を識別する修正を加えた。単体テスト12件、unit／regression352件、Ruff、tyは成功。
この修正を使った66セルの実データ再監査はEmbedding要求中で、結果はまだ得られていない。全PDF監査とUpgrade再検証も未完了であり、誤対応が解消したとは判定しない。


### 🔬 sample長表・sample1〜4の現行コード再検証

表ヘッダーではEmbedding類似度が同点になり、同じ列位置でも前の別表へ候補が流れる誤りが4件残っていた。各表の先頭行だけ、同列の次行ラベルをEmbedding入力と構造優先順位へ加え、OCR空白を正規化して比較するよう変更した。
保存済み候補ベクトルを使ったsample長表66セルの再監査は66/66件が正しい候補を選択（`.tmp/matching-audit/sample-longtable-v15/candidate-audit-v16.json`）。訳文側の長表ヘッダー3セルを現在のReviewTask／実LLMへ送った検証も1回で3組すべて期待対応になった（`.tmp/matching-audit/sample-longtable-v15/llm-header-recheck/check.json`）。

保存済みsample Reviewのfindingとmatched groupを照合すると、長表の行サンプル番号がずれた誤対応が10件あり、例えば原文sample 05を訳文sample 07と結び付けた結果が「番号誤り」として報告されていた。現行の候補検索は表セルを同じ行・隣接行・同じ列の優先集合から順位付けする。保存済み失敗範囲を現行ReviewTask／実LLMへ再送した検証では正しい行だけをmatchedとし、対応候補にない行はtranslation-onlyで残した（`.tmp/matching-audit/table-review-recheck-v36/`）。

同じ選択規則のまま、順位比較と近傍確認に必要な候補ベクトルだけを段階取得するよう変更した。実sample1のE-2セルでは訳文1,204表セルの比較が2候補（Embedding入力は起点を含め3テキスト）となり、正しいセルを選んだ。原文近傍には従来どおり有効な種別の全候補を用い、訳文近傍は順位決定後に必要な範囲だけ追加取得する。unit／regression357件、Ruff、tyは通過。sample1全文Reviewは再実行中（`.tmp/matching-audit/sample1-full-current-v38/`）。

sample1・sample2・sample4の保存済み失敗範囲を現行ReviewTaskへ再送し、既知の期待8組・1組・1組に一致した。sample3は期待2組に加え、原文`#/texts/45/content`（核発電・燃料・核融合の広い段落）を訳文`#/texts/63/content`（核廃棄物処分の一部）へ対応付ける結果を返した。話題の関連はあるが全Unitの対応としては根拠不足で、誤対応候補として残す（`.tmp/matching-audit/sample3-kind-v17/check.json`）。この再送は広い保存済み候補集合を使っており、現行候補検索後の全PDF結果とは区別する。

ここでの結果から、Unitを一文単位へ全面変更する前に、段落内部の部分対応と全体対応の判定を改善する必要がある。`TextUnit.spans`の文境界をLLMへ示す比較も実施したが、広い候補範囲では誤対応が残ったため、その入力変更は採用しない。sample3の現行候補検索後の再検証、sample5の全指摘監査、Upgrade候補検索版、現行候補検索を通したsample1〜4検証は未完了。

#### 🧪 sample3現行候補検索後の再検証

source `#/texts/45/content`の最有力候補はtranslation `#/texts/45/content`だった。初回監査では、同じ訳unitへsource `#/texts/43/content`（クリーンコールの公約）を加えるのを誤対応と判定したが、PDF抽出本文を読み直すと訳文unitには核融合の訳に続いてクリーンコールの訳も含まれていた。したがってこれは英語2unitを日本語1unitへまとめた正しい対応であり、前回の誤対応判定を撤回する。`.tmp/matching-audit/sample3-current-retrieval-v19/check.json`。

近傍unitを独立した最有力候補を確認せず加えると、真の分割・結合に必要な断片と似た話題の別断片を区別できない。修正では、節番号が近い候補を優先し、節をまたぐ原文近傍はその訳候補が近傍自身にとっても最有力の場合に限る。sample3ではsource45とsource43をtranslation45へまとめ、実LLMが1回で正しい対応を返した（`.tmp/matching-audit/sample3-filtered-v28/check.json`）。sample4ではsource80とsource83をtranslation164へまとめ、実LLMが1回で正しい対応を返した（`.tmp/matching-audit/sample4-filtered-v29/check.json`）。この2例では分割・結合と節をまたぐ結合を確認した。

sample Upgradeは現行コードで再実行し、旧版146unit／新版142unitを網羅した。差分4件はすべて削除で、英語`Appendix A`を日本語`4 コード`と誤対応した前版の結果は、見出し番号をEmbedding入力から除く修正で`11 付録 A`へ訂正された。4件は原文`Appendix A`、`Chapter Title`、`Section Title`、`Appendix body text sample.`とそれぞれ正しい日本語見出し・本文の組で、未知の追加・変更はない（`.tmp/matching-audit/upgrade-sample-current-v31/21-diff/plan.json`）。sample1／2／5の全文再監査と、他PDFの現行Upgrade再検証は未完了。

sample1の長表失敗例では、保存済みの分割差source `#/tables/4/cell-r0003-c0000/content`（`E-2`）を現在の検索でtranslation `#/tables/10/cell-r0003-c0000/content`へ対応付け、実LLMが1回で正解を返した（`.tmp/matching-audit/sample1-current-v32/check.json`）。同じ行見出しがある場合に他行をEmbedding前に候補から外す改善を入れた。これは同じ後段ロジックが選ぶ範囲を先に絞るため、正解の意味は変えず候補検索の無駄なEmbeddingを避ける。sample1全文の再実行は未完了。

#### 🔬 sample1表紙見出しの候補再確認

sample1全文Reviewの現行コード試行v90で、source `#/texts/1/content`（表紙の`Joint Planning`）をtranslation `#/texts/560/content`（本文62ページの`32 Joint Strategic Planning System`）へ誤対応した。PDFの1ページ目には訳文側にも原文と同じ`Joint Planning`があるが、Docling LOADは当該訳見出しをTextUnitとして含めていなかったことを両PDFレンダーで確認した。全文v90はこの誤groupを保存した後停止し、成果物として採用しない。

候補順位に正規化ページ位置（0〜1）の弱い補正を加え、位置差だけで対応を確定しないようにした。ページ1対62のsample1候補を現行検索で再現すると、以前の遠い本文見出しではなく同じ先頭位置の訳文見出し（`Joint Publication 5-0`）へ順位が移った。訳見出し自体は抽出漏れのため候補に存在せず、これは「正しい対応」の確認ではなく誤対応を避ける順位変更の確認である。source／translationの文書全体から再検索したときも、表紙の`Joint Planning`をtranslationの同一表紙見出しへ候補化し、対応は既存の複製原文ページ判定へ委ねる。位置補正と表紙の一致候補を守る単体テストを追加。`test_matching.py`と`test_agents.py`、PDF全体でのReview再実行は未完了。

現行コードでの全文Review再実行v91は、Windowsのsubprocess起動時に`translate`のimport pathを引き継げず、Review Call 0件のまま中止。candidate cacheは保存した（`.tmp/matching-audit/sample1-full-current-v91/`）。このrunの成果物は検証結果に含めない。

位置補正だけでは不十分だった。sample1全訳文書のtranslation見出し403件（保存Embedding cacheで利用可能なもの）をsource `#/texts/1/content`（`Joint Planning`）と順位付けすると、最高候補は本文19ページの`#/texts/131/content`（`7.1.5 Planning Process`）で、cosine 0.705・位置補正後0.561だった。これは意図された対応とは確認できない。遠いページの表紙見出し候補は補正後スコア0.60未満なら追加しないようにし、全403候補の検索でtranslation候補なしとなることを確認した（`.tmp/matching-audit/sample1-full-cover-candidate-check.py`）。実`ReviewTask`＋LLMもsource-onlyを返し、「この候補範囲で対応を確認できないが文書全体に訳がないとは限らない」とした（Call `call-d9576c9f876d4770273e1c2c7dc68f730243510260740a7bd8cc6f54d3ab8cf1`、`.tmp/matching-audit/sample1-cover-heading-review-v2/`）。ページ位置はReview／UpgradeのLLM payloadから除き、候補順位にだけ使う。関連unit test 38件pass、Ruff check／format、ty check pass。マッチ規則世代は4。

この判断で段落・表など他種別の候補閾値は変更しない。遠く離れた正しい表紙見出し対応をsource-onlyにする可能性はあり、全文Reviewとfinding監査で確認する。現行コードのsample1全文Review v93は起動したが、現在は保存Callがなく、完了・finding監査は未確認（`.tmp/matching-audit/sample1-full-current-v93/`）。

sample2の保存済み誤groupではsource `#/texts/97/content`（戦場状況の引用）がtranslation `#/texts/151/content`（C2S／C4の説明）へ誤対応していた。既知の正解`#/texts/115/content`と誤候補の2件だけを候補文書として現行検索へ渡すと、正解の`#/texts/115/content`が選ばれ、実LLMも1回で期待groupを返した（`.tmp/matching-audit/sample2-targeted-v33/check.json`）。この確認は失敗した組とgold候補の限定比較であり、sample2の全訳文書を対象にした候補順位・全文Reviewの再実行ではない。

#### 🧪 sample5保存済みfindingと照合groupの監査

保存済みsample5 Review17件をmatched groupの対象unitと照合し、追加の誤指摘を分類した。うち11件は訳文PDFの先頭に残る原文と同一の英語ページに対するOCR差・数式記号差の指摘である。現行複製ページ判定はsample5の先頭ページ14unitを検出し、該当matched groupでは原文LOAD本文を比較基準にして修正spanを作らない。そのため同類の誤指摘は抑制される（`.tmp/matching-audit/copied-front-page-v68/check.json`）。

残る指摘には、誤group由来のfalse positiveが3件あった。source `#/texts/101/content`（式8）→translation `#/texts/61/content`（free-fermion条件の説明）、source `#/texts/102/content`（式9前の導入文）→translation `#/texts/63/content`（[18]の評価説明）、source `#/texts/113/content`（式12の係数定義）→translation `#/texts/78/content`（ダイマー相関の式13）である。本文上、正しい対応は106→61、108→63。現行候補検索と実LLMの照合は8件の数式周辺対応すべてで期待結果になった（`.tmp/matching-audit/retrieval-science-v7/check.json`）。さらに、source113の現行候補検索はtranslation66を選び、ReviewTaskもsource113→translation66だけをmatched、translation62をtranslation-onlyと返し、誤ったtranslation78は選ばなかった（`.tmp/matching-audit/sample5-source113-focused-v43/check.json`）。訳文の式`f_{86}`など日本語訳ページの実際の誤記は別対象であり、残る全指摘の正否確認も継続する。

訳文PDFは8ページで、1ページ目は英語原文、2〜8ページには日本語訳がある。一方、`SYS-DD-001`の表紙・目次・ヘッダー・フッターが翻訳ページへ混入していた。以前の「2ページ目は別文書」という判定を訂正する。確認用レンダーは`.tmp/matching-audit/sample5-review-pages/`に保存した。

#### ⏳ sample1全文Review（現行コード）

保存済みReview入力`01a1956c-0f32-7a40-a128-a08f86f2354a`で現行ReviewAgent全文を試行した。最適化版v38（`.tmp/matching-audit/sample1-full-current-v38/`）ではEmbedding cacheを2,173件まで生成したが、応答待ちが続いたため停止し、cacheを再開用に保管した。後続v51（`.tmp/matching-audit/sample1-full-current-v51/`）は制御判断LLMの出力上限1024超過で失敗。v52（`.tmp/matching-audit/sample1-full-current-v52/`）は出力上限を4096に増やしたが、78件のcall保存後にLLMTimeoutErrorで失敗。v53（`.tmp/matching-audit/sample1-full-current-v53/`）はv52の78件とEmbedding cacheを引き継ぎ、161件の成功call後に中断した。訳文表セル`#/tables/41/cell-r0004-c0000/content`（`ISR`）は原文の別々の23セルと照合され、全23件がsource-only／translation-onlyだった。同じ訳文unitへの不成立回数は23回に達し、既存の完全一致scope検出では相手候補が毎回違うため停滞を検出できていなかった。

この事例に対しReviewはunitごとの不成立回数を保存callの再生から復元し、3回不成立後は再探索候補から除く。Upgradeは保存された失敗callをunitごとに数え、3回のmatch失敗を未確認として記録する。sample2 Upgradeの保存履歴では同じ原文v1/v2セルが各13回使われ、そのうち12件は5回のLLM応答再試行後に失敗していたため、Upgrade側にも同じ上限を追加した。回帰テストは追加済み。sample1の実PDF全文再開とfinding監査は未完了。

v55ではv53の161callとEmbedding cacheを新しい出力先へ複製し、現行コードで再開した。181call／179round時点で`ISR`セルへの参照は保存済みの23回から増えておらず、全文Review成果物はまだない。23候補の原文セル本文は空欄記号`•`であり、原文には別セルおよび本文に`ISR`の記載があることをDocling成果物で確認した。保存callの一覧監査は`.tmp/matching-audit/sample1-repeat-failure-v54/check.json`に記録した。現行Reviewの全文再開とfinding監査は継続中。現行差分のunit／regression362件、Ruff lint／format、ty、`git diff --check`は成功。


### 🧪 Unit内の文境界を使った照合試験

前節のsample3では、原文の長い核エネルギー段落と、訳文の核廃棄物に限定した段落が話題の類似だけで結び付いた。文単位へ全面分割する前段として、LOAD済み`TextUnit.spans`の文列をREVIEW要求へ追加し、複数文を個別に照合する指示を加えた。

保存済みの広い候補範囲を実LLMへ再送したところ、誤対応は解消しなかった。核エネルギーの部分対応に加え、別節同士の誤対応も返った（`.tmp/matching-audit/sample3-sentences-v18/check.json`）。したがって文境界を提示するだけでは精度改善の根拠にならない。後続の候補検索版では、無条件近傍追加による重複ID応答を確認した。現行修正は候補の節構造と近傍ごとの最有力相手を使い、sample3／4の既知groupとsample Upgradeの4差分を正しい対応で復元した。sample1／2／5の全文再監査と他PDFのUpgrade検証は継続する。

#### sample1目次セルの誤候補

sample1の保存済みfindingでは、source p.7「Planning Products」がtranslation p.38の本文表「計画機能」と誤対応していた。translation p.7には同じ目次行の「計画成果物」がある。どちらも表の先頭列で、行見出しがなく、従来の検索文には当該行の隣接セルが含まれなかったため、Embeddingが話題の近い本文表を選んでいた。

表セルの検索文へ同じ行の他セル本文を加えた。sample1 LOAD実データに既知の正候補と誤候補を限定して検索したところ、p.7「計画成果物」を選び、ReviewTask＋実LLMも1回で期待groupを返した（`.tmp/matching-audit/sample1-planning-products-real-review-v1/check.json`）。回帰テスト`test_matching_uses_sibling_cells_to_disambiguate_table_rows`を追加。unit／regression 375件、Ruff、format、tyは成功。sample1全文Reviewの再開・finding監査は継続中。

同じ保存済みfindingの照合groupも再構築し、誤groupが影響したのは「Planning Products」と「Ill-1」の2件と確認した。「Ill-1」は既存の行ラベル修正で、正しい同一行の「図-1」を選ぶfocused Reviewが成功済み。「5 第III章」の余分な5というfindingは翻訳PDF上にも見える。CICSのfindingはsource PDF画像ではCJCS、翻訳ではCICSとなっており、LOAD OCRのCICS表記が誤りだったが指摘自体は正しい。これらは誤groupとは区別する。

現行コードでのsample1全文Review v62は全体期限6時間で終了し、820 call保存後に`LLMTimeoutError: LLM Task deadline exceeded`となった。保存済みのcall・Embedding cacheをv63（`.tmp/matching-audit/sample1-full-current-v63/`）へ引き継ぎ、現行コードで再開した。v63は820件の旧callを再利用するため、最終Reviewは全件が修正後コードから新規照合されたものではない。既知誤groupはfocused Reviewで独立検証し、全文結果のfinding監査では再利用groupと新規groupを区別する。


#### sample1全文Review再開とEmbedding再起動後の確認

v63は1,517件のcallを保存した後、2026-11-06 04:57 JSTにEmbedding endpointへの要求がタイムアウトして失敗した。Review成果物は未生成。失敗時点のdiagnosticsは空で、callとcandidate vector cache（約122 MB）は保持されている。利用者によるEmbedding再起動後、軽量なEmbedding要求1件が成功したため、v63のcall/cacheをv64へ引き継いでReviewを再開した。v64は保存callを再生した後、新しいReview/Embedding要求へ進んでいる。v63に含まれる旧820callとその後の現行コードcallの混在、および全文finding監査が未完了である点は継続して区別する。


#### 🧪 sample2の結合unit／構造種別差による誤候補

sample2の保存済みReviewでは、source `#/texts/294`（`list_item`）がtranslation `#/texts/229`へ誤対応していた。正しい訳文はtranslation `#/texts/325`に含まれるが、同unitは42 spanの`paragraph`であり、従来処理は同kind候補が存在すると異kind候補を順位付け前に除外していた。現行Embedding cacheを使ったspan評価では正候補325のcoverage平均が0.734、誤候補229は0.508だった一方、unit全体cosineは229が0.692、325が0.641だった（`.tmp/matching-audit/sample2-mobile-source294-v76/span-score.json`）。

候補検索は同kind候補に加えて長いcross-kind unitを限定数含め、上位候補をspan coverageで再順位付けするよう変更した。異kindの結合unitを選ぶ回帰テストを追加。修正後のunit/regression全体は376 passed。Ruff check／formatとtyもpass。限定候補（229／325）の現行コード検索は保存済みscore/span cacheで再生し、正候補325を選択した。325の全体cosineは保存済み実測値を使い、source／誤候補のunit vectorと全span vectorは同一モデルのcacheを使用した。続けて実ReviewTask＋LLMが294→325を`matched`と返した（`.tmp/matching-audit/sample2-mobile-focused-v79/check.json`、`real-review.json`）。全訳文書の候補順位検索v78はEmbedding batchが応答せずsample1全文Reviewと競合したため停止。


#### 🧪 sample2保存Reviewの誤対応findings再監査

保存Reviewの誤対応findingを照合group・LOAD本文・focused Review結果で再点検した。source `#/texts/97`→translation `#/texts/151`は誤groupで、focused検索／実LLMは正しいtranslation `#/texts/115`を選ぶ（`.tmp/matching-audit/sample2-targeted-v33/check.json`）。source `#/texts/632`→`#/texts/977`も誤groupで、focused Reviewは`#/texts/736`をmatchedにし、977をtranslation-onlyとした（`.tmp/matching-audit/sample2-naval-reordered-v72/check.json`）。source `#/texts/900`は`#/texts/1248`でなく`#/texts/1105`に対応し、source `#/texts/1062`（RSI見出し）は`#/texts/1252`に対応するfocused Review結果を確認（`sample2-saved-false-positive-followup-v64/nmcs/check.json`、`sample2-glossary_rsi-recheck-v67/check.json`）。source `#/texts/62`の6項目は翻訳側`#/texts/362`〜`#/texts/368`に分割され、再照合では一つのsource groupから7件をmatchedにした（`sample2-saved-false-positive-followup-v64/split_enumeration/match/calls/`）。

source `#/texts/341`→translation `#/texts/482`は本文の残りではなく「NOTE: DOD指令4630.5」という引用だけの部分対応だった。保存Reviewの「本文の訳出がない」というfindingは誤検知ではなく、訳漏れを指摘している。sample2の保存結果では、正しい相手が分割・結合・異kind unitに入ることで誤groupが起きる例と、実際の訳漏れを区別できた。

#### 🧪 sample5の式記号OCRと原文LOAD欠落

訳PDFのページ画像（`.tmp/matching-audit/sample5-review-pages/page-6.png`）をsource PDF画像と比較した。保存Reviewの式(10)（source `#/texts/105`→translation `#/texts/60`）と式(12)（source `#/texts/109`→translation `#/texts/64`）の`f_{8ν}`指摘は、訳PDF画像では記号が正しく、LOAD文字列の`86`／`□`というOCR差に由来するfalse positiveだった。

一方、訳PDFページ7の`#/texts/78`はsource PDFの式(18)と同じ式を持つが番号が(13)になっており、実際の訳誤記である。保存Reviewはこれをsource `#/texts/113`（別の式(13)定義）へ誤対応していた。source LOADには式(16)（`#/texts/121`）の後の式(17)/(18)がTextUnitとして存在せず、現行Reviewが評価するmatched groupから外すと、translation-onlyの`#/texts/78`は品質評価されない。誤対応を正すだけではこの実誤記を再検出できない、原文抽出欠落に由来する残課題として記録する。PDF画像は`.tmp/matching-audit/sample5-audit-source-p4.png`と上記translation page 6/7.

#### 🧪 現行コードのsample Upgrade再検証

2026-11-06に保存済みsample Upgrade入力でUpgradeAgentを実行（`.tmp/matching-audit/upgrade-sample-current-v80/`）。現行コード指紋`883ad05a…`で成功し、変更4件を検出した。原文v1の`Appendix A`、`Chapter Title`、`Section Title`、`Appendix body text sample.`各unitが原文v2に存在せず、対応する日本語unitを削除とする結果は入力差分どおりだった。1件でLLMのmatch参照制約違反を検出したが、再試行で回復し、成果物を生成した。

同日、過去に同一cellのmatchを12回失敗したsample2 Upgradeと同じ3入力を、現行UIから`outputs/sample2/01a1aed5-1b6c-78c0-9199-0065584226be/`へ再実行した。Upgradeは成功し、planは変更0件。source v1/v2は各859 TextUnitの本文列が完全一致し、Agentが824 IDずつ未変更として確認した。旧planにあった2件のmodifiedは再現せず、旧Review/Upgrade結果のfalse positiveを抑えられた。UI成果物検査も成功（`.tmp/matching-audit/sample2-upgrade-current.png`）。ただし完全一致の早期確定によりDIFF LLM callは0件で、match失敗上限そのものはこのPDF runでは発火せず、再試行抑制はunit testで別途確認する。

#### 🧪 sample5保存Reviewの残り6finding

保存Review v75の17findingを分類した。英語複製ページ上の11件はOCR差による既知の除外対象。残りは、Figure 4表記は許容されるスタイル差、source #/texts/101→translation #/texts/61は誤group（現行focused再照合ではsource-only、正しい数式相手はsource #/texts/106）、source #/texts/102→translation #/texts/63は誤group（現行ReviewTaskはsource #/texts/102→translation #/texts/53）、式(10)/(12)はPDF画像で記号が正しいOCR false positive、source #/texts/113→translation #/texts/78は誤group（現行focused Reviewはsource #/texts/113→translation #/texts/66）だった。translation #/texts/78には式番号(13)の実誤記があるが、対応するsource式(17)/(18)がLOADに抽出されず、現行matched-only品質評価では指摘できない。根拠は .tmp/matching-audit/sample5-finding-group-audit-v75/check.json、.tmp/matching-audit/sample5-known-false-v49/check.json、およびsource／translation PDFレンダー。

2026-11-06の現行コードsample5全文Review v81はsample1とEmbeddingを同時実行した際、両要求が80秒超pendingとなり、sample5のみinterruptedとして入力とcall/cacheを保持した。sample5はsample1完了後、同じ出力先から順次再開する。

#### sample3表の数値セル誤group

原文表の「Environmental Management」行の7,434に対し、保存Reviewは訳文の「Legislative Proposal」行の749を選んだ。訳PDFの同じ「環境管理」行には7,43 4があり、保存Reviewの数値不一致findingは誤対応由来である。現行候補文には行ラベルと兄弟セルが入るため、位置だけでなく行の意味を候補順位へ反映する。回帰テストでは兄弟セルに基づき正しい行を選ぶ。sample3で確認した`7,43 4`のような数値の行折り返しがEmbedding候補順位を損ねないよう、候補生成時だけ、千位カンマ付きの単一数値で3桁の末尾群が分割された場合に数字間空白を除く`_table_value`を追加した。`1,234 567`のように別数値の可能性がある文字列は変更しない。focusedテスト26件、全unit/regression 377件、Ruff check/format、tyはpass。このsample3実データを用いた現行コード検索はEmbedding cache missで要求待ちとなり、正しい候補選択の確認は残る。

同じ表ではsource「Total, Discretionary budget authority (gross)」`#/tables/2/cell-r0012-c0000/content`が、別行の訳「総計、任意支出（純額）」`#/tables/2/cell-r0015-c0000/content`とmatchedになり、gross/netの誤訳としてfindingが出ている。PDF画像ではsource grossの正しい訳「総計、任意予算権限（総額）」が訳文同じ行にあり、これは行を取り違えたfalse positive。行ラベルと同一行の数値列が候補検索に使われるため、同じ sibling-cell 修正の実データ再検証対象に加える。

同じ表の別行誤groupは次の二つもある。source「Legislative Proposal: Reclassify Nuclear Waste Fund receipts」`#/tables/2/cell-r0013-c0000/content`が、訳の別表・別項目 `#/tables/3/cell-r0000-c0000/content`（「立法提案」のみ）へ誤対応している。訳文同じ表の`#/tables/2/cell-r0013-c0000/content`には「立法提案：核廃棄物基金の収入を再分類」と全文訳がある。source「Existing law」`#/tables/2/cell-r0017-c0000/content`も、別表の「総計、義務的支出」`#/tables/3/cell-r0001-c0000/content`へ誤対応し、正しい訳は同じ表の`#/tables/2/cell-r0017-c0000/content`「現行法」。表がページをまたぐ箇所で同名・類似行を誤選択した明確なfalse positiveである。

もう一つ、source `#/tables/0/cell-r0006-c0000/content`の「NNSA-Elimination of Weapons Grade Plutonium Production (EWGPP)」が別表のNational Nuclear Security Administration `#/tables/2/cell-r0005-c0000/content`へ誤対応し、「EWGPP未翻訳」と指摘されていた。訳PDF page 20には対応する訳「NNSA-兵器級プルトニウム生産の廃止（EWGPP）」が同じ表の`#/tables/0/cell-r0006-c0000/content`にあるため、このfindingもfalse positive。

PDF画像（source p.16、translation p.22）ではsource「Existing law」の数値に負号が見える一方、訳表の「現行法」は正数で、LOADのsource cell本文は負号を落としている。セル内数値の折り返しによる空白findingはfalse positiveだが、負号差は別の実誤りの可能性があり、元のOCR本文だけでは評価できない。

source「Existing law」の1,796／1,357を訳の「1,79 6」／「1,35 7」とした「不要なスペース」findingも保存Reviewにある。source・訳PDF画像ではセル幅に合わせて数値が次行へ折り返されているため、空白指摘はfalse positive。一方source PDFの値は負数（−1,796、−1,357）だが、LOAD本文では符号が落ち、訳PDFでは正数表示に見える。これは誤groupと抽出欠落の影響を分離して扱う必要があり、数値符号の差は今回のLOADベースfocused Reviewでは検証できていない。


#### 🧪 sample3表の隣接行文脈によるfocused実LLM再照合

現行候補検索v82では、7,434、gross予算権限、Legislative Proposal、Existing law、1,796、EWGPPの既知6件すべてで正しい訳unitを候補に選んだ（`.tmp/matching-audit/sample3-table-cells-current-v82/check.json`）。続いてDocumentの表cell文脈へ前後行ラベルを加え、候補全体の処理と同じ`match_documents`＋実LLMを用いたfocused照合v84を実行。期待6件すべてを正しい同一行へ単独matchedとし、gross source row12は訳row12へ対応、Legislative Proposalは全文訳row13のみに対応した。前回v83のgross行見落としと提案見出しrow0への重複groupは再現せず、残り候補はtranslation-onlyになった。実行結果は`.tmp/matching-audit/sample3-table-cells-review-current-v84/check.json`と保存Callに記録。これは既知表範囲のfocused照合であり、sample3全文Reviewの受け入れ結果ではない。


#### 🧪 Review再開時に旧match/evaluate Callが新groupと衝突する問題

sample1の保存済み操作を現行コードで再生すると、過去のmatch応答が作るgroup数・対応範囲が変わり、後続の評価が存在しない`review/alignment-*`を参照して`InputError: Invalid Review evaluation target`となった。古いmatch操作にも、現行stateですでにmatchedになったunitを再指定して`InputError: Match requires units without a confirmed correspondence`となる例があった。外部サービス停止ではなく、異なる照合結果を保存操作列へ再生する際の依存関係の不整合。

再開時は、現行stateにないtargetを参照するevaluate/recheckと、すでにmatched済みunitを含む保存matchをskipする。これらの対象は未確認のまま残るため、現在のAgent stateから再評価・再照合できる。修正前に失敗する保存Call列の回帰テストを追加し、修正後は成功を確認。sample1現行全文再実行v87では、stale evaluate 2件・stale match 3件をskipして旧失敗点を通過し、Reviewを継続中。v87の最終成果物とfinding監査は未完了。

再生Callが現在のtarget IDと一致していても、別の保存evaluateで同一targetをすでに確認済みの場合は旧evaluateをskipする。IDのずれで同じ現行targetが複数の旧Callから参照される場合に、Review全体が停止しないようにする。

Upgrade再開時も同じ現象が起きることを保存Callテストで確認した。現行照合結果に含まれる英文unitを過去のmatch/evaluate Callが再指定する場合、再生中に`InputError`で停止していた。Review／Upgradeとも再開時のみ、現行結果へ適用できない保存操作をskipし、対象をpending/unmatched stateに残して現在のAgentが再照合できるようにする。

#### 2026-11-06 再起動後のsample1全文Review再開確認

sample1全文Review v94はEmbeddingサービス再起動後に再開したが、Review初期化後、Embedding endpoint（http://192.168.1.100:31000）へのTCP接続が確立したまま応答せず、約1分間Callも成果物も増えなかったため停止した。設定上のLLM endpoint http://192.168.1.183:1234/v1/modelsはHTTP 200、Embedding endpointの/modelsはHTTP 401を返した。後者は接続到達性のみを示し、Embedding要求成功の確認にはならない。記録は.tmp/matching-audit/sample1-full-current-v94/validation.json。

外部APIを使わない範囲では、sample3の表cell 6件についてfocused実Review保存結果を再確認し、すべて期待した同一行対応だった（.tmp/matching-audit/sample3-table-cells-review-current-v84/check.json）。現行コードでの全文Review結果ではない。

#### Embedding要求の短時間疎通と旧cacheの適用範囲

2026-11-06 14:30 JST、現設定のEmbedding endpointへ1件だけ要求し、timeout 12秒・再試行なしで確認したがtimeoutした。sample1 v94全文Reviewは実行していない。sample長表v44の113-vector cache fingerprintは現在の設定と異なり、現行コード／モデルでの候補検索再検証には使えなかった。v44当時の40/40結果は当時の設定・コードを対象とする証跡に限る。

#### sample3表セルの照合候補数による結果差

2026-11-06、現行LLMを使い、既知のsample3表セル6件と誤候補を含むfocused照合を実施した。6 source／12 translationを一括したv95では5件だけmatchedとなり、EWGPP source／訳セルはsource_only／translation_onlyになった。EWGPP source 1件を未対応translation候補7件と再照合したv98は正しいEWGPP訳セルを選んだ。

候補数の影響を分離するため、sourceを1件ずつtranslation 12件と照合したv99／v100では合計5/6正解。Legislative Proposal sourceを同じ表行の数値cell #/tables/2/cell-r0013-c0004/contentへ誤対応し、正しい説明cell #/tables/2/cell-r0013-c0000/contentを選ばなかった。行見出しだけでは同一行の説明と値を区別できない実例である。

この実験はReviewTask.match_documentsへ候補を直渡ししており、MatchingCandidates.expandの同一行・同一列filterを経ていない。したがって現行ReviewAgentで同じ誤対応が生じる証拠ではない。既存の列位置・同じ行内の列優先・sibling-cell候補test 4件は現行コードでpass。Embedding endpointはtimeoutし、RAG込みの実Review再検証は未実施。v97部分ReviewAgentは初回match後に品質評価へ進んだが、評価Callが処理中のまま停止し、最終成果物を作っていない。実証からは、unmatched再探索と候補数の違いを含むReviewAgent全体をEmbedding復旧後に確認する必要がある。証跡は.tmp/matching-audit/sample3-table-cells-review-current-v95/、sample3-ewgpp-retry-v98/、sample3-cellwise-matches-v99/、sample3-cellwise-matches-v100/およびsample3-full-agent-targeted-v97/。
#### 未matched同士の再照合とEmbedding再起動後の確認（2026-11-06）

Reviewでsource-onlyとtranslation-onlyが同時に残った場合、従来は両側のunitが未解決でもfinishでき、fallbackも同じ未matched対象を再照合しなかった。未matched IDだけの再照合へ進むfallbackと、同じscopeの再試行を最大3回に制限する処理を追加した。matched済みunitを再指定する操作は引き続き拒否する。回帰testは修正前に未matchedで完了することを確認し、修正後に再照合で回復するケースと3回後に打ち切るケースを確認した。matching versionを5へ上げ、旧versionの保存Callを新しい照合で再利用しない。

修正後は全pytest 391 passed（90.46s）。`ruff check translate tests`、`ruff format --check translate tests`、`ty check`、`git diff --check`も成功。

利用者からEmbedding再起動完了の連絡を受け、実際の1件Embedding要求を再試行したが、設定timeout 12秒で再びtimeoutした。接続可能性や`/models`応答はEmbedding処理の成功を証明しないため、sample1等の全文Review/Upgrade検証は再開できていない。既存sample3のfocused再照合証跡は利用可能だが、今回の未matched再探索修正を含むPDF実処理の受け入れ検証は未実施。
#### sample1・sample4保存Reviewの同一文面に対する矛盾したfinding

保存済みsample1 Review `outputs/sample1/01a1a1fe-c9fa-77b0-bc92-5bc68e83de36/tasks/41-review/review.json`（226 findings）を調べ、`#/texts/332/content`の`TPFDD`と`#/texts/333/content`の`WARNORD`を確認した。各対象のsource、translation、spanは同じ略語のみだが、対応するLLM応答は略語が訳文に含まれないと指摘し、同じ略語を修正案に返していた。

保存済みsample4 Review `outputs/sample4/01a19d7e-7d4e-7600-b001-4b4efd8b8979/tasks/41-review/review.json`では、`#/tables/1/cell-r0004-c0000/content`の`Spec. dec.`が原文・訳文で同一だった。LLM応答は「技術的な略語なのでそのまま保持すべき」と説明しながらFindingを作り、さらに最初のspanへセル全体の文字列を修正案として割り当てていた。これは対応group誤りではなく、入力と理由が矛盾するfindingである。

Review応答検証では、sourceとtranslationが一致し、理由文が同じ引用文字列の欠落を主張するか、同一表記の保持を勧めている場合、そのfindingを正常判定に直す。単にsourceとtranslationが同じ英語見出し`GLOSSARY`のような、理由上は未訳として成立するfindingは残す。略語2件・Spec. dec. 1件を除外し、GLOSSARY未訳を保持する回帰ケースを確認した。

修正後は4ケースの回帰testを含む全pytest 395件が成功（95.13秒）。`ruff check translate tests`、`ruff format --check translate tests`、`ty check`、`git diff --check`も成功。Embedding 1件スモーク要求を再試行したが設定済みtimeoutで失敗し、全文PDF再実行は未実施。保存応答の実データ監査とローカル回帰検証は完了したが、他のfalse positiveが残っていないこと、および現行コードでの全文結果は未確認。


#### sample1目次のページ参照で空白方向が逆のfinding

sample1 Review run `01a1a1fe-c9fa-77b0-bc92-5bc68e83de36`の目次表で5件確認した。LOADのsourceは`III-1 5`、`III-1 8`、`III-1 9`、`IV-1 1`、`IV-3 1`、translationはそれぞれ`III-15`、`III-18`、`III-19`、`IV-11`、`IV-31`だった。LLMは訳文の空白欠落を指摘し、sourceの空白をtranslationへ加える修正案を返していた。

source PDF p.10と訳PDF pp.12–13の画像、および評価targetを比較すると、5件とも目次の同じページ参照値であり、source側の抽出空白を欠陥として扱っている。ページ参照のローマ数字＋数字に限り、数字間空白を除いて値が一致すればfindingを正常判定にする。異なる番号`III-1 5`対`III-16`はfindingを残し、通常英文`now here`対`nowhere`も同じ規則で同一化しない。sample2の`NCTS Naval Computer and Telecommunications Stations`も、sourceとtranslationが同じ英語の正式名称で、finding自体は未訳を指摘しているため保持する。PDFレンダーは`.tmp/false-positive-review/sample1-source-p010.png`、`sample1-translation-p012.png`、`sample1-translation-p013.png`。

保存済み5 findingは静的監査で確認した。既存の`42-fix/document.json`では5件すべてsourceの抽出空白を`revised`へ書き戻しており、正しいページ参照へ不要な空白を加えていた。sample1・sample4の実保存Call responseをcurrent ReviewTask検証へ通すローカルreplayでは、略語2件・Spec. dec. 1件・page reference 5件の計8 assessmentが`correct`へ正規化され、外部API呼び出しなしで再現できた。今回の正規化分岐は回帰testでも検証したが、Embedding timeoutのため、現行コードでsample1 PDF全文を再評価して5件が成果物から消えることまでは未確認。

最終全pytestは399 passed（88.38秒）。`ruff check translate tests`、`ruff format --check translate tests`、`ty check`、`git diff --check`も成功。


#### 保存sampleの既存FIX結果による副作用確認

sample4の既存`42-fix/document.json`では、Review対象`Spec. dec.`の最初のspanへ`Spec. dec.`を設定し、2番目の`dec.`はそのまま残していた。FIX後のPDF Table 2には`Spec. dec.dec.`と出力され、source PDFの`Spec. dec.`より`dec.`が重複した。今回追加した「理由が保持を勧めるなら、同一source／translationのissueをcorrectへ直す」検証は、この保存Callの再生でissueを除外する。

sample1の既存FIX成果物では、目次のページ参照5件すべてで`III-15`等のtranslationをsourceの`III-1 5`等へ置換していた。今回のpage-reference正規化はこの不要な編集を防ぐ。最新のsample Review 3件についても、p.5／p.8のsourceとFIX後PDFを目視し、表の未訳語句・意図的な長文sample・captionの冗長な「図のサンプル」は実際に出力にある文面と一致し、明確な誤検知とは分類しなかった。

#### 2026-11-06 現行focused照合の追加確認

sample5の既知失敗範囲を現行ReviewTaskと実LLMへ再送した。本文source106→translation61、source108→translation63、式(8)前後source86→translation46、図caption3→caption3の4組が期待値どおり一致し、式と説明文の誤対応は再現しなかった（`.tmp/matching-audit/current-sample5-v103/result.json`）。

sample1のE-2セルは、広い候補集合をそのままLLMへ渡す試験では同名の別行・別列セルを選ぶ失敗を再現した。一方、現行候補検索が使う同列の候補に絞った再照合ではsource `#/tables/4/cell-r0003-c0000/content`をtranslation `#/tables/10/cell-r0003-c0000/content`へ正しく対応付けた（`.tmp/matching-audit/current-matching-rerun-v101/sample1/check.json`、`.tmp/matching-audit/current-matching-narrow-v102/check.json`）。これは候補絞り込み後段のfocused確認であり、Embeddingを含むReviewAgent全文の再実行ではない。

sample Upgradeの保存済み現行結果v80は、旧・新版146／142 unitを確認し、末尾4 unitの削除だけを報告していた（`.tmp/matching-audit/upgrade-sample-current-v80/validation.json`）。これは候補検索を追加する前の比較証跡である。現行UpgradeAgentのEmbedding cacheは35ベクトルしかなく全文候補検索に足りず、再起動連絡後のEmbedding単発要求もtimeoutしたため、UpgradeAgent全文の現行コード再実行は未確認。

全文PDFの現行コード受け入れ確認と全finding監査は未完了。unit粒度を文単位へ一律変更する根拠は得られておらず、TextUnit IDを保ったまま分割・結合候補と表の行列構造を検索・判定へ使う方針を維持する。

#### 2026-11-06 sample1の見出し・長文候補再検証（matching v8）

現行sample1全文Review v6のround 4ではsource `#/texts/9/content`（PREFACE）がtranslation `#/texts/273/content`（計画原則の長い本文）と一緒にsource-only／translation-onlyとなり、正しい相手translation `#/texts/13/content`（1 序文）が候補にならなかった。translation `#/texts/46/content`（意図的な白紙）も近接見出し候補だった。候補cacheからスコアを調べると、short source headingに対するlong candidate spanの最大類似が見出し全体の類似度を上回る。短いheadingでのspan rerankを無効にし、スコア差の小さい同種の近接見出しを最大2件候補に残す修正を追加した。現行候補検索＋実LLMはsource PREFACE→translation 1 序文をmatchedにし、意図的な白紙をtranslation-onlyで保持（`.tmp/matching-audit/sample1-preface-v6/check.json`）。

現行全文Review v6のround 16でもsource `#/texts/20/content`「Expands discussion on global campaigning and campaign planning.」が、正しいtranslation `#/texts/41/content`「グローバル・キャンペーンおよびキャンペーン計画に関する議論を拡充する。」ではなく、別節のlong candidateとsource-only／translation-onlyになった。誤候補`#/texts/497/content`は同じlist_item種別だが多数spanを含み、sourceが1 spanのため1 span間の偶然の類似が本文全体の意味を上回っていた。span rerankはsource側に複数spanがあるときだけ行うよう拡張し、単一spanの長文候補でも同じ誤選択を防ぐ回帰testを追加。現行MatchingCandidates＋実LLMはsource 20→translation 41を正しくmatchedにした（`.tmp/matching-audit/sample1-campaign-v8/check.json`）。分割・結合用の既存cross-kind rerank testも維持し、unit/regressionを含む全pytest 402件が成功。Ruff check／format、ty、diff-checkも通過。

この改善を含む現行sample1全文Review v8を開始した。round 4でPREFACE→1 序文、round 16でglobal campaign summary→translation 41が正しくmatchedになったことを確認したが、全文成果物はまだ生成されていない。旧世代v6／v7の不完全runは採用しない。

#### 2026-11-06 Upgrade sample全文再検証（matching v8）

前後で異なるsample PDFを使ったUpgradeAgent全文runが成功し、旧146／新版142 unitの確認済みplanを監査した。変更4件はsource v1の削除4件で、`Appendix A`→translation v1 `11 付録 A`、`Chapter Title`→`11.1 章のタイトル`、`Section Title`→`11.1.1 セクションのタイトル`、`Appendix body text sample.`→`付録の本文サンプル。`。新版source側に対応unitはなく、誤追加・誤変更はなかった（`.tmp/matching-audit/upgrade-sample-current-v108/21-diff/plan.json`）。全source v1／v2確認IDを含み、現行UpgradeAgentの実PDF受け入れはこのケースで成功。

sample1全文Reviewのfinding監査とsample2〜5の現行PDF受け入れ／既知false positive全件の再確認は残っている。これらが済むまでmainへのmerge・pushは行わない。

#### 2026-11-06 sample3表行候補の再検証（matching v9）

現行候補検索がsource `#/tables/2/cell-r0012-c0000/content`（Total, Discretionary budget authority (gross)）に対し、translation表3の「総計、支出」を選ぶ新しい誤候補を検出した。対象行の数値兄弟セル列（空白を除去した順序付き値）が完全一致する候補に小さな順位加点を加え、行ラベルを持たない先頭列セルでも一致する数値列で元の表行を選べるようにした。専用回帰testを追加し、照合規則版を9へ更新。

sample3の既知表セル6件を現行MatchingCandidatesと実LLMで再検証し、候補検索が各回とも期待する訳セル1件だけを選び、6/6をmatchedと確認した（`.tmp/matching-audit/sample3-candidate-review-v8/check.json`）。全pytest 403 passed、Ruff check／format、ty、`git diff --check`が成功。隣接行ラベルによる暫定案は実データの誤候補を除けなかったため削除した。

sample1全文Review run v108（matching v8で起動）は引き続き`processing`で、version 9の変更を含まない。全文成果物とfinding監査は未確認であり、sample2〜5の現行PDF受け入れも残っている。

数値列の補正が別PDFの同一行・同一列候補を変えないことを確認するため、sample4の既知3セル（source table2 row1 column1〜3）を現行v9で検索した。各々が同IDのtranslation cellのみを選択し、期待pairを保持した。既知の同一行3組は以前の実LLM検証でもmatched（`.tmp/matching-audit/sample4-table-candidates-v56/check.json`）。sample3 row12の数値列は正答候補score 0.565、誤候補score 0.6205だったが、数値列完全一致への+0.20補正後は正答0.765となる。補正は意味類似度の代替ではなく同じ数値並びへの順位補助である。

sample5の数式source `#/texts/113/content`もv9の候補検索＋実LLMで再検証した。候補translation 66／62のうちtranslation 66だけがsourceとmatchedになり、既知の正解と一致（`.tmp/matching-audit/sample5-candidate-review-v9/check.json`）。式の誤対応に対するfocused受入確認であり、sample5全文Reviewの再実行ではない。

#### 2026-11-06 sample1目次の同一ページ行候補（matching v11）

sample1全文Review v108（matching v8）の保存Callを調べ、source `Planning is Commander's Business`がtranslation `計画機能`（row5）へmatchedし、本来のrow0 `計画は指揮官の責務である`が候補から外れた後、source `Planning Functions`が別の「概要」へmatchedする連鎖を確認した。正しい英日対応はsource row0→translation row0、source row5→translation row5。候補embedding scoreはsource row0で誤row5が0.6713、正row0が0.6328、近接row1が0.6432だった。表セルの兄弟ページ番号を数字列として比較し、同一ページの近接rowが僅差なら双方をLLMへ渡す処理と回帰testを追加しmatching versionを11へ更新。現行候補検索＋実LLMではrow0が翻訳row0へ、source row5が翻訳row5へmatched（`.tmp/matching-audit/sample1-toc-pages-v11/check.json`、source row5の実LLM証跡は`.tmp/matching-audit/sample1-toc-pages-v10/check.json`）。同ページ候補を含むunit testを追加し、matching unit test 34件pass。

追加で保存済みtable-cell match全件を検査し、source「Overarching Elements of Operational Design」→translation「作戦設計の包括的要素」は正常な一致と確認した。LOAD本文ではページ番号がsource IV-9、translation IV-19に見えたが、source page 8とtranslation page 9のPDF画像には双方IV-19と印字されている。これはsource側のOCRで先頭の1が落ちた抽出問題であり、誤groupではない（`.tmp/pdfs/sample1-toc-audit/source-p8.png`、`translation-p9.png`）。

sample1全文Review v108（matching version 8）は誤対応調査後に停止し、検証状態を`interrupted`として記録した。全保存CallとEmbedding cacheを保持。focused修正を統合したsample1全文Review v12 runはmatching version 12で処理中。後から追加したv13変更を含む全文受け入れではなく、v13 focused確認と全文finding監査は未完了。

同じsample1 TOCのsource「Elements of a Combatant Command Campaign Plan」ページV-12と「Assessing Campaign Plans」V-15は、LOAD上でそれぞれ「V-1 2」「V-1 5」と数字が分割されている。翻訳側はV-12／V-15で行自体は正しい対応だった。Roman numeral付きページ参照に限って数字内OCR空白を除去して照合する処理と回帰testを追加し、matching versionを12へ更新。focused helper testではV-1 2 == V-12、V-1 0 == V-10、一般数値の「1 2」は「12」と別値を確認した。

version 12のsample1全文Reviewを新しい保存先で開始し、version 8の234 MB候補Embedding cacheを引き継いだ（`.tmp/matching-audit/sample1-full-current-v12/validation.json`）。開始後のsaved match Callはmatching_version 12を記録。version 8 runは現行版受け入れを優先するため中断した。

matching v12の回帰確認としてsample3の既知表誤対応6組を、現行候補検索＋実LLMで再送し、期待する同じ行の訳セル6/6だけがmatchedとなった（`.tmp/matching-audit/sample3-candidate-review-v12/check.json`）。

#### 2026-11-06 sample2の複数unit対単一unit照合（matching v13）

sample2保存Reviewのsource `#/texts/632/content`「Naval C4I strategy…」から現行v12の候補検索を実行したところ、結合訳unit `#/texts/736/content` ではなく別内容の `#/texts/901/content` を唯一の候補として選んだ。source 632は1span、translation 736は6spanで、unit全体のEmbeddingと位置補正はそれぞれ0.561 cosine、開始位置差0.084だった一方、対応する訳spanは0.823だった。さらに隣接source unit 633・634・635と訳unit 736本文の類似度は0.782・0.792・0.716で、単一source unitだけを順位付けすることが原因と確認した。

matching v13では、1spanのparagraph／list_itemを照合する際、同じ節の隣接source unitが支持する6span以上・同種の訳候補にも順位補助を適用する。これにより開始位置が結合unitの先頭だけを表す場合でも、分割された隣接sourceの文脈を利用できる。matching unit test `test_matching_uses_neighboring_units_to_find_a_merged_counterpart`を追加し、単一source spanの一部だけが長文に似る既存の誤候補抑止testも維持した。

sample2 v13の現行候補検索＋実LLM確認では `#/texts/736/content` を選び、source `#/texts/632/content`〜`#/texts/635/content` の4unitをtranslation 736の単一unitへmatchedした（`.tmp/matching-audit/sample2-naval-candidate-v13/check.json`）。sample1の単一span campaign summaryもv13で再確認し、source `#/texts/20/content`→translation `#/texts/41/content`を維持（`.tmp/matching-audit/sample1-campaign-v13/check.json`）。sample Upgradeのv13実行もsource v1の146unit／v2の142unitを確認し、期待する削除4件（`Chapter Title`、`Appendix A`、`Section Title`、`Appendix body text sample.`）を出力した。旧v8 runと変更のID集合は一致し、翻訳側の各対応IDも同じ（`.tmp/matching-audit/upgrade-sample-current-v13/validation.json`、`21-diff/plan.json`、`audit.json`）。matching v13時点の全pytest 407 passed、Ruff check／format、ty checkが成功した。

sample1全文Review v12はv13変更前に起動した別プロセスで、2026-11-06 20:31 JST時点で保存Call 168件、状態`processing`、Review artifact未生成。再開後に保存Callは200件まで増えたが、その後約50分増加がなく、Review artifactも生成されなかったため停止した。保存CallとEmbedding cacheは保持している。保存済みmatched groupではsource／translation unitの重複割当はなく、表cell match 143件中の数値兄弟列差2件は、同じ「Overarching Elements of Operational Design」行のsource OCR「IV-9」と翻訳「IV-19」だった。source PDF p8とtranslation PDF p9の画像では双方IV-19印字を確認済み。v13の全文Review・sample2以外の全PDF受け入れ・全文finding監査は未完了。

利用者からEmbeddingサービス再起動完了の連絡を受け、単発Embeddingは成功した。一方、sample2 Mobile v13 focused候補検索は既存cache外Embedding要求から約2時間進まず、結果未生成のため中断した。sample1全文Reviewも同じく進捗が止まった。Embedding待ちを伴う全文Reviewおよびこのfocusedケースの現行実処理検証は未完了である。

#### 2026-11-07 sample2 Mobileの現行v13再確認

source `#/texts/294/content`の旧Reviewは、誤訳候補 `#/texts/229/content`と対応付いていた。現行v13候補検索に必要なEmbeddingが旧cacheに無かったため、同じsample2 LOAD文書を使い、候補unit 476件と長い候補のspan 228件を取得してcacheへ保存した。現行候補検索はtranslation `#/texts/325/content`だけを選び、旧誤候補229は選ばなかった（`.tmp/matching-audit/sample2-mobile-current-v13-cache/check.json`）。この候補範囲を現行ReviewTask／実LLMへ渡すとsource 294→translation 325がmatchedとなった（`real-review.json`）。以前の広い候補直渡しで残った誤対応は、現行候補検索経由では再現しなかった。

sample1全文Reviewおよびsample1〜5の全findingに対する網羅的な最終監査は未完了。今回のsample2 Mobile確認は既知失敗1件のfocused受け入れであり、sample2全文または全PDFの誤検知がないことを示すものではない。

#### 2026-11-07 sample4表内アルゴリズム名の未訳誤検知

保存済みsample4 Review `01a19d7e-7d4e-7600-b001-4b4efd8b8979`では、table 3のPolicy列`Tree`と`Forest`を英語未訳として指摘していた。source PDF p.4の表と本文を確認すると、これらはdecision tree／random forestを表すアルゴリズム名で、LogRegを含む他のpolicy識別子と並ぶ表ラベルである。日本語へ置換すべき一般文ではなく、両findingをfalse positiveと分類した。

品質評価規則へ、表のモデル・アルゴリズム・手法名は周辺列と値を使って名称か一般語かを判別する指示を追加した。LOADのPolicy列文脈付きで現行ReviewTask／実LLMに`Tree`と`Forest`を再評価させ、両方ともfinding・revisionなしとなった（`.tmp/matching-audit/sample4-policy-labels-v2/check.json`）。全文で同種の誤検知がないことは未確認。全pytest 407件、Ruff check／format、ty check、`git diff --check`は成功。

追加監査でsample3 Reviewのsource `#/tables/2/cell-r0010-c0000/content`（`Nuclear Waste Disposal .....................................................`）と訳文が同じドットリーダーを含むのに、「不要なドット」とするfindingがあった。source PDF p.132ではドットは項目名から数値欄までを結ぶ表レイアウトであり、内容の句読点ではないと確認した。規則に表・目次のドットリーダーを保持する指示を加え、sample3のcellとsample4のTree／Forestを同じ現行ReviewTask／実LLM要求で再評価し、finding・revisionとも0件（`.tmp/matching-audit/sample3-leader-and-sample4-policy-v2/check.json`）。この3指摘を保存Review上の誤検知として確認した。

sample3 source `#/texts/91/content`の`$43 million`も誤検知の可能性を調べたが、訳文の数字は`4,300万`と等価でも通貨表記が「ドル」ではなく「ドリン」になっていた。現行LLMも単位誤りに対するfindingと修正案を返したため、これはfalse positiveから除外した。

sample1の保存Reviewには、参考文献付録「Chairman of the Joint Chiefs of Staff Publications」「Service Publications」にある番号付き公式タイトルが未訳として複数指摘されていた。`JP 3-60, Joint Targeting`、`AFDA 3-12, Cyberspace Operations`、`ADP 5-0, The Operations Process`は番号で識別される出版物の正式タイトルであり、参照目的で英語保持が妥当と分類した。規則へ書誌・出版物一覧の公式タイトルを識別名称として扱う文を加え、現行ReviewTask／実LLMでこの3件にfinding・revisionが出ないことを確認（`.tmp/matching-audit/sample1-publication-citations-v1/check.json`）。同じ一覧にある他のfinding、全文Review、sample1の全付録の網羅監査は未完了。

sample3 `#/texts/129/content`では`Lawrence Livermore National Laboratory`を「ローレンス・リバモア国立研究所」と訳した表記へ、旧Reviewが「リバーモア」への任意置換を提案していた。施設を一意に特定でき、意味の違いもないため、許容される固有名詞の音訳差によるfalse positiveとした。規則へ公式の定着訳と許容音訳の揺れを区別する指示を加え、実LLMで当該targetがfindingなしとなることを確認。同じ再評価要求に含めた`#/texts/91/content`では、`$43 million`に対する訳文`4,300万ドリン`の誤字をfindingとして維持した（`.tmp/matching-audit/sample3-livermore-transliteration-v1/check.json`）。

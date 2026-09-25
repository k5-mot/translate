<!-- markdownlint-disable MD013 MD041 -->

## Context

動機と既存要求は[proposal.md](proposal.md)を参照。`translation.translate_node`が`read_rules(settings, "translation")`を読み、`translate._translate_page`の全送信経路へ同じrulesを渡す。保護記号は`_protect_chunk_for_prompt`で付与され、user JSONにはtargetと記号一覧があるが、配布system指示は一般的な翻訳ルール3項目だけである。

実応答は3件とも期待する14 IDを含む一方、本文中の記号2件が欠落し、記号だけの要素1件は保持されていた。表記揺らぎや復元処理の誤判定ではない。指示の不足は観測事実だが、補足による成功は実モデル検証まで未証明とする。

## Goals / Non-Goals

**Goals:** 既存の配布ルールとloaderを使い、初回・検証retry・切断分割のすべてで保護記号の扱いを明示する。既存の失敗時公開拒否を維持する。

**Non-Goals:** 復元アルゴリズムの緩和、欠落値の自動追記、専用repair loop、要求並列化、推論設定変更、新規Module、独自再開記録、他の文書品質問題の同時修正。

## Decisions

1. **既存Rule fileへ追加する。** `translate/templates/translation-rules.md`で、targetのIDを維持し各対象へ非空の訳文を返すこと、前後文脈・用語・参照は文脈用であることを明記する。各`__PROTECTED_<unit>_<fragment>__`は不透明な文字列として同じID内に1回だけ残し、翻訳・省略・複製・別IDへの移動・実値の推測をしない。本文途中の記号にも適用する。Adapter共通promptを変更するとSTRUCTURE等へ波及するため採用しない。
2. **復元側の契約を変えない。** canonical記号を返すよう依頼することと、既存の安全な表記揺らぎ復元を廃止することは別である。既存の検証、有限retry、分割深さ上限をそのまま使う。失敗応答を次のpromptへ転記する方式も、今回の根拠だけでは不要なので導入しない。
3. **既存Testに到達確認を足す。** `tests/test_translation_output_failures.py`で配布ルールを実loaderから読み、Taskが`structured`へ渡すsystem/user引数を捕捉する。通常とOFF、保護欠落後のretry、切断後のsub-chunkを検査する。本文中の識別子・URL、記号のみ、複数記号の合成入力を使う。既存の欠落・重複・未知記号・別IDの拒否、atomic公開前の失敗Testを維持する。Mock応答が正しく返ることは実モデルの品質証明にしない。
4. **既存fingerprintを再利用する。** 公開fingerprintのrules hashとWorkflowのtranslation_rules hashを変更検出に使い、新しいVersion管理を作らない。`tests/test_fingerprint.py`と必要なWorkflow Testでルール変更の検出を確認する。旧Runへの強制Resume・hash書換え・Artifact移植を禁止する。
5. **既に確定した契約の実装補足として扱う。** 保護対象保持・失敗時停止・OFF検証・逐次実行は既存要求であり、新たな利用者判断を前提にしない。grill-with-docsの検討では「保持できなければ捏造せず失敗」「旧ルールRunを保持して新規検証」を既存方針に照合した。新しいDomain用語・不可逆なArchitecture判断はなく、Glossary/ADRを増設しない。他Changeの未回答事項は承認済みにしない。

## Quality Attribute Design

- Q-FUNC/Q-REL: 配布指示の到達と既存拒否条件をTestで確認し、実翻訳の対象ID・保護値の対応をArtifactから検査する。成功コードのみでは合格にしない。
- Q-PERF/Q-COMP: 送信回数の回帰Test、ルールhash差分と旧Run保持、新規OFFの設定を確認する。token使用量は取得できる項目だけ記録する。
- Q-SEC: 合成Fixtureを使用し、実入力・Provider応答はコミットしない。診断ではID・件数・分類のみを記録する。
- Q-USE/Q-MAINT/Q-PORT: 既存入口・loaderを維持し、実DOCX/PDFを目視へ提示する。全体品質検査では既存未コミット差分を含むか明示する。

## Lifecycle, Migration and Operations

設定追加やデータ移行は行わない。旧OFF Run `01a0d5f5-beb9-79d1-a1e4-f4300066b6b5`は失敗証拠として保持する。新規検証は`sample3.pdf`、プロセス限定`LLM_REASONING_MODE=off`、非対話、`--resume`なし、未使用export先とし、事前に既存実処理の終端を確認する。

翻訳成功後、自分で起動したMicrosoft WordでDOCXを別PDFへ変換し、原本との公開ReviewをOFFで逐次実行する。Word操作は検証手順だけで、製品機能には加えない。実行hash・所要時間・失敗分類・公開成果物を記録し、旧成果物で新規検証を代用しない。

## Risks / Trade-offs

- [Risk] 明示指示後も欠落が続く → 有限retry後に停止し、安全な証拠を記録する。受入基準を下げず、次の診断根拠とする。
- [Risk] 指示が長くなりContextへ影響する → ルールは短い箇条書きに留め、30208の実設定で検証する。token上限を暗黙増額しない。
- [Risk] 他の既知不具合で後続Gateが失敗する → 当該指摘と本修正の結果を分離し、全体受入やarchiveを成功扱いしない。

## Migration Plan

1. 配布ルールとTestを修正し、関連Test・全体pytest・Ruff・tyを通す。
2. ルールhash変更を確認し、新規OFF翻訳→Word PDF→Reviewを実施する。
3. 利用者目視と正式verifyを記録し、適用できる同一実行証拠を関連Changeへ参照する。
4. 本Changeの必要条件を満たしてからarchive判定を行う。PR/CI・mainへのmerge・originへのpushは全体の受入状況に従う。
5. Rollbackは本修正のルール/Test差分を戻す。旧Run・新規Run・exportは削除せず、ルールの異なるResume互換性を迂回しない。

<!-- markdownlint-disable MD013 MD041 -->

## 状態

2026-09-26、実装と静的・合成回帰まで完了し、Taskは4/6。修正後の新規実E2Eと利用者受入は未完了。正式verify成功・archive可能という意味ではない。以下の提案時記録は履歴として保持する。

## 再現根拠

- check.pyのdeterministic_findingsは原語をcasefoldした部分一致で判定する。matching_glossaryは単語境界・大小文字・連続空白を扱い、TRANSLATE/REVIEWから既に使用される。
- 外部要求なしの直接呼出しで、原文「Complete a Capital Asset Management Plan and certify the Earned Value Management System.」と用語API→APIに対し、前者はglossary/APIを1件返し、後者は適用対象0件だった。
- 実翻訳Run 01a0d8b6-c2ab-7c92-bed9-58403a8410b3の第14ページでも、VERIFYはAPI指摘を当該文と無関係と判定した。詳しい経過は[先行検証記録](../simplify-translation-literal-checks/verification.md)を参照する。
- 数値符号の抽出欠落、ALIGNの誤対応、図一覧と本文のCaption重複出現は別の課題である。本提案の成功条件へすり替えたり、本件の実装だけで解消済みとしたりしない。

## 設計確認の境界

用語検査維持・既存API再利用・過剰な固有名詞保護廃止は承認済みであり、本件に新たな公開方針の選択はない。ALIGN側の判定不能時と追加一覧の扱いは別途利用者へ確認中で、本Changeには含めない。

実行中の旧比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2へCode/Ruleを混在させない。実装前にその終端を確認し、修正後E2Eは新規Runで実施する。

## 提案文書の検査

OpenSpec statusはmysddのproposal/specs/design/tasksの4/4 artifacts complete、strict validationはvalid。既存tests/test_documentation.pyは21 passed（0.28秒）、git diff --check成功。これは計画文書の検査だけで、6件の実装Taskはすべて未完了。Code未変更のため製品全suiteを新たに実行したとは記録しない。

## Apply結果

比較Run 01a0d8e0-73da-73e0-97b9-e1d0bcf442f2は2026-09-25 14:25:52 UTCにcompleted・child exit 0を保存し、対象の親子Processが存在しないことを確認してから製品Code/Ruleを変更した。比較の旧結果を本修正後の合格証拠には使わない。

- check.pyの原語選択を既存matching_glossaryへ委譲した。独自の単純部分一致2行を置換し、指定訳の包含条件・Findingの形式は維持した。新Helper・Module・依存・再開状態を追加していない。
- 配布review Ruleへ語境界と正規化を明記。既存Rule hashを使用し、fingerprintの構造・Workflow状態を新設していない。
- 先行Testは10 failed / 71 passed。Capital/API等の誤一致7条件と本文/Caption/セルの3ケースで現行不具合を検出した（空白を含む2条件は必要な指摘の見落としであり、10件すべてが誤指摘ではない）。
- 修正後の関連4 Fileは120 passed（3.90秒）。16条件×指定訳あり/なし、3領域×原語あり/なし、Rule変更の公開互換性と両Workflow識別を検査した。領域別CHECK→report試験ではsocket接続を禁止し、追加サービス呼出し0、両Document不変、真の指摘の対象ID・根拠・修正提案を確認した。実PDF解析の代替ではない。
- LLM/LibreTranslateと比較の公開fingerprintはdefault/OFFで旧Ruleと非互換、同Ruleと互換。翻訳の両Backendと比較WorkflowのthreadもRule変更で分離した。既存の正常な用語集・数値・否定・条件・URL警告の試験は維持した。
- Testの初回Lint指摘はTest引数の組み合わせ・例外文字列・fixture構築を整理して解消し、規約の無効化は行っていない。
- 全体pytestの最初のsession 65636は観測handleが失われ、終了結果を取得できなかった。Process一覧でpytest/uv/pythonが稼働していないことを確認した後に再実行し、session 35617は728 passed / 1 skipped、48.48秒、exit 0。skipはWindows上のPOSIX PTY試験。
- 全体Ruff check、format（359 files）、ty、OpenSpec strict、git diff --checkが成功。全体suiteは秘密情報・例外・関数説明の既存回帰を含む。

検査基点は27667caに既存差分と今回の変更を含むworktreeである。AGENTS/config、LLM/Review/診断/過去記録などの既存変更と未追跡Changeは本commitへ含めない。今回のCode/Ruleと4 Test File、当該tasks/verificationだけを対象とし、.agents・PDF/DOCX・outputs/runsを除外する。

## 残る受入

tasks 2.2〜2.3は未完了。新Ruleの新規翻訳→Word PDF→比較Reviewと、利用者の目視が必要である。先行比較の診断counter=0と実LLM観測39件の不整合は別件として[診断保存Change](../overwrite-diagnostic-json-in-place/verification.md)へ記録し、本件に診断機構の修正を混入させない。

2026-09-26 11:35 UTC、診断入口修正a222a9b後に新規翻訳Run 01a0dd7f-a0a9-75f0-bc80-4693ee212389をreasoning OFFで開始した。[共通実検証記録](../reuse-canonical-detached-child-module/verification.md)で追跡する。現時点は実行中であり、用語集の実成果物合格・目視受入は未確定。

同Runは12:30 UTCにSTRUCTURE/page 2/text-invokeのOpenAIAPIErrorでfailed、exit 1となった。用語検査へ到達せず、DOCX/PDF/比較Reviewは生成していない。上記の実行中記録をこの終端結果で更新し、Task 2.2〜2.3は未完了とする。入力とCheckpoint等は保持されており、詳細と診断counterの限界は共通実検証記録を参照する。

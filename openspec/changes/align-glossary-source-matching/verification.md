<!-- markdownlint-disable MD013 MD041 -->

## 状態

2026-09-25の提案時点。製品Code・Ruleは未変更、実装Taskは0/6。正式verify成功・受入・archive可能という意味ではない。

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

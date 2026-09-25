<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)を参照。check.pyのmatching_glossaryは大小文字・連続空白・端の単語境界を考慮し、TRANSLATEとREVIEWが既に使用する。一方、同じFileのdeterministic_findingsは単純なcasefold部分一致を使う。実sample3第14ページのCapitalでAPIを誤検出し、VERIFYも無関係な指摘と判定した。新しい用語選択方式の決定は不要であり、既存APIの利用先の不一致を修正する。

## Goals / Non-Goals

**Goals:** 共通CHECKの適用原語を既存選択と一致させる。異なる文書領域・公開操作とRule互換性を検証する。

**Non-Goals:** NER、語形変化・日本語形態素解析、訳語の曖昧一致、全角正規化、用語辞書の変更、独立Module、LLM検査の追加、ALIGNと金額の抽出修正。

## Decisions

1. deterministic_findingsの用語選択を同じFile内のmatching_glossaryへ委譲する。指定訳の文字列包含判定、Findingのkind/severity/message/evidence、対象ID付与は維持する。別のregexや新Helperを作る案は既存と同じ責務を増やすため採らない。
2. 既存APIの挙動を試験で固定する。Capital/API、APIs/API、API_key/APIは不一致、API/api/(API)は一致、複数語の空白・改行は正規化する。句読点を含む原語は既存のescapeと端境界をそのまま用い、regexのメタ文字として解釈しない。すべての言語の語境界を保証するとはしない。
3. 共通のCHECKを本文/Caption/セルで通し、既存の対象IDとreportを検査する。誤指摘が消えることと、実在用語の指定訳欠落が残ることを対にする。意味Reviewの判断内容を全件同じに固定する要求ではない。
4. 配布review Ruleへ原語の適用範囲を明記する。既存の翻訳両Backend/比較のRule hashとWorkflow識別がこの変更を含むことを確認し、旧RuleのResume拒否と同Ruleの互換性を回帰試験する。新しいfingerprint機構は作らない。

## Quality Attribute Design

Q-FUNC/Q-RELは境界fixtureと領域別CHECK、Q-USEは対象と根拠のreportで検証する。Q-COMPはRule hash、Q-SECは既存安全性Test、Q-MAINはAPI委譲と全体品質検査、Q-PERF/Q-PORTは新規Model段階なしの逐次Windows E2Eで確認する。部分一致より厳しい境界へ揃えるため、複合識別子内の用語を意図的に適用しない。

## Lifecycle, Migration and Operations

利用者が承認済みの「用語集検査は維持」「既存APIを再利用」「固有名詞の厳密保護は不要」の範囲内である。grill-with-docsの設計確認では、この修正に未確定の公開方針はない。ALIGNの判定不能・一覧の扱いは別の回答待ちであり混入させない。新Domain用語・難しく逆戻りするArchitecture判断はないため、CONTEXT追記とADRは不要。

先行の実検証Runを旧契約の証拠として保持する。稼働中workerへCode/Rule変更を反映せず、終了後にapplyする。実装後の受入は新規sample3翻訳→Microsoft Word PDF→原本との比較Reviewで共有可能な同一実行証拠を記録し、利用者へ提示する。

## Risks / Trade-offs

- [Risk] APIを含む複合識別子にも用語適用したいケースがある → 今回は既存の用語選択と承認済み境界に揃え、網羅的な識別子解析は追加しない。
- [Risk] 決定的検査が直ってもLLMが無関係な指摘を作る → 実reportの根拠を確認し、本修正だけで意味Review全体を合格としない。
- [Risk] Rule変更前の結果を再利用する → 既存互換性Testと新規Runで検証する。旧データは消さない。

## Migration Plan

境界Testを先に追加し、API委譲とRuleを最小差分で変更、回帰検査と新規実E2Eへ進む。RollbackはCode/Ruleのみを戻し、旧新Run・公開成果物を削除しない。仕様同期時はsimplify-translation-literal-checksの後継要求を保ち、旧marker要求を復活させない。

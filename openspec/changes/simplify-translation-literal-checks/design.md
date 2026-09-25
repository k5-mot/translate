<!-- markdownlint-disable MD013 MD041 -->

## Context

動機は[proposal.md](proposal.md)を参照。check.pyのPROTECTED_REは名前認識ではなく、ドット区切り・camelCase等の形を対象にする。translate.pyには置換/復元だけでなく_validated_mappingの原文fragment完全一致があり、translate_lite.pyにも独立したmarker処理がある。CHECKは同じ抽出器を使うため、停止処理だけを外しても略語の誤指摘が残る。

## Goals / Non-Goals

**Goals:** 本文marker機構を両Backendから除去し、狭いURL/ファイル名warningと既存の品質確認へ委ねる。既存の構造情報を使ってCode/Linkを保持する。

**Non-Goals:** 固有表現認識、網羅的なファイル名推定、新しい判定LLM、feedback retry強化、ALIGN修正、common再編、再開台帳追加。未翻訳公開の別Changeの範囲をここへ取り込まない。

## Decisions

1. **本文をそのまま翻訳対象にする。** _protect_chunk_for_prompt、_restore_chunk_placeholders、marker用文字数計算・prompt field・復元例外を廃止する。_validated_mappingのfragment照合も除去するが、対象IDと空応答の検査は残す。translate_liteの_protect/復元も同じ方針にする。通常・retry・切断後の再分割で同じ経路を使う。記号の許容綴りを増やす案は採用しない。
2. **CHECKは小さく限定する。** 既存check.py内の抽出を明示的URL（http/https/www）と明確な拡張子を持つファイル名に限定する。U.S./U.K./U.S.A.、裸の固有名詞、大文字略語、camelCase、underscoreだけを根拠に対象化しない。拡張子はpdf/docx等の小さい明示集合を初期fixtureで固定し、未知拡張子や曖昧な識別子の網羅を目指さない。大小文字や句読点境界はfixtureで確認し、分類器や外部辞書は導入しない。数値/単位等の既存検査とは分離し、文字列warningをerrorへ昇格させない。
3. **既存Reviewを使用する。** CHECKの対象ID付きwarningを保存し、既存REVIEW/FIX/VERIFYへ渡す。意味Reviewが別の問題を判断することは許すが、同じ表記不一致だけによる停止を復活させない。比較Review側でも共通CHECKのwarningと根拠をreportへ残す。warningと修正失敗は同一概念ではなく、fix-skippedだけを警告記録の代用にしない。
4. **構造と文字列推測を分ける。** Inline.kind=codeは両Backendの翻訳・FIXの書換対象から除外して原文内容を出力層へ渡す。linkのhrefは既存model_copyで保持し、表示ラベルは翻訳する。kind=textのコードらしい本文まで推測保護する機構は追加しない。Markdown/DOCX描画の回帰と翻訳→FIX経由の試験を組み合わせる。
5. **旧契約の再導入を防ぐ。** preserve-protected-fragments-after-split、harden-protected-fragment-restoration、protect-all-translation-chunks、clarify-translation-placeholder-instructionsのmarker完全一致要求を本Changeで置き換える。apply時に各verificationへ廃止対象と後継を追記し、残すID/切断等の要求を区別する。旧Changeを無条件に成功扱いしない。sync/archive時はそれらの廃止差分を再適用せず、本Changeの最終要求との整合を確認する。

## Quality Attribute Design

Q-FUNC/Q-RELは両Backend、通常/切断分割、CHECK、Code/Link、比較reportのfixtureで確認する。Q-PERFは新規検査LLMを作らず既存逐次経路を維持する。Q-COMPはRule hashのResume拒否、Q-USEはwarning根拠の保存、Q-SECは失敗情報への本文非混入を試験する。Q-MAIN/Q-PORTは専用分岐削減、依存差分0、品質commandとWindows E2Eで確認する。

## Lifecycle, Migration and Operations

利用者の「ok」により、固有名詞・略語の厳密照合廃止とURL/ファイル名warning化は確認済み。既存Findingの語義を変更せず、新用語・CONTEXT追記・ADRは不要。Ruleと検査仕様を変更するため旧Runを受入に使わず、sample3で新規実行する。rule fingerprintで旧LLM Runを拒否することと、LibreTranslate/比較側の既存fingerprintに必要な検査契約識別が含まれるかを確認し、含まれなければ既存version項目で区別する。新しい互換性機構は作らない。

## Risks / Trade-offs

- [Risk] URL/ファイル名の誤訳がwarning付きで残る → これは承認済みの境界。Reviewと利用者目視で確認し、無誤訳保証とは表示しない。
- [Risk] 抽出範囲を狭めると未知拡張子を見逃す → 意味Reviewへ委ね、固有名詞検出の再開発はしない。
- [Risk] marker除去でchunk長が変わる → 原文で予算を計算し、context上限・有限再分割のTestを維持する。
- [Risk] 古いDeltaのarchiveで厳密停止が戻る → 後継対応を明記し、最後の同期結果を要求単位で再確認する。

## Migration Plan

1. 両Backend/CHECK/構造化要素のTestを先に更新し、旧動作との差を確認する。
2. marker処理とRuleを整理し、既存障害・reasoning OFF・fingerprint回帰を通す。
3. 診断保存Changeの確認後に、新規sample3をreasoning OFFで逐次翻訳し、Word PDF化、原PDFとのReviewを一度ずつ順に実施する。共通のE2E証拠は実行commit/設定/Run IDを両Changeから参照する。
4. DOCX/PDFを利用者へ提示し、未解決の別件をverificationへ残す。仕様同期・archive・PR/CI・main merge/pushは必要な受入完了後に行う。

RollbackではCode/Ruleだけを戻す。旧・新Runや成果物を削除・上書きしない。

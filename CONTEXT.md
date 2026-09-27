# 📘 Translate JA

Translate JAは、文書構造を維持しながら原文を日本語成果物へ変換し、独立した英日文書の品質を比較するためのContextである。

## 🗣️ Language

**Task**:
一つの主要責務と、明示された入力・出力契約を持つ処理単位。
_Avoid_: Stage、phase、processor

**Pipeline**:
Taskの順序と分岐を調整し、利用者向け成果物を生成する処理。
_Avoid_: Workflow

**Docling Schema JSON**:
Docling-serveが生成し、Internal Documentへ変換される前の構造化文書表現。
_Avoid_: Raw JSON、Bronze JSON

**Internal Document**:
翻訳、Reviewおよび描画のTaskが共有する、検証済みの文書表現。
_Avoid_: Model、normalized JSON、Silver JSON、Gold JSON

**Finding**:
原文と訳文の組にある問題を特定し、訳文自体は変更しない検査またはReviewの結果。
_Avoid_: 個別の問題を指すReview result

**Artifact**:
Resumeと診断のために保持されるTaskの中間結果。
_Avoid_: Stage output、永続性が本質である場合のcache

**LLM Call**:
固定された対象ID群に対する一つの論理的なLLM要求。通信やSchema不正による再試行は同じLLM Callとし、分割後の要求は子LLM Callとする。
_Avoid_: attempt、chunk

**Translation ID**:
一回のTranslateの入力、設定、進捗、Artifactおよび成果物を関連付けるUUIDv7。
_Avoid_: job ID、session ID

**Review ID**:
一回のReviewの原文、訳文、進捗、Artifactおよび成果物を関連付けるUUIDv7。
_Avoid_: Translation IDとの共用

**Registration ID**:
一回のRegisterの登録対象、設定、進捗および登録結果を関連付けるUUIDv7。
_Avoid_: Qdrant point ID

**Resume**:
入力と設定の互換性を確認し、同じTranslation ID、Review IDまたはRegistration IDに属する完了済み処理を再利用して、未完了または失敗した位置から処理を再開すること。LLM Callの再利用はTranslateとReviewだけで行う。
_Avoid_: retry、restart

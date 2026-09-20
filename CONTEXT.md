# 📘 Translate JA

Translate JAは、文書構造を維持しながら原文を日本語成果物へ変換し、独立した英日文書の品質を比較するためのContextである。

## 🗣️ Language

**Task**:
一つの主要責務と、明示された入力・出力契約を持つ処理単位。
_Avoid_: Stage、phase、processor

**Workflow**:
Taskの順序と分岐を調整し、利用者向け成果物を生成する処理。
_Avoid_: Domain概念を指すPipeline

**Docling Schema JSON**:
Doclingが生成し、Internal Documentへ変換される前の構造化文書表現。
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

**Run**:
一つの公開操作について、入力、設定、進捗、Artifactおよび成果物を関連付ける実行単位。
_Avoid_: job、session

**Resume**:
互換性を確認したRunについて、完了済みTaskを再利用し、未完了または失敗したTaskから処理を再開すること。
_Avoid_: retry、restart


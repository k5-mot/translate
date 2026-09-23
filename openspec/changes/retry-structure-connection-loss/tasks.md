## 1. Implementation

- [x] 1.1 接続断retryと仕様Deltaを定義する
- [x] 1.2 STRUCTUREの接続系LLMErrorを最大1回逐次再試行する
- [x] 1.3 retry成功・枯渇・redactionをunit testする

## 2. Verification

- [ ] 2.1 全pytest、Ruff、format、ty baseline、strict validation
- [ ] 2.2 同じRun IDでdetached Gateを再実行しsource hash/temp cleanup/終端を記録
- [ ] 2.3 成功後にResume証跡を記録

## 3. Archive

- [ ] 3.1 verification.md作成
- [ ] 3.2 差分レビュー
- [ ] 3.3 受入後archive

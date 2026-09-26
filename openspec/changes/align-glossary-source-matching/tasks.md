<!-- markdownlint-disable MD013 MD041 -->

## 1. 原語の照合を統一する

- [x] 1.1 Capital/API、APIs/API、API_key/API、API/api/(API)、複数語の改行・連続空白、句読点を含む原語、指定訳あり/なしの対になるTestを追加し、CHECKを既存matching_glossaryへ委譲して全成功させる。新Helper/Moduleを作らず、Finding形式と他の品質指摘を維持する（Q-FUNC/Q-REL/Q-MAIN）。
- [x] 1.2 本文/Caption/表セルのCHECKと比較reportの統合Testで、誤API指摘0件、真の違反の対象ID・根拠保持、両入力不変、専用LLM呼出し追加0を確認する（Q-FUNC/Q-USE/Q-SEC/Q-PERF）。
- [x] 1.3 配布review Ruleへ同じ原語適用契約を反映し、LLM/LibreTranslate/比較の公開fingerprintとWorkflow識別が旧Ruleを区別し、同Rule同士は互換であることをTestする。独立の互換性・再開状態を追加しない（Q-COMP/移行）。

## 2. 回帰検査と実成果物の受入

- [x] 2.1 全体pytest、Ruff check/format、ty、OpenSpec strict、git diff --checkを実行し、Code/設定/既存差分と結果をverification.mdへ記録する。新依存/Module/専用LLM段階0、コメント規約と秘密情報回帰を確認する（Q-MAIN/Q-SEC）。
- [ ] 2.2 稼働中の比較の終了を確認後、修正Codeでsample3を新規Run・reasoning OFF・逐次翻訳し、同じDOCXをMicrosoft WordでPDF化して原本と比較Reviewする。Run ID/入力・成果物hash/終端/要求設定/所要時間/取得可能な呼出し数と対象用語Findingを記録し、先行Runの結果を修正後の証拠へ流用しない（Q-FUNC/Q-REL/Q-PERF/Q-PORT/運用）。
- [ ] 2.3 DOCX/PDFを利用者に提示し、目視結果と本件以外の未解決問題を区別する。正式verifyで要求・Test・実データを対応付け、必要な受入完了後に仕様同期/archive/PR・CI/main merge/pushへ進む。旧Runを保持し、.agents・サンプル・outputs/runs・無関係な差分をcommitしない（供給・保守・廃止）。

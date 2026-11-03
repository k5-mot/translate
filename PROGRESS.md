# 📈 進捗

スクラッチ実装の削減と実機検証の進捗を記録する。不具合は[BUG.md](BUG.md)へ記録する。

## 🧭 現在の状況

- 作業ブランチ: `feature/reduce-scratch-implementations`
- 実装: 完了。Review／Upgrade Agentの連続した操作選択失敗からの回復を追加
- 品質検査: 回帰テスト68件成功。Ruff・型検査は全体実行中
- 実機検証: sample2 Register／Translate成功、Review実行中。実行記録は`.tmp/acceptance/20261103-131445-8554b4b8/state.json`

## 🧪 実機検証

今回の対象順序はsample2、sample1。各文書をRegister→Translate→Review→Upgradeの順で検証する。起動は`scripts/real_acceptance.ps1 -StartAt sample2`とし、実行記録のパスは完了後に追記する。

Reviewの訳文はTranslateのDOCXをWordでPDF化したものを使う。Upgradeは英文v1に元PDF、英文v2に最終ページを削除したPDF、日本語v1に訳文PDFを指定し、差分処理も検証する。

| 文書 | Register | Translate | Review | Upgrade |
|---|---|---|---|---|
| sample | 成功 (`01a19c62-8e22-7122-8466-6223fc7bc637`) | 成功 (`01a19c64-60a7-7cc2-a9a4-f2b7234ff37b`) | 成功 (`01a19c6e-5408-7722-a481-343979864921`) | 成功 (`01a19c9d-067a-7e81-a505-931a0d770ea4`) |
| sample5 | 成功 (`01a19ca0-2f7f-7cd3-8ae1-8b1c0fbadc46`) | 成功 (`01a19cc6-99de-7441-9c48-f0bce42649cb`) | 成功 (`01a19cf1-bc56-7be0-8049-5b34d11b211a`) | 成功 (`01a19d2e-8f8a-79f2-9616-4a7d66f60b09`) |
| sample4 | 成功 (`01a19d75-7293-7281-a82a-53c5b5f69c70`) | 成功 (`01a19d7e-7d4e-7600-b001-4b4efd8b8979`) | 成功 (`01a19d9a-a44d-7d73-980e-61ede59e59bb`) | 成功 (`01a19de8-a4ba-7b80-8e27-37e629478037`) |
| sample3 | 成功 (`01a19ded-1c63-7382-a00f-9efa86f6b2bd`) | 成功 (`01a19df6-d813-7fa1-832d-0e89ea9ed911`) | 成功 (`01a19e1a-96b2-7f73-835e-6adaf2252131`) | 成功 (`01a19e38-0950-7641-9c93-077cc9e0d421`) |
| sample2 | 成功 (`01a19f9d-ef80-7c83-a096-3637c23f8bfc`) | 成功 (`01a19fc3-3534-7671-8bb0-baf717c4b0df`, 88ページ・859 units) | 成功 (`01a1a043-6246-76b0-9fcb-a743005bb887`) | 成功 (`01a1a144-3d5f-7a82-b3f7-44c7ccedbd79`) |
| sample1 | 成功 (`01a1a14a-2b3c-7961-980c-4bd975341274`) | 処理中 (`01a1a1fe-c9fa-77b0-bc92-5bc68e83de36`) | 実行待ち | 実行待ち |

sample2 Translateの内部REVIEWでは、2026-11-03 15:19に1対象が`Assessment references an unselected or unowned span`で5回のLLM試行後も失敗した。その後、処理は次の対象へ継続し、Translate全体が成功して成果物を作成した。

sample2 Reviewは2026-11-03 16:15に開始。18:13にEmbedding endpointのHTTP 500で一度失敗したが、20:06にUIから同じIDでResumeし、20:55に成功した。最終ログはLLM完了call 461件、応答検証拒否582件、決定的fallback32回。Review結果画面の確認後、sample2 Upgradeも成功した（`01a1a144-3d5f-7a82-b3f7-44c7ccedbd79`）。

sample1 Registerは11月3日21:02に開始し、11月4日00:19に成功した。PDFの36 partをDocling変換し、Embedding 1,037件・1024次元の登録まで完了。続くTranslateは00:19に開始し、03:48時点で処理中。LLM完了callは431件、応答検証拒否108件、失敗call 9件。Translate完了後にReview、Upgradeを順に実行する。

## ✅ 実装済みの修正

- Upgrade: 同一英文を`difflib`で事前照合し、LLMへ送らない
- LLM入力上限: LiteLLMの`/utils/token_counter`で判定し、未対応のendpointでは`LLM_INPUT_BYTES_PER_TOKEN`で換算する
- Embedding: 再試行をOpenAI SDKへ委譲する
- MERGE: `docling-core`の`concatenate`へ置換する（既存6文書のLOAD結果と本文が一致）
- 文分割: `pysbd`へ統一する
- OOXML: `python-docx`へ置換する
- JSON Schema: STRUCTUREとTRANSLATEをPydanticの生成へ統一する
- Docling: 断線を最大30分待機し、変換済みpartを再利用する。到達しないOffice対応と未公開の状態値を削除する
- LLM応答: HTTP 200の非JSONを応答不正として再試行する。Schema深度の検査で`$ref`を展開する
- 小規模な整理: `hashlib.file_digest`、用語集の正規表現、Pandoc ASTのキャッシュ、`python-dotenv`の削除、未使用コードとコメントアウトの削除、重複処理の共通化、Docstringの`Returns`修正

## ⏸️ 見送りと未対応

- LOADの`dict`処理は`docling-core`へ移していない。適用範囲はMERGEだけとした
- STRUCTUREとTRANSLATEのLLM Call保存処理は統一していない。分割と`partial`の扱いがREVIEW・DIFFと異なるため
- `.env.sample`へ`LLM_INPUT_BYTES_PER_TOKEN`を追記していない。権限でファイルを読めなかったため

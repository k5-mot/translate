<!-- markdownlint-disable MD013 MD041 -->

## 2026-09-25: 提案段階

状態は計画完了・実装未着手。`TRANSLATE-PROTECTED-OFF-001`は未解決で、tasksは0/9。既存の失敗記録は[OFF検証記録](../configure-verification-reasoning-policy/verification.md)を参照する。

- proposal/design/tasksを作成。既存要求の実装指示修正のため`skip_specs: true`でDeltaを作らない。
- OpenSpec statusはproposal/design/tasksがdone、specsがskipped。これは計画Artifactの充足で、実装・受入完了ではない。
- `openspec validate clarify-translation-placeholder-instructions --strict`: valid。
- `openspec validate configure-verification-reasoning-policy --strict`: valid。
- `uv run pytest tests/test_documentation.py -q`: 21 passed、0.30秒。
- `git diff --check`: 指摘なし。
- 既存configの未知operation `verify`警告は継続しており、今回の修正範囲外として変更しない。
- 製品Code・翻訳Rule・既存成果物は変更していない。モデル要求、Word操作、全製品suiteは今回未実行で、apply/verifyの未完了Taskに残す。
- 既存未コミット差分を保持し、新Changeの文書と元失敗記録への引継ぎリンクのみをcommit対象とする。`.agents`、サンプル、outputs/runs、秘密は含めない。

## 次の検証条件

配布ルール修正と自動Testの後、新しいルールhashでsample3のOFF翻訳を新規実行する。成功した同じDOCXをWordでPDF化し、原本とReviewする。本文内の保護値保持、利用者目視、既知ALIGN/表内画像問題を別々に判定し、未達条件がある間はarchive・main merge・pushを完了扱いにしない。

## 2026-09-25: 実装・自動検査

- 配布ルールへ4項目を追加した。製品Python・Dependency・retry/復元条件は変更していない。
- Test先行で配布指示10条件＋送信経路6条件が旧ルールに対して16 failed。ルール修正後は翻訳出力Test 42 passed、fingerprint/Workflowを含む関連60 passed。さらに別IDへ記号を移した応答の拒否Testを追加した。
- 配布ルールを実loaderで読み、通常/OFF、初回・欠落retry・逐次分割のsystem指示到達、IDごとの保護値復元、送信順と推論指定を検査した。Mock応答による検査は実LLMの成功証明ではない。
- 通常/OFFそれぞれのルール変更で公開Resumeが非互換となり、旧metadata不変、Workflowのルールhash/thread IDが異なることを、実GraphをSPLITで停止する外部通信なしのTestで確認した。
- 全体初回: **652 passed / 4 failed / 1 skipped、40.09秒**。テスト親にだけ`PYTHONUTF8=1`を与えた一方、既存CLI隔離Testは子環境へその値を渡さず、cp932のstderrを親がUTF-8で読みUnicodeDecodeErrorになった。4件とも出力読取り側の同じ失敗だった。
- 追加した環境指定を外し、既存CLI Testを変更せず再確認: **5 passed / 1 skipped、14.63秒**。同じ通常環境の全体再実行: **656 passed / 1 skipped、40.26秒**。初回失敗は上記に保持する。任意の親子文字コード混在への対応を今回実装したとは扱わない。
- `ruff check .`、`ruff format --check .`（340 files）、`ty check`、OpenSpec strict、`git diff --check`: 成功。
- 全体検査は既存未コミットのLLM/REVIEW/Lifecycle/terminal Evidenceの差分も含むworktreeを対象とする。それらを本Changeへ混ぜず保持する。今回のcommit対象はルール、既存Test 2 files、tasks/verificationのみ。
- tasks 1.1〜1.4を完了。2.1以降の実検証、利用者目視、正式verify、archive、merge/pushは未完了である。

新ルールSHA-256: `501f2e459290ea37b0f5bb70c09d166dc4ef1e3c422c5e410f46c70d44d45f81`。入力sample3 SHA-256: `5ccb472e2b072a83713814d13ceb303957b1a9b3dcb2740fe1bf55d95d79b34f`。09:51 JSTの確認時点で`outputs/sample3-acceptance-off-markers`は存在しない。旧失敗Runは保持している。

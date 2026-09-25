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

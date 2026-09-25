# Translation Rules

- 意味、条件、否定、比較、因果関係を省略せず、正確で自然な日本語へ翻訳する。
- 数値と単位を正確に伝え、明確なURLとファイル名はできるだけ原文の表記を維持する。
- 固有名詞と略語は文脈に合う自然な日本語表記を認める（例: U.S. → 米国）。
- 原文にない説明を追加しない。
- 入力JSONのtargetだけを翻訳する。previous_context、following_context、glossary、referencesは文脈・用語の参考情報であり、追加の翻訳対象ではない。
- targetのすべてのidに対応する空でない訳文をtranslationsへ返す。idは変更せず、別の対象の訳文と混ぜない。

# 📜 CONTRIBUTING_GUIDELINE

本書は、開発者が従う開発フローの基本規約を一意に定める文書である。

## 📝 Git コミット規則

コミットメッセージは、Conventional commitsをベースとした以下のルールに従うこと

- MUST; 日本語でメッセージを記述すること
- MUST; 修正の理由と内容をセットで記述すること
- MUST; 1コミットには1つの論理変更のみを含めること
- MUST; 変更目的に合う以下の type を使うこと
  - `🐛 fix:` バグ修正
  - `✨ feat:` 新機能
  - `📝 docs:` ドキュメント追加・更新
  - `🎨 style:` コード構造・フォーマット改善
  - `♻️ refactor:` リファクタリング
  - `⚡️ perf:` パフォーマンス改善
  - `✅ test:` テスト追加・更新
  - `📦️ build:` コンパイル済みファイル・パッケージの追加・更新
  - `👷 ci:` CIビルドシステムの追加・更新
  - `🔧 chore:` 設定ファイルなどの追加・更新
- SHOULD; `git-cz` の使用することを推奨する

```text
<gitmoji> <type>[optional scope][!]: <変更理由>のため、<変更内容>

<詳細な変更内容 (箇条書き)>
```

### コミットメッセージ例

```text
✨ feat(search): 商品を条件で絞り込めるようにするため、価格帯フィルターを追加

- 最低価格と最高価格の入力欄を追加
- 指定した価格帯を検索APIのクエリに反映
```

## 🌳 Git ブランチ戦略

ブランチ戦略は、GitHub Flowをベースとした以下のルールに従うこと

- MUST; 最新の`main`ブランチから各作業用ブランチ`feature/<作業内容>`を作成すること
- MUST; 作業用ブランチ`feature/<作業内容>`はPull RequestでCIを完了してから`main`へマージすること
- SHOULD; 作業用ブランチ`feature/<作業内容>`はPull Requestでレビューを完了してから`main`へマージすることを推奨する
- SHOULD; マージ後、作業用ブランチ`feature/<作業内容>`は削除を推奨する
- MUST; 作業用ブランチ`feature/<作業内容>`は、Pull Requestとマージ前に
  `git pull --rebase origin main`で Fast-Forward すること

## 🏷️ Git タグ命名規則

タグ命名規則は、Semantic Versioning 2.0.0 をベースとした以下のルールに従うこと

- MUST; `v<MAJOR>.<MINOR>.<PATCH>`形式のタグを付けること
- MUST; 対象の`main` CommitでGitHub Actionsの`quality` Jobが成功してから
  Maintainerが手動でタグを付与すること
- MUST NOT; CIから自動でRelease Tagを作成しないこと
- MUST NOT; 公開済みタグの移動、削除、上書きを禁止する
- MUST; バージョンのアップグレードは以下の基準に従うこと
  - `MAJOR` 後方互換性を壊す変更
  - `MINOR` 後方互換な機能追加
  - `PATCH` 後方互換な不具合修正

## 🔀 Pull Request規則

Pull Requestは、レビューとマージに必要な情報を明確にするため、以下のルールに従うこと

- MUST; Pull Requestの本文に変更理由、変更内容、動作確認内容を記述すること
- MUST; `main`ブランチへのマージ時はマージコミットを作成すること
- MUST; レビューで指摘された事項を解消してからマージすること
- SHOULD; 作業途中のPull RequestはDraftとして作成することを推奨する
- SHOULD; UI変更を含む場合はスクリーンショットまたはGIFを添付することを推奨する
- SHOULD; 関連Issueがある場合はPull Requestから参照することを推奨する

### Pull Request本文例

```markdown
## 変更理由

商品を価格帯で絞り込めるようにするため。

## 変更内容

- 最低価格と最高価格の入力欄を追加
- 指定した価格帯を検索条件に反映

## 動作確認

- 最低価格、最高価格それぞれの条件で正しく絞り込まれることを確認

スクリーンショットまたはGIFなど

## 関連Issue

- Closes #123
```

## 🔖 参考文献

- Git commit rules
  - [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
  - [gitmoji Specification](https://gitmoji.dev/specification)
  - [git-cz](https://github.com/streamich/git-cz)
- Git branch strategy
  - [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow)
- Git tagging convention
  - [Semantic Versioning 2.0.0](https://semver.org/)

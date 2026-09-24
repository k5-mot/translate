<!-- markdownlint-disable MD013 MD041 -->

## Why

common/identifiers.pyはUUIDv7の時刻・乱数・bit配置を独自実装しているが、既に導入済みのuuid-utilsに同等の生成APIがある。利用者要求③-2に従い再実装を廃止し、common内の不要な1 Moduleを減らす。

## What Changes

- Run作成元でuuid_utils.compat.uuid7を直接利用し、標準uuid.UUIDという戻り値型を保つ。
- uuid-utilsを間接依存から明示依存へ追加する。解決済み0.17.1を維持し、新しいPackageを導入しない。
- common/identifiers.pyを廃止し、Testも公開UUID契約へ依存させる。独自乱数bit配置へのmonkeypatchを要求しない。

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

なし。run-lifecycleのUUIDv7限定・時刻・canonical形式・不正ID拒否を変更しない純粋なRefactorとしてskip_specsを指定する。

## Impact

pyproject.toml、uv.lock、common/runs.py、廃止するidentifiers.pyと関連Test。公開CLI/UI、Run保存形式、既存UUIDv7データは変更しない。UUIDv4互換を追加しない。

## Stakeholders and Lifecycle Impact

保守者の独自生成器の維持責任を既存Packageへ戻す。取得/供給は既存versionを明示するだけで、運用手順や移行作業は増えない。廃止ModuleはGitで復元可能であり、Runや成果物は削除しない。

## Quality Considerations

Q-FUNC/Q-PORT: 標準UUID型、version7、RFC variant、canonical文字列、生成時刻、2,000件の衝突0をTestする。Q-MNT: 独自生成器とそのwrapperを0件にする。Q-COMP: CLI/UIの既存Run Testを通す。速度向上や新しいSecurity機能は目的にせず、既存依存の再利用に限定する。正式verifyには実translation→Word PDF→reviewを含める。

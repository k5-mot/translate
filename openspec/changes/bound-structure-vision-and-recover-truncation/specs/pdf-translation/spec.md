<!-- markdownlint-disable MD013 MD022 MD032 MD041 -->

## Purpose

利用者が読取り可能な英語PDFを、原文の構造、図表、保護対象および表紙を維持した検証済み日本語DOCXへ変換できるようにする。STRUCTUREの画像入力がlocal Modelの安全域を超えないこともこのCapabilityに含める。

## ADDED Requirements

### Requirement: STRUCTUREの画像入力を画素数上限内に収める
Systemは、STRUCTUREでvision Modelへ送る各page画像を1,000,000 pixels以下にし、縦横比とpage全域を維持しなければならない（MUST）。縮小後も読取り可能なpage構造を用いて補正し、画像入力を利用できない場合には既存のtext-only経路で完全なschema適合応答を得るか、成果物を公開せず失敗しなければならない（MUST）。Q-FUNCおよびQ-PERF（ISO/IEC 25010）として、上限超過画像の送信0件、cropping 0件、同時Model request最大1件を画像境界Testと実page probeで確認しなければならない（MUST）。

#### Scenario: 上限を超えるpageを処理する
- **WHEN** 元のSTRUCTURE page画像が1,000,000 pixelsを超える
- **THEN** Systemは縦横比とpage全域を保った1,000,000 pixels以下の画像だけをvision Modelへ渡す

#### Scenario: 上限内のpageを処理する
- **WHEN** 元のSTRUCTURE page画像が1,000,000 pixels以下である
- **THEN** Systemは不要な縮小やcroppingをせず、そのpageの構造補正を続ける

#### Scenario: 画像入力を使用できない
- **WHEN** 有界な画像でもvision処理が失敗する
- **THEN** Systemは切れたvision応答を採用せず、text-only経路で完全なschema適合応答を得た場合だけ構造補正を継続する

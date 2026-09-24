# 📚 template.docx スタイル一覧

[template.docx](template.docx) の `word/styles.xml` に明示定義された全 110 スタイルを記録しています。表示名は XML の値をそのまま記載しています。Word の言語設定により組み込みスタイルの表示名は異なる場合があります。

`paragraph` は段落、`character` は文字、`table` は表のスタイルです。継承元は style ID で、`—` は明示指定なしを表します。参照だけが存在する `TableNormal` は本テンプレート内の定義数に含めません。

| Style ID | 種別 | 表示名 | 継承元 |
| --- | --- | --- | --- |
| Normal | paragraph | Normal | — |
| BodyText | paragraph | Body Text | Normal |
| FirstParagraph | paragraph | First Paragraph | BodyText |
| Compact | paragraph | Compact | BodyText |
| Title | paragraph | Title | Normal |
| TitleChar | character | Title Char | DefaultParagraphFont |
| Subtitle | paragraph | Subtitle | Title |
| SubtitleChar | character | Subtitle Char | DefaultParagraphFont |
| Author | paragraph | Author | Title |
| Date | paragraph | Date | Title |
| AbstractTitle | paragraph | Abstract Title | Normal |
| Abstract | paragraph | Abstract | Normal |
| Bibliography | paragraph | Bibliography | Normal |
| Heading1 | paragraph | heading 1 | Normal |
| Heading2 | paragraph | heading 2 | Normal |
| Heading3 | paragraph | heading 3 | Normal |
| Heading4 | paragraph | heading 4 | Normal |
| Heading5 | paragraph | heading 5 | Normal |
| Heading6 | paragraph | heading 6 | Normal |
| Heading7 | paragraph | heading 7 | Normal |
| Heading8 | paragraph | heading 8 | Normal |
| Heading9 | paragraph | heading 9 | Normal |
| Heading1Char | character | Heading 1 Char | DefaultParagraphFont |
| Heading2Char | character | Heading 2 Char | DefaultParagraphFont |
| Heading3Char | character | Heading 3 Char | DefaultParagraphFont |
| Heading4Char | character | Heading 4 Char | DefaultParagraphFont |
| Heading5Char | character | Heading 5 Char | DefaultParagraphFont |
| Heading6Char | character | Heading 6 Char | DefaultParagraphFont |
| Heading7Char | character | Heading 7 Char | DefaultParagraphFont |
| Heading8Char | character | Heading 8 Char | DefaultParagraphFont |
| Heading9Char | character | Heading 9 Char | DefaultParagraphFont |
| BlockText | paragraph | Block Text | BodyText |
| FootnoteBlockText | paragraph | Footnote Block Text | FootnoteText |
| DefaultParagraphFont | character | Default Paragraph Font | — |
| Table | table | Table | TableNormal |
| DefinitionTerm | paragraph | Definition Term | Normal |
| Definition | paragraph | Definition | Normal |
| TableCaption | paragraph | 表タイトル | Caption |
| ImageCaption | paragraph | 図タイトル | Caption |
| BodyTextChar | character | Body Text Char | DefaultParagraphFont |
| SectionNumber | character | Section Number | BodyTextChar |
| KeywordTok | character | KeywordTok | VerbatimChar |
| DataTypeTok | character | DataTypeTok | VerbatimChar |
| DecValTok | character | DecValTok | VerbatimChar |
| BaseNTok | character | BaseNTok | VerbatimChar |
| FloatTok | character | FloatTok | VerbatimChar |
| ConstantTok | character | ConstantTok | VerbatimChar |
| CharTok | character | CharTok | VerbatimChar |
| SpecialCharTok | character | SpecialCharTok | VerbatimChar |
| StringTok | character | StringTok | VerbatimChar |
| VerbatimStringTok | character | VerbatimStringTok | VerbatimChar |
| SpecialStringTok | character | SpecialStringTok | VerbatimChar |
| ImportTok | character | ImportTok | VerbatimChar |
| CommentTok | character | CommentTok | VerbatimChar |
| DocumentationTok | character | DocumentationTok | VerbatimChar |
| AnnotationTok | character | AnnotationTok | VerbatimChar |
| CommentVarTok | character | CommentVarTok | VerbatimChar |
| OtherTok | character | OtherTok | VerbatimChar |
| FunctionTok | character | FunctionTok | VerbatimChar |
| VariableTok | character | VariableTok | VerbatimChar |
| ControlFlowTok | character | ControlFlowTok | VerbatimChar |
| OperatorTok | character | OperatorTok | VerbatimChar |
| BuiltInTok | character | BuiltInTok | VerbatimChar |
| ExtensionTok | character | ExtensionTok | VerbatimChar |
| PreprocessorTok | character | PreprocessorTok | VerbatimChar |
| AttributeTok | character | AttributeTok | VerbatimChar |
| RegionMarkerTok | character | RegionMarkerTok | VerbatimChar |
| InformationTok | character | InformationTok | VerbatimChar |
| WarningTok | character | WarningTok | VerbatimChar |
| AlertTok | character | AlertTok | VerbatimChar |
| ErrorTok | character | ErrorTok | VerbatimChar |
| NormalTok | character | NormalTok | VerbatimChar |
| SourceCode | paragraph | コードブロック | BodyText |
| VerbatimChar | character | Verbatim Char | DefaultParagraphFont |
| Caption | paragraph | Caption | Normal |
| Figure | paragraph | Figure | Normal |
| CaptionedFigure | paragraph | Captioned Figure | Figure |
| FootnoteText | paragraph | Footnote Text | Normal |
| FootnoteReference | character | Footnote Reference | DefaultParagraphFont |
| Hyperlink | character | Hyperlink | DefaultParagraphFont |
| TOC1 | paragraph | TOC 1 | Normal |
| TOC2 | paragraph | TOC 2 | Normal |
| TOC3 | paragraph | TOC 3 | Normal |
| TOC4 | paragraph | TOC 4 | Normal |
| TOC5 | paragraph | TOC 5 | Normal |
| TOC6 | paragraph | TOC 6 | Normal |
| TOCHeading | paragraph | TOC Heading | Normal |
| ListBullet | paragraph | List Bullet | BodyText |
| ListBullet2 | paragraph | List Bullet 2 | BodyText |
| ListBullet3 | paragraph | List Bullet 3 | BodyText |
| ListNumber | paragraph | List Number | BodyText |
| ListNumber2 | paragraph | List Number 2 | BodyText |
| ListNumber3 | paragraph | List Number 3 | BodyText |
| Equation | paragraph | Equation | Normal |
| Note | paragraph | Note / 注記 | BlockText |
| Warning | paragraph | Warning / 警告 | BlockText |
| Caution | paragraph | Caution / 注意 | BlockText |
| Header | paragraph | Header | Normal |
| Footer | paragraph | Footer | Normal |
| CodeCaption | paragraph | コードタイトル | Normal |
| AppendixLabel | paragraph | Appendix Label / 付録ラベル | Heading1 |
| AppendixHeading1 | paragraph | Appendix Heading 1 / 付録 章 | Heading1 |
| AppendixHeading2 | paragraph | Appendix Heading 2 / 付録 見出し2 | Heading2 |
| AppendixHeading3 | paragraph | Appendix Heading 3 / 付録 見出し3 | Heading3 |
| AppendixHeading4 | paragraph | Appendix Heading 4 / 付録 見出し4 | Heading4 |
| AppendixHeading5 | paragraph | Appendix Heading 5 / 付録 見出し5 | Heading5 |
| AppendixHeading6 | paragraph | Appendix Heading 6 / 付録 見出し6 | Heading6 |
| Tip | paragraph | Tip / ヒント | BlockText |
| Important | paragraph | Important / 重要 | BlockText |
| EquationBlock | paragraph | 数式ブロック | BodyText |

## 📝 出力時の扱い

`Heading1`～`Heading9` はテンプレート内に自動採番を持ちます。生成 DOCX では本文番号との重複を避けるため、その採番指定を除去し、見出し階層を保持します。テンプレート本体は変更しません。

目次の対象は `Heading1`～`Heading6`、図一覧は `ImageCaption`、表一覧は `TableCaption` です。各一覧の日本語見出しには `TOCHeading`、項目には `TOC1`～`TOC6` を使用します。一覧は生成時の静的な項目一覧で、ページ番号や Word による自動更新は含みません。

## 🔄 更新手順

テンプレート変更時は ZIP 内の `word/styles.xml` の全 `w:style` を確認し、`w:styleId`、`w:type`、`w:name/@w:val`、`w:basedOn/@w:val` とこの表を照合してください。Style ID の欠落・重複や表示名・継承元の差があれば、この文書を同時に更新します。

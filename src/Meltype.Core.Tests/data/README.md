# 報告された誤変換のコーパス

GitHub の `誤判定` Issue から、「打ったもの (キーをそのまま)」と「期待した結果」を取り出したものです
(`--expect` にそのまま渡せます)。

```bash
dotnet run --project src/Meltype.Core.Tests -c Release -- --expect src/Meltype.Core.Tests/data/issue-cases.tsv /tmp/issue.json
MELTYPE_READING=1 dotnet run --project src/Meltype.Core.Tests -c Release -- --expect src/Meltype.Core.Tests/data/issue-cases.tsv /tmp/issue-beta.json
```

- 打ったものが英数字・記号だけのもの
- 期待がかな・カタカナ・英字だけのもの (漢字を含む期待は、テストの変換器が Mozc を使わないため除いています)
- 同じ組は 1 回だけ

いまの結果: 74 件中 51 件 (既定) / 53 件 (β版)。β版で直るのは `printenv` と `mainnipushsuru` で、
β版で壊れるものはありません。残りは、カタカナの綴り (ウェットティッシュ など)・英単語の検出・
候補変換 (漢字) の話で、日英の区切りの話ではありません。

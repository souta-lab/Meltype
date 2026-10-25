// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 souta

using Meltype.Composition;

namespace Meltype.Tests;

/// <summary>
/// 日英の区切りを点数で決める β版 (<see cref="ReadingComparison"/>) のテスト。
/// 既定は OFF なので、テストの中だけで有効にして、OFF の結果を壊していないことも見る。
/// </summary>
internal static class ReadingComparisonTests
{
    /// <summary>環境変数 MELTYPE_READING=1 で β 版を強制しているか (そのときは「切ったとき」を作れない)。</summary>
    private static bool BetaForcedByEnvironment =>
        Environment.GetEnvironmentVariable("MELTYPE_READING") == "1";

    private static void WithBeta(bool enabled, Action action)
    {
        var previous = CompositionTests.Detector.UseReadingComparison;
        CompositionTests.Detector.UseReadingComparison = () => enabled;
        try
        {
            action();
        }
        finally
        {
            CompositionTests.Detector.UseReadingComparison = previous;
        }
    }

    [Test]
    public static void Beta_FixesWordsWhoseSplitCrossesAUnit()
    {
        // main|に は nn の途中で分かれるため、今までの決まりでは表せない (まいんいpushする)。
        // printenv は main の english-readable.txt で既定でも英字になったので、β版でも同じ。
        WithBeta(true, () =>
        {
            Assert.Equal("mainにpushする", Committed("mainnipushsuru"), "main に push する の区切り");
            Assert.Equal("printenv", Committed("printenv"), "english-readable にある語は英字のまま");
        });
    }

    [Test]
    public static void Beta_Off_KeepsTheExistingDecision()
    {
        // 環境変数で有効にしたままテストを流したときは、「切ったとき」を作れないので飛ばす
        if (BetaForcedByEnvironment) return;
        WithBeta(false, () =>
        {
            Assert.Equal("まいんいpushする", Committed("mainnipushsuru"), "β版を切れば今までどおり");
            Assert.Equal("printenv", Committed("printenv"), "english-readable にある語は既定でも英字");
        });
    }

    [Test]
    public static void ExplicitJapaneseLearning_IsNotOverridden()
    {
        // ユーザーが明示的に「日本語」と直した語 (main → まいん) は、点数でも英語にしない。
        var memory = new LanguageMemory(null);
        memory.Remember("main", english: false, explicitChoice: true);
        var previous = CompositionTests.Detector.Memory;
        CompositionTests.Detector.Memory = memory;
        try
        {
            WithBeta(true, () =>
            {
                var typed = Committed("mainnipushsuru");
                Assert.True(typed != "mainにpushする", "明示的に日本語と覚えた語を英語にしない: " + typed);
                Assert.True(typed.Contains("まいん", StringComparison.Ordinal), "日本語の読みのまま: " + typed);
            });
        }
        finally
        {
            CompositionTests.Detector.Memory = previous;
        }
    }

    [Test]
    public static void TogglingTheSetting_DoesNotReuseStaleSegments()
    {
        // 環境変数で有効にしたままテストを流したときは、OFF から始められないので飛ばす
        if (BetaForcedByEnvironment) return;
        // 同じ CompositionText のまま設定を切り替えたときに、前の区間の控えを返さない。
        var text = new CompositionText(CompositionTests.Detector);
        foreach (var c in "mainnipushsuru") text.Append(c);
        var before = string.Join("|", text.Segments(final: true).Select(s => (s.IsEnglish ? "EN:" : "JA:") + s.Raw));
        // テストの前の値に必ず戻す (共有の Detector を他のテストと取り合わない)
        var previous = CompositionTests.Detector.UseReadingComparison;
        try
        {
            CompositionTests.Detector.UseReadingComparison = () => true;
            var after = string.Join("|", text.Segments(final: true).Select(s => (s.IsEnglish ? "EN:" : "JA:") + s.Raw));
            Assert.True(before != after, "設定を変えたら区間を計算し直す: " + before + " / " + after);
            Assert.Equal("EN:main|JA:ni|EN:push|JA:suru", after);
        }
        finally
        {
            CompositionTests.Detector.UseReadingComparison = previous;
        }
    }

    /// <summary>アプリと同じ構成 (既定の検出器 + 同梱の英単語) で、β版の有無だけを変えて確定した文字列。</summary>
    private static string Render(string typed, bool beta)
    {
        var detector = CompositionDetector.CreateDefault();
        detector.SpellChecker = Detection.BuiltInWordChecker.Shared;
        detector.UseReadingComparison = () => beta;
        var text = new CompositionText(detector);
        foreach (var c in typed) text.Append(c);
        return text.RenderSegments(final: true, convert: null);
    }

    [Test]
    public static void Beta_AbsorbsShortKanaIntoAKnownWord()
    {
        // 環境変数で有効にしたままテストを流したときは、「切ったとき」を作れないので飛ばす
        if (BetaForcedByEnvironment) return;
        // 今までの決まりは、短いかなを英単語の一部として読めない (わたしので|limit)。
        // DP が で を delimit の de として取り込んだら採る。
        Assert.Equal("わたしのでlimitが", Render("watashinodelimitga", beta: false));
        Assert.Equal("わたしのdelimitが", Render("watashinodelimitga", beta: true));
    }

    [Test]
    public static void Beta_SplitsTrailingParticleToKana()
    {
        if (BetaForcedByEnvironment) return;
        // 英語のあとに続く助詞は、かなにする (destroyers|は)。
        Assert.Equal("きのうはdestroyersha", Render("kinouhadestroyersha", beta: false));
        Assert.Equal("きのうはdestroyersは", Render("kinouhadestroyersha", beta: true));
    }

    [Test]
    public static void Beta_LeavesCanonicalCasesAlone()
    {
        // 大文字の語 (Tokyo・Hello) と、固有名詞の混ざった語は変えない
        foreach (var input in new[] { "Tokyo", "Hello", "yabaiTshatuyasann" })
            Assert.Equal(Render(input, beta: false), Render(input, beta: true));
    }

    /// <summary>打って Enter で確定した文字列。</summary>
    private static string Committed(string keys)
    {
        var keyboard = new CompositionTests.Keyboard();
        keyboard.Type(keys + "\n");
        return keyboard.Host.Document;
    }
}

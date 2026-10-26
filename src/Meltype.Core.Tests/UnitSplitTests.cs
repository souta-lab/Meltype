// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 souta

using Meltype.Composition;
using Meltype.Input;
using static Meltype.Tests.CompositionTests;

namespace Meltype.Tests;

/// <summary>
/// 区間が単位 (1 かな) の途中で分かれるときのテスト (issue #838 の土台)。
/// medalsha は め|だ|l|しゃ の 4 単位になる。区間分けを差し替えて、単位 sha の途中で medals (英語) と は (日本語) に分けた区間を直接組み立て、
/// 表示・BackSpace・F6 / F10・候補選択が単位を壊さずに動くかを確かめる。
/// </summary>
internal static class UnitSplitTests
{
    /// <summary>単位 sha の s までを英語、ha (は) からを日本語にする区間分け。sha が無ければ普通に分ける。</summary>
    private static IReadOnlyList<CompositionSegment>? SplitSha(IReadOnlyList<CompositionUnit> units, string pending)
    {
        var at = units.ToList().FindIndex(u => u.Raw == "sha");
        if (at <= 0) return null;
        var rest = units.Skip(at + 1).ToList();
        return [
            new CompositionSegment(true, "", string.Concat(units.Take(at).Select(u => u.Raw)) + "s"),
            new CompositionSegment(false, "は" + string.Concat(rest.Select(u => u.Kana)), "ha" + string.Concat(rest.Select(u => u.Raw)) + pending),
        ];
    }

    private static CompositionDetector SplitDetector()
    {
        var detector = CompositionDetector.CreateDefault();
        detector.SegmentOverride = SplitSha;
        return detector;
    }

    private static CompositionText Typed(string typed)
    {
        var text = new CompositionText(SplitDetector());
        foreach (var c in typed) text.Append(c);
        return text;
    }

    [Test]
    public static void SplitUnit_IsBuiltInTheMiddleOfAUnit()
    {
        // 前提: sha は 1 つの単位 (しゃ) で、区間はその途中 (s|ha) で分かれている
        var text = Typed("medalsha");
        Assert.Equal("め|だ|l|しゃ", string.Join("|", text.Units.Select(u => u.Kana)));
        Assert.Equal("medals|ha", string.Join("|", text.Segments().Select(s => s.Raw)));
    }

    [Test]
    public static void SplitUnit_Display()
    {
        var text = Typed("medalsha");
        Assert.Equal("medalsは", text.Display(final: false), "変換ボックス");
        Assert.Equal("medalsは", text.Display(final: true), "確定");
        // 後ろに続けて打っても、分かれた単位の後ろの日本語につながる
        Assert.Equal("medalsはいい", Typed("medalshaii").Display(final: true));

        var k = new Keyboard(detector: SplitDetector());
        k.Type("medalsha");
        Assert.Equal("medalsは", k.Showing, "変換ボックス");
        k.Type("\n");
        Assert.Equal("medalsは", string.Concat(k.Host.Output), "Enter で確定");
    }

    [Test]
    public static void SplitUnit_BackspaceRemovesOnlyTheKanaOfTheLastSegment()
    {
        // BackSpace は は (ha) だけを消し、前の英語の区間に入っている s は残す (しゃ を丸ごと消して medal にしない)
        var text = Typed("medalsha");
        text.RemoveLast();
        Assert.Equal("medals", text.Raw);
        Assert.Equal("s", text.Pending, "s は入力途中の文字に戻る");
        text.RemoveLast();
        Assert.Equal("medal", text.Raw, "次の BackSpace で s を消す");

        // 分かれた単位の後ろに続くかなは、今までどおり 1 音ずつ消える
        var longer = Typed("medalshaii");
        longer.RemoveLast();
        Assert.Equal("medalshai", longer.Raw);
        longer.RemoveLast();
        longer.RemoveLast();
        Assert.Equal("medals", longer.Raw);

        // BackSpace の後は、medals と打ったときと同じ (s の見せ方は普通の判定が決める)
        var k = new Keyboard(detector: SplitDetector());
        k.Type("medalsha\b\n");
        var plain = new Keyboard(detector: SplitDetector());
        plain.Type("medals\n");
        Assert.Equal(string.Concat(plain.Host.Output), string.Concat(k.Host.Output), "BackSpace の後に Enter");
    }

    [Test]
    public static void SplitUnit_KanaAndRawOfEachSegment()
    {
        // 区間ごとのかな (F6 で使う) と打った英字 (F10・打ったままの英字の候補で使う) が、単位のかけらで分かれる
        var text = Typed("medalsha");
        Assert.Equal("めだls", text.KanaForSegment(0), "英語の区間のかな: しゃ を丸ごと入れない");
        Assert.Equal("は", text.KanaForSegment(1), "日本語の区間のかな");
        Assert.Equal("ha", text.RawForReading(1, 0, 1), "日本語の区間の打った英字");
        Assert.Equal("medals|ha", string.Join("|", text.RawForKanas(["めだls", "は"])), "文節の区切りを動かした後の打った英字");
    }

    [Test]
    public static void SplitUnit_FunctionKeysOnSelectedClause()
    {
        // F10 は選んだ日本語の文節 (は) だけを、その文節の打った英字 (ha) にする
        var k = new Keyboard(detector: SplitDetector()) { FunctionKeysAffectSelectedClause = true };
        k.Type("medalsha ");
        Assert.Equal("medals|は", string.Join("|", k.Host.View!.Clauses!));
        k.Press(VirtualKeys.Right);
        k.Press(VirtualKeys.F10);
        Assert.Equal("medals|ha", string.Join("|", k.Host.View!.Clauses!), "F10");
        k.Type("\n");
        Assert.Equal("medalsha", string.Concat(k.Host.Output), "s が 2 回入ったり消えたりしない");

        // F6 は選んだ英語の文節 (medals) だけを、その文節のかな (めだls) にする
        var f6 = new Keyboard(detector: SplitDetector()) { FunctionKeysAffectSelectedClause = true };
        f6.Type("medalsha ");
        f6.Press(VirtualKeys.F6);
        Assert.Equal("めだls|は", string.Join("|", f6.Host.View!.Clauses!), "F6");
    }

    [Test]
    public static void SplitUnit_CandidatesApplyToTheRightClause()
    {
        // 日本語の文節 (は) の候補に、その文節の打った英字 (ha) が出て、選ぶとその文節だけが変わる
        var k = new Keyboard(detector: SplitDetector());
        k.Type("medalsha ");
        k.Press(VirtualKeys.Right);
        var candidates = k.Host.View!.Candidates;
        Assert.True(candidates.Contains("ha"), $"打った英字の候補: {string.Join(",", candidates)}");
        Assert.True(!candidates.Contains("sha"), "前の文節の s を含めない");
        for (var i = 0; i < candidates.Count && k.Host.View!.Clauses![1] != "ha"; i++) k.Press(VirtualKeys.Space);
        Assert.Equal("medals|ha", string.Join("|", k.Host.View!.Clauses!), "選んだ候補は 2 つ目の文節に入る");
        k.Type("\n");
        Assert.Equal("medalsha", string.Concat(k.Host.Output));
    }
}

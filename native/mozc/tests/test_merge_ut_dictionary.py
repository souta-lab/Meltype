#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 souta
"""native/mozc/merge-ut-dictionary.py のテスト。

Mozc の代わりに、id.def と辞書だけを持つ小さな偽の Mozc を git で作り、そこで統合を試す。
本物の Mozc も辞書も要らない (fixtures/ の辞書はテストのために作ったもので、実際の Mozc-UT のデータではない)。

python3 native/mozc/tests/test_merge_ut_dictionary.py
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "merge-ut-dictionary.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "mozcdic-ut-sample.txt"

# 偽の Mozc の id.def に入れる品詞
POS_GENERAL = "名詞,一般,*,*,*,*,*"
POS_PROPER = "名詞,固有名詞,一般,*,*,*,*"
ID_GENERAL = 1851
ID_PROPER = 1849

BASE_LINE = "ああると\t1851\t1851\t7129\tアアルト\n"
BASE_LINE_LOW = "ほげ\t1851\t1851\t5000\tホゲ\n"


def load_module():
    spec = importlib.util.spec_from_file_location("merge_ut_dictionary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_ut = load_module()


def make_id_def(general_id=ID_GENERAL, proper_id=ID_PROPER, count=1900) -> str:
    lines = []
    for pos_id in range(count):
        if pos_id == general_id:
            lines.append(f"{pos_id} {POS_GENERAL}")
        elif pos_id == proper_id:
            lines.append(f"{pos_id} {POS_PROPER}")
        else:
            lines.append(f"{pos_id} 補助記号,一般,*,*,*,*,*")
    return "\n".join(lines) + "\n"


# テストは、その人の git の設定 (commit.gpgsign など) に左右されないようにする。
GIT_CONFIG = (
    "-c", "user.name=test",
    "-c", "user.email=test@example.com",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
)


def git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(root), *GIT_CONFIG, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} が失敗しました: {result.stderr}")
    return result


def run_script(mozc_src, *args):
    """統合スクリプトを動かす。コンソールの文字コードに関係なく日本語を読めるよう、子は UTF-8 にする。"""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--mozc-src", str(mozc_src), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=environment, check=False,
    )


class FakeMozc:
    """テスト用の Mozc。src/data/dictionary_oss に id.def と辞書だけを置く。"""

    def __init__(self, root: Path, lines=(BASE_LINE,), general_id=ID_GENERAL):
        self.root = root
        self.src = root / "src"
        self.directory = self.src / "data" / "dictionary_oss"
        self.directory.mkdir(parents=True)
        (self.directory / "id.def").write_text(
            make_id_def(general_id=general_id), encoding="utf-8")
        self.target = self.directory / "dictionary00.txt"
        self.write_target("".join(lines))
        for index in range(1, 10):
            (self.directory / f"dictionary{index:02d}.txt").write_text(
                "", encoding="utf-8")
        self.commit()

    def write_target(self, text: str) -> None:
        self.target.write_text(text, encoding="utf-8")

    def commit(self) -> None:
        git(self.root, "init", "-q", check=True)
        git(self.root, "add", "-A", check=True)
        git(self.root, "commit", "-q", "-m", "mozc", check=True)

    def target_lines(self) -> list[str]:
        return self.target.read_text(encoding="utf-8").splitlines()

    def target_sha(self) -> str:
        return hashlib.sha256(self.target.read_bytes()).hexdigest()


class MergeTestBase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.temp = Path(self._temp.name)
        self.mozc = FakeMozc(self.temp / "mozc")

    def write(self, name: str, content: str, encoding="utf-8") -> Path:
        path = self.temp / name
        path.write_text(content, encoding=encoding)
        return path

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return run_script(self.mozc.src, *args)

    def merge(self, dictionary: Path, *args: str) -> subprocess.CompletedProcess:
        return self.run_script("--dictionary", str(dictionary), *args)


class MergeTest(MergeTestBase):
    def test_adds_entries_that_are_not_in_mozc(self):
        result = self.merge(SAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.mozc.target_lines()
        self.assertEqual(len(lines), 1 + 4)  # 元の 1 行 + 重複を除いた 4 件
        self.assertIn("がんまかんすう\t1851\t1851\t7400\tガンマ関数", lines)

    def test_same_word_in_mozc_is_not_added_twice(self):
        # 「あるふぁべっと / アルファベット研究」を Mozc の辞書に置いておく
        self.mozc.write_target(BASE_LINE + "あるふぁべっと\t1851\t1851\t7000\tアルファベット研究\n")
        self.mozc.commit()
        result = self.merge(SAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.mozc.target_lines()), 2 + 3)

    def test_duplicate_in_ut_keeps_lowest_cost(self):
        result = self.merge(SAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        costs = [
            line.split("\t")[3] for line in self.mozc.target_lines()
            if line.endswith("\tアルファベット研究")
        ]
        self.assertEqual(costs, ["7300"])

    def test_output_is_sorted(self):
        result = self.merge(SAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        added = [line for line in self.mozc.target_lines()
                 if line != BASE_LINE.rstrip("\n")]
        self.assertEqual(len(added), 4)
        keys = [line.split("\t") for line in added]
        self.assertEqual(keys, sorted(keys))

    def test_merging_twice_does_not_duplicate(self):
        # 2 回目は、1 回目の記録 (--report) を前回の統合として渡す。ビルドスクリプトと同じ形。
        report = self.temp / "MOZC-UT.json"
        first = self.merge(SAMPLE, "--report", str(report))
        self.assertEqual(first.returncode, 0, first.stderr)
        after_first = self.mozc.target_sha()
        count_after_first = len(self.mozc.target_lines())

        second = self.merge(SAMPLE, "--report", str(report))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.mozc.target_sha(), after_first)
        self.assertEqual(len(self.mozc.target_lines()), count_after_first)
        # 2 回目は、前の統合を取り消してから統合したと出す
        self.assertIn("前の統合を取り消してから統合しました", second.stdout)

    def test_restore_undoes_merge(self):
        original = self.mozc.target_sha()
        report = self.temp / "MOZC-UT.json"
        self.assertEqual(self.merge(SAMPLE, "--report", str(report)).returncode, 0)
        self.assertNotEqual(self.mozc.target_sha(), original)

        restored = self.run_script("--restore", "--state", str(report))
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.mozc.target_sha(), original)
        self.assertIn("取り消しました", restored.stdout)

    def test_restore_does_not_touch_changes_made_outside_the_tool(self):
        # issue #961: MELTYPE_UT_DICTIONARY を指定していないのに、手元で書き換えた
        # dictionary00.txt を Mozc の git の状態に戻してしまう、という報告。
        # 統合の記録が無い辞書は、このツールが変えたものではないので触らない。
        self.mozc.write_target("".join([BASE_LINE, "じかせい\t1851\t1851\t5000\tジカセイ\n"]))
        before = self.mozc.target_sha()
        result = self.run_script("--restore")
        self.assertNotEqual(result.returncode, 0, "黙って戻してはいけない")
        self.assertEqual(self.mozc.target_sha(), before, "手元の辞書を消さない")
        self.assertIn("やめました", result.stderr)

    def test_restore_with_state_undoes_our_merge(self):
        # このツールの統合結果 (記録のハッシュと一致) なら、今までどおり戻せる。
        original = self.mozc.target_sha()
        report = self.temp / "MOZC-UT.json"
        self.assertEqual(self.merge(SAMPLE, "--report", str(report)).returncode, 0)
        restored = self.run_script("--restore", "--state", str(report))
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.mozc.target_sha(), original)
        self.assertIn("取り消しました", restored.stdout)

    def test_restore_refuses_when_edited_after_our_merge(self):
        # 統合したあとに手元で書き換えた辞書も消さない。
        report = self.temp / "MOZC-UT.json"
        self.assertEqual(self.merge(SAMPLE, "--report", str(report)).returncode, 0)
        self.mozc.write_target("".join(self.mozc.target_lines()) + "じかせい\t1851\t1851\t5000\tジカセイ\n")
        before = self.mozc.target_sha()
        result = self.run_script("--restore", "--state", str(report))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mozc.target_sha(), before)

    def test_restore_force_undoes_foreign_changes(self):
        self.mozc.write_target("".join([BASE_LINE, "じかせい\t1851\t1851\t5000\tジカセイ\n"]))
        result = self.run_script("--restore", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mozc.target_lines(), [BASE_LINE.strip()])

    def test_merge_refuses_to_append_to_foreign_changes(self):
        # 手元で書き換えた辞書に、黙って Mozc-UT を足さない (戻すときに消えてしまうため)。
        self.mozc.write_target("".join([BASE_LINE, "じかせい\t1851\t1851\t5000\tジカセイ\n"]))
        before = self.mozc.target_sha()
        result = self.merge(SAMPLE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("やめました", result.stderr)
        self.assertEqual(self.mozc.target_sha(), before)

    def test_restore_when_clean_does_nothing(self):
        result = self.run_script("--restore")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("統合する前の状態のままです", result.stdout)

    def test_check_does_not_write(self):
        original = self.mozc.target_sha()
        result = self.merge(SAMPLE, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mozc.target_sha(), original)
        self.assertIn("書き換えていません", result.stdout)

    def test_check_after_merge_compares_with_pristine_mozc(self):
        self.assertEqual(self.merge(SAMPLE).returncode, 0)
        result = self.merge(SAMPLE, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        # 統合済みでも、元の Mozc と比べるので「4 件」のままになる
        self.assertIn("統合: 4 件", result.stdout)

    def test_report_is_written(self):
        report_path = self.temp / "report.json"
        result = self.merge(SAMPLE, "--report", str(report_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["mode"], "merge")
        self.assertEqual(report["dictionary"]["sha256"],
                         hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
        self.assertEqual(report["mozc"]["pos_id"], ID_GENERAL)
        self.assertTrue(report["mozc"]["commit"])  # git の commit を記録する
        self.assertEqual(report["result"]["lines_added"], 4)
        self.assertEqual(report["removed"]["duplicate_in_ut"], 1)
        # 1 回目は取り消す前の統合が無い
        self.assertFalse(report["result"]["previous_merge_undone"])
        second = self.merge(SAMPLE, "--report", str(report_path))
        self.assertEqual(second.returncode, 0, second.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["result"]["previous_merge_undone"])


    def test_license_notice_is_recorded(self):
        report_path = self.temp / "report.json"
        result = self.merge(SAMPLE, "--report", str(report_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("同梱しません", result.stdout)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertFalse(report["license"]["bundled_with_meltype"])
        self.assertIn("alt-cannadic", report["license"]["notice"])
        # UT の辞書の出所ごとのライセンスを、レポートに残す
        self.assertEqual(set(report["license"]["sources"]),
                         {"place_names", "personal_names", "sudachidict", "jawiki",
                          "neologd", "edict2", "skk_jisyo", "alt_cannadic"})


    def test_staged_merge_is_restored_from_head(self):
        # 統合した辞書を git の index に載せてから、もう一度統合する。
        # index から戻すと統合済みの中身が戻って重複するので、HEAD から戻すことを確かめる。
        report = self.temp / "MOZC-UT.json"
        self.assertEqual(self.merge(SAMPLE, "--report", str(report)).returncode, 0)
        git(self.mozc.root, "add", "src/data/dictionary_oss/dictionary00.txt", check=True)
        result = self.merge(SAMPLE, "--report", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.mozc.target_lines()
        self.assertEqual(len(lines), 1 + 4)
        self.assertEqual(len(set(lines)), len(lines))

    def test_non_utf8_console_does_not_crash(self):
        # Windows のコンソール (cp1252 など) でも、日本語を出そうとして止まらないこと。
        environment = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        original = self.mozc.target_sha()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--mozc-src", str(self.mozc.src),
             "--dictionary", str(SAMPLE), "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=environment, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # cp1252 で表せない文字は \uXXXX の形になる
        self.assertIn("\\u", result.stdout)
        self.assertEqual(self.mozc.target_sha(), original)


class PosIdTest(MergeTestBase):
    def test_pos_id_of_another_mozc_version_is_remapped(self):
        # 辞書を作った Mozc では ID 1849 が「名詞,一般」だった (ビルドする Mozc では固有名詞)
        dictionary = self.write(
            "drifted.txt",
            "あるふぁべっと\t1849\t1849\t7600\tアルファベット研究\n",
        )
        result = self.merge(dictionary, "--report", str(self.temp / "report.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"1849 (名詞,固有名詞,一般,*,*,*,*) → {ID_GENERAL}", result.stdout)
        self.assertIn(
            f"あるふぁべっと\t{ID_GENERAL}\t{ID_GENERAL}\t7600\tアルファベット研究",
            self.mozc.target_lines(),
        )
        report = json.loads((self.temp / "report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["dictionary"]["pos_drift"])
        self.assertEqual(report["dictionary"]["pos_remap"],
                         {"1849": ID_GENERAL})

    def test_pos_id_not_in_id_def_is_remapped(self):
        dictionary = self.write(
            "unknown-id.txt",
            "あるふぁべっと\t60000\t60000\t7600\tアルファベット研究\n",
        )
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"あるふぁべっと\t{ID_GENERAL}\t{ID_GENERAL}\t7600\tアルファベット研究",
            self.mozc.target_lines(),
        )

    def test_multiple_known_pos_ids_are_kept(self):
        dictionary = self.write(
            "mixed.txt",
            f"あるふぁべっと\t{ID_PROPER}\t{ID_PROPER}\t7600\tアルファベット研究\n"
            f"べーたせいり\t{ID_GENERAL}\t{ID_GENERAL}\t7800\tベータ整理\n",
        )
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.mozc.target.read_text(encoding="utf-8")
        self.assertIn(f"あるふぁべっと\t{ID_PROPER}\t{ID_PROPER}\t7600\tアルファベット研究", target)
        self.assertIn(f"べーたせいり\t{ID_GENERAL}\t{ID_GENERAL}\t7800\tベータ整理", target)

    def test_keep_pos_ids_rejects_unknown_id(self):
        dictionary = self.write(
            "unknown-id.txt",
            "あるふぁべっと\t60000\t60000\t7600\tアルファベット研究\n",
        )
        result = self.merge(dictionary, "--keep-pos-ids")
        self.assertEqual(result.returncode, 2)
        self.assertIn("id.def にありません", result.stderr)

    def test_pos_option_selects_the_target_pos(self):
        dictionary = self.write(
            "drifted.txt",
            "あるふぁべっと\t1849\t1849\t7600\tアルファベット研究\n",
        )
        result = self.merge(dictionary, "--pos", POS_PROPER)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"あるふぁべっと\t{ID_PROPER}\t{ID_PROPER}\t7600\tアルファベット研究",
            self.mozc.target_lines(),
        )


class InvalidDictionaryTest(MergeTestBase):
    def assert_invalid(self, content: str, message: str) -> None:
        dictionary = self.write("invalid.txt", content)
        original = self.mozc.target_sha()
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.mozc.target_sha(), original)  # 壊さない

    def test_wrong_column_count(self):
        self.assert_invalid("あるふぁべっと\t1851\t1851\t7600\n", "5 列ではありません")

    def test_too_many_columns(self):
        self.assert_invalid(
            "あるふぁべっと\t1851\t1851\t7600\tアルファベット研究\tSPELLING_CORRECTION\n",
            "5 列ではありません",
        )

    def test_empty_column(self):
        self.assert_invalid("あるふぁべっと\t1851\t1851\t\tアルファベット研究\n", "空の列")

    def test_cost_is_not_a_number(self):
        self.assert_invalid("あるふぁべっと\t1851\t1851\tやすい\tアルファベット研究\n", "整数ではありません")

    def test_cost_out_of_range(self):
        self.assert_invalid("あるふぁべっと\t1851\t1851\t70000\tアルファベット研究\n", "範囲外")

    def test_id_out_of_range(self):
        self.assert_invalid("あるふぁべっと\t70000\t70000\t7600\tアルファベット研究\n", "範囲外")

    def test_not_utf8(self):
        dictionary = self.temp / "sjis.txt"
        dictionary.write_bytes("あるふぁべっと\t1851\t1851\t7600\tアルファベット研究\n".encode("cp932"))
        original = self.mozc.target_sha()
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 2)
        self.assertIn("UTF-8", result.stderr)
        self.assertEqual(self.mozc.target_sha(), original)

    def test_bom_is_rejected(self):
        dictionary = self.temp / "bom.txt"
        dictionary.write_bytes(
            b"\xef\xbb\xbf" + "あるふぁべっと\t1851\t1851\t7600\tアルファベット研究\n".encode()
        )
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 2)
        self.assertIn("BOM", result.stderr)

    def test_nul_byte_is_rejected(self):
        dictionary = self.temp / "nul.txt"
        dictionary.write_bytes(b"\x00" + "あるふぁべっと\t1851\t1851\t7600\tx\n".encode())
        result = self.merge(dictionary)
        self.assertEqual(result.returncode, 2)
        self.assertIn("NUL", result.stderr)

    def test_empty_file_is_rejected(self):
        self.assert_invalid("", "空です")

    def test_missing_file_is_reported(self):
        result = self.merge(self.temp / "no-such-file.txt")
        self.assertEqual(result.returncode, 1)
        self.assertIn("見つかりません", result.stderr)


class ReadingTest(MergeTestBase):
    def test_non_hiragana_reading_is_a_warning(self):
        dictionary = self.write(
            "katakana.txt",
            "アルファベット\t1851\t1851\t7600\tアルファベット研究\n",
        )
        result = self.merge(dictionary, "--report", str(self.temp / "report.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.temp / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("ひらがなではありません", report["warnings"][0])

    def test_strict_readings_makes_it_an_error(self):
        dictionary = self.write(
            "katakana.txt",
            "アルファベット\t1851\t1851\t7600\tアルファベット研究\n",
        )
        original = self.mozc.target_sha()
        result = self.merge(dictionary, "--strict-readings")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ひらがなではありません", result.stderr)
        self.assertEqual(self.mozc.target_sha(), original)


class EnvironmentTest(MergeTestBase):
    def test_not_a_git_repository_is_reported(self):
        plain = self.temp / "plain"
        directory = plain / "src" / "data" / "dictionary_oss"
        directory.mkdir(parents=True)
        (directory / "id.def").write_text(make_id_def(), encoding="utf-8")
        (directory / "dictionary00.txt").write_text(BASE_LINE, encoding="utf-8")
        result = run_script(plain / "src", "--dictionary", str(SAMPLE))
        self.assertEqual(result.returncode, 1)
        self.assertIn("git リポジトリ", result.stderr)

    def test_mozc_src_must_point_at_src(self):
        result = run_script(self.temp, "--dictionary", str(SAMPLE))
        self.assertEqual(result.returncode, 1)
        self.assertIn("dictionary_oss", result.stderr)

    def test_dictionary_cannot_be_the_target(self):
        result = self.merge(self.mozc.target)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Mozc の辞書そのもの", result.stderr)

    def test_restore_and_dictionary_are_exclusive(self):
        result = self.run_script("--restore", "--dictionary", str(SAMPLE))
        self.assertEqual(result.returncode, 1)
        self.assertIn("同時に指定できません", result.stderr)

    def test_neither_dictionary_nor_restore(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("--dictionary", result.stderr)


class ModuleTest(unittest.TestCase):
    def test_hiragana_pattern(self):
        self.assertTrue(merge_ut.HIRAGANA.match("あるふぁべっと"))
        self.assertTrue(merge_ut.HIRAGANA.match("がっこうー"))
        self.assertTrue(merge_ut.HIRAGANA.match("ゝゞ"))
        self.assertFalse(merge_ut.HIRAGANA.match("アルファベット"))
        self.assertFalse(merge_ut.HIRAGANA.match("がっこう!"))
        self.assertFalse(merge_ut.HIRAGANA.match(""))

    def test_duplicates_are_counted(self):
        entries = [
            merge_ut.Entry("よみ", 1, 1, 5000, "語", 1),
            merge_ut.Entry("よみ", 1, 1, 6000, "語", 2),
            merge_ut.Entry("よみ", 1, 1, 7000, "語", 3),
        ]
        kept, in_ut, in_mozc = merge_ut.remove_duplicates(entries, set())
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].cost, 5000)
        self.assertEqual(in_ut, 2)
        self.assertEqual(in_mozc, 0)


if __name__ == "__main__":
    unittest.main()

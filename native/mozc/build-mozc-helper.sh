#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Yukishiro
#
# Mozc の変換ヘルパー (meltype_mozc_helper) を Linux 用にビルドする (Windows 版は Build-MozcHelper.ps1)。
#   native/mozc/build-mozc-helper.sh [Mozc を置く場所 (既定: ~/mozc)] [Bazel のディスクキャッシュ]
# 必要なもの: git、Bazelisk (bazel、環境変数 BAZEL で場所を指定できる)、clang、Mozc の Linux のビルドに要るライブラリ (README.md)。
# Mozc-UT の辞書を扱うときは Python 3.10 以降 (PYTHON で場所を指定できる)。
# できたものは native/mozc/bin/linux/ に置く。
#
# Mozc-UT の辞書 (https://github.com/utuhiro78/merge-ut-dictionaries などで作る mozcdic-ut.txt) を
# 変換の候補に足す場合は、環境変数 MELTYPE_UT_DICTIONARY にそのファイルを指定する。
#   MELTYPE_UT_DICTIONARY=~/mozcdic-ut.txt native/mozc/build-mozc-helper.sh
# 指定しなければ、これまでどおり Mozc だけのヘルパーを作る。
# 辞書は Mozc の辞書に足すだけで、同梱も再配布もしない (ライセンスは README.md)。
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mozc="${1:-$HOME/mozc}"
cache="${2:-}"
commit="$(tr -d '[:space:]' < "$here/MOZC_COMMIT")"
out="$here/bin/linux"
ut_dictionary="${MELTYPE_UT_DICTIONARY:-}"
# Python は使う条件より前に決める (条件を変えたときに set -u で落ちないように)。
python="${PYTHON:-python3}"
# 前回の統合の記録 (前の版で統合したかを確かめるのにも使う)
previous="$out/MOZC-UT.json"

# src の有無ではなく .git で見る (GitHub Actions のキャッシュが src/third_party_cache だけを先に戻すため)。
if [[ ! -d "$mozc/.git" ]]; then
    mkdir -p "$mozc"
    git -C "$mozc" init -q
    git -C "$mozc" remote add origin https://github.com/google/mozc.git
    git -C "$mozc" fetch -q --depth 1 origin "$commit"
    git -C "$mozc" checkout -q FETCH_HEAD
    git -C "$mozc" submodule update -q --init --recursive --depth 1
fi
src="$mozc/src"

mkdir -p "$out"

# 前の版 (1.3.1-pre.1 まで) で Mozc-UT を統合した Mozc の辞書00 は、初回だけ元に戻す。
# この版からは Mozc の辞書00 を書き換えないので、古い語が残ると UT を指定しないビルドにも混ざる。
# 記録 (MOZC-UT.json) の中身とハッシュが一致するときだけ戻す (手元で書き換えた辞書は消さない)。
if [[ -e "$previous" ]]; then
    if ! command -v "$python" >/dev/null 2>&1; then
        echo "エラー: Python 3.10 以降が見つかりません ($python)。前の版の Mozc-UT の語を取り除くのに使います。" >&2
        echo "Mozc の辞書00 を自分で戻す場合は、git -C $mozc checkout HEAD -- src/data/dictionary_oss/dictionary00.txt を実行してください。" >&2
        exit 1
    fi
    if ! "$python" "$here/merge-ut-dictionary.py" --mozc-src "$src" --migrate --state "$previous"; then
        echo "エラー: 前の版で統合した Mozc-UT の語を、Mozc の辞書から取り除けませんでした。" >&2
        exit 1
    fi
fi

# Mozc-UT の語は Mozc の辞書とは別の dictionary_ut.txt に置き、ビルドのたびに作り直す
# (Mozc の辞書は書き換えないので、手元で書き換えた辞書も残る)。
# dictionary_ut.txt はいつもビルドに含め、MELTYPE_UT_DICTIONARY が無いときは空にする。
dictionary_build="$src/data/dictionary_oss/BUILD.bazel"
if ! grep -q '"dictionary_ut.txt"' "$dictionary_build"; then
    sed -i 's/^\( *\)"dictionary09\.txt",$/&\n\1"dictionary_ut.txt",/' "$dictionary_build"
    if ! grep -q '"dictionary_ut.txt"' "$dictionary_build"; then
        echo "エラー: $dictionary_build に dictionary_ut.txt を足せませんでした (Mozc の BUILD.bazel の形が変わった可能性があります)。" >&2
        exit 1
    fi
fi
: > "$src/data/dictionary_oss/dictionary_ut.txt"

# 統合した内容 (辞書と Mozc のハッシュ) は、ビルドが通ってから印 (MOZC-UT.json) にする。
# 途中で失敗したときに印だけ消すと、前のビルドのヘルパー (Mozc-UT 入りのことがある) が
# 標準のヘルパーに見えてしまうため、ビルドが終わるまでは書かない。
report=""
if [[ -n "$ut_dictionary" ]]; then
    python="${PYTHON:-python3}"
    if ! command -v "$python" >/dev/null 2>&1; then
        echo "エラー: Python 3.10 以降が見つかりません ($python)。Mozc-UT の辞書の統合に使います。" >&2
        exit 1
    fi
    report="$(mktemp)"
    if ! "$python" "$here/merge-ut-dictionary.py" --mozc-src "$src" \
        --dictionary "$ut_dictionary" --report "$report"; then
        rm -f "$report"
        exit 1
    fi
fi

# ヘルパーのソースと BUILD の定義を Mozc の converter パッケージに入れる (エンジンを使えるのがこのパッケージのため)。
cp "$here/meltype_mozc_helper.cc" "$src/converter/"
if ! grep -q 'name = "meltype_mozc_helper"' "$src/converter/BUILD.bazel"; then
    printf '\n%s\n' "$(cat "$here/BUILD.fragment")" >> "$src/converter/BUILD.bazel"
fi

cd "$src"
options=(build //converter:meltype_mozc_helper --config oss_linux --config release_build)
[[ -n "$cache" ]] && options+=("--disk_cache=$cache")
if ! "${BAZEL:-bazel}" "${options[@]}"; then
    # ビルドできなかったので、前のヘルパーとその印はそのまま残す。
    [[ -n "$report" ]] && rm -f "$report"
    exit 1
fi

cp -f bazel-bin/converter/meltype_mozc_helper "$out/"
# Bazel の出力は読み取り専用なので、上書きできるようにする。
chmod u+w,a+x "$out/meltype_mozc_helper"
# ヘルパーを置いたので、このヘルパーに合わせて印を入れ替える (最後に印を動かす)。
rm -f "$out/MOZC-UT.json"
[[ -n "$report" ]] && mv -f "$report" "$out/MOZC-UT.json"
cp -f data/installer/credits_en.html "$out/MOZC-CREDITS.html"
cp -f "$mozc/LICENSE" "$out/MOZC-LICENSE.txt"
echo "作成しました: $out/meltype_mozc_helper"
if [[ -n "$ut_dictionary" ]]; then
    echo "このヘルパーには Mozc-UT の辞書が入っています ($out/MOZC-UT.json)。"
    echo "再配布するときは、辞書ごとのライセンスに従ってください (native/mozc/README.md)。"
else
    echo "Mozc-UT の辞書は入っていません (MELTYPE_UT_DICTIONARY を指定すると入ります)。"
fi

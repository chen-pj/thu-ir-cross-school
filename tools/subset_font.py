#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 Noto Sans TC（思源黑體）取出頁面用得到的字，產生 src/fonts/noto-sans-tc.woff。

網頁不連外部資源，所以字型嵌入頁面；整套中文字型太大，只保留用得到的字。
資料或頁面文字更新後，build.py 若提醒「字型缺字」，就重新執行本程式並 commit 產出的檔案。

用法：
  python tools/subset_font.py                         # 預設讀 Windows 內建的 C:\\Windows\\Fonts\\NotoSansTC-VF.ttf
  python tools/subset_font.py --font 路徑/NotoSansTC-VF.ttf

字型授權：SIL Open Font License 1.1，可修改、取子集後隨網頁散布；子集保留字型內的版權與授權欄位。
需要 fonttools（pip install fonttools）。
"""
import argparse
import json
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "src", "fonts", "noto-sans-tc.woff")
CHARS = os.path.join(ROOT, "src", "fonts", "noto-sans-tc.chars.txt")
DEFAULT_FONT = r"C:\Windows\Fonts\NotoSansTC-VF.ttf"

# 一定要有的字：英數、常用標點、全形標點、箭頭與數學符號
BASE = ("".join(chr(c) for c in range(0x20, 0x7F))
        + "，。、；：？！「」『』（）《》〈〉【】…—–～·・／％＋－＝＜＞←→↑↓›‹＊＃＆｜　"
        + "０１２３４５６７８９")


def page_chars():
    """頁面範本與資料裡出現的所有字。"""
    text = BASE
    for p in ("src/index.html", "data/dashboard.json", "data/notes.json"):
        with open(os.path.join(ROOT, p), encoding="utf-8") as f:
            raw = f.read()
        text += json.dumps(json.loads(raw), ensure_ascii=False) if p.endswith(".json") else raw
    return sorted({c for c in text if c >= " " and c != "\x7f"})


def main():
    ap = argparse.ArgumentParser(description="產生頁面用的 Noto Sans TC 子集")
    ap.add_argument("--font", default=DEFAULT_FONT, help="Noto Sans TC 字型檔（可變字重 VF 版）")
    a = ap.parse_args()
    if not os.path.exists(a.font):
        sys.exit("[找不到字型] %s\n  請從 https://fonts.google.com/noto/specimen/Noto+Sans+TC 取得後用 --font 指定" % a.font)

    chars = page_chars()
    font = TTFont(a.font)
    cmap = font.getBestCmap()
    missing = [c for c in chars if ord(c) not in cmap and not c.isspace()]

    opt = subset.Options()
    opt.flavor = "woff"
    opt.name_IDs = ["*"]          # 保留版權、授權欄位（OFL 要求）
    opt.name_languages = ["*"]
    opt.layout_features = ["*"]
    opt.notdef_outline = True
    sub = subset.Subsetter(opt)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    font.save(OUT)

    covered = "".join(c for c in chars if ord(c) in cmap or c.isspace())
    with open(CHARS, "w", encoding="utf-8", newline="\n") as f:
        f.write(covered)
    print("子集：%d 字，%.0f KB → %s" % (len(covered), os.path.getsize(OUT) / 1024, os.path.relpath(OUT, ROOT)))
    if missing:
        print("[提醒] 字型本身沒有這些字（會用系統字型顯示）：%s" % "".join(missing))


if __name__ == "__main__":
    main()

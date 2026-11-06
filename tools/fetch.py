#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下載教育部「大學校院校務資訊公開平台」報表 CSV 到 data/raw/<年>/，並寫下載紀錄.csv。

只下載 tools/config.py 的 REPORTS（18 份）與 RESEARCH_REPORTS（研究類 3 份），共 21 份；其他一律不下載。
只用標準函式庫，可用 python -I 執行。

用法：
  python tools/fetch.py --folder 115                 # 下載到 data/raw/<今年西元>/
  python tools/fetch.py --folder 115 --year 2027
  python tools/fetch.py --folder 115 --only 學12-3   # 只下載指定報表（可重複）
  python tools/fetch.py --folder 115 --force         # 該年資料夾已有下載紀錄時，覆寫重抓

--folder 是平台網址 .../static_file/<編號>/ 的資料夾編號，每年要到平台確認（去年為 114）。
檔名須與平台完全一致；平台更名時，下載會出現 HTTP 404，請修改 config.py 的 name。

下載紀錄.csv 的欄位與原始流程相同；compute.py 從中讀取每份報表的下載日與平台資料夾編號。
"""
import argparse
import csv
import datetime
import hashlib
import os
import runpy
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
cfg = runpy.run_path(os.path.join(HERE, "config.py"))

HEADER = ["報表代號", "檔名", "網址", "網址(編碼)", "下載時間", "檔案大小(位元組)", "HEAD大小(位元組)", "大小核對", "SHA256"]
RECORD = "下載紀錄.csv"


def download(url, dest):
    """下載到 .part 再改名；回傳（位元組數、HEAD 大小或 None、SHA256）。"""
    head_size = None
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
        if r.headers.get("Content-Length"):
            head_size = int(r.headers["Content-Length"])
    sha, n = hashlib.sha256(), 0
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            sha.update(b)
            n += len(b)
    os.replace(tmp, dest)
    return n, head_size, sha.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--folder", required=True, help="平台資料夾編號（網址 .../static_file/<編號>/），例如 115")
    ap.add_argument("--year", default=str(datetime.date.today().year), help="下載年（西元），存到 data/raw/<年>/；預設今年")
    ap.add_argument("--only", action="append", default=[], help="只下載指定報表代號（例：學12-3），可重複")
    ap.add_argument("--force", action="store_true", help="已有下載紀錄時仍重新下載並覆寫")
    a = ap.parse_args()

    reports = cfg["REPORTS"] + cfg["RESEARCH_REPORTS"]
    keys = [r["key"] for r in reports]
    unknown = [k for k in a.only if k not in keys]
    if unknown:
        raise SystemExit("[錯誤] 不在核准清單的報表：%s；可用：%s" % ("、".join(unknown), "、".join(keys)))
    todo = [r for r in reports if not a.only or r["key"] in a.only]

    raw_dir = os.path.join(ROOT, "data", "raw", a.year)
    rec_path = os.path.join(raw_dir, RECORD)
    old = {}
    if os.path.exists(rec_path):
        with open(rec_path, encoding="utf-8-sig", newline="") as f:
            old = {r["報表代號"]: r for r in csv.DictReader(f)}
    redo = [r["key"] for r in todo if r["key"] in old]
    if redo and not a.force:
        raise SystemExit("[停止] %s 已有下載紀錄：%s。要重新下載請加 --force，或改用新的 --year。"
                         % (os.path.relpath(rec_path, ROOT), "、".join(redo)))
    os.makedirs(raw_dir, exist_ok=True)

    base = cfg["BASE_URL_FMT"] % a.folder
    rows, bad = {}, []
    for rp in todo:
        fname = rp["name"] + ".csv"
        url = base + urllib.parse.quote(fname)
        t0 = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            n, head_size, sha = download(url, os.path.join(raw_dir, fname))
        except urllib.error.HTTPError as e:
            raise SystemExit("[下載失敗] %s：HTTP %d（檔名或資料夾編號 %s 可能不對）\n  %s"
                             % (rp["key"], e.code, a.folder, base + fname))
        ok = head_size is not None and n == head_size
        if not ok:
            bad.append(rp["key"])
        rows[rp["key"]] = [rp["key"], fname, base + fname, url, t0, n,
                           head_size if head_size is not None else "", "一致" if ok else "不一致", sha]
        print("%-7s %10d 位元組  %s" % (rp["key"], n, "OK" if ok else "大小不一致或無 HEAD 大小"), flush=True)

    # 紀錄依核准清單順序；這次沒下載的報表保留舊紀錄
    merged = []
    for k in keys:
        if k in rows:
            merged.append(rows[k])
        elif k in old:
            merged.append([old[k].get(h, "") for h in HEADER])
    with open(rec_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(merged)
    print("總大小 %.2f MB；紀錄：%s" % (sum(r[5] for r in rows.values()) / 1048576, os.path.relpath(rec_path, ROOT)))
    missing = [k for k in keys if k not in rows and k not in old]
    if missing:
        print("[提醒] 這個資料夾還沒有下載：%s" % "、".join(missing))
    if bad:
        print("[錯誤] 大小核對不一致：%s；請重新下載（加 --force --only <代號>）" % "、".join(bad))
        sys.exit(1)


if __name__ == "__main__":
    main()

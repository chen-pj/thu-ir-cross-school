#!/usr/bin/env python3
"""把 data/ 的資料注入 src/index.html，輸出 dist/index.html（GitHub Pages 用）。

交付檔處理：
- 區塊內部編號（B01…B17）換成依顯示順序的中性代號（m1…m17），不寫入交付檔。
- 只保留頁面用得到的欄位；口徑摘要、學校代碼、序列編號等留在 data/，不進交付檔。
- 文字只改「交互參照內部編號」的一處，口徑與數字不動。
- 建置時逐值比對：交付檔中每個數值都必須與 data/ 原始值相同，否則中止。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "index.html"
DATA = ROOT / "data" / "dashboard.json"
NOTES = ROOT / "data" / "notes.json"
OUT = ROOT / "dist" / "index.html"

# 頁面實際讀取的欄位
TOP_KEYS = ["資料來源", "資料更新日期", "本校", "學年度清單", "各學年度母體", "區塊"]
BLOCK_KEYS = ["區塊編號", "指標", "單位", "方向說明", "學制選項", "預設學制",
              "資料最新年度", "時間單位", "年度清單", "來源報表", "序列"]
SERIES_KEYS = ["學制", "序列標題", "年度資料"]
YEAR_KEYS = ["學年度", "狀態", "本校名次", "本校數值", "母體校數", "本校第1名",
             "比較學校", "並列學校數", "備註", "卡片"]
CMP_KEYS = ["學校名稱", "數值", "同分"]
CARD_KEYS = ["學年度", "主文字", "比較學校名稱", "比較標籤", "差距"]

# 只換掉指向內部編號的交互參照文字（不影響口徑）
TEXT_FIX = {
    "見合併區塊 B14 與資料檔": "見「學生參與競賽、論文出版」卡片",
}

INTERNAL_ID = re.compile(r"(?<![A-Za-z0-9])B\d{2}(?:-\d+)?(?![0-9])")


def pick(d, keys):
    return {k: d[k] for k in keys if k in d}


def fix_text(s):
    for a, b in TEXT_FIX.items():
        s = s.replace(a, b)
    return s


def main():
    D = json.loads(DATA.read_text(encoding="utf8"))
    N = json.loads(NOTES.read_text(encoding="utf8"))

    # 依總覽分組的顯示順序給中性代號；不在分組裡的接在後面
    order = [bid for g in N["_groups"] for bid in g[1]]
    order += [b["區塊編號"] for b in D["區塊"] if b["區塊編號"] not in order]
    idmap = {bid: f"m{i + 1}" for i, bid in enumerate(order)}

    out = pick(D, TOP_KEYS)
    out["本校"] = {"學校名稱": D["本校"]["學校名稱"]}
    blocks = []
    for b in D["區塊"]:
        nb = pick(b, BLOCK_KEYS)
        nb["區塊編號"] = idmap[b["區塊編號"]]
        nb["序列"] = []
        for s in b["序列"]:
            ns = pick(s, SERIES_KEYS)
            ns["年度資料"] = []
            for r in s["年度資料"]:
                nr = pick(r, YEAR_KEYS)
                if "比較學校" in nr:
                    nr["比較學校"] = [pick(c, CMP_KEYS) for c in nr["比較學校"]]
                if "卡片" in nr:
                    nr["卡片"] = pick(nr["卡片"], CARD_KEYS)
                ns["年度資料"].append(nr)
            nb["序列"].append(ns)
        blocks.append(nb)
    out["區塊"] = blocks

    notes = {"_src": N["_src"],
             "_groups": [[g[0], [idmap[x] for x in g[1]]] + g[2:] for g in N["_groups"]]}
    for bid, v in N.items():
        if bid.startswith("_"):
            continue
        nv = dict(v)
        nv["base"] = fix_text(nv.get("base", ""))
        nv["extra"] = [fix_text(x) for x in nv.get("extra", [])]
        if nv.get("cond"):
            nv["cond"] = dict(nv["cond"], text=fix_text(nv["cond"]["text"]))
        notes[idmap[bid]] = nv

    verify(D, out, idmap)

    data_s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    notes_s = json.dumps(notes, ensure_ascii=False, separators=(",", ":"))
    for name, s in (("data", data_s), ("notes", notes_s)):
        if "</" in s:
            sys.exit(f"{name} 含有 '</'，不能直接嵌入 <script>")
    html = SRC.read_text(encoding="utf8")
    for ph in ("__DATA__", "__NOTES__"):
        if html.count(ph) != 1:
            sys.exit(f"範本中 {ph} 應恰好出現一次")
    html = html.replace("__DATA__", data_s).replace("__NOTES__", notes_s)

    leaks = sorted(set(INTERNAL_ID.findall(html)))
    if leaks:
        sys.exit(f"交付檔仍含內部編號：{leaks}")
    if re.search(r"<script[^>]+src=|https?://(?!udb\.moe\.edu\.tw)", html):
        sys.exit("交付檔含外部資源請求")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf8")
    print(f"OK  {OUT.relative_to(ROOT)}  {len(html.encode('utf8')):,} bytes  {len(blocks)} 區塊")


def verify(D, out, idmap):
    """交付檔裡的每一個欄位值都必須與原始資料相同（鍵名改代號除外）。"""
    src = {idmap[b["區塊編號"]]: b for b in D["區塊"]}
    n = 0

    def same(a, b, path):
        nonlocal n
        if isinstance(b, dict):
            for k in b:
                same(a[k], b[k], f"{path}.{k}")
        elif isinstance(b, list):
            if len(a) != len(b):
                sys.exit(f"長度不符：{path}")
            for i, (x, y) in enumerate(zip(a, b)):
                same(x, y, f"{path}[{i}]")
        else:
            if type(a) is not type(b) or a != b:
                sys.exit(f"數值不符：{path}  原始={a!r}  交付={b!r}")
            n += 1

    for k in ("資料來源", "資料更新日期", "學年度清單", "各學年度母體"):
        same(D[k], out[k], k)
    for nb in out["區塊"]:
        ob = dict(src[nb["區塊編號"]], 區塊編號=nb["區塊編號"])
        same(ob, nb, nb["區塊編號"])
    print(f"驗證通過：{n:,} 個值與 data/ 原始資料一致")


if __name__ == "__main__":
    main()

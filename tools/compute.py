#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依口徑把 data/raw/<年>/ 的平台報表算成 data/dashboard.json。

整理自原始流程 scripts/02_clean.py（清理）、03_indicators.py（母體、取值、排名）、
04_build_dashboard_data.py（JSON 與口徑摘要）；計算方式與輸出格式不變，只保留產生 dashboard.json 需要的部分
（不產生 parquet、xlsx、定義對照表與稽核檔）。

用法：
  python tools/compute.py                          # 用 data/raw/ 下最新的年資料夾，執行日＝今天
  python tools/compute.py --raw data/raw/2026 --date 20261029
  python tools/compute.py --check                  # 只比對：算出的結果與現有 data/dashboard.json 是否完全相同，不寫檔
  python tools/compute.py --out other.json         # 輸出到其他位置

--date 是「資料更新日期」（YYYYMMDD），會寫入 JSON 並顯示在頁面上。
需要 pandas、numpy（不能加 -I）。

內建檢查（任一不通過就中止，不寫檔）：
- CSV 讀到的列數與 csv 模組一致；數值欄只能是數字或缺值字串；欄名前綴須唯一對上一欄。
- 東海每年都在排名母體。
- 追溯：比較結果的本校與前 1～3 名數值、名次都能在完整排名找到；名次可由數值重算。
- 東海數值直接回查原始 CSV（不經清理流程）一致。
系所報表驗算（校層級與系所加總逐校比對）只印出不一致校數，不中止；不為 0 時請人工查明。
"""
import argparse
import csv
import datetime
import json
import os
import re
import runpy
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
cfg = runpy.run_path(os.path.join(HERE, "config.py"))

REPORTS = cfg["REPORTS"]
RESEARCH_REPORTS = cfg["RESEARCH_REPORTS"]
BLOCKS = cfg["BLOCKS"]
BLK = {b["id"]: b for b in BLOCKS}
START_YEAR = cfg["START_YEAR"]
THU_CODE = cfg["THU_CODE"]
NORM = cfg["norm"]
MISSING = cfg["MISSING_TOKENS"]

UNIVERSE_PRIMARY = "學12-3"
NO_DATA = "無資料"
RECORD = "下載紀錄.csv"


# ================================================================ 清理（原 02_clean.py）
def find_col(columns, prefix, report):
    exact = [c for c in columns if NORM(c) == NORM(prefix)]
    if len(exact) == 1:          # 欄名完全相同時優先
        return exact[0]
    p = NORM(prefix)
    hit = [c for c in columns if NORM(c).startswith(p)]
    if len(hit) != 1:
        raise SystemExit("[欄位錯誤] %s：前綴「%s」對上 %d 欄：%s" % (report, prefix, len(hit), hit))
    return hit[0]


def degree_group(deg):
    for g, vals in cfg["DEGREE_GROUPS"].items():
        if deg in vals:
            return g
    return "全校" if deg == "全校" else "其他"


def clean_one(rp, raw_dir):
    path = os.path.join(raw_dir, rp["name"] + ".csv")
    if not os.path.exists(path):
        raise SystemExit("[找不到原始檔] %s\n  請先執行 tools/fetch.py" % path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], encoding="utf-8-sig")
    with open(path, encoding="utf-8-sig", newline="") as f:
        raw_n = sum(1 for _ in csv.reader(f)) - 1
    if len(df) != raw_n:
        raise SystemExit("%s：pandas 讀到 %d 列，csv 模組 %d 列" % (rp["key"], len(df), raw_n))
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    out = pd.DataFrame(index=df.index)
    out["報表"] = rp["key"]
    is_res = rp.get("time_unit") == "年度"      # 研究類：時間欄是「年度」，轉成內部通用年度鍵（欄名仍為「學年度」）
    common = cfg["RESEARCH_COMMON_COLS"] if is_res else cfg["COMMON_COLS"]
    for new, old in common.items():
        if old not in df.columns:
            raise SystemExit("[欄位錯誤] %s 缺少欄位 %s" % (rp["key"], old))
        out[new] = df[old]
    bad_year = ~out["學年度"].str.fullmatch(r"\d{3}")
    if bad_year.any():
        raise SystemExit("%s：年度格式異常 %s" % (rp["key"], out.loc[bad_year, "學年度"].unique()[:5]))
    out["學年度"] = out["學年度"].astype(int)
    out["學校簡稱"] = out["學校名稱"].str.split("學校財團法人").str[-1]   # 去掉「xx學校財團法人」前綴
    out["是否一般大學"] = out["學校類別"] == cfg["GENERAL_UNIV_TYPE"]

    if rp["degree_col"] is None:
        out["學制"] = "全校"
    else:
        dc = find_col(df.columns, rp["degree_col"], rp["key"])
        if rp["key"] == "學12-2":
            ds = find_col(df.columns, "日間/進修", rp["key"])
            keys = list(zip(df[dc], df[ds]))
            out["學制"] = [cfg["STD_DEGREE_12_2"].get(k, "%s(%s)" % k) for k in keys]
        else:
            out["學制"] = df[dc]
    out["學制群組"] = out["學制"].map(degree_group)

    for role, prefix in rp["cols"].items():
        src = find_col(df.columns, prefix, rp["key"])
        s = df[src]
        is_miss = s.isin(MISSING)
        num = pd.to_numeric(s.where(~is_miss), errors="coerce")
        bad = (~is_miss) & num.isna()
        if bad.any():
            raise SystemExit("%s 欄「%s」出現非數字且非缺值字串：%s" % (rp["key"], src, s[bad].unique()[:5]))
        out[role] = num

    yrs = sorted(out["學年度"].unique())
    if START_YEAR not in yrs:
        raise SystemExit("%s 沒有 %d %s資料" % (rp["key"], START_YEAR, rp.get("time_unit", "學年度")))
    print("%-7s %6d 列  %s %d~%d" % (rp["key"], raw_n, rp.get("time_unit", "學年度"), yrs[0], yrs[-1]))
    out["代碼"] = out["學校代碼"].map(lambda c: cfg["CODE_MAP"].get(c, c))
    return out


# ================================================================ 母體、取值、排名（原 03_indicators.py）
def build_universe(data, years):
    """每個（代碼, 學年度）的學校類別、設立別、名稱；一般大學＝類別為「一般大學」。"""
    parts = pd.concat([d[d["學年度"].isin(years)][["報表", "學年度", "代碼", "學校代碼", "學校簡稱", "設立別", "學校類別"]]
                       for d in data.values()], ignore_index=True).drop_duplicates()
    rows = []
    for (code, yr), g in parts.groupby(["代碼", "學年度"], sort=True):
        p = g[g["報表"] == UNIVERSE_PRIMARY]
        src = p if len(p) else g
        rows.append(dict(代碼=code, 學年度=int(yr),
                         類別=src["學校類別"].mode().iloc[0], 設立別=src["設立別"].mode().iloc[0],
                         名稱=src["學校簡稱"].mode().iloc[0]))
    u = pd.DataFrame(rows)
    u["一般大學"] = u["類別"] == cfg["GENERAL_UNIV_TYPE"]
    return u


def clean_num(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    x = float(x)
    return int(round(x)) if abs(x - round(x)) < 1e-9 else round(x, 4)


def degrees_of(label):
    return cfg["DEGREE_SETS"].get(label, [label])


def school_values(d, cols, agg, label, years):
    """每校每年數值 DataFrame[代碼, 學年度, 值, 列數]。"""
    d = d[d["學年度"].isin(years)]
    if label is not None:
        d = d[d["學制"].isin(degrees_of(label))]
    d = d.copy()
    d["_v"] = d[cols].sum(axis=1, min_count=1)
    if agg == "single":
        dup = d.duplicated(["代碼", "學年度"], keep=False)
        if dup.any():
            raise SystemExit("[錯誤] single 取值卻有重複列：%s" % d.loc[dup, ["學年度", "代碼", "學制"]].head().to_dict("records"))
    return d.groupby(["代碼", "學年度"]).agg(值=("_v", lambda s: s.sum(min_count=1)), 列數=("_v", "size")).reset_index()


def fmt_amount(x, unit):
    """整數加千分位；百分點固定兩位小數；其他非整數最多 4 位小數。"""
    x = round(float(x), 6)
    if unit == "%":
        return "{:,.2f}".format(x)
    if abs(x - round(x)) < 1e-9:
        return "{:,d}".format(int(round(x)))
    return "{:,.4f}".format(x).rstrip("0").rstrip(".")


def fmt_gap_text(gap, ref, unit):
    u = "百分點" if unit == "%" else unit
    if gap is None:
        return ""
    if abs(gap) < 1e-9:
        return "與%s相同" % ref
    return "較%s%s %s %s" % (ref, "多" if gap > 0 else "少", fmt_amount(abs(gap), unit), u)


def rank_and_compare(vals, direction, unit):
    """vals：DataFrame[代碼, 名稱, 值]（已排除缺值）。回傳（vals 加名次、比較資訊 dict）。"""
    v = vals.copy().reset_index(drop=True)
    sgn = 1.0 if direction == "高" else -1.0
    v["_s"] = (v["值"] * sgn).round(6)
    s = v["_s"].values
    v["名次"] = 1 + (s[None, :] > s[:, None]).sum(axis=1)
    thu = v[v["代碼"] == THU_CODE]
    info = dict(狀態="有資料", 母體校數=len(v))
    if thu.empty:
        info["狀態"] = "本校無資料"
        return v, info
    t = thu.iloc[0]
    others = v[v["代碼"] != THU_CODE]
    front = others[others["_s"] > t["_s"]]
    tied = others[others["_s"] == t["_s"]]
    info.update(本校名次=int(t["名次"]), 本校數值=float(t["值"]), 並列學校=list(tied["名稱"]), 並列代碼=list(tied["代碼"]))
    if len(front) > 0:
        cand, ctype, ref = front, "名次在本校前面", "前1名"
    else:
        cand, ctype, ref = others[others["_s"] < t["_s"]], "名次在本校後面（本校為第1名）", "後1名"
    cand = cand.assign(_d=(cand["_s"] - t["_s"]).abs()).sort_values(["_d", "名稱", "代碼"])
    picked = cand.head(cfg["N_COMPARE"])
    comp = []
    for i, (_, r) in enumerate(picked.iterrows(), start=1):
        same = int(((cand["_s"] == r["_s"]) & (cand["代碼"] != r["代碼"])).sum())
        comp.append(dict(順位=i, 學校代碼=r["代碼"], 學校名稱=r["名稱"], 名次=int(r["名次"]), 數值=float(r["值"]),
                         同分=same > 0, 同分校數=same))
    info.update(比較類型=ctype, 本校第1名=(len(front) == 0), 比較學校=comp)
    if comp:
        gap = round(float(t["值"]) - comp[0]["數值"], 6)
        info["與前一名差距"] = gap
        info["差距說明"] = fmt_gap_text(gap, ref, unit)
    notes = []
    if len(front) == 0:
        notes.append("本校為第 1 名；列出名次在本校後面、最接近的學校，差距＝本校－後1名")
    if len(tied):
        notes.append("與本校並列：%s" % ("、".join(tied["名稱"]) if len(tied) <= 5 else "%d 所" % len(tied)))
    tie_slots = [c for c in comp if c["同分"]]
    if tie_slots:
        notes.append("%s同分（與其他學校數值相同，依學校名稱排序）" % "、".join(
            ("前%d名" if len(front) > 0 else "後%d名") % c["順位"] for c in tie_slots))
    if 0 < len(front) < cfg["N_COMPARE"]:
        notes.append("名次在本校前面的學校只有 %d 所" % len(front))
    if len(front) == 0 and len(comp) < cfg["N_COMPARE"]:
        notes.append("名次在本校後面的學校只有 %d 所" % len(comp))
    info["備註"] = "；".join(notes)
    return v, info


def run(raw_dir):
    data, rdata = {}, {}
    for rp in REPORTS + RESEARCH_REPORTS:
        (rdata if rp.get("time_unit") == "年度" else data)[rp["key"]] = clean_one(rp, raw_dir)
    alld = dict(data, **rdata)      # 研究類（時間單位＝年度）不進入全案母體
    max_year = max(int(d["學年度"].max()) for d in data.values()) if cfg["YEAR_LAST"] is None else cfg["YEAR_LAST"]
    YEARS = list(range(START_YEAR, max_year + 1))
    uni = build_universe(data, YEARS)
    gen = uni[uni["一般大學"]]
    gen_n = gen.groupby("學年度").size().to_dict()
    if (gen["代碼"] == THU_CODE).sum() != len(YEARS):
        raise SystemExit("[錯誤] 東海不是每年都在母體")

    # 研究類區塊：母體用該報表本身的學校類別欄逐年判定；年度只到該報表最新年度
    block_gen, block_years, block_latest = {}, {}, {}
    for b in BLOCKS:
        d0 = alld[b["report"]]
        latest0 = int(d0[d0["學年度"] >= START_YEAR]["學年度"].max())
        block_latest[b["id"]] = latest0
        block_years[b["id"]] = [y for y in YEARS if y <= latest0] if b["time_unit"] == "年度" else YEARS
        if b["universe"] == "self":
            us = build_universe({b["report"]: d0}, block_years[b["id"]])
            block_gen[b["id"]] = us[us["一般大學"]]
        else:
            block_gen[b["id"]] = gen

    long_rows, comp_rows = [], []
    for b in BLOCKS:
        d = alld[b["report"]]
        latest = block_latest[b["id"]]
        gen_b = block_gen[b["id"]]
        YEARS_B = block_years[b["id"]]
        for si, label in enumerate(b["series"], start=1):
            sid = "%s-%d" % (b["id"], si)
            sv = school_values(d, b["cols"], b["agg"], label, YEARS_B)
            for y in YEARS_B:
                base = dict(區塊編號=b["id"], 指標=b["name"], 序列編號=sid, 學制=label, 學年度=y)
                gy = gen_b[gen_b["學年度"] == y]
                vy = sv[sv["學年度"] == y].merge(gy[["代碼", "名稱", "設立別"]], on="代碼", how="inner")
                has_val = vy[vy["值"].notna()]
                if len(has_val) == 0:
                    comp_rows.append(dict(base, 狀態=NO_DATA, 母體校數=0,
                                          備註="該報表尚無 %d 學年度資料" % y if y > latest else "該年度無資料"))
                    continue
                v, info = rank_and_compare(has_val[["代碼", "名稱", "值"]], b["direction"], b["unit"])
                if info["狀態"] == "本校無資料":
                    thu_rows = d[(d["學年度"] == y) & (d["代碼"] == THU_CODE)]
                    if thu_rows.empty:
                        why = "%s 沒有東海該年度的資料列，不參與排名" % b["report"]
                    elif THU_CODE in set(vy.loc[vy["值"].isna(), "代碼"]):
                        why = "東海在 %s 該年度「%s」的數值為缺值（不補 0），不參與排名" % (b["report"], label)
                    else:
                        why = "東海在 %s 沒有「%s」學制的資料列（學校未設此學制、該年度沒有此項人次或未填報），不參與排名" % (b["report"], label)
                    info["備註"] = why
                for _, r in v.iterrows():
                    long_rows.append(dict(學校代碼=r["代碼"], 學年度=y, 區塊編號=b["id"], 序列編號=sid,
                                          數值=clean_num(r["值"]), 名次=int(r["名次"])))
                comp_rows.append(dict(base, **info))

    long = pd.DataFrame(long_rows)
    if long.duplicated(["學校代碼", "學年度", "序列編號"]).any():
        raise SystemExit("[錯誤] 完整排名有重複（同校同年度同序列兩列）；檢查 CODE_MAP")
    comp = pd.DataFrame(comp_rows)
    for b in BLOCKS:
        for si in range(1, len(b["series"]) + 1):
            got = sorted(comp.loc[comp["序列編號"] == "%s-%d" % (b["id"], si), "學年度"])
            if got != block_years[b["id"]]:
                raise SystemExit("[錯誤] %s-%d 缺少年度：%s" % (b["id"], si, got))
    return dict(YEARS=YEARS, gen=gen, gen_n=gen_n, long=long, comp=comp, data=data,
                block_gen=block_gen, block_years=block_years, block_latest=block_latest)


# ================================================================ 檢查（原 03 post_checks、04 trace_check 的相關部分）
def trace_check(R):
    comp, long = R["comp"], R["long"]
    idx = long.set_index(["序列編號", "學年度", "學校代碼"])
    n, bad = 0, []
    for _, r in comp[comp["狀態"] == "有資料"].iterrows():
        items = [(THU_CODE, r["本校數值"], r["本校名次"])] + [(c["學校代碼"], c["數值"], c["名次"]) for c in r["比較學校"]]
        for code, val, rk in items:
            n += 1
            try:
                x = idx.loc[(r["序列編號"], int(r["學年度"]), code)]
                if abs(float(x["數值"]) - float(val)) > 1e-6 or int(x["名次"]) != int(rk):
                    bad.append((r["序列編號"], int(r["學年度"]), code))
            except KeyError:
                bad.append((r["序列編號"], int(r["學年度"]), code))
    rk_bad = 0
    for (sid, y), g in long.groupby(["序列編號", "學年度"]):
        d = BLK[g["區塊編號"].iloc[0]]["direction"]
        s = (g["數值"] * (1 if d == "高" else -1)).round(6).values
        rk_bad += int(((1 + (s[None, :] > s[:, None]).sum(axis=1)) != g["名次"].values).sum())
    if bad or rk_bad:
        raise SystemExit("[追溯檢查失敗] 不符 %d 筆（例：%s）；名次重算不符 %d 筆" % (len(bad), bad[:5], rk_bad))
    print("追溯檢查：%d 筆，不符 0；名次重算不符 0" % n)


def raw_check_thu(R, raw_dir):
    """東海數值直接讀原始 CSV 回查（不經 clean_one）。"""
    long = R["long"]
    rpmap = {r["key"]: r for r in REPORTS + RESEARCH_REPORTS}
    cache, n, bad = {}, 0, []

    def _find(cols, prefix):
        p = NORM(prefix)
        ex = [c for c in cols if NORM(c) == p]
        if len(ex) == 1:
            return ex[0]
        hit = [c for c in cols if NORM(c).startswith(p)]
        if len(hit) != 1:
            raise SystemExit("原始 CSV 欄位對不上：%s -> %s" % (prefix, hit))
        return hit[0]

    for b in BLOCKS:
        rp = rpmap[b["report"]]
        if b["report"] not in cache:
            with open(os.path.join(raw_dir, rp["name"] + ".csv"), encoding="utf-8-sig", newline="") as f:
                cache[b["report"]] = list(csv.DictReader(f))
        recs = cache[b["report"]]
        cols = list(recs[0].keys())
        c_year = _find(cols, "年度" if rp.get("time_unit") == "年度" else "學年度")
        c_code = _find(cols, "學校統計處代碼")
        c_deg = _find(cols, rp["degree_col"]) if rp["degree_col"] else None
        c_day = _find(cols, "日間/進修") if b["report"] == "學12-2" else None
        vcols = [_find(cols, rp["cols"][c]) for c in b["cols"]]
        for si, label in enumerate(b["series"], start=1):
            sid = "%s-%d" % (b["id"], si)
            degs = set(degrees_of(label))
            lg = long[(long["序列編號"] == sid) & (long["學校代碼"] == THU_CODE)]
            for y in sorted(lg["學年度"].unique()):
                tot = None
                for r in recs:
                    if r[c_year] != str(y) or r[c_code] != THU_CODE:
                        continue
                    deg = r[c_deg] if c_deg else "全校"
                    if c_day:
                        deg = cfg["STD_DEGREE_12_2"].get((deg, r[c_day]), "%s(%s)" % (deg, r[c_day]))
                    if deg not in degs:
                        continue
                    for vc in vcols:
                        s = r[vc].strip()
                        if s in MISSING:
                            continue
                        tot = (tot or 0) + float(s)
                lv = lg[lg["學年度"] == y]["數值"].iloc[0]
                n += 1
                if tot is None or abs(tot - lv) >= 1e-9:
                    bad.append((sid, int(y), clean_num(tot), lv))
    if bad:
        raise SystemExit("[東海數值與原始 CSV 不一致] %d 筆（例：%s）" % (len(bad), bad[:5]))
    print("東海原始 CSV 回查：%d 筆，全部一致" % n)


def cross_check(R):
    """校層級報表與系所報表加總逐校驗算；只印不一致校數，不中止。"""
    data, gen, YEARS = R["data"], R["gen"], R["YEARS"]
    total, worst = 0, []
    for b in BLOCKS:
        if not b["check"]:
            continue
        for si, label in enumerate(b["series"], start=1):
            a = school_values(data[b["report"]], b["cols"], b["agg"], label, YEARS)
            s = school_values(data[b["check"]], b["cols"], "sum", label, YEARS)
            m = a.merge(s, on=["代碼", "學年度"], how="outer", suffixes=("_校", "_系所"))
            m = m.merge(gen[["代碼", "學年度"]], on=["代碼", "學年度"], how="inner")
            k = int(((m["值_校"].fillna(0) - m["值_系所"].fillna(0)).abs() > 1e-9).sum())
            total += k
            if k:
                worst.append("%s-%d（%s，%d 校）" % (b["id"], si, label, k))
    print("系所報表驗算不一致：%d 校次%s" % (total, "：" + "、".join(worst) if worst else ""))
    if total:
        print("[提醒] 驗算不一致不會中止，但交付前須逐筆查明原因")


# ================================================================ JSON（原 04_build_dashboard_data.py）
_CODE_RE = re.compile(r"（D\d+(?:[、～]D?\d+)*）")


def strip_codes(t):
    """拿掉內部決策編號（例：（D17、D22））。"""
    return _CODE_RE.sub("", t) if isinstance(t, str) else t


def download_info(raw_dir):
    """從下載紀錄.csv 讀每份報表的下載日與平台資料夾編號。"""
    p = os.path.join(raw_dir, RECORD)
    if not os.path.exists(p):
        raise SystemExit("[找不到下載紀錄] %s；請用 tools/fetch.py 下載" % p)
    res_keys = {r["key"] for r in RESEARCH_REPORTS}
    dates, folders = {}, set()
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            dates[r["報表代號"]] = r["下載時間"][:10]
            m = re.search(r"/static_file/([^/]+)/", r["網址"])
            if m:
                folders.add(m.group(1))
    need = [r["key"] for r in REPORTS + RESEARCH_REPORTS if r["key"] not in dates]
    if need:
        raise SystemExit("[下載紀錄缺報表] %s" % "、".join(need))
    if len(folders) != 1:
        raise SystemExit("[下載紀錄] 平台資料夾編號不唯一：%s" % sorted(folders))
    main = sorted({d for k, d in dates.items() if k not in res_keys})
    res = sorted({d for k, d in dates.items() if k in res_keys})
    txt = "、".join(main)
    if res and res != main:
        txt += "（研究類 %s）" % "、".join(res)
    return dates, txt, folders.pop()


def sanitize(o, key=None):
    """NaN／numpy 型別轉成 JSON 可用的值（「備註」缺值轉空字串）。"""
    if isinstance(o, dict):
        return {k: sanitize(v, k) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v, key) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if o is None or o is pd.NaT:
        return "" if key == "備註" else None
    if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
        return "" if key == "備註" else None
    return o


def _range_text(ys):
    ys = sorted(ys)
    return "%d～%d" % (ys[0], ys[-1]) if len(ys) > 1 else str(ys[0])


def _name_of(R, code):
    """某原始學校代碼在資料中最常見的簡稱。"""
    s = pd.concat([d.loc[d["學校代碼"] == code, "學校簡稱"] for d in R["data"].values()])
    return s.mode().iloc[0] if len(s) else code


def build_summary_lines(R):
    """口徑摘要。年度、校數、區塊數、學校名稱都由設定與資料產生，不寫死。"""
    YEARS, last = R["YEARS"], R["YEARS"][-1]
    n_blocks, n_series = len(BLOCKS), sum(len(b["series"]) for b in BLOCKS)
    parts = []
    for code, nm in cfg["NAMED_PARTIAL_YEAR_SCHOOLS"].items():
        ys = sorted(R["gen"].loc[R["gen"]["代碼"] == code, "學年度"])
        if ys:
            parts.append("%s（%s）" % (nm, _range_text(ys)))
    partial = "；%s在有資料的年度納入（D1、D21）" % "、".join(parts) if parts else "（D1、D21）"
    maps = ["%s(%s)與%s(%s)視為同一所學校，統一用 %s" % (_name_of(R, old), old, _name_of(R, new), new, new)
            for old, new in cfg["CODE_MAP"].items()]
    code_line = "學校代碼：%s，名稱用當年度名稱；同年度兩個代碼只算一所（D20）。" % "；".join(maps) if maps else "學校代碼：無需合併的更名換代碼個案。"
    short = {}
    for b in BLOCKS:
        if b["time_unit"] == "年度":
            continue
        lv = R["block_latest"][b["id"]]
        if lv < last:
            short.setdefault(lv, []).append(b["name"])
    if short:
        # 合併區塊（學生參與競賽、論文出版）與兩個單項同組時只列單項
        for y in short:
            v = list(dict.fromkeys(short[y]))
            if "學生參與競賽" in v and "論文出版" in v and "學生參與競賽、論文出版" in v:
                v.remove("學生參與競賽、論文出版")
            short[y] = v
        seg = "；".join("%s只到 %d 學年度" % ("、".join(v), y) for y, v in sorted(short.items()))
        nd = "、".join(str(y) for y in range(min(short) + 1, last + 1))
        year_line = "年度：%d 學年度起至各報表最新年度；%s，%s 學年度標「無資料」，不補值（D6、D19）。" % (START_YEAR, seg, nd)
    else:
        year_line = "年度：%d～%d 學年度；各區塊最新年度相同（D6、D19）。" % (START_YEAR, last)
    rb = [b for b in BLOCKS if b["time_unit"] == "年度"]
    research_line = ("研究類區塊（%s）：時間單位為「年度」，不是學年度（平台每年 3 月統計前一年度資料），年度範圍 %s；金額單位為元；"
                     "母體為各報表本身標示為「一般大學」的學校，逐年判定（部分學校沒有填報，母體校數因年度與報表而不同）；越高越好。" % (
                         "、".join(b["id"] for b in rb), "、".join("%s %s" % (b["id"], _range_text(R["block_years"][b["id"]])) for b in rb))) if rb else "研究類區塊：無。"
    return [
        "排名母體：每個學年度、學校類別為「一般大學」的學校（公立＋私立；不含技專校院、宗教研修學院），逐年依平台報表判定" + partial + "。",
        "比較方式：每個區塊、每個學制、每個學年度各自排名（共 %d 區塊、%d 個排名序列）；取名次在本校前面、數值最接近本校的 3 所，最接近者為前 1 名；比較學校會隨指標、學制、年度改變（D1）。" % (n_blocks, n_series),
        "名次：數值越高越好者由大到小排；休學、退學人數由小到大排；同分給相同名次（1、2、2、4）；與本校同分者算並列，不算排在前面（D10）。",
        "前面學校之間同分：依學校名稱排序（Unicode 順序）並標示「同分」（D10、D31）。",
        "本校為第 1 名：標示「本校為第 1 名」，改列名次在本校後面、最接近的學校（D1）。",
        "與前1名差距＝本校數值－前 1 名數值；休學、退學越低越好，差距為正代表人數較前 1 名多；本校為第 1 名時為本校－後 1 名（D12）。",
        "數值用平台報表原始數值，不換算比率；缺值學校不參與該年度排名，不補 0（D4）。學校未設某學制（例如沒有博士班）時，不參與該學制排名。",
        "學制：全部學制＝學士＋碩士＋博士，不含二專、五專、七年一貫、附設進專/進院、學士後第二專長學士班；學士＝學士班(日間)＋學士班(進修)；碩士＝碩士班(日間)＋碩士在職專班。學3-x 只有日間學制，標示為「全部學制・日間」（D17、D22）。",
        "學制標記以全校層級報表為準；系所報表只用來驗算（D23）。僑生及港澳生、陸生、外國學生用學3-7（校層級）計算，並與學3-3、學3-4、學3-2 的系所加總逐校驗算。",
        code_line,
        "單位：實習、出國進修交流、雙聯為「人次」（兩學期或多類型加總，同一人可能重複計算）；論文出版、競賽為「人次」；註冊率、就學穩定率為 %，平台以 100% 為上限（D14～D16）。",
        "學16 就學穩定率照報表學年度呈現，數值是前一學年度新生的就學穩定率（D18）。",
        year_line,
        research_line,
        "限制：人數類指標受學校規模影響；排名與前 1～3 名只描述數字位置，不代表表現優劣或因果；全校結果不推論到個別學系。",
    ]


def build_json(R, run_date, dl_dates, dl_text, folder):
    comp, YEARS = R["comp"], R["YEARS"]
    blocks = []
    for b in BLOCKS:
        latest = R["block_latest"][b["id"]]
        sers = []
        for si, label in enumerate(b["series"], start=1):
            sid = "%s-%d" % (b["id"], si)
            years_data, line = [], []
            for _, r in comp[comp["序列編號"] == sid].sort_values("學年度").iterrows():
                y = int(r["學年度"])
                if r["狀態"] != "有資料":
                    years_data.append(dict(學年度=y, 狀態=r["狀態"], 備註=r["備註"]))
                    continue
                cs = [dict(順位=c["順位"], 學校代碼=c["學校代碼"], 學校名稱=c["學校名稱"], 名次=c["名次"],
                           數值=clean_num(c["數值"]), 同分=bool(c["同分"])) for c in r["比較學校"]]
                first = bool(r["本校第1名"])
                gap = clean_num(r["與前一名差距"]) if pd.notna(r.get("與前一名差距", np.nan)) else None
                card = dict(學年度=y,
                            主文字="本校為第 1 名" if first else (cs[0]["學校名稱"] if cs else ""),
                            比較學校名稱=cs[0]["學校名稱"] if cs else "",
                            比較標籤="後1名" if first else "前1名",
                            差距=gap, 差距說明=r.get("差距說明", ""))
                years_data.append(dict(
                    學年度=y, 狀態="有資料", 本校名次=int(r["本校名次"]), 本校數值=clean_num(r["本校數值"]),
                    母體校數=int(r["母體校數"]), 本校第1名=first, 比較類型=r["比較類型"], 比較學校=cs,
                    與前1名差距=gap, 差距說明=r.get("差距說明", ""), 並列學校數=len(r["並列學校"]),
                    並列學校=list(r["並列學校"]), 備註=r["備註"], 卡片=card))
                line.append(dict(學年度=y, 本校數值=clean_num(r["本校數值"]),
                                 比較學校數值=clean_num(cs[0]["數值"]) if cs else None,
                                 比較學校名稱=cs[0]["學校名稱"] if cs else "", 比較標籤="後1名" if first else "前1名"))
            sers.append(dict(序列編號=sid, 學制=label, 序列標題="%s(%s)" % (b["base"], label),
                             年度資料=years_data, 折線=line))
        blocks.append(dict(
            區塊編號=b["id"], 指標=b["name"], 標題=b["base"], 單位=b["unit"],
            方向="高" if b["direction"] == "高" else "低", 方向說明="數值越高名次越前面" if b["direction"] == "高" else "數值越低名次越前面",
            說明=strip_codes(b["note"].replace("{latest}", str(latest))), 學制選項=list(b["series"]), 預設學制=b["series"][0],
            資料最新年度=latest, 時間單位=b["time_unit"], 年度清單=R["block_years"][b["id"]],
            時間說明=("數字為年度（平台每年 3 月統計前一年度資料），資料列的「學年度」鍵在此區塊代表年度" if b["time_unit"] == "年度" else "數字為學年度"),
            資料至=("資料至 %d %s" % (latest, b["time_unit"])), 來源報表=b["report"], 驗算報表=b["check"],
            資料下載日=dl_dates[b["report"]], 序列=sers))
    gen_n, gu = R["gen_n"], R["gen"]
    pop = {str(y): dict(一般大學校數=int(gen_n[y]),
                        公立=int(((gu["學年度"] == y) & (gu["設立別"] == "公立")).sum()),
                        私立=int(((gu["學年度"] == y) & (gu["設立別"] == "私立")).sum())) for y in YEARS}
    return dict(
        資料來源=cfg["SOURCE_NAME"],
        資料更新日期="%d/%s/%s" % (int(run_date[:4]) - 1911, run_date[4:6], run_date[6:8]),
        資料更新日期_西元="%s-%s-%s" % (run_date[:4], run_date[4:6], run_date[6:8]),
        資料下載日期=dl_text, 平台資料夾=folder, 本校=dict(學校代碼=THU_CODE, 學校名稱=cfg["THU_NAME"]),
        起始學年度=START_YEAR, 學年度清單=YEARS, 各學年度母體=pop,
        時間單位說明="區塊的「時間單位」為學年度或年度；年度類區塊（研究類）的資料列鍵名仍為「學年度」（程式內部統一年度鍵），顯示請標「年度」",
        口徑摘要=[strip_codes(t) for t in build_summary_lines(R)], 區塊=blocks)


# ================================================================ 主程式
def rel(p):
    """顯示用路徑：在儲存庫內用相對路徑，其他（含不同磁碟）用絕對路徑。"""
    p = os.path.abspath(p)
    try:
        r = os.path.relpath(p, ROOT)
    except ValueError:
        return p
    return p if r.startswith("..") else r


def latest_raw_dir():
    base = os.path.join(ROOT, "data", "raw")
    ys = sorted(d for d in os.listdir(base) if d.isdigit()) if os.path.isdir(base) else []
    if not ys:
        raise SystemExit("[找不到原始資料] data/raw/<年>/ 不存在；請先執行 tools/fetch.py")
    return os.path.join(base, ys[-1])


def main():
    ap = argparse.ArgumentParser(description="依口徑把 data/raw/<年>/ 算成 data/dashboard.json")
    ap.add_argument("--raw", help="原始報表資料夾（預設 data/raw/ 下最新的年）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"), help="資料更新日期 YYYYMMDD（預設今天）")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "dashboard.json"), help="輸出路徑")
    ap.add_argument("--check", action="store_true", help="只比對 --out 現有檔案，不寫檔；不同時結束碼 1")
    a = ap.parse_args()
    if not re.fullmatch(r"\d{8}", a.date):
        raise SystemExit("--date 須為 YYYYMMDD")
    raw_dir = os.path.abspath(a.raw) if a.raw else latest_raw_dir()
    print("原始資料：%s" % rel(raw_dir))

    dl_dates, dl_text, folder = download_info(raw_dir)
    R = run(raw_dir)
    trace_check(R)
    raw_check_thu(R, raw_dir)
    cross_check(R)
    print("學年度 %s；一般大學校數 %s" % (R["YEARS"], R["gen_n"]))

    js = sanitize(build_json(R, a.date, dl_dates, dl_text, folder))
    text = json.dumps(js, ensure_ascii=False, indent=1, allow_nan=False)

    if a.check:
        if not os.path.exists(a.out):
            raise SystemExit("[比對] %s 不存在" % a.out)
        with open(a.out, encoding="utf-8") as f:
            cur = f.read()
        same_val = json.loads(cur) == js
        same_txt = cur.replace("\r\n", "\n").rstrip("\n") == text
        print("比對 %s：內容%s；文字%s" % (rel(a.out), "相同" if same_val else "不同", "相同" if same_txt else "不同"))
        if not same_val:
            show_diff(json.loads(cur), js)
            sys.exit(1)
        return
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("輸出：%s" % rel(a.out))


def show_diff(old, new, path="", limit=[20]):
    """列出前 20 個不同的位置（舊 → 新）。"""
    if limit[0] <= 0:
        return
    if type(old) is not type(new):
        limit[0] -= 1
        print("  %s：%r → %r" % (path or "/", old, new))
    elif isinstance(old, dict):
        for k in list(old) + [k for k in new if k not in old]:
            if k not in old or k not in new:
                limit[0] -= 1
                print("  %s/%s：%s" % (path, k, "新增" if k not in old else "移除"))
            else:
                show_diff(old[k], new[k], "%s/%s" % (path, k), limit)
    elif isinstance(old, list):
        if len(old) != len(new):
            limit[0] -= 1
            print("  %s：長度 %d → %d" % (path, len(old), len(new)))
        for i, (x, y) in enumerate(zip(old, new)):
            show_diff(x, y, "%s[%d]" % (path, i), limit)
    elif old != new:
        limit[0] -= 1
        print("  %s：%r → %r" % (path, old, new))


if __name__ == "__main__":
    main()

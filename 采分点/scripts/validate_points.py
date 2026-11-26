#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采分点 CSV 校验器（本项目版 · 2026-11-25 修订）。

与 `原始资料/gaokao-physics-rubric/scripts/validate_points.py` 的差异：
    A. 「② 原始方程 ≥30%」改为**逐题**判定。原版跨题累加，单题 0 个 ② 也能过。
    B. 若 CSV 含「备注」列（17 列总表格式），强制校验「分值A/B/C」等级存在。
       9 列旧格式不检此项，保持向后兼容。

用法:
    python3 validate_points.py 采分点.csv [--strict]
    python3 validate_points.py 五卷力学大题_采分点总表_v2.xlsx [--strict]   # 直接读「采分点总表」

检查项:
    1. 表头完整
    2. 每题各步分值合计 == 本题卷面总分   (error)
    3. 步号从 1 起连续无缺号              (error)
    4. 采分类别在 ①②③④⑤ 之内            (error)
    5. 判分口径为空 / 含"酌情"类空话       (warn / error)
    6. 题内采分点文本重复                  (error)
    7. 单步分值 > 4 或 < 0.5               (warn)
    8. ② 原始方程分值占比 < 30%（逐题）    (warn)
    9. 备注列缺「分值A/B/C」等级（有备注列时）(error)
退出码: 有 error 返回 1，否则 0（--strict 下 warn 也返回 1）。
"""

import csv
import sys
import os
import re
from collections import OrderedDict, defaultdict

CATS = ["① 状态判断", "② 原始方程", "③ 过程量", "④ 结果规范", "⑤ 临界与范围"]
CAT_KEYS = {
    "①": CATS[0], "1": CATS[0], "状态判断": CATS[0],
    "②": CATS[1], "2": CATS[1], "原始方程": CATS[1], "方程": CATS[1],
    "③": CATS[2], "3": CATS[2], "过程量": CATS[2],
    "④": CATS[3], "4": CATS[3], "结果规范": CATS[3], "结果": CATS[3],
    "⑤": CATS[4], "5": CATS[4], "临界与范围": CATS[4], "临界": CATS[4],
}
HEADER = ["卷别", "题号", "本题总分", "小问", "步", "采分点", "分值", "判分口径", "类别"]
VAGUE = ["酌情", "视情况", "按标准答案", "合理即可", "酌情给分"]


def norm_cat(s):
    s = (s or "").strip()
    if s in CATS:
        return s
    for k in "①②③④⑤":
        if s.startswith(k):
            return CAT_KEYS[k]
    for k in ("状态判断", "原始方程", "过程量", "结果规范", "临界与范围"):
        if k in s:
            return CAT_KEYS[k]
    if s in CAT_KEYS:
        return CAT_KEYS[s]
    return None


def load(path):
    if path.lower().endswith(".xlsx"):
        return load_xlsx(path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        rows = list(csv.DictReader(f, delimiter=delim))
    return rows


def load_xlsx(path, sheet="采分点总表"):
    """直接读采分点总表，避免「xlsx 与 CSV 双事实源」。

    总表列名与 CSV 不同（「采分点（必须出现的式子或判断）」「采分类别」），这里做一次改名。
    """
    try:
        import openpyxl
    except ImportError:
        print("[ERROR] 读 xlsx 需要 openpyxl：pip install openpyxl")
        sys.exit(2)
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet not in wb.sheetnames:
        print("[ERROR] %s 里没有工作表「%s」" % (path, sheet))
        sys.exit(2)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    header = ["" if h is None else str(h).strip() for h in next(it)]
    alias = {"采分点（必须出现的式子或判断）": "采分点", "采分类别": "类别",
             "卷别 / 来源": "卷别", "卷面分": "本题总分"}
    header = [alias.get(h, h) for h in header]
    out = []
    for row in it:
        if not any(v not in (None, "") for v in row):
            continue
        out.append({header[i]: ("" if v is None else v) for i, v in enumerate(row) if i < len(header)})
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    strict = "--strict" in sys.argv
    if not os.path.exists(path):
        print("[ERROR] 文件不存在: %s" % path)
        return 2

    rows = load(path)
    if not rows:
        print("[ERROR] CSV 无数据行")
        return 1
    missing = [h for h in HEADER if h not in rows[0]]
    if missing:
        print("[ERROR] 缺列: %s" % "、".join(missing))
        print("       需要的列: %s" % ",".join(HEADER))
        return 1

    has_note = "备注" in rows[0]
    if not has_note:
        print("[提示] 无「备注」列（9 列旧格式）：跳过「分值来源等级」校验")

    errors, warns = [], []
    groups = OrderedDict()
    seen = defaultdict(list)

    for i, r in enumerate(rows, start=2):  # 行号（含表头）
        paper = (r.get("卷别") or "").strip()
        no = str(r.get("题号") or "").strip()
        key = (paper, no)
        try:
            total = float(r.get("本题总分"))
            step = int(float(r.get("步")))
            score = float(r.get("分值"))
        except (TypeError, ValueError):
            errors.append("第 %d 行: 本题总分/步/分值 不是数字" % i)
            continue
        pt = (r.get("采分点") or "").strip()
        rule = (r.get("判分口径") or "").strip()
        cat = norm_cat(r.get("类别"))

        if not paper or not no:
            errors.append("第 %d 行: 卷别或题号为空" % i)
        if cat is None:
            errors.append("第 %d 行: 类别『%s』不在五类内" % (i, r.get("类别")))
        else:
            r["_cat"] = cat
        if not pt:
            errors.append("第 %d 行: 采分点为空" % i)
        if not rule:
            warns.append("第 %d 行: 判分口径为空（%s 第 %d 步）" % (i, paper, step))
        elif any(v in rule for v in VAGUE):
            errors.append("第 %d 行: 判分口径含空话『%s』，改写成“写成 X 给几分”" % (i, rule))
        if score <= 0 or score > 4:
            warns.append("第 %d 行: 单步 %g 分，超出 0.5—4 的常见范围" % (i, score))
        if has_note and not re.search(r"分值[ABC]", r.get("备注") or ""):
            errors.append("第 %d 行: 备注缺「分值A/B/C」等级（规范 §3 第三步，这一栏不许空）" % i)
        seen[key].append(pt)

        g = groups.setdefault(key, {"total": total, "steps": [], "sum": 0.0,
                                   "cats": defaultdict(lambda: {"s": 0.0, "n": 0})})
        g["steps"].append(step)
        g["sum"] += score
        if cat:
            g["cats"][cat]["s"] += score
            g["cats"][cat]["n"] += 1

    # 题内重复
    for key, pts in seen.items():
        dup = {p for p in pts if pts.count(p) > 1}
        for d in dup:
            errors.append("%s %s: 采分点重复『%s』" % (key[0], key[1], d[:30]))

    # 逐题校验
    print("=" * 66)
    print("逐题校验")
    print("=" * 66)
    grand = 0.0
    npts = 0
    cat_sum = defaultdict(float)
    cat_cnt = defaultdict(int)
    for (paper, no), g in groups.items():
        n = len(g["steps"])
        steps = sorted(g["steps"])
        ok_seq = steps == list(range(1, n + 1))
        ok_sum = abs(g["sum"] - g["total"]) < 1e-9
        flag = "OK " if (ok_seq and ok_sum) else "FAIL"
        print("%s  %-14s %-4s  %2d 步  %5.1f / %-4.0f 分  %s"
              % (flag, paper, no, n, g["sum"], g["total"],
                 "" if ok_seq else "步号不连续:%s" % steps))
        if not ok_seq:
            errors.append("%s %s: 步号应为 1..%d，实际 %s" % (paper, no, n, steps))
        if not ok_sum:
            diff = g["sum"] - g["total"]
            errors.append("%s %s: 分值合计 %.1f ≠ 卷面 %.0f（差 %+g）" % (paper, no, g["sum"], g["total"], diff))
        # —— 逐题判 ② 占比（本项目修订 A）：不许跨题累加 ——
        q_eq = g["cats"].get(CATS[1], {"s": 0.0, "n": 0})["s"]
        q_pct = (q_eq / g["sum"] * 100) if g["sum"] else 0.0
        print("     ② 原始方程 %2d 个 %4.1f 分 %5.1f%%%s"
              % (g["cats"].get(CATS[1], {"n": 0})["n"], q_eq, q_pct,
                 "" if q_pct >= 30 else "   ← 低于 30%"))
        if g["sum"] and q_pct < 30:
            warns.append("%s %s: ② 原始方程仅占 %.1f%%（<30%%），可能把方程合并进了一步"
                         % (paper, no, q_pct))
        grand += g["sum"]
        npts += n
        for c, v in g["cats"].items():
            cat_sum[c] += v["s"]
            cat_cnt[c] += v["n"]

    # 类别覆盖
    print("\n" + "=" * 66)
    print("类别分布（全量汇总，仅供参考；② 的 30% 判定已按逐题执行，见上）")
    print("=" * 66)
    for c in CATS:
        s = cat_sum.get(c, 0.0)
        cnt = cat_cnt.get(c, 0)
        pct = (s / grand * 100) if grand else 0
        print("%-10s %2d 个  %5.1f 分  %5.1f%%" % (c, cnt, s, pct))
    if cat_cnt.get(CATS[0], 0) == 0 and grand >= 15:
        warns.append("没有任何 ① 状态判断：检查是否漏了共速/分离/极值这类判断句")

    print("\n合计: %d 题 / %d 个采分点 / %.0f 分 / 平均 %.2f 分每点"
          % (len(groups), npts, grand, grand / npts if npts else 0))

    # 输出
    print("\n" + "=" * 66)
    if warns:
        print("警告 %d 条" % len(warns))
        for w in warns:
            print("  [!] " + w)
    if errors:
        print("错误 %d 条" % len(errors))
        for e in errors:
            print("  [x] " + e)
        return 1
    print("全部通过，可以生成总表。" if not warns else "无错误；警告建议处理后生成。")
    return 1 if (strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())

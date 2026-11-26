#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由采分点 CSV 生成可筛选/可统计的总表工作簿。

用法:
    python3 build_workbook.py 采分点.csv 输出.xlsx [标题]

CSV 列（顺序不限，需有表头）:
    卷别,题号,本题总分,小问,步,采分点,分值,判分口径,类别

产出两个工作表:
    采分点总表 — 10 列平表，冻结首行 + 自动筛选
    统计       — 按题汇总 / 按类别汇总 / 说明
"""

import csv
import math
import sys
from collections import OrderedDict, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

INK = "1B1A18"; BLUE = "1F3A5F"; RED = "A6392E"; CREAM = "FBF8F1"
GREY = "6B6B68"; LINE = "D9D2C5"
thin = Side(style="thin", color=LINE)
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
FONT = "微软雅黑"

CATS = ["① 状态判断", "② 原始方程", "③ 过程量", "④ 结果规范", "⑤ 临界与范围"]


def norm_cat(s):
    s = (s or "").strip()
    if s in CATS:
        return s
    for k in "①②③④⑤":
        if s.startswith(k):
            return CATS["①②③④⑤".index(k)]
    for i, k in enumerate(("状态判断", "原始方程", "过程量", "结果规范", "临界与范围")):
        if k in s:
            return CATS[i]
    return s or "—"


def hdr(ws, row, n, fill=BLUE, height=32):
    for c in range(1, n + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row].height = height


def body(ws, r1, r2, n, size=9.5):
    for r in range(r1, r2 + 1):
        for c in range(1, n + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = Font(name=FONT, size=size, color=INK)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = BORDER
        if r % 2 == 0:
            for c in range(1, n + 1):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=CREAM)


def widths(ws, arr):
    for i, w in enumerate(arr, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def auto_h(ws, r1, r2, n, minh=28, lineh=14.5):
    for r in range(r1, r2 + 1):
        lines = 1
        for c in range(1, n + 1):
            v = ws.cell(row=r, column=c).value
            if v is None:
                continue
            w = ws.column_dimensions[get_column_letter(c)].width or 10
            per = max(6, int(float(w) / 2.05))
            lines = max(lines, sum(max(1, math.ceil(len(seg) / per)) for seg in str(v).split("\n")))
        ws.row_dimensions[r].height = max(minh, lines * lineh + 6)


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        return list(csv.DictReader(f, delimiter=delim))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, out = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else "高考物理采分点总表"

    rows = load(src)
    D = []
    for r in rows:
        D.append((
            (r.get("卷别") or "").strip(),
            str(r.get("题号") or "").strip(),
            float(r.get("本题总分") or 0),
            (r.get("小问") or "").strip(),
            int(float(r.get("步") or 0)),
            (r.get("采分点") or "").strip(),
            float(r.get("分值") or 0),
            (r.get("判分口径") or "").strip(),
            norm_cat(r.get("类别")),
        ))
    D.sort(key=lambda d: (d[0], d[1], d[4]))
    n = len(D)
    grand = sum(d[6] for d in D)

    wb = Workbook()

    # ---------- Sheet1 ----------
    ws = wb.active
    ws.title = "采分点总表"
    ws.sheet_view.showGridLines = False
    H = ["序号", "卷别", "题号", "本题总分", "小问", "步",
         "采分点（必须出现的式子或判断）", "分值", "判分口径", "采分类别"]
    ws.append(H)
    hdr(ws, 1, len(H))
    widths(ws, [5, 15, 6, 8, 6, 5, 52, 6, 40, 13])
    for i, d in enumerate(D, start=1):
        ws.append([i, d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8]])
    body(ws, 2, 1 + n, len(H))
    auto_h(ws, 2, 1 + n, len(H), minh=28)
    for r in range(2, 2 + n):
        for c in (1, 2, 3, 4, 5, 6, 8, 10):
            ws.cell(row=r, column=c).alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True)
        ws.cell(row=r, column=8).font = Font(name="Arial", size=10.5, bold=True, color=RED)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:J%d" % (1 + n)

    # ---------- Sheet2 ----------
    ws2 = wb.create_sheet("统计")
    ws2.sheet_view.showGridLines = False
    ws2["B2"] = title
    ws2["B2"].font = Font(name=FONT, size=15, bold=True, color=BLUE)
    ws2["B3"] = "共 %d 题 / %.0f 分 / %d 个采分点" % (len({(d[0], d[1]) for d in D}), grand, n)
    ws2["B3"].font = Font(name=FONT, size=10, color=GREY)

    r0 = 5
    ws2.cell(row=r0, column=2, value="一、按题汇总").font = Font(name=FONT, size=11, bold=True, color=RED)
    H2 = ["卷别", "题号", "小问数", "采分点数", "卷面分值", "平均每个采分点"]
    for j, h in enumerate(H2, start=2):
        c = ws2.cell(row=r0 + 1, column=j, value=h)
        c.font = Font(name=FONT, size=9.5, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER
    ws2.row_dimensions[r0 + 1].height = 30

    grp = OrderedDict()
    for d in D:
        k = (d[0], d[1], d[2])
        g = grp.setdefault(k, {"n": 0, "parts": set()})
        g["n"] += 1
        g["parts"].add(d[3])

    r = r0 + 2
    for (paper, no, total), v in grp.items():
        vals = [paper, no, len(v["parts"]), v["n"], total, round(total / v["n"], 2)]
        for j, val in enumerate(vals, start=2):
            c = ws2.cell(row=r, column=j, value=val)
            c.font = Font(name=FONT, size=9.5, color=INK)
            c.alignment = Alignment(horizontal="center" if j > 2 else "left", vertical="center")
            c.border = BORDER
        r += 1
    vals = ["合计", "—", "—", n, grand, round(grand / n, 2)]
    for j, val in enumerate(vals, start=2):
        c = ws2.cell(row=r, column=j, value=val)
        c.font = Font(name=FONT, size=9.5, bold=True, color=BLUE)
        c.alignment = Alignment(horizontal="center" if j > 2 else "left", vertical="center")
        c.border = BORDER
        c.fill = PatternFill("solid", fgColor="E8EEF6")

    r += 3
    ws2.cell(row=r, column=2, value="二、按采分类别汇总").font = Font(name=FONT, size=11, bold=True, color=RED)
    r += 1
    for j, h in enumerate(["采分类别", "采分点数", "分值合计", "分值占比"], start=2):
        c = ws2.cell(row=r, column=j, value=h)
        c.font = Font(name=FONT, size=9.5, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER
    cat = defaultdict(lambda: {"n": 0, "s": 0.0})
    for d in D:
        cat[d[8]]["n"] += 1
        cat[d[8]]["s"] += d[6]
    order = [c for c in CATS if c in cat] + [c for c in cat if c not in CATS]
    for k in order:
        v = cat[k]
        r += 1
        vals = [k, v["n"], v["s"], "{:.1%}".format(v["s"] / grand if grand else 0)]
        for j, val in enumerate(vals, start=2):
            c = ws2.cell(row=r, column=j, value=val)
            c.font = Font(name=FONT, size=9.5, color=INK)
            c.alignment = Alignment(horizontal="left" if j == 2 else "center", vertical="center")
            c.border = BORDER

    r += 3
    ws2.cell(row=r, column=2, value="三、说明").font = Font(name=FONT, size=11, bold=True, color=RED)
    notes = [
        "1. 分值按“官方答案分步结构 + 教辅解析版标注 + 按步给分通行规则”反推，各版本可能有 ±2 分差异；每题合计与卷面分值一致。",
        "2. 官方评分细则不公开，只下发至各省评卷点。用于正式阅卷请以本省评卷点文件为准；用于讲评与估分，本表结构可用。",
        "3. “采分类别”为本表自定义归纳，便于筛选与统计，非官方分类。",
        "4. “采分点”列写的是必须出现的式子或判断，不是完整解答；完整推导见配套讲义。",
    ]
    for i, t in enumerate(notes):
        c = ws2.cell(row=r + 1 + i, column=2, value=t)
        c.font = Font(name=FONT, size=9, color=GREY)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws2.merge_cells(start_row=r + 1 + i, start_column=2, end_row=r + 1 + i, end_column=5)
        ws2.row_dimensions[r + 1 + i].height = 32

    widths(ws2, [2, 16, 8, 10, 10, 10, 14])
    wb.save(out)
    print("saved %s | %d 行 | %.0f 分" % (out, n, grand))
    return 0


if __name__ == "__main__":
    sys.exit(main())

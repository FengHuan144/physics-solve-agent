#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采分点入库器：17 列 CSV → xlsx「采分点总表」+ 同步「选题清单_30题」。

背景：`采分点拆解规范_v1.md` 的出闸校验用的是 validate_points.py（9 列即可），
但总表是 17 列。缺这一层转换，「拆完」和「入册」之间一直有个手抄环节。
本脚本就是那个环节，幂等：按 point_id upsert，重复跑不会产生重复行。

用法:
    python import_points.py 新题/*.csv --dry-run     # 只校验，不写盘
    python import_points.py 新题/*.csv               # 写盘
    python import_points.py X.csv --xlsx 路径.xlsx

退出码: 0 成功；1 有校验错误（不写盘）；2 参数/文件错误。
"""

import csv
import glob
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_XLSX = os.path.join(ROOT, "原始资料", "五卷力学大题_采分点总表_v2.xlsx")

COLS = ["point_id", "组别", "卷别 / 来源", "题号", "卷面分", "小问", "步",
        "采分点（必须出现的式子或判断）", "分值", "判分口径", "采分类别",
        "章节 · 知识点", "过程数", "含临界", "依赖图", "错误码", "备注"]
CATS = {"① 状态判断", "② 原始方程", "③ 过程量", "④ 结果规范", "⑤ 临界与范围"}
PID = re.compile(r"^([AB]-\d{2})-S(\d{2})$")


def read_csv(path, errs):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        errs.append("%s: 空文件" % os.path.basename(path))
        return []
    missing = [c for c in COLS if c not in rows[0]]
    if missing:
        errs.append("%s: 缺列 %s（本脚本要求 17 列总表格式）"
                    % (os.path.basename(path), "、".join(missing)))
        return []
    out = []
    for i, r in enumerate(rows, start=2):
        pid = (r.get("point_id") or "").strip()
        m = PID.match(pid)
        if not m:
            errs.append("%s 第 %d 行: point_id『%s』不合 A-01-S01 格式" % (os.path.basename(path), i, pid))
            continue
        if (r.get("采分类别") or "").strip() not in CATS:
            errs.append("%s 第 %d 行: 类别『%s』不在五类内" % (os.path.basename(path), i, r.get("采分类别")))
        if not (r.get("备注") or "").strip() or not re.search(r"分值[ABC]", r.get("备注") or ""):
            errs.append("%s 第 %d 行: 备注缺「分值A/B/C」等级" % (os.path.basename(path), i))
        try:
            float(r["分值"])
            float(r["卷面分"])
            int(float(r["步"]))
        except (TypeError, ValueError):
            errs.append("%s 第 %d 行: 分值/卷面分/步 不是数字" % (os.path.basename(path), i))
        r["_code"] = m.group(1)
        out.append(r)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    xlsx = DEFAULT_XLSX
    if "--xlsx" in sys.argv:
        xlsx = sys.argv[sys.argv.index("--xlsx") + 1]
    if not args:
        print(__doc__)
        return 2

    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(a)) if any(ch in a for ch in "*?") else [a])
    if not paths:
        print("[ERROR] 没有匹配到 CSV")
        return 2

    errs = []
    rows = []
    for p in paths:
        rows.extend(read_csv(p, errs))
    if errs:
        print("校验未过，未写盘：")
        for e in errs:
            print("  [x] " + e)
        return 1
    if not rows:
        print("[ERROR] 无数据行")
        return 1

    # 题内自查：步号连续 + 分值合计 == 卷面分
    g = defaultdict(lambda: {"steps": [], "sum": 0.0, "total": None, "no": None, "paper": None})
    for r in rows:
        k = r["_code"]
        g[k]["steps"].append(int(float(r["步"])))
        g[k]["sum"] += float(r["分值"])
        g[k]["total"] = float(r["卷面分"])
        g[k]["no"] = str(r["题号"]).strip()
        g[k]["paper"] = r["卷别 / 来源"].strip()
    bad = False
    for k, v in g.items():
        n = len(v["steps"])
        if sorted(v["steps"]) != list(range(1, n + 1)):
            print("  [x] %s 步号应为 1..%d，实际 %s" % (k, n, sorted(v["steps"])))
            bad = True
        if abs(v["sum"] - v["total"]) > 1e-9:
            print("  [x] %s 分值合计 %g ≠ 卷面 %g" % (k, v["sum"], v["total"]))
            bad = True
    if bad:
        print("校验未过，未写盘。")
        return 1

    print("待入库：%d 题 / %d 步 / %g 分" % (len(g), len(rows), sum(x["sum"] for x in g.values())))
    for k, v in g.items():
        print("  %s  %s %s题  %d 步  %g/%g 分" % (k, v["paper"], v["no"], len(v["steps"]), v["sum"], v["total"]))

    if dry:
        print("\n[dry-run] 未写盘。去掉 --dry-run 即入库。")
        return 0

    import openpyxl
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["采分点总表"]
    hdr = [c.value for c in ws[1]]
    idx = {h: i + 1 for i, h in enumerate(hdr)}
    existing = {}
    for row in ws.iter_rows(min_row=2):
        if row[0].value:
            existing[str(row[0].value).strip()] = row[0].row

    n_new = n_upd = 0
    for r in rows:
        pid = r["point_id"].strip()
        target = existing.get(pid)
        if target:
            n_upd += 1
        else:
            target = ws.max_row + 1
            existing[pid] = target
            n_new += 1
        for c in COLS:
            v = r[c]
            if c in ("题号",):
                v = int(float(v))
            elif c in ("卷面分", "分值"):
                v = float(v)
            elif c in ("步", "过程数"):
                v = int(float(v))
            ws.cell(row=target, column=idx[c], value=v)

    # 同步选题清单
    ws2 = wb["选题清单_30题"]
    h2 = [c.value for c in ws2[1]]
    j = {h: i for i, h in enumerate(h2)}
    synced = 0
    for row in ws2.iter_rows(min_row=2):
        code = row[j["编号"]].value
        if code in g:
            row[j["状态"]].value = "已完成"
            row[j["采分点数"]].value = len(g[code]["steps"])
            synced += 1
    wb.save(xlsx)
    print("\n入库完成：新增 %d 行，更新 %d 行；选题清单同步 %d 题 → %s"
          % (n_new, n_upd, synced, os.path.relpath(xlsx, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

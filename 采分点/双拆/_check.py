#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双拆 CSV 的出闸校验封装（2026-11-25）。

为什么需要这一层：
    17 列 CSV 用的是空白模板表头（卷别 / 来源、卷面分、采分点（必须出现的式子或判断）、采分类别），
    而 validate_points.py 的「缺列」检查用的是 9 列视图名（卷别、本题总分、采分点、类别）。
    它的列名别名映射只写在 load_xlsx() 里，读 CSV 时不做映射 —— 直接跑会报「缺列」。

    本脚本把 17 列 CSV 逐份落成一个临时 xlsx（工作表名固定为「采分点总表」），
    再调 validate_points.py 校验同一批数据。校验规则、数据都没变，只换了读入口。

用法:
    python 采分点/双拆/_check.py            # 全部 10 题
    python 采分点/双拆/_check.py A-08       # 单题
"""

import csv
import glob
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VALIDATOR = os.path.join(ROOT, "采分点", "scripts", "validate_points.py")
COLS = ["point_id", "组别", "卷别 / 来源", "题号", "卷面分", "小问", "步",
        "采分点（必须出现的式子或判断）", "分值", "判分口径", "采分类别",
        "章节 · 知识点", "过程数", "含临界", "依赖图", "错误码", "备注"]


def to_xlsx(csv_path, out_path):
    import openpyxl
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("%s: 无数据行" % csv_path)
    missing = [c for c in COLS if c not in rows[0]]
    if missing:
        raise SystemExit("%s: 缺列 %s" % (os.path.basename(csv_path), "、".join(missing)))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "采分点总表"
    ws.append(COLS)
    for r in rows:
        ws.append([r[c] for c in COLS])
    wb.save(out_path)


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(glob.glob(os.path.join(HERE, "*.csv")))
    if pat:
        files = [f for f in files if pat in os.path.basename(f)]
    if not files:
        print("没有匹配的 CSV")
        return 2

    rc = 0
    with tempfile.TemporaryDirectory() as td:
        for f in files:
            print("\n" + "#" * 66)
            print("# %s" % os.path.basename(f))
            print("#" * 66)
            x = os.path.join(td, os.path.basename(f).replace(".csv", ".xlsx"))
            to_xlsx(f, x)
            p = subprocess.run([sys.executable, VALIDATOR, x, "--strict"],
                               capture_output=True, text=True, encoding="utf-8")
            print(p.stdout.strip())
            if p.returncode != 0:
                rc = 1
    print("\n==== 总判定：%s ====" % ("有题目未过" if rc else "10 题全过（含 warn 零条）"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

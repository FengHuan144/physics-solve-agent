#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T07 核对表：把每条记录的「标准答案 + 模型最终答案区 + 自动判分」并排打出来，
供人工逐条核对（判分表必须人工过一遍）。不改任何数据。

用法：
    python 评测/基线/review.py --variant v1
    python 评测/基线/review.py --variant v1 --only B-17,A-09
    python 评测/基线/review.py --variant v1 --width 240
"""

import argparse
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "sc", os.path.join(os.path.dirname(os.path.abspath(__file__)), "score.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))


def evidence(rec, width):
    """
    取「模型自认的最终答案」：
      ① 全部 \\boxed 内容（最可靠）
      ② 无 boxed 时取「3. 求解与结果」段（v2 结构），或「最终答案/综上」之后
      ③ 再不行取末段
    """
    content = rec.get("content") or ""
    plain = sc.latex_to_plain(content)
    boxes = []
    i = 0
    raw = content
    while True:
        i = raw.find("\\boxed", i)
        if i < 0:
            break
        inner, k = sc._group(raw, i + 6)
        boxes.append(" ".join(sc.latex_to_plain(inner).split()))
        i = k
    if boxes:
        return "【boxed×%d】%s" % (len(boxes), " ; ".join(boxes))[-width:]
    m = re.search(r"3[.、]\s*求解与结果(.{0,1200}?)(?:4[.、]\s*必要的讨论|$)",
                  plain, re.S)
    if m:
        return "【结果段】" + " ".join(m.group(1).split())[:width]
    return "【末段】" + " ".join(sc.final_region(plain).split())[-width:]



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v1")
    ap.add_argument("--only", default=None)
    ap.add_argument("--width", type=int, default=220)
    args = ap.parse_args()

    std = sc.load_std()
    d = os.path.join(ROOT, "raw", args.variant)
    only = set(args.only.split(",")) if args.only else None

    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        qid = fn[:-5]
        if only and qid not in only:
            continue
        rec = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        comps = std.get(qid, [])
        std_s = " ; ".join("%s=%s%s" % (c["sub_no"], c["answer_raw"],
                                        "" if c["unit"] in ("—", "-") else "")
                           for c in comps)
        verdict, ft, note = sc.judge_question(qid, args.variant, rec, comps)
        region = evidence(rec, args.width)
        print("=" * 78)
        print("【%s】 std: %s" % (qid, std_s))
        print("[auto] %s / %s | %s" % (verdict, ft, note))
        print("[fin]  %s" % region)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""拆点 CSV 公共生成器：17 列总表格式 + 9 列校验副本。

每个 _gen_*.py 只提供 BASE / STEPS / NOTE，由本模块负责列名、写盘与分值合计自检。
"""
import csv
import os

COLS = ["point_id", "组别", "卷别 / 来源", "题号", "卷面分", "小问", "步",
        "采分点（必须出现的式子或判断）", "分值", "判分口径", "采分类别",
        "章节 · 知识点", "过程数", "含临界", "依赖图", "错误码", "备注"]

MAP9 = [("卷别 / 来源", "卷别"), ("题号", "题号"), ("卷面分", "本题总分"), ("小问", "小问"),
        ("步", "步"), ("采分点（必须出现的式子或判断）", "采分点"), ("分值", "分值"),
        ("判分口径", "判分口径"), ("采分类别", "类别"), ("备注", "备注")]

HERE = os.path.dirname(os.path.abspath(__file__))


def emit(code, base, steps, note, quiet=False):
    """steps: [(小问, 采分点, 分值, 判分口径, 类别, 错误码), ...]"""
    rows = []
    for i, (sub, pt, score, rule, cat, err) in enumerate(steps, 1):
        r = dict(base)
        r.update({"point_id": "%s-S%02d" % (code, i), "小问": sub, "步": i,
                  "采分点（必须出现的式子或判断）": pt, "分值": score,
                  "判分口径": rule, "采分类别": cat, "错误码": err, "备注": note})
        rows.append(r)

    total = sum(r["分值"] for r in rows)
    assert abs(total - base["卷面分"]) < 1e-9, \
        "%s 分值合计 %g ≠ 卷面 %g" % (code, total, base["卷面分"])

    out17 = os.path.join(HERE, code + ".csv")
    out9 = os.path.join(HERE, "_%s_9col.csv" % code)
    with open(out17, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    with open(out9, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([b for _, b in MAP9])
        for r in rows:
            w.writerow([r[a] for a, _ in MAP9])

    if not quiet:
        eq = sum(r["分值"] for r in rows if r["采分类别"].startswith("②"))
        print("%s  %2d 步  %g/%g 分  ② %g 分 %.1f%%"
              % (code, len(rows), total, base["卷面分"], eq, eq / total * 100))
    return rows

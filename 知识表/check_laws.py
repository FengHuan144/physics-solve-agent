#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T10 定律适用条件表 · 校验脚本

用法：
    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python3 知识表/check_laws.py

七项验收（对应任务卡 §4 / §5）：条数、成立条件、否定式、自检问句、不成立替代、题号覆盖、外键。
两项附加（对应 R5 / R7）：典型误用必须挂实题号、错误码必须取自 21 条枚举。

外键口径：
    知识表/公式库_v1.csv 存在 → 严格对照 T09 真表；
    不存在 → 对照 知识表/公式库_需求清单.csv（T10 给 T09 的输入契约），该项判 WARN。
"""

import csv
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
LAW_CSV = BASE / "定律适用条件_v1.csv"
FORMULA_REQ = BASE / "公式库_需求清单.csv"
FORMULA_LIB = BASE / "公式库_v1.csv"

EXPECTED_LAWS = [f"L-{i:02d}" for i in range(1, 13)]

# 27 道实题：29 个编号 − B-11 / B-14 两个缺口；A-07 已撤销不计
A_GROUP = ["A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-08", "A-09", "A-10"]
B_GROUP = ([f"B-{i:02d}" for i in range(1, 11)]
           + ["B-12", "B-13"]
           + [f"B-{i:02d}" for i in range(15, 21)])
REAL_QIDS = A_GROUP + B_GROUP          # 27 条

# 21 条错误码枚举
ERROR_CODES = {f"E-{i:02d}" for i in range(1, 17)} | {f"E-{i:02d}" for i in range(20, 25)}

COLUMNS = ["law_id", "名称", "一句话表述", "成立条件_1", "成立条件_2", "成立条件_3",
           "否定式条件", "自检问句", "不成立时替代", "易混对象", "典型误用",
           "关联错误码", "关联公式", "涉及题号"]

RESULTS = []   # (label, status, detail)


def dwidth(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text, width):
    return text + " " * max(1, width - dwidth(text))


def add(label, status, detail=""):
    RESULTS.append((label, status, detail))


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_ids(value):
    return [x.strip() for x in value.replace("，", ";").split(";") if x.strip()]


def main():
    if not LAW_CSV.exists():
        print(f"找不到 {LAW_CSV}")
        return 2

    rows = read_csv(LAW_CSV)
    header = list(rows[0].keys()) if rows else []

    # ---- 0. 列结构（不属于七项，但错了后面全错） ----
    if header != COLUMNS:
        print(f"[ERROR] 列名或顺序不符：{header}")
        return 2

    # ---- 1. 条数 ----
    ids = [r["law_id"].strip() for r in rows]
    if ids == EXPECTED_LAWS:
        add("定律表", "OK", f"{len(rows)} 条（L-01…L-12 连续）")
    else:
        add("定律表", "ERROR", f"{len(rows)} 条，law_id 为 {ids}")

    # ---- 2. 成立条件 ----
    cond_counts = []
    for r in rows:
        n = sum(1 for c in ("成立条件_1", "成立条件_2", "成立条件_3") if r[c].strip())
        cond_counts.append(n)
    bad = [r["law_id"] for r, n in zip(rows, cond_counts) if n < 2]
    ge3 = sum(1 for n in cond_counts if n >= 3)
    if bad:
        add("成立条件", "ERROR", f"少于 2 条的是 {bad}")
    elif ge3 < 8:
        add("成立条件", "ERROR", f"仅 {ge3} 条达到 3 条条件（要求 ≥8）")
    else:
        add("成立条件", "OK", f"{len(rows)} 条均 ≥2 条，其中 ≥3 条的 {ge3} 条")

    # ---- 3. 否定式条件 ----
    neg_bad = []
    for r in rows:
        v = r["否定式条件"].strip()
        if not v or "若" not in v or "则" not in v:
            neg_bad.append(r["law_id"])
        elif not any(k in v for k in ("不能用", "不可用", "不成立", "须改用", "须用")):
            neg_bad.append(r["law_id"])
    if neg_bad:
        add("否定式条件", "ERROR", f"{len(rows) - len(neg_bad)}/{len(rows)} 非空或格式不符：{neg_bad}")
    else:
        add("否定式条件", "OK", f"{len(rows)}/{len(rows)} 非空，均为「若…则不能用」式")

    # ---- 4. 自检问句 ----
    q_bad, q_reason = [], {}
    for r in rows:
        q = r["自检问句"].strip()
        why = []
        if not q:
            why.append("空")
        if q.count("？") + q.count("?") != 1:
            why.append(f"问号 {q.count('？') + q.count('?')} 个")
        if "且" in q or "并" in q:
            why.append("含「且」或「并」")
        if q.count("是否") > 1:
            why.append("多重复合")
        if not q.endswith(("？", "?")):
            why.append("未以问号结尾")
        if why:
            q_bad.append(r["law_id"])
            q_reason[r["law_id"]] = "、".join(why)
    if q_bad:
        add("自检问句", "ERROR", "不合规：" + "；".join(f"{k}（{q_reason[k]}）" for k in q_bad))
    else:
        add("自检问句", "OK", f"{len(rows)}/{len(rows)} 单问（无「且」「并」）")

    # ---- 5. 不成立时替代 ----
    alt_bad = []
    for r in rows:
        alt = r["不成立时替代"].strip()
        own = r["law_id"]
        refs = [x for x in split_ids(alt.replace("（", ";").replace("）", "")) if x.startswith("L-")]
        others = [x for x in refs if x != own]
        has_method = any(k in alt for k in ("动能定理", "能量守恒", "机械能守恒", "牛顿第二定律",
                                            "动量定理", "动量守恒", "开普勒", "平抛", "图像", "运动学"))
        if not alt or (not others and not has_method):
            alt_bad.append(own)
    if alt_bad:
        add("不成立替代", "ERROR", f"未指向另一条定律/方法：{alt_bad}")
    else:
        add("不成立替代", "OK", f"{len(rows)}/{len(rows)} 指向另一条定律/方法")

    # ---- 6. 题号覆盖 ----
    hit = {q: set() for q in REAL_QIDS}
    stray = set()
    for r in rows:
        for q in split_ids(r["涉及题号"]):
            if q in hit:
                hit[q].add(r["law_id"])
            else:
                stray.add(q)
    missed = [q for q, laws in hit.items() if not laws]
    if missed:
        add("题号覆盖", "WARN",
            f"{len(REAL_QIDS) - len(missed)}/{len(REAL_QIDS)} 命中；未命中：{'、'.join(missed)}（见说明 §5）")
    else:
        add("题号覆盖", "OK", f"{len(REAL_QIDS)} 道实题全部至少命中 1 条定律")
    if stray:
        add("题号越界", "ERROR", f"表内出现非实题编号或已撤销题：{sorted(stray)}")

    # ---- 7. 外键 ----
    referenced = set()
    for r in rows:
        referenced |= set(split_ids(r["关联公式"]))
    if FORMULA_LIB.exists():
        lib = read_csv(FORMULA_LIB)
        lib_ids = {x["formula_id"].strip() for x in lib}
        lost = sorted(referenced - lib_ids)
        if lost:
            add("外键", "ERROR", f"公式库中不存在：{lost}")
        else:
            # 归属校验：引用是否落在该定律自有的公式集合内
            own = {}
            for x in lib:
                for lid in split_ids(x.get("关联定律", "")):
                    own.setdefault(lid, set()).add(x["formula_id"].strip())
            cross = []
            for r in rows:
                mine = own.get(r["law_id"], set())
                for i in split_ids(r["关联公式"]):
                    if i not in mine:
                        cross.append(f"{r['law_id']}→{i}")
            if cross:
                add("外键", "WARN",
                    f"{len(referenced)} 个 id 全部存在；**{len(cross)} 条跨定律引用**（须人工确认是否联立必需）："
                    + "、".join(cross))
            else:
                add("外键", "OK",
                    f"{len(rows)}/{len(rows)} 条关联公式均存在，且全部落在各自定律的自有公式集合内"
                    f"（{len(referenced)} 个 id）")
    else:
        add("外键", "ERROR",
            "公式库_v1.csv 缺失，无法验外键。不再降级对照已废弃的 公式库_需求清单.csv"
            "（该表用 T10 自拟编号，自 F-006 起与真表错位，曾被当作基准判过「通过」）")

    # ---- 附加 A. 典型误用挂题号（R5） ----
    misuse_bad = []
    for r in rows:
        text = r["典型误用"]
        qids = [q for q in REAL_QIDS if q in text] + [q for q in ("A-07", "B-11", "B-14") if q in text]
        if not qids:
            misuse_bad.append(r["law_id"] + "（无题号）")
        elif any(q in ("A-07", "B-11", "B-14") for q in qids):
            misuse_bad.append(r["law_id"] + "（挂到撤销/缺口题）")
    if misuse_bad:
        add("典型误用", "ERROR", "；".join(misuse_bad))
    else:
        add("典型误用", "OK", f"{len(rows)}/{len(rows)} 挂到 29 题范围内的实题号")

    # ---- 附加 A2. 典型误用里的 S 编号必须真实存在（2026-11-25 T00 加） ----
    # 起因：13 项「典型误用」挂在不存在或错位的步骤上活到交付，脚本只查题号不查步号。
    # 存在性校验拦不住「口径写反」，但能拦住「编一个不存在的步骤」。
    step_ok = set()
    try:
        for r in read_csv(BASE / "覆盖率映射_v1.csv"):
            pid = (r.get("point_id") or "").strip()
            if pid:
                step_ok.add(pid)
    except OSError:
        add("典型误用·步号", "WARN", "覆盖率映射_v1.csv 缺失，跳过步号存在性校验")
        step_ok = None
    if step_ok is not None:
        pat = re.compile(r"[AB]-\d{2}-S\d{2}")
        no_step, ghost_step = [], []
        for r in rows:
            found = pat.findall(r["典型误用"])
            if not found:
                no_step.append(r["law_id"])
            for pid in found:
                if pid not in step_ok:
                    ghost_step.append(f"{r['law_id']}→{pid}")
        if ghost_step:
            add("典型误用·步号", "ERROR", "引用了不存在的 point_id：" + "、".join(ghost_step))
        elif no_step:
            add("典型误用·步号", "ERROR", "未写 S 编号，无法逐条追溯：" + "、".join(no_step))
        else:
            add("典型误用·步号", "OK", f"{len(rows)}/{len(rows)} 引用的 point_id 全部存在于 223 步")

    # ---- 附加 B. 错误码合法性（R7） ----
    code_bad = []
    for r in rows:
        codes = split_ids(r["关联错误码"])
        if not codes:
            code_bad.append(r["law_id"] + "（空）")
        bad = [c for c in codes if c not in ERROR_CODES]
        if bad:
            code_bad.append(f'{r["law_id"]}（{bad}）')
    if code_bad:
        add("错误码", "ERROR", "；".join(code_bad))
    else:
        add("错误码", "OK", f"{len(rows)}/{len(rows)} 取自 21 条枚举（E-01~E-16、E-20~E-24）")

    # ---- 附加 C. 一句话表述字数 ----
    long_ones = [r["law_id"] for r in rows if len(r["一句话表述"].strip()) > 40]
    if long_ones:
        add("一句话表述", "ERROR", f"超 40 字：{long_ones}")
    else:
        add("一句话表述", "OK", f"{len(rows)}/{len(rows)} ≤40 字")

    # ---- 输出 ----
    width = max(dwidth(lbl) for lbl, _, _ in RESULTS) + 2
    for label, status, detail in RESULTS:
        print(f"{pad(label + '：', width)}{detail}  {status}")

    errors = [r for r in RESULTS if r[1] == "ERROR"]
    warns = [r for r in RESULTS if r[1] == "WARN"]
    print("-" * 60)
    if errors:
        print(f"未通过：{len(errors)} 项 ERROR / {len(warns)} 项 WARN")
        return 1
    if warns:
        print(f"硬校验全过，{len(warns)} 项 WARN 需人工/后续裁定（退出码 0）")
        return 0
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

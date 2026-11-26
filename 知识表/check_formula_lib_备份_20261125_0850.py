# -*- coding: utf-8 -*-
"""
公式库五项校验（T09 任务卡 §4 / §5）

用法：
    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python3 知识表/check_formula_lib.py

退出码 0 = 五项全 OK；非 0 = 有 FAIL。
校验对象：
    知识表/公式库_v1.csv
    知识表/符号白名单_v1.csv
    知识表/覆盖率映射_v1.csv（覆盖率用）
"""
import csv
import os
import re
import sys

from sympy import parse_expr
from sympy.parsing.sympy_parser import parse_expr as _pe

BASE = os.path.dirname(os.path.abspath(__file__))
F_LIB = os.path.join(BASE, "公式库_v1.csv")
S_LIB = os.path.join(BASE, "符号白名单_v1.csv")
C_MAP = os.path.join(BASE, "覆盖率映射_v1.csv")

# 分层配额（任务卡 §2.2，上限）与总配额
QUOTA = {"运动学": 12, "力与平衡": 12, "牛顿动力学": 12, "能量": 12,
         "临界与多过程": 10, "万有引力": 8, "动量": 8}
QUOTA_TOTAL = 74
RANGE = (70, 80)

LAWS = {"L-%02d" % i for i in range(1, 13)}
ERR_CODES = {"E-01", "E-02", "E-03", "E-04", "E-05", "E-06", "E-07", "E-08",
             "E-09", "E-10", "E-11", "E-12", "E-13", "E-14", "E-15", "E-16",
             "E-20", "E-21", "E-22", "E-23", "E-24"}
# 29 题编号（A-07 已撤销；B-11 / B-14 为查证缺口，均不计）
PROBLEMS = ({"A-%02d" % i for i in [1, 2, 3, 4, 5, 6, 8, 9, 10]} |
            {"B-%02d" % i for i in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13,
                                    15, 16, 17, 18, 19, 20]})

# 公式_sympy 中允许出现的函数/常量名（不是符号）
ALLOWED_CALLS = {"Rational", "sqrt", "sin", "cos", "tan", "pi", "Integer", "S"}
# sympy 里已被占用的名字：写进表达式会被静默替换（E→自然常数、I→虚数单位、N/S/Q→函数），
# 必须禁用，否则「解析成功」但物理量被换成了别的东西。
RESERVED = {"E", "I", "N", "S", "Q", "O", "C", "beta", "gamma", "zeta", "Lambda",
            "oo", "lambda"}

# 适用条件里的废话（R4：必须可判定）
VAGUE = ["注意使用条件", "视情况", "一般情况", "适当选择", "具体情况具体分析",
         "满足条件即可", "根据题意"]
# 受限 LaTeX 子集（R8）
LATEX_MACROS = {"frac", "sqrt", "cdot", "times", "sin", "cos", "tan", "le", "ge",
                "approx", "mu", "theta", "alpha", "omega", "Delta", "pi"}
LATEX_BANNED = ["\\begin", "\\end", "\\text", "\\displaystyle", "\\left", "\\right",
                "\\bar", "\\vec", "\\mathrm", "\\tag", "\\rho", "\\lambda", "\\circ"]


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def tokens(expr):
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr)


def main():
    fails = []
    formulas = read_csv(F_LIB)
    symbols = read_csv(S_LIB)
    cov = read_csv(C_MAP)

    sym_ids = [r["symbol_id"].strip() for r in symbols]
    sym_set = set(sym_ids)

    # ---------- 1. 条数与分层配额 ----------
    n = len(formulas)
    lo, hi = RANGE
    if n < lo or n > hi:
        fails.append("公式库条数 %d 不在 %d-%d 区间" % (n, lo, hi))
    per = {}
    for r in formulas:
        per[r["层级"]] = per.get(r["层级"], 0) + 1
    over = {k: v for k, v in per.items() if v > QUOTA.get(k, 0)}
    if over:
        fails.append("分层超配额：%s" % over)
    unknown_layer = [k for k in per if k not in QUOTA]
    if unknown_layer:
        fails.append("未知层级：%s" % unknown_layer)

    # ---------- 2. sympy 解析 ----------
    ok_parse, parse_err = 0, []
    expr_syms = {}
    for r in formulas:
        fid, expr = r["formula_id"], r["公式_sympy"].strip()
        bad_tok = [t for t in tokens(expr) if t in RESERVED]
        if bad_tok:
            parse_err.append("%s 含 sympy 保留名 %s" % (fid, bad_tok))
            continue
        try:
            ex = _pe(expr, evaluate=False)
            ex2 = parse_expr(expr)
            expr_syms[fid] = {str(s) for s in ex.free_symbols}
            if ex2.free_symbols != ex.free_symbols:
                parse_err.append("%s 两次解析符号集不一致" % fid)
            ok_parse += 1
        except Exception as e:  # noqa: BLE001
            parse_err.append("%s %s: %s" % (fid, type(e).__name__, e))
    if ok_parse != n:
        fails.extend(["sympy 解析失败：" + s for s in parse_err])
        fails.append("sympy 解析：%d/%d" % (ok_parse, n))

    # ---------- 3. 符号闭合 ----------
    used = set()
    for fid, ss in expr_syms.items():
        missing = ss - sym_set
        if missing:
            fails.append("%s 用了未在册符号 %s" % (fid, sorted(missing)))
        used |= ss
    for r in formulas:  # 符号列表须与表达式一致，防止清单漏写
        fid = r["formula_id"]
        listed = {s.strip() for s in r["符号列表"].split(";") if s.strip()}
        if fid in expr_syms and listed != expr_syms[fid]:
            fails.append("%s 符号列表与表达式不一致：列 %s / 实 %s"
                         % (fid, sorted(listed), sorted(expr_syms[fid])))
        ghost = listed - sym_set
        if ghost:
            fails.append("%s 符号列表含未在册 %s" % (fid, sorted(ghost)))
    # 备注标「非公式符号」的行（如 t2 只服务 answer.schema 的过程时间）不计死行
    exempt = {r["symbol_id"].strip() for r in symbols
              if "非公式符号" in (r.get("备注") or "")}
    dead = [s for s in sym_ids if s not in used and s not in exempt]
    if dead:
        fails.append("符号表死行（未被任何公式引用）：%s" % dead)
    dup = [s for s in set(sym_ids) if sym_ids.count(s) > 1]
    if dup:
        fails.append("符号表重复 id：%s" % dup)

    # ---------- 4. 反例与适用条件 ----------
    ok_rev = 0
    for r in formulas:
        fid = r["formula_id"]
        rev = r["失效反例"].strip()
        cond = r["适用条件"].strip()
        misuse = r["常见误用"].strip()
        if len(rev) < 10:
            fails.append("%s 失效反例为空或过短" % fid)
        elif any(v in rev for v in VAGUE):
            fails.append("%s 失效反例含废话短语" % fid)
        else:
            ok_rev += 1
        if len(cond) < 8 or any(v in cond for v in VAGUE):
            fails.append("%s 适用条件不可判定（疑似废话）" % fid)
        if len(misuse) < 6:
            fails.append("%s 常见误用为空" % fid)

    # ---------- 5. 单位 pint 可解析 ----------
    try:
        import pint
        ureg = pint.UnitRegistry()
    except Exception as e:  # noqa: BLE001
        print("pint 未安装，无法校验单位：%s" % e)
        return 2
    ok_unit = 0
    for r in symbols:
        sid, unit = r["symbol_id"], r["单位_SI"].strip()
        try:
            ureg.parse_units(unit)
            ok_unit += 1
        except Exception:  # noqa: BLE001
            fails.append("单位不可解析：%s → %r" % (sid, unit))
        if not r["量纲"].strip():
            fails.append("量纲为空：%s" % sid)

    # ---------- 附加：外键、题号、错误码、latex 子集、单等号 ----------
    for r in formulas:
        fid = r["formula_id"]
        laws = {x.strip() for x in r["关联定律"].split(";") if x.strip()}
        if not laws or not laws <= LAWS:
            fails.append("%s 关联定律非法：%s" % (fid, sorted(laws)))
        probs = {x.strip() for x in r["用于题号"].split(";") if x.strip()}
        if not probs or not probs <= PROBLEMS:
            fails.append("%s 用于题号越界：%s" % (fid, sorted(probs - PROBLEMS)))
        codes = {x.strip() for x in r["关联错误码"].split(";") if x.strip()}
        if codes - ERR_CODES:
            fails.append("%s 错误码非法：%s" % (fid, sorted(codes - ERR_CODES)))
        latex = r["公式_latex"]
        if latex.count("=") != 1:
            fails.append("%s latex 等号数 %d（R9 只允许一个）" % (fid, latex.count("=")))
        for b in LATEX_BANNED:
            if b in latex:
                fails.append("%s latex 含禁用宏 %s" % (fid, b))
        for m in re.findall(r"\\([A-Za-z]+)", latex):
            if m not in LATEX_MACROS:
                fails.append("%s latex 用了子集外的宏 \\%s" % (fid, m))
        if "'" in latex:
            fails.append("%s latex 含撇号（子集外，改用 v_{1p}）" % fid)
        if not r["是否入白名单"].strip() in ("是", "否"):
            fails.append("%s 是否入白名单 值非法" % fid)

    # ---------- 覆盖率 ----------
    total = len(cov)
    matched = [r for r in cov if r["步类型"] == "方程步" and r["formula_id"].strip()]
    judged = [r for r in cov if r["步类型"] == "判断步"]
    unmatched = [r for r in cov if r["步类型"] == "方程步" and not r["formula_id"].strip()]
    bad_fid = [r["point_id"] for r in matched
               if not all(f.strip() in {x["formula_id"] for x in formulas}
                          for f in r["formula_id"].split(";"))]
    if bad_fid:
        fails.append("覆盖率映射引用了不存在的 formula_id：%s" % bad_fid)
    if unmatched:
        fails.append("采分点步未匹配到公式：%s" % [r["point_id"] for r in unmatched])
    if total != 51:
        fails.append("覆盖率映射应覆盖 51 步，实为 %d 步" % total)

    fk_ok = not any("关联定律非法" in s or "用于题号越界" in s or "错误码非法" in s for s in fails)
    # ---------- 输出 ----------
    ok = not fails
    print("公式库：%d 条（配额 %d，区间 %d-%d）%s"
          % (n, QUOTA_TOTAL, lo, hi, "  OK" if lo <= n <= hi and not over else "  FAIL"))
    print("sympy 解析：%d/%d%s" % (ok_parse, n, "  OK" if ok_parse == n else "  FAIL"))
    print("符号闭合：出现 %d 个符号，%s%s"
          % (len(used), "全部在册" if used <= sym_set and not dead else "存在未在册/死行",
             "  OK" if used <= sym_set and not dead else "  FAIL"))
    print("反例非空：%d/%d%s" % (ok_rev, n, "  OK" if ok_rev == n else "  FAIL"))
    print("单位 pint：%d/%d 可解析%s" % (ok_unit, len(symbols),
          "  OK" if ok_unit == len(symbols) else "  FAIL"))
    print("外键与枚举：定律 %d/%d、题号 %d/%d、错误码 %d/%d 合法%s"
          % (sum(1 for r in formulas if {x.strip() for x in r["关联定律"].split(";")} <= LAWS), n,
             sum(1 for r in formulas if {x.strip() for x in r["用于题号"].split(";")} <= PROBLEMS), n,
             sum(1 for r in formulas if not ({x.strip() for x in r["关联错误码"].split(";")} - ERR_CODES)), n,
             "  OK" if fk_ok else "  FAIL"))
    print("覆盖率：A-01~A-05 的 %d 步中，%d 步可匹配到公式；%d 步为纯判断/结果步（不计）"
          % (total, len(matched), len(judged)))
    print("分层实收：" + " / ".join("%s %d" % (k, per.get(k, 0)) for k in QUOTA))

    if fails:
        print("\n不合格项 %d 条：" % len(fails))
        for s in fails:
            print("  - " + s)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

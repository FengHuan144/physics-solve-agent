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
XLSX = os.path.join(os.path.dirname(BASE), "原始资料", "五卷力学大题_采分点总表_v2.xlsx")

# 覆盖率映射（2026-11-25 11:10 起覆盖全量 27 题）
# 步类型三分：方程步必须指到库内公式；判断步/结果步本不产生新方程，但**不许**挂 formula_id。
COVER_TOTAL = 223
STEP_KINDS = ("方程步", "判断步", "结果步")

# 分层配额（任务卡 §2.2，上限）与总配额
# 2026-11-25 T09R：运动学 12→13（补 F-075 斜抛水平射程）。
# 依据 agent.md:168 的上位区间 70-80；74/12 是 T09 卡自设的分层上限，不是上位约束。
QUOTA = {"运动学": 13, "力与平衡": 12, "牛顿动力学": 12, "能量": 12,
         "临界与多过程": 10, "万有引力": 8, "动量": 8}
QUOTA_TOTAL = 75
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
    # 非公式符号白名单：写死在脚本里，不读数据。
    # 理由（2026-11-25 修正）：原逻辑读「备注含『非公式符号』」做豁免，
    # 任何人往备注写四个字就能让死行过检——豁免条件不能写在被检查的数据里。
    # 2026-11-25 11:20 T08b 扩表：T07 类题型需要的题干状态量，不进任何公式。
    # 加这条豁免必须同时改这里的常量（不许靠备注文本自我豁免，见备份里的反断言）。
    # 2026-11-25 13:25 T00 裁定登记（T08c 申请 6 个）：M0/n/Mp 属 A-10 天体题内推导记号，
    # k1/k2/b2 属 B-20 的 a–F 图读数记号。六者都不进通用公式库，故一律走豁免集合。
    NON_FORMULA_SYMBOLS = {"t2", "t1", "Iimp", "dt", "v2b", "N1", "N2", "d",
                           "M0", "n", "Mp", "k1", "k2", "b2",
                           # 2026-11-25 T08f 登记（B-10 电动机题）：U/I/R_内 三记号只出现在题干
                           # 给定量与 UI=I²R+T₁v 的换算中，不进通用公式库。
                           "Uvolt", "Icur", "Rr",
                           # 2026-11-25 21:33 用户授权登记（A-04 实测缺口）：声速与「时刻」是
                           # 题干给定量/时间轴上的点，不属于任何通用公式的结构符号。
                           "vsnd", "tinst",
                           # 2026-11-25 22:44 用户裁定「k 统一为系数」后登记：k 已改为无量纲
                           # 通用槽（摩擦因数/比值系数/比例常数），承接的是题目自定义的比值，
                           # 本就不该有通用公式。弹簧劲度已拆出 kspring，由 F-014/F-045 引用。
                           "k"}
    dead = [s for s in sym_ids if s not in used and s not in NON_FORMULA_SYMBOLS]
    if dead:
        fails.append("符号表死行（未被任何公式引用）：%s" % dead)
    # 反向断言：豁免集合里的 id 必须真在册，且不得被任何公式引用（防止拿它藏真符号）
    for s in NON_FORMULA_SYMBOLS:
        if s not in sym_set:
            fails.append("非公式符号 %s 不在符号表里" % s)
        if s in used:
            fails.append("非公式符号 %s 被公式引用了，应改为普通符号" % s)
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
        # T09R 拆列：口径由「单列非空」改为「两列各自 ⊆ 29 题」。
        # 被采分点步引用 允许为空（30 条未被引用的公式本就没有）；题内实际用到 同理。
        # 这是拆列带来的语义变化，不是放宽：原来只查 1 列，现在查 2 列，且新增了下方的包含关系。
        for col in ("被采分点步引用", "题内实际用到"):
            probs = {x.strip() for x in r[col].split(";") if x.strip()}
            if not probs <= PROBLEMS:
                fails.append("%s %s 越界：%s" % (fid, col, sorted(probs - PROBLEMS)))
        cited = {x.strip() for x in r["被采分点步引用"].split(";") if x.strip()}
        usedp = {x.strip() for x in r["题内实际用到"].split(";") if x.strip()}
        if not cited <= usedp:
            fails.append("%s 被采分点步引用 未被 题内实际用到 覆盖：%s"
                         % (fid, sorted(cited - usedp)))
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
    bad_kind = [r["point_id"] for r in cov if r["步类型"] not in STEP_KINDS]
    dup = [k for k, v in __import__("collections").Counter(r["point_id"] for r in cov).items() if v > 1]
    matched = [r for r in cov if r["步类型"] == "方程步" and r["formula_id"].strip()]
    judged = [r for r in cov if r["步类型"] == "判断步"]
    results = [r for r in cov if r["步类型"] == "结果步"]
    unmatched = [r for r in cov if r["步类型"] == "方程步" and not r["formula_id"].strip()]
    # 反向纪律：判断步/结果步挂了 formula_id，等于把判定包装成方程，同样算错
    overtagged = [r["point_id"] for r in cov
                  if r["步类型"] in ("判断步", "结果步") and r["formula_id"].strip()]
    bad_fid = [r["point_id"] for r in matched
               if not all(f.strip() in {x["formula_id"] for x in formulas}
                          for f in r["formula_id"].split(";"))]
    if bad_kind:
        fails.append("覆盖率映射的步类型非法（只允许 %s）：%s" % ("/".join(STEP_KINDS), bad_kind))
    if dup:
        fails.append("覆盖率映射 point_id 重复：%s" % dup)
    if bad_fid:
        fails.append("覆盖率映射引用了不存在的 formula_id：%s" % bad_fid)
    if unmatched:
        fails.append("方程步未匹配到公式：%s" % [r["point_id"] for r in unmatched])
    if overtagged:
        fails.append("判断步/结果步不应挂 formula_id：%s" % overtagged)
    if total != COVER_TOTAL:
        fails.append("覆盖率映射应覆盖 %d 步，实为 %d 步" % (COVER_TOTAL, total))

    # 与采分点总表对账（防「映射写完了、采分点又改了」这类双事实源）
    xlsx_note = ""
    if os.path.exists(XLSX):
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(BASE), "采分点", "scripts"))
            from validate_points import load as _load_pts
            pts = {p["point_id"] for p in _load_pts(XLSX)}
            only_map = sorted({r["point_id"] for r in cov} - pts)
            only_xlsx = sorted(pts - {r["point_id"] for r in cov})
            if only_map or only_xlsx:
                fails.append("覆盖率映射与采分点总表不一致：仅映射有 %s；仅总表有 %s"
                             % (only_map[:5], only_xlsx[:5]))
            else:
                xlsx_note = "，与采分点总表 %d 步逐条对齐" % len(pts)
        except Exception as e:  # xlsx 缺失/格式变动不应静默通过
            fails.append("无法与采分点总表对账：%r" % e)

    # 公式库「被采分点步引用」↔ 覆盖率映射 逐条集合相等（T09R 新增）
    # 这是本项目第三次同类漂移：A-06 样例撞 point_id（C11）、采分点依赖图 135 行旧值、
    # 用于题号按知识点推定后未随拆点重跑。前两次靠人眼发现，这条改成机器拦。
    derived = {}
    for r in cov:
        if r["步类型"] == "方程步" and r["formula_id"].strip():
            for fid in r["formula_id"].split(";"):
                derived.setdefault(fid.strip(), set()).add(r["point_id"][:4])
    drift = []
    for r in formulas:
        fid = r["formula_id"]
        col = {x.strip() for x in r["被采分点步引用"].split(";") if x.strip()}
        if col != derived.get(fid, set()):
            drift.append("%s[列:%s|映射:%s]"
                         % (fid, "".join(sorted(col)), "".join(sorted(derived.get(fid, set())))))
    if drift:
        fails.append("题号列与覆盖率映射不一致 %d 行：%s" % (len(drift), drift[:5]))
        recheck_note = ""
    else:
        recheck_note = "；题号列 %d 条与映射逐条相等" % len(formulas)

    fk_ok = not any("关联定律非法" in s or "越界" in s or "错误码非法" in s or "未被" in s
                    for s in fails)
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
    print("外键与枚举：定律 %d/%d、题号(两列) %d/%d、错误码 %d/%d 合法%s"
          % (sum(1 for r in formulas if {x.strip() for x in r["关联定律"].split(";")} <= LAWS), n,
             sum(1 for r in formulas
                 if {x.strip() for x in r["被采分点步引用"].split(";") if x.strip()} <= PROBLEMS
                 and {x.strip() for x in r["题内实际用到"].split(";") if x.strip()} <= PROBLEMS), n,
             sum(1 for r in formulas if not ({x.strip() for x in r["关联错误码"].split(";")} - ERR_CODES)), n,
             "  OK" if fk_ok else "  FAIL"))
    print("覆盖率：全量 %d 步中，方程步 %d/%d 可匹配公式；判断步 %d、结果步 %d（本不产生方程）%s"
          % (total, len(matched), total - len(judged) - len(results),
             len(judged), len(results), xlsx_note + recheck_note))
    print("分层实收：" + " / ".join("%s %d" % (k, per.get(k, 0)) for k in QUOTA))

    if fails:
        print("\n不合格项 %d 条：" % len(fails))
        for s in fails:
            print("  - " + s)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

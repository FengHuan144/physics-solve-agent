#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T07 基线实验 · 判分脚本

读 answers_std.csv + raw/{variant}/{qid}.json → 写 scores.csv
不改 raw，不改题干原文。

判分口径（任务卡 R7/R8）：
    三态 correct / wrong / undecidable；undecidable 不进准确率分母。
    数值：相对容差 2%。
    多解：全部命中才 correct，漏解记 wrong + failure_type=miss_root。
    非数值（序号、能否）：label_nec_suff 规则——结论与支撑判据缺一不可；
    只有结论没有依据判 wrong(insufficient_derivation)，判不出走 undecidable。
    符号：sympy 化简比对（开启隐式乘法）；解析不出 → undecidable。

多分量小问（一小问两个答案，如 A-06 (1) 的 v 与 t）：
    answers_std 里拆成 1.1 / 1.2 两行，判分按出现次序取第 k 个带对应单位的量。

人工复核通道：
    manual_overrides.csv：qid,variant,verdict,failure_type,note
    score.py 用其覆盖自动判分，scores.notes 标 [manual]。自动判分仍可复现。

用法：
    python 评测/基线/score.py [--variant v1]
"""

import argparse
import csv
import json
import math
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
TOL = 0.02
NEAR_MISS = 0.06

G_MAP = {
    "A-06": "10", "A-08": "10", "A-09": "10", "A-10": "-",
    "B-01": "-", "B-02": "symbolic", "B-03": "10", "B-04": "10",
    "B-05": "10", "B-06": "-", "B-07": "symbolic", "B-08": "symbolic",
    "B-09": "10", "B-10": "10", "B-12": "10", "B-13": "10",
    "B-15": "symbolic", "B-16": "symbolic", "B-17": "symbolic",
    "B-18": "10", "B-19": "10", "B-20": "10",
}

SUP_MAP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
           "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-"}


def desup(s, to_pow=False):
    """上标数字：v² → v**2（to_pow）或 v2"""
    def rep(m):
        body = "".join(SUP_MAP[ch] for ch in m.group())
        return ("**" + body) if to_pow else body
    return re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+", rep, s)


# ------------------------------------------------------------------ 数值
def to_number(s):
    if s is None:
        return None
    t = str(s).strip()
    t = (t.replace("−", "-").replace("－", "-").replace("—", "-")
          .replace("，", ",").replace(" ", "").replace("\u3000", ""))
    t = desup(t)
    t = t.replace("×10", "e").replace("x10", "e").replace("*10", "e")
    t = re.sub(r"e\^", "e", t)
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)", t)
    if m:
        try:
            return float(m.group(1)) / float(m.group(2))
        except ZeroDivisionError:
            return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\*?√(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1)) * math.sqrt(float(m.group(2)))
    m = re.fullmatch(r"√(\d+(?:\.\d+)?)", t)
    if m:
        return math.sqrt(float(m.group(1)))
    try:
        return float(t)
    except ValueError:
        return None


def num_close(got, std):
    if got is None or std is None:
        return False
    if std == 0:
        return abs(got) < 1e-9
    return abs(got - std) / abs(std) <= TOL


def near_miss(got, std):
    if got is None or std in (None, 0):
        return False
    return TOL < abs(got - std) / abs(std) <= NEAR_MISS


# ------------------------------------------------------------------ 单位
UNIT_PAT = {
    "s":     r"(?<![A-Za-z/²])\s*s(?!\s*[/A-Za-z])",
    "m":     r"(?<![A-Za-z/])\s*m(?!\s*/|\s*[A-Za-z]|²|2)",
    "m/s":   r"m\s*/\s*s(?!\s*[²2])",
    "m/s²":  r"m\s*/\s*s\s*\^?\s*[²2]",
    "N":     r"(?<![A-Za-z])\s*N(?![A-Za-z])",
    "J":     r"(?<![A-Za-z])\s*J(?![A-Za-z])",
    "W":     r"(?<![A-Za-z])\s*W(?![A-Za-z])",
    "kg":    r"kg(?![A-Za-z])",
    "°":     r"[°度]",
}


def unit_near(text, unit):
    """单位出现在 text 里（text 是数值附近的一小段）"""
    if unit in ("—", "-", "", None):
        return True
    pat = UNIT_PAT.get(unit)
    if pat is None:
        return unit.replace(" ", "") in text.replace(" ", "")
    return re.search(pat, text) is not None


# ------------------------------------------------------------------ 符号
SYMS = ["G", "M", "m", "R", "r", "n", "g", "v", "t", "L", "d", "l",
        "mu", "theta", "h", "E_p", "T", "F", "a", "E", "P", "x", "s", "k", "Q"]


def expand_sqrt(s):
    """把 √ 展开成 sqrt(...)：支持嵌套括号，√2d 按 √2·d 处理"""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch != "√":
            out.append(ch)
            i += 1
            continue
        j = i + 1
        if j < n and s[j] == "(":
            depth, k = 0, j
            while k < n:
                if s[k] == "(":
                    depth += 1
                elif s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            atom = s[j + 1:k]
            out.append("sqrt(%s)" % expand_sqrt(atom))
            i = k + 1
        else:
            m = re.match(r"\d+(?:\.\d+)?", s[j:])
            if m:
                out.append("sqrt(%s)" % m.group())
                i = j + len(m.group())
            elif j < n and (s[j].isalpha() or s[j] == "_"):
                # 取单个符号（mu/theta 这类在替换后已是多字母，按整段取）
                m = re.match(r"(mu|theta|[A-Za-z_])", s[j:])
                tok = m.group() if m else s[j]
                out.append("sqrt(%s)" % tok)
                i = j + len(tok)
            else:
                out.append("√")
                i += 1
    return "".join(out)


def norm_expr(s):
    if s is None:
        return None
    t = str(s).strip()
    # 先把 sinθ / cosθ 这类无括号函数补上括号（在符号替换前做）
    t = re.sub(r"(sin|cos|tan|ln|log)\s*([θμ])", r"\1(\2)", t)
    t = re.sub(r"(sin|cos|tan)\s*([A-Za-z])(?![A-Za-z])", r"\1(\2)", t)
    t = desup(t, to_pow=True)
    rep = [("θ", "theta"), ("μ", "mu"), ("Δ", "D"), ("′", ""), ("＇", ""),
           (" ", ""), ("\u3000", ""), ("＝", "="), ("＋", "+"), ("−", "-"),
           ("－", "-"), ("×", "*"), ("·", "*"), ("÷", "/"), ("，", ","),
           ("（", "("), ("）", ")"), ("［", "("), ("］", ")"),
           ("[", "("), ("]", ")"), ("^", "**")]
    for a, b in rep:
        t = t.replace(a, b)
    t = t.replace("½", "(1/2)").replace("¼", "(1/4)").replace("¾", "(3/4)")
    t = expand_sqrt(t)
    # 隐式乘法补显式：字母/右括号紧跟 sqrt( 会粘成 rsqrt(...) 这种假函数名
    t = re.sub(r"(?<=[A-Za-z0-9_)])sqrt\(", "*sqrt(", t)
    # 小写紧跟大写（hE_p、GM 一类）补 *
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", "*", t)
    # mu 与后面的函数名粘连（μcosθ → mucos(theta)）补 *
    t = re.sub(r"(?<=[a-z])(?=(?:sin|cos|tan|sqrt|log|ln)\()", "*", t)
    return t


def _numeric_agree(ea, eb, sp):
    """
    符号化简不动的等价式（根号分支、等价写法），用数值采样兜底：
    在正有理点各取 12 组，两式值全一致才算等价。
    只要有一组采样算不出来（除零、复数值），本轮不采信 → 返回 False。
    """
    import random
    syms = sorted(ea.free_symbols | eb.free_symbols, key=lambda s: s.name)
    try:
        fa = sp.lambdify(syms, ea, "math")
        fb = sp.lambdify(syms, eb, "math")
    except Exception:
        return False
    rng = random.Random(20261125)
    ok_n = 0
    for _ in range(12):
        vals = [rng.choice([0.7, 1.3, 1.7, 2.3, 3.1, 4.7]) for _ in syms]
        try:
            va, vb = fa(*vals), fb(*vals)
        except Exception:
            continue
        if isinstance(va, complex) or isinstance(vb, complex):
            continue
        if vb == 0:
            continue
        if abs(va - vb) / max(abs(vb), 1e-12) > 1e-9:
            return False
        ok_n += 1
    return ok_n >= 6


def sym_equal(got, std):
    """返回 (是否等价, 是否可解析)"""
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations, implicit_multiplication_application)
    except ImportError:
        return False, False
    a, b = norm_expr(got), norm_expr(std)
    if not a or not b:
        return False, False
    local = {k: sp.Symbol(k) for k in SYMS}
    tr = standard_transformations + (implicit_multiplication_application,)
    try:
        ea = parse_expr(a, transformations=tr, local_dict=local)
        eb = parse_expr(b, transformations=tr, local_dict=local)
    except Exception:
        return False, False
    try:
        if sp.simplify(ea - eb) == 0:
            return True, True
        if ea != 0 and eb != 0:
            ratio = sp.simplify(ea / eb)
            if getattr(ratio, "is_number", False) and abs(complex(ratio) - 1) < 1e-9:
                return True, True
        if _numeric_agree(ea, eb, sp):
            return True, True
        return False, True
    except Exception:
        return False, True


# ------------------------------------------------------------------ LaTeX
def _group(s, i):
    """从 i 起取一个参数：{...} 花括号组，或单个字符/命令"""
    n = len(s)
    if i >= n:
        return "", i
    if s[i] == "{":
        depth, k = 0, i
        while k < n:
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        return s[i + 1:k], k + 1
    if s[i] == "\\":
        m = re.match(r"\\[A-Za-z]+", s[i:])
        if m:
            return m.group(), i + len(m.group())
        return s[i:i + 2], i + 2
    return s[i], i + 1


def latex_to_plain(s):
    """
    模型大量输出 LaTeX（\\frac{1}{3}、\\text{ m/s}、\\boxed{}）：
    抽答案前先降成可读文本。\\boxed 保留内容，供"结论区"优先取用。
    """
    if not s:
        return ""
    t = s
    # 数学定界符
    for a, b in [("\\(", " "), ("\\)", " "), ("\\[", " "), ("\\]", " "),
                 ("$$", " "), ("$", " ")]:
        t = t.replace(a, b)
    # \frac 递归展开
    guard = 0
    while "\\frac" in t and guard < 500:
        guard += 1
        i = t.find("\\frac")
        a, j = _group(t, i + 5)
        b, k = _group(t, j)
        simple = re.fullmatch(r"-?\d+(?:\.\d+)?", a) and re.fullmatch(r"-?\d+(?:\.\d+)?", b)
        t = t[:i] + (("%s/%s" % (a, b)) if simple else "((%s)/(%s))" % (a, b)) + t[k:]
    # \text/\mathrm 去壳留内容
    for cmd in ("\\text", "\\mathrm", "\\boxed", "\\left", "\\right"):
        guard = 0
        while cmd + "{" in t and guard < 500:
            guard += 1
            i = t.find(cmd + "{")
            inner, k = _group(t, i + len(cmd))
            t = t[:i] + inner + t[k:]
        t = t.replace(cmd, "")
    for a, b in [("\\cdot", "*"), ("\\times", "*"), ("\\div", "/"),
                 ("\\approx", "≈"), ("\\leq", "<="), ("\\geq", ">="),
                 ("\\quad", " "), ("\\qquad", " "), ("\\,", " "),
                 ("\\;", " "), ("\\!", " "), ("\\ ", " "),
                 ("\\pi", "pi"), ("\\sqrt", "sqrt"), ("\\\\", "\n")]:
        t = t.replace(a, b)
    t = re.sub(r"\^\s*\{([^{}]*)\}", r"^\1", t)
    # sqrt{...} 的花括号换成圆括号（sqrt 是函数，不是分组）
    guard = 0
    while "sqrt{" in t and guard < 500:
        guard += 1
        i = t.find("sqrt{")
        inner, k = _group(t, i + 4)
        t = t[:i] + "sqrt(" + inner + ")" + t[k:]
    # 希腊字母与度数符号
    for a, b in [("\\circ", "°"), ("\\degree", "°"),
                 ("\\sin", "sin"), ("\\cos", "cos"), ("\\tan", "tan"),
                 ("\\lg", "lg"), ("\\ln", "ln"), ("\\alpha", "alpha"),
                 ("\\beta", "beta"), ("\\theta", "theta"), ("\\mu", "mu"),
                 ("\\omega", "omega"), ("\\pi", "pi"), ("\\Delta", "D")]:
        t = t.replace(a, b)
    t = re.sub(r"\^\s*°", "°", t)
    # 裸露的 _ 与 ^ 保留（符号判分要用），去掉多余反斜杠命令
    t = re.sub(r"\\[A-Za-z]+", " ", t)
    return t


def parse_boxes(plain):
    """
    取 \\boxed 内容并按 '(n)' 归到小问。
    注意：必须在 latex_to_plain 之前解析，否则花括号已被拆掉。
    """
    out = {}
    i = 0
    while True:
        i = plain.find("\\boxed", i)
        if i < 0:
            break
        inner, k = _group(plain, i + 6)
        txt = latex_to_plain(inner)
        m = re.match(r"\s*[（(]\s*(\d)\s*[）)]", txt)
        if m:
            # 去掉行首的 "(n)" 标记，否则那个 n 会被当成答案数字
            out.setdefault(m.group(1), txt[m.end():].strip())
        i = k
    return out


# ------------------------------------------------------------------ 抽取
SUB_PAT = re.compile(r"[（(]\s*(\d)\s*[）)]")

NUM_RE = re.compile(
    r"(-?\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?)"
    r"|(-?\d+(?:\.\d+)?\s*\*?√\d+(?:\.\d+)?)"
    r"|(√\d+(?:\.\d+)?)"
    r"|(-?\d+(?:\.\d+)?\s*[*×x]\s*10\s*\^?\s*\{?\s*-?\d+\s*\}?)"
    r"|(-?\d+(?:\.\d+)?)")


def split_by_sub(content):
    hits = list(SUB_PAT.finditer(content))
    if not hits:
        return {"*": content}
    out = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(content)
        out.setdefault(m.group(1), content[m.end():end])
    return out


def numbers_in(text):
    out = []
    for m in NUM_RE.finditer(text):
        raw = next(g for g in m.groups() if g)
        # 下标/指数里的数字不是答案：v_0 的 0、t^2 的 2、m_1 的 1
        prev = text[m.start() - 1] if m.start() > 0 else ""
        if prev in "_^":
            continue
        v = to_number(raw)
        if v is not None:
            out.append((raw.strip(), v, m.start(), m.end()))
    return out


def candidates_with_unit(chunk, unit, win=16):
    """带单位窗口过滤的数值候选；一次都没命中就退回全部数值"""
    allc = numbers_in(chunk)
    if unit in ("—", "-", "", None):
        return allc
    kept = []
    for raw, v, s, e in allc:
        seg = chunk[max(0, s - 4):min(len(chunk), e + win)]
        if unit_near(seg, unit):
            kept.append((raw, v, s, e))
    return kept or allc


# 非数值答案的「充分必要匹配」判据。
# 只命中结论不算——结论可能是蒙的；必须同时给出与标准答案同构的支撑判据。
NEC_SUFF = {
    "B-01:2": {
        "support": [r"(?:到不了|不能|不超过|无法)\s*(?:经过)?\s*(?:第)?\s*5\s*号",
                    r"4\.3[0-9]",
                    r"[<>＜＞]\s*3\.6",
                    r"3\.00125"],
        "std_concl": "4",
        "why": "缺与 5 号（或 3.6 m）的比较，未证明到不了 5 号",
    },
    "B-09:1": {
        "support": [r"=\s*s_?2\b", r"s_2\s*="],
        "std_concl": "能",
        "why": "缺 x = s₂ 的等式（0.02 m = 2.0×10⁻² m），未证明恰好到达",
    },
}


def _b01_concl(plain):
    """结论取最后一条结论性表述，避开过程描述里的「经过 1 号」"""
    cands = re.findall(r"(?:最远|最终|因此|所以|故)[^。]{0,24}?(?:经过|停在)\s*(?:第)?\s*(\d)\s*号", plain)
    if not cands:
        cands = re.findall(r"(?:经过|停在)\s*(?:第)?\s*(\d)\s*号", plain)
    return cands[-1] if cands else None


def _b09_concl(plain):
    """否定优先：先看「不能/无法」，避免「不能滑到」被读成「能滑到」"""
    if re.search(r"(?:不能|无法|不可能|不可以)\s*(?:滑动?到|滑到|到达)\s*(?:边框)?\s*a", plain):
        return "不能"
    if re.search(r"(?:能|可以|会)\s*(?:滑动?到|滑到|到达)\s*(?:边框)?\s*a", plain):
        return "能"
    return None


def judge_label_nec_suff(qid, sub_no, plain):
    """
    充分必要匹配：结论正确 且 支撑判据到位，才判 correct。
    返回 (verdict, detail)
    """
    key = "%s:%s" % (qid, sub_no)
    spec = NEC_SUFF.get(key)
    if not spec:
        return "undecidable", "no_criteria"

    got = _b01_concl(plain) if qid == "B-01" else _b09_concl(plain)
    if got is None:
        return "undecidable", "concl_not_found"
    if got != spec["std_concl"]:
        return "wrong", "concl=%s≠%s" % (got, spec["std_concl"])
    hit = [p for p in spec["support"] if re.search(p, plain)]
    if not hit:
        return "wrong", "insufficient_derivation｜%s" % spec["why"]
    return "correct", "nec_suff_ok｜support=%s" % hit[0][:22]


def extract_symbolic(chunk, std):
    """
    在结论区里找等式右端；把 "v=…, r>R" 这类复合片段按逗号/分号切开逐段试。
    status: match / mismatch / unparsable / no_expr
    """
    tail = chunk[-1200:]
    eqs = re.findall(r"[=＝]\s*([^\n。]{1,90})", tail)
    if not eqs:
        return None, None, "no_expr"

    frags = []
    for cand in reversed(eqs):
        parts = re.split(r"[,，;；、]|\s{2,}|以及|其中|式中|方向|单位", cand)
        for pt in parts:
            pt = pt.strip(" .。)）")
            if pt:
                frags.append(pt)

    tried = []
    for c in frags:
        ok, parsable = sym_equal(c, std)
        tried.append((c, ok, parsable))
        if ok:
            return c, c, "match"
    if not tried:
        return None, None, "no_expr"
    for c, _, parsable in tried:
        if parsable:
            return c, c, "mismatch"
    return tried[0][0], tried[0][0], "unparsable"


# ------------------------------------------------------------------ 判分
UNIT_LIST = ["m/s2", "m/s^2", "m/s²", "m/s", "kg", "°", "N", "J", "W", "s", "m"]


def norm_unit(u):
    if not u or u in ("—", "-", ""):
        return ""
    return u.replace("^2", "2").replace("²", "2").replace(" ", "")


def final_region(plain):
    """取「最终答案/综上」之后的结论区；没有标记就取末段"""
    best = -1
    for key in ("最终答案", "综上所述", "综上", "答案是", "答案："):
        i = plain.rfind(key)
        if i > best:
            best = i
    if best > 0 and best > len(plain) * 0.3:
        return plain[best:]
    return plain[-max(260, int(len(plain) * 0.30)):]


def squeeze_thousands(t):
    """'1 200 N' 的空格千分位：并成 1200"""
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(?<=\d)\s(?=\d{3}(?!\d))", "", t)
    return t


def infer_unit(text, end):
    seg = text[end:end + 16].lstrip()
    for u in UNIT_LIST:
        if seg.startswith(u):
            return norm_unit(u)
    return ""


def build_atoms(region):
    txt = squeeze_thousands(region)
    return [{"raw": raw, "val": v, "unit": infer_unit(txt, e), "pos": s}
            for raw, v, s, e in numbers_in(txt)]


def assign_components(atoms, comps):
    """
    原子 → 分量对齐：先严格按单位+出现次序，单位缺失的原子留到第二轮补。
    这样 (1) 里两个答案（v 与 t）不会互相串位。
    """
    res, used, cur = {}, set(), 0
    for c in comps:
        want = norm_unit(c["unit"])
        for i in range(cur, len(atoms)):
            if i in used:
                continue
            if atoms[i]["unit"] == want:
                res[c["sub_no"]] = atoms[i]
                used.add(i)
                cur = i + 1
                break
    for c in comps:
        if c["sub_no"] in res:
            continue
        for i, a in enumerate(atoms):
            if i in used or a["unit"] != "":
                continue
            res[c["sub_no"]] = a
            used.add(i)
            break
    return res


def judge_question(qid, variant, rec, comps):
    content = rec.get("content") or ""
    if not rec.get("ok"):
        return "undecidable", "api_error", "请求失败：" + str(rec.get("failure"))
    if rec.get("finish_reason") == "length":
        return "undecidable", "truncated", "输出被截断，答案不完整"

    plain = latex_to_plain(content)
    region = final_region(plain)
    atoms = build_atoms(region)
    numeric = [c for c in comps if c["tolerance_rule"] not in ("symbolic", "label", "label_nec_suff")
               and c["is_multi"] != "1"]
    assigned = assign_components(atoms, numeric)

    verdicts, notes = [], []
    for c in comps:
        if c["decidable"] == "no":
            verdicts.append("undecidable")
            notes.append("%s:decidable=no" % c["sub_no"])
            continue

        if c["tolerance_rule"] == "symbolic":
            got, raw, why = extract_symbolic(region, c["answer_value"])
            if why != "match":
                got2, raw2, why2 = extract_symbolic(plain, c["answer_value"])
                if why2 == "match":
                    got, raw, why = got2, raw2, why2
            if why == "match":
                verdicts.append("correct")
                notes.append("%s:sym=%s" % (c["sub_no"], raw))
            elif why == "mismatch":
                verdicts.append("wrong")
                notes.append("%s:sym got=%s std=%s" % (c["sub_no"], raw, c["answer_value"]))
            else:
                verdicts.append("undecidable")
                notes.append("%s:symbolic_%s" % (c["sub_no"], why))
            continue

        if c["tolerance_rule"] in ("label", "label_nec_suff"):
            vd, det = judge_label_nec_suff(qid, c["sub_no"], plain)
            verdicts.append(vd)
            notes.append("%s:label %s" % (c["sub_no"], det))
            continue

        if c["is_multi"] == "1":
            stds = [to_number(x) for x in c["answer_value"].split("|")]
            hit = sum(1 for st in stds if any(num_close(a["val"], st) for a in atoms))
            verdicts.append("correct" if hit == len(stds) else "wrong")
            notes.append("%s:roots %d/%d" % (c["sub_no"], hit, len(stds)))
            continue

        a = assigned.get(c["sub_no"])
        if not a:
            verdicts.append("undecidable")
            notes.append("%s:no_atom" % c["sub_no"])
            continue
        std = to_number(c["answer_value"])
        ok = num_close(a["val"], std)
        verdicts.append("correct" if ok else "wrong")
        nm = ""
        if not ok and near_miss(a["val"], std):
            nm = "(near_miss %.1f%%)" % (abs(a["val"] - std) / abs(std) * 100)
        notes.append("%s:got=%s%s std=%s%s" % (c["sub_no"], a["raw"],
                                               ("[" + a["unit"] + "]") if a["unit"] else "",
                                               c["answer_value"], nm))

    if "wrong" in verdicts:
        verdict = "wrong"
    elif all(v == "undecidable" for v in verdicts):
        verdict = "undecidable"
    elif "undecidable" in verdicts:
        verdict = "undecidable"
    else:
        verdict = "correct"

    ft = "none"
    joined = " ".join(notes)
    if verdict == "wrong":
        miss = re.search(r"roots (\d)/(\d)", joined)
        ft = "miss_root" if (miss and miss.group(1) != miss.group(2)) else "calc"
    elif verdict == "undecidable":
        ft = "truncated" if "truncated" in joined else "format"
    return verdict, ft, joined


def load_std():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "answers_std.csv"), encoding="utf-8")))
    by_q = {}
    for r in rows:
        by_q.setdefault(r["qid"], []).append(r)
    return by_q


def load_overrides():
    p = os.path.join(ROOT, "manual_overrides.csv")
    if not os.path.exists(p):
        return {}
    return {(r["qid"], r["variant"]): r
            for r in csv.DictReader(open(p, encoding="utf-8"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default=None)
    args = ap.parse_args()

    std = load_std()
    overrides = load_overrides()
    variants = [args.variant] if args.variant else ["v1", "v2", "v3"]
    out_rows = []

    for v in variants:
        d = os.path.join(ROOT, "raw", v)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            qid = fn[:-5]
            rec = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            comps = std.get(qid, [])
            if not comps:
                verdict, ft, note = "undecidable", "format", "answers_std 无此题"
            else:
                verdict, ft, note = judge_question(qid, v, rec, comps)
            ov = overrides.get((qid, v))
            if ov:
                verdict, ft = ov["verdict"], ov.get("failure_type", ft)
                note = "[manual] " + ov.get("note", "") + " || auto: " + note
            usage = rec.get("usage") or {}
            out_rows.append({
                "qid": qid, "variant": v, "verdict": verdict,
                "g_used": G_MAP.get(qid, "?"),
                "elapsed_s": rec.get("elapsed_s") if rec.get("elapsed_s") is not None else "",
                "prompt_tokens": usage.get("prompt_tokens", ""),
                "completion_tokens": usage.get("completion_tokens", ""),
                "failure_type": ft, "notes": note[:800],
            })

    fields = ["qid", "variant", "verdict", "g_used", "elapsed_s",
              "prompt_tokens", "completion_tokens", "failure_type", "notes"]
    with open(os.path.join(ROOT, "scores.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    print("scores.csv 写入 %d 行" % len(out_rows))
    for v in variants:
        rs = [r for r in out_rows if r["variant"] == v]
        if not rs:
            continue
        c = sum(1 for r in rs if r["verdict"] == "correct")
        wr = sum(1 for r in rs if r["verdict"] == "wrong")
        ud = sum(1 for r in rs if r["verdict"] == "undecidable")
        den = c + wr
        print("  %s: n=%d correct=%d wrong=%d undecidable=%d 准确率=%s"
              % (v, len(rs), c, wr, ud, ("%.1f%%" % (c / den * 100)) if den else "NA"))


if __name__ == "__main__":
    main()

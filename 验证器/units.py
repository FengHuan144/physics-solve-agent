# -*- coding: utf-8 -*-
"""units.py — 白名单读取 + 符号→pint 单位 + 量纲遍历。

L2 的底座。三条硬约束（T12a 卡 §3.1）：

1. **不用 pint 的 sympy 集成**（不存在稳定集成）：自己遍历表达式树，
   叶子 Symbol 转成 ``ureg.Quantity(1, 单位)``，逐层合成量纲。
2. **单位只取白名单的「单位_SI」列**。题干里的 ``m/s`` 有四种写法变体，
   一律不作准入；白名单是唯一准入名单。
3. **不用 eval()**。``sympify`` 之前先做标识符白名单校验：出现白名单外的
   名字、sympy 保留名、等号、``^``、非 ASCII 字符，一律 DataError。

两类异常分开：
- ``DataError``：上游数据问题（R5）。报出来、跳过该步，绝不静默修。
- ``DimError``：量纲遍历失败（L2 的判定结果，对应 E-12）。
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

import pint
import sympy
from sympy import Integer, Rational, S, Symbol, sympify

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
SYMBOL_CSV = PROJECT_ROOT / "知识表" / "符号白名单_v1.csv"
FORMULA_CSV = PROJECT_ROOT / "知识表" / "公式库_v1.csv"

#: sympy 串里允许出现的「非物理量」名字（函数/常量）
ALLOWED_CALLS = {
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "Rational": Rational,
    "Integer": Integer,
    "S": S,
    "pi": sympy.pi,
}

#: sympy 已占用、写进表达式会被静默替换成别的东西的名字（T09 已踩过）
RESERVED = {
    "E", "I", "N", "Q", "O", "C", "beta", "gamma", "zeta", "Lambda",
    "oo", "lambda", "nan", "zoo", "True", "False", "None",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: 允许的字符集。逗号留给 Rational(1,2)；点号留给小数（Schema 禁止，这里只放行不认可）
_CHARSET = re.compile(r"^[A-Za-z0-9_+\-*/().,\s]+$")


class DataError(Exception):
    """上游数据问题。不静默修，报出来并跳过该步（卡 R5）。"""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message
        super().__init__(f"{kind}: {message}")


class DimError(Exception):
    """量纲遍历失败（L2 判 E-12 的依据）。

    kind:
      - ``add``  ：加减项量纲不一致
      - ``func`` ：sin/cos/tan/exp/log 的参数带量纲
      - ``pow``  ：指数带量纲或含符号
      - ``leaf`` ：遇到不认识的节点
    """

    def __init__(self, kind: str, message: str, terms=None):
        self.kind = kind
        self.message = message
        self.terms = terms or []
        super().__init__(message)


class DimUndecidable(Exception):
    """量纲**不可判定**——不是判错，是没资格判。L2 须落 ``na``，不得落 ``fail``。

    只在一种情形抛：加减式里有一项的**数值系数可能带单位**。

    例：模型写 ``L - Rational(1,2)*(6-2)*t**2``。这里 ``6`` 与 ``2`` 是 a 轴读数
    （m/s²），``½·4·t² = 2t²`` 的量纲是 m，与 ``L`` 一致，式子是对的。
    但 sympy 串里 ``2`` 只剩一个裸数字，单位信息已经丢了——遍历器只能看到
    ``s²``，于是判「加减项量纲不一致」。这是**验证器的信息盲区**，不是模型的错。

    取舍（2026-11-25 裁定，用户「按你的来」）：宁可放过，不可冤枉。
    代价明写：``m*v**2 - 5`` 这类**真错**也抓不到（5 无符号，本来就被跳过）；
    更一般地，凡是「先算系数再列式」的写法，L2 在这类步上失去判错能力，
    退化为 ``na``。根因治理在生成侧——``equation.sympy`` 不许把单位算进系数。
    """

    def __init__(self, kind: str, message: str, terms=None):
        self.kind = kind
        self.message = message
        self.terms = terms or []
        super().__init__(message)


@lru_cache(maxsize=1)
def ureg() -> pint.UnitRegistry:
    """全局唯一 UnitRegistry。pint 的注册表构造不便宜，缓存住。"""
    return pint.UnitRegistry()


@lru_cache(maxsize=4)
def load_symbols(path: str | None = None) -> dict[str, dict]:
    """读符号白名单。返回 ``{symbol_id: {unit, dimension, canonical, meaning}}``。"""
    p = Path(path) if path else SYMBOL_CSV
    if not p.exists():
        raise FileNotFoundError(f"符号白名单不存在：{p}")
    out: dict[str, dict] = {}
    with open(p, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            sid = (row.get("symbol_id") or "").strip()
            if not sid:
                continue
            out[sid] = {
                "unit": (row.get("单位_SI") or "").strip(),
                "dimension": (row.get("量纲") or "").strip(),
                "canonical": (row.get("规范写法") or "").strip(),
                "meaning": (row.get("含义") or "").strip(),
            }
    if not out:
        raise ValueError(f"符号白名单为空：{p}")
    return out


def unit_map(path: str | None = None) -> dict[str, str]:
    """``{symbol_id: 单位_SI}``，pint 串。"""
    return {k: v["unit"] for k, v in load_symbols(path).items()}


def parse_sympy(text: str, symbols: dict | None = None) -> sympy.Expr:
    """把 ``equation.sympy`` 解析成 sympy 表达式；越界一律 DataError。

    入参是「左边减右边」的式子（Schema 硬规定）。这里**不做任何修补**：
    有等号、有 ``^``、有白名单外的符号，都按上游数据问题报出来。
    """
    if text is None:
        raise DataError("empty", "sympy 串为空")
    s = str(text).strip()
    if not s:
        raise DataError("empty", "sympy 串为空")
    if "=" in s:
        raise DataError("eq_sign", f"含等号「=」，Schema 要求写「左边减右边」：{s}")
    if "^" in s:
        raise DataError("caret", f"用 ^ 表示幂，应为 **：{s}")
    if not _CHARSET.match(s):
        bad = sorted({c for c in s if not re.match(r"[A-Za-z0-9_+\-*/().,\s]", c)})
        raise DataError("charset", f"含非法字符 {bad}（中文/希腊字母/全角符号）：{s}")

    syms = symbols if symbols is not None else load_symbols()
    names = _IDENT.findall(s)
    for name in names:
        if name in RESERVED:
            raise DataError("reserved", f"用了 sympy 保留名「{name}」，会被静默替换：{s}")
        if name not in syms and name not in ALLOWED_CALLS:
            raise DataError("unknown_symbol", f"符号「{name}」不在白名单：{s}")

    locals_ = {k: Symbol(k) for k in syms}
    locals_.update(ALLOWED_CALLS)
    try:
        expr = sympify(s, locals=locals_)
    except Exception as exc:  # noqa: BLE001  sympy 的异常类型太杂，统一收口
        raise DataError("parse", f"sympy 解析失败（{type(exc).__name__}）：{s}") from exc

    if not isinstance(expr, sympy.Expr):
        raise DataError("parse", f"解析结果不是表达式：{s}")
    stray = {str(x) for x in expr.free_symbols} - set(syms)
    if stray:
        raise DataError("unknown_symbol", f"表达式里出现未登记符号 {sorted(stray)}：{s}")
    return expr


def parse_unit_text(text: str):
    """把 ``value.unit`` 这类写法转成 pint 单位；失败抛 DataError。"""
    if text is None or str(text).strip() == "":
        raise DataError("unit_empty", "单位为空")
    norm = str(text).strip().replace("^", "**")
    try:
        return ureg().Unit(norm)
    except Exception as exc:  # noqa: BLE001
        raise DataError("unit_not_pint", f"单位不是 pint 可解析串：{text!r}") from exc


#: 无量纲的几种写法（Schema 的 given.unit 规定「无量纲写 1」）
_DIMLESS_TEXT = {"", "-", "1", "dimensionless", "无量纲"}


@lru_cache(maxsize=1)
def _whitelist_units() -> frozenset[str]:
    """白名单「单位_SI」列出现过的写法（唯一准入名单）。"""
    return frozenset(u for u in unit_map().values() if u)


def to_si(number, unit=None, symbol: str | None = None) -> float:
    """把一处数值按 ``unit`` 换算到 SI 基本单位，返回数值（T12aR2 卡 §3.3）。

    这是 L1 读任何 ``number`` 的**唯一入口**。四条规则：

    1. ``unit`` 为空 / ``None`` / ``-`` / ``1`` / ``dimensionless`` → 原值
       （无量纲量，如 μ、n）
    2. pint 能解析（含词头 ``cm``/``mm``/``km``/``g``/``mg``/``kJ``…）→
       ``(number × unit).to_base_units()`` 的数值
    3. ``unit`` 是白名单「单位_SI」列里的写法 → 同上（白名单是唯一准入名单）
    4. 解析失败 → ``DataError``，**绝不静默当 SI**

    ``symbol`` 只用来写错误信息，不参与换算、也不做量纲校验——量纲是 L2 的职责
    （卡 §3.4 第一条：不许把单位换算的活算到 L2 头上，也不许在 L1 里重复判量纲）。
    """
    try:
        val = float(number)
    except (TypeError, ValueError) as exc:
        raise DataError("number", f"数值无法转成实数：{number!r}") from exc

    text = "" if unit is None else str(unit).strip()
    if text in _DIMLESS_TEXT:
        return val

    # 规则 2 / 3：先按原样给 pint，解析不了再拿白名单里的写法顶（白名单是可信托名单）
    norm = text.replace("^", "**")
    q = None
    try:
        q = ureg().Quantity(1, norm)
    except Exception:  # noqa: BLE001  pint 的解析异常类型很杂，统一收口
        if text in _whitelist_units():
            try:
                q = ureg().Quantity(1, text.replace("^", "**"))
            except Exception as exc:  # noqa: BLE001
                raise DataError(
                    "unit_not_si",
                    f"单位 {text!r} 在白名单里但 pint 仍解析不了"
                    f"（符号 {symbol or '?'}）：{exc}",
                ) from exc
        else:
            raise DataError(
                "unit_not_si",
                f"单位 {text!r} 不是 pint 可解析串，也不在白名单（符号 {symbol or '?'}）",
            )

    try:
        return val * q.to_base_units().magnitude
    except Exception as exc:  # noqa: BLE001  含 offset 单位（degC/degF）等不可乘算的情况
        raise DataError(
            "unit_not_si",
            f"单位 {text!r} 无法换算到基本单位（符号 {symbol or '?'}）：{exc}",
        ) from exc


def dim_str(q) -> str:
    """量纲的人话写法：统一化到基本单位，``kg·m/s^2``、``无量纲``。"""
    try:
        u = q.to_base_units().units
    except Exception:  # noqa: BLE001
        u = q.units
    s = f"{u:~}"
    if s in ("", "dimensionless"):
        return "无量纲"
    return s.replace(" ** ", "^").replace(" * ", "·").replace(" / ", "/")


def dim_of(expr: sympy.Expr, units: dict[str, str] | None = None):
    """递归求表达式的量纲，返回 ``Quantity(1, 单位)``；失败抛 DimError。

    规则（卡 §3.1）：
      Symbol → Quantity(1, 白名单单位)
      Add    → 各项量纲必须相同
      Mul    → 量纲相乘
      Pow    → 量纲取幂（指数必须是无量纲数）
      sin/cos/tan/exp/log → 参数必须无量纲，结果无量纲

    另有一种**非失败**出口：``DimUndecidable``（2026-11-25 加）。加减项量纲不符、
    但某一项带整数数值系数时抛出——那系数可能本身就是带单位的物理量（a=2 m/s²），
    sympy 串里单位已丢失。调用方必须把它当 ``na``，不得当 ``fail``。
    """
    um = units if units is not None else unit_map()
    DIMLESS = ureg().Quantity(1, "dimensionless")

    def walk(e: sympy.Expr):
        # 常量（pi 等）与纯数：无量纲
        if isinstance(e, sympy.NumberSymbol) or isinstance(e, sympy.Number):
            return DIMLESS
        if isinstance(e, Symbol):
            name = str(e)
            if name not in um:
                raise DimError("leaf", f"符号「{name}」不在白名单，L2 无法给单位")
            unit = um[name]
            if not unit:
                raise DimError("leaf", f"符号「{name}」的白名单单位为空")
            return ureg().Quantity(1, unit)
        if isinstance(e, sympy.Add):
            return _walk_add(e, um, walk, DIMLESS)
        if isinstance(e, sympy.Mul):
            out = DIMLESS
            for a in e.args:
                out = out * walk(a)
            return out
        if isinstance(e, sympy.Pow):
            base, exp = e.args
            if exp.free_symbols:
                raise DimError("pow", f"指数含符号（{exp}），量纲无法确定")
            if not exp.is_number:
                raise DimError("pow", f"指数不是数值（{exp}），量纲无法确定")
            try:
                fexp = float(exp)
            except (TypeError, ValueError) as exc:
                raise DimError("pow", f"指数无法转成实数（{exp}）") from exc
            try:
                return walk(base) ** fexp
            except pint.DimensionalityError as exc:
                raise DimError("pow", f"幂运算量纲不可用：{base} ** {exp}（{exc}）") from exc
        if isinstance(e, sympy.Function):
            fname = type(e).__name__
            if fname not in ("sin", "cos", "tan", "exp", "log"):
                raise DimError("leaf", f"不认识的函数 {fname}()，L2 不判")
            arg = e.args[0]
            da = walk(arg)
            if da.dimensionality != ureg().Quantity(1, "dimensionless").dimensionality:
                raise DimError(
                    "func",
                    f"{fname}() 的参数「{arg}」带了量纲 {dim_str(da)}，必须无量纲",
                    terms=[(str(arg), dim_str(da))],
                )
            return DIMLESS
        raise DimError("leaf", f"不认识的表达式节点 {type(e).__name__}：{e}")

    return walk(expr)


def _coeff_may_carry_unit(term: sympy.Expr) -> bool:
    """该项的数值系数是否「可能带单位」。

    判据：拆成 coeff * rest 后，coeff 是**整数**且绝对值 ≠ 1，rest 含符号。
    ``2*t**2`` → True（2 可能是 2 m/s²，由 a=4 m/s² 与 ½ 相乘得来）；
    ``m*v**2`` → False（系数 1）；
    ``Rational(1,2)*a2*t`` → False（½ 是公式系数，a2 仍以符号在册）。

    **为什么必须是整数**（2026-11-25 实测收窄）：最初写成「任何 ≠1 的系数」，
    回归用例 C03 立刻破——``½·a2·t − L/6`` 是真错（m/s vs m），却因 ½ 被放过。
    整数/非整数的区别有物理含义：**读数代入后的系数通常是整数**（a=4 → ½·4=2），
    而 ½、1/6 这类是公式自带的系数，单位仍在后面的符号里。

    已知残留盲区（明写，不掩盖）：``L - 3.5*t**2``（a=7 m/s²）系数非整数，
    仍会被判 fail；``L - 2*t**2`` 若模型的 2 其实是纯数字，则被放过。
    """
    try:
        coeff, rest = term.as_coeff_Mul()
    except (AttributeError, TypeError):
        return False
    return bool(coeff.is_Integer) and abs(coeff) != 1 and bool(rest.free_symbols)


def _walk_add(e: sympy.Expr, um, walk, DIMLESS):
    """加减式：比较各项量纲。

    三条特殊规则（都写进 说明.md，属于 L2 的已知取舍）：

    1. **字面零忽略**：``Fnet - 0`` 里的 0 不参与量纲比较。牛顿方程里
       「合力等于零」与「合力为某值」是同一类式子。
    2. **纯数字字面量按 SI 值处理**：``v0 - 4`` 里的 4 视为 4 m/s，不按
       无量纲去和 v0 比较。否则凡「代入数值」的步全部假阳性。
       代价：``m*v**2 - 5`` 这种写错的式子 L2 抓不到。
    3. **带单位的数值系数 → 判不了，不判错**（2026-11-25 加）：项形如
       ``2*t**2`` 且量纲不符时，那个 2 可能本身就是带单位的物理量（如 a=2 m/s²），
       sympy 串里单位已丢失，遍历器无权判 fail → 抛 ``DimUndecidable``，
       L2 落 ``na``。代价见 ``DimUndecidable`` 的 docstring。
    """
    sym_terms: list[tuple[sympy.Expr, object]] = []
    for t in e.args:
        if t.is_zero is True:
            continue
        # 纯数字字面量（不含符号）不参与量纲比较
        if t.is_number and not t.free_symbols:
            continue
        sym_terms.append((t, walk(t)))
    if not sym_terms:
        return DIMLESS
    base_t, base_q = sym_terms[0]
    base_dim = base_q.dimensionality
    bad = [(t, q) for t, q in sym_terms[1:] if q.dimensionality != base_dim]
    if bad:
        detail = "；".join([f"{base_t} 为 {dim_str(base_q)}"] + [f"{s} 为 {dim_str(q)}" for s, q in bad])
        terms = [(str(base_t), dim_str(base_q))] + [(str(s), dim_str(q)) for s, q in bad]
        # 只要有一项的数值系数可能在承载单位，就没资格判 fail —— 盲区在验证器这边
        suspect = [t for t, _ in sym_terms if _coeff_may_carry_unit(t)]
        if suspect:
            raise DimUndecidable(
                "add_coeff",
                f"加减项量纲不一致，但含带单位的数值系数（{', '.join(str(x) for x in suspect)}），"
                f"无法判定是模型错还是单位已并入系数：{detail}",
                terms=terms,
            )
        raise DimError(
            "add",
            f"加减项量纲不一致：{detail}",
            terms=terms,
        )
    return base_q

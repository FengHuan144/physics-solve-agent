# -*- coding: utf-8 -*-
"""l1_deduce.py — L1 计算层（sympy 回代）。

口径（卡 §1.1）：**L1 = 计算**。主目标是 E-10 代入代数错。
两种模式都要做（卡 §1.2）：

- ``per_step``：只用**前序**步骤的值当已知，看本步方程能否解出本步 value。
  能定位到「哪一步代错了」，但列方程步（本来没有 value）只能给 na。
- ``chain``：全题所有值一起代入，看方程组是否相容；再用「只改一个值能否
  让全题残差归零」做归因。能抓跨步矛盾，但定位粒度粗。

两种结果合并成**一条** L1 check，detail 里写清哪个模式判的（卡 §1.2）。

三种「不是错」的状态，绝不混用（卡 §1.3 / §7 陷阱 2、3）：
- 欠定（方程数 < 未知数）→ ``na``，不是 fail
- ``parse_status=degraded`` → ``skipped``（Schema 里 skipped 专指这个）
- 非方程步（judgment/discussion/critical 且无方程）→ ``na``
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sympy
from sympy import Symbol

from . import units as U

TOL_REL = 0.02      # 相对容差 2%：g 取 10 或 9.8 差 2%，有效数字舍入也在这一档
TOL_ABS = 1e-9      # 绝对值小于 1e-9 按 0 处理
MAX_FIX = 3         # chain 最多连续归因 3 个错值，防病态输入拖死


# --------------------------------------------------------------------------- 结构

@dataclass
class StepRec:
    """一步的解析结果。expr 为 None 表示这一步 L1 不判。

    ``val_*`` 四个字段是**本步取值的唯一来源**：``prepare()`` 里统一经
    ``U.to_si()`` 按 ``value.unit`` 折成 SI，下游不再回读 JSON——回读一处就漏一处
    （T12aR2 卡 §3.3：原来 5 处各读一遍 ``number``，漏改一处就留一个洞）。
    """
    step_id: str
    step_no: int
    kind: str
    raw: dict
    expr: sympy.Expr | None = None
    skip_kind: str | None = None     # 'degraded' | 'failed' | 'data_error' | 'identity'
    skip_note: str = ""
    val_symbol: str | None = None
    val_raw: float | None = None     # 原样 value.number（只用于写 detail）
    val_si: float | None = None      # 按 value.unit 折成 SI 后的值（判定用这个）
    val_note: str = ""               # 换算说明，如「原写 3 cm/s^2，按 SI 折为 0.03」
    val_err: str | None = None       # value 侧的数据问题


@dataclass
class Verdict:
    status: str                      # pass / fail / na / skipped
    detail: str
    error_code: str | None = None
    mode: str = ""


@dataclass
class ChainResult:
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    attributed: list[dict] = field(default_factory=list)     # 归因成功的错值
    ambiguous: list[str] = field(default_factory=list)       # 归因不唯一的步
    unclassified: list[dict] = field(default_factory=list)   # 抓到但未分类的残差


# --------------------------------------------------------------------------- 工具

def _close(a: float, b: float) -> bool:
    """2% 相对容差 + 1e-9 绝对容差。"""
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) <= max(TOL_REL * scale, TOL_ABS)


def _fmt(x: float) -> str:
    """detail 里的数字：6 位有效，去掉浮点尾巴。"""
    if x == int(x) and abs(x) < 1e12:
        return str(int(x))
    return f"{x:.6g}"


def _subs(expr: sympy.Expr, knowns: dict[str, float]) -> sympy.Expr:
    names = {str(s) for s in expr.free_symbols}
    pairs = {Symbol(k): v for k, v in knowns.items() if k in names}
    return expr.subs(pairs) if pairs else expr


def _is_zero(expr: sympy.Expr) -> bool:
    if expr == 0:
        return True
    try:
        return bool(sympy.simplify(expr) == 0)
    except Exception:  # noqa: BLE001
        return False


def _numeric(expr: sympy.Expr) -> float | None:
    if expr.free_symbols:
        return None
    try:
        return float(expr)
    except (TypeError, ValueError):
        return None


def _scale(expr: sympy.Expr, knowns: dict[str, float]) -> float:
    """残差的比较尺度：代入已知后各项绝对值的最大值。

    用「最大项」而不是「各项之和」：和会把容差放大（两项各 100 时放成 4%），
    最大项才是这道式子的量级。
    """
    terms = expr.args if expr.is_Add else (expr,)
    vals = [abs(v) for v in (_numeric(_subs(t, knowns)) for t in terms) if v is not None]
    return max(vals) if vals else 0.0


def _residual(expr: sympy.Expr, knowns: dict[str, float]) -> tuple[str, float | None]:
    """代入已知后判残差。返回 ``(kind, 残差值)``，kind ∈ zero / bad / sym。

    容差 2% 相对 + 1e-9 绝对。**必须给数值留容差**：A-06 样例里的
    ``t=0.3333``、``h=0.5556`` 是四位小数的近似值，代回去残差是 1e-4 量级，
    按精确 0 判会把金标判成错——这正是「假阳性」最常见的来源。
    """
    r = _subs(expr, knowns)
    if _is_zero(r):
        return "zero", 0.0
    if r.free_symbols:
        return "sym", None
    val = _numeric(r)
    if val is None:
        return "sym", None
    tol = max(TOL_REL * _scale(expr, knowns), TOL_ABS)
    return ("zero" if abs(val) <= tol else "bad"), val


def _free(expr: sympy.Expr, n: int = 4) -> str:
    return ", ".join(sorted({str(x) for x in expr.free_symbols})[:n])


# --------------------------------------------------------------------------- 取值

def read_value(val: dict | None) -> tuple[str | None, float | None, float | None, str | None]:
    """读一处 ``{symbol, number, unit}``。**全模块唯一读 ``number`` 的位置。**

    返回 ``(symbol, 原值, SI 值, 数据错误)``。换算一律走 ``U.to_si()``——
    原来 5 处各读一遍 ``number``，漏改一处就留一个洞（T12aR2 卡 §3.3），
    现在只剩这一个入口。

    题干 ``given`` 的字段名是 ``value`` 不是 ``number``，调用方先归一成同一形状
    （见 ``collect_knowns``），不在这里分两套。
    """
    if not isinstance(val, dict):
        return None, None, None, None
    sym = (val.get("symbol") or "").strip() or None
    raw = val.get("number")
    if not sym or raw is None:
        return sym, None, None, None
    try:
        rawf = float(raw)
        si = U.to_si(raw, val.get("unit"), sym)
    except (TypeError, ValueError, U.DataError) as exc:
        if isinstance(exc, U.DataError):
            err = f"data_error({exc.kind}): {exc.message}"
        else:
            err = f"data_error(number): 数值无法转成实数 {raw!r}"
        return sym, None, None, err
    return sym, rawf, si, None


# --------------------------------------------------------------------------- 已知

def collect_knowns(answer: dict) -> tuple[dict, dict, list[str], list[str]]:
    """收集已知：题干 ``situation.given`` + 各步 ``value.number``。

    返回 ``(givens, step_values, conflicts, data_errors)``：
    - ``givens``      ：题干的数值条件，per_step 从它起步
    - ``step_values`` ：``{symbol: (value, step_id)}``，按步序展开
    - ``conflicts``   ：同符号两处数值相差 > 2%（不静默取一个）
    - ``data_errors`` ：单位折不成 SI 的已知量（**不使用，也不猜**）

    **所有数值都经 ``U.to_si()`` 折成 SI**（T12aR2 卡 §3.3 方案 ①）：
    题干写 ``h = 50 cm``、步级写 ``h = 0.5 m`` 是同一个量，必须能对上；
    折算失败的量宁可不用（后续步判 na），也不拿错单位硬比。
    """
    steps = answer.get("steps") or []
    given = ((answer.get("situation") or {}).get("given") or [])
    givens: dict[str, float] = {}
    gsrc: dict[str, str] = {}
    conflicts: list[str] = []
    data_errors: list[str] = []

    for g in given:
        # given 的字段名是 value，归一成 {symbol, number, unit} 后走同一入口
        sym, _raw, fv, err = read_value({
            "symbol": g.get("symbol"), "number": g.get("value"), "unit": g.get("unit"),
        })
        if err:
            data_errors.append(f"题干 {sym}：{err}（该量不参与回代）")
            continue
        if not sym or fv is None:
            continue
        if sym in givens and not _close(givens[sym], fv):
            conflicts.append(f"{sym}：题干内两处取值不一致（{_fmt(givens[sym])} vs {_fmt(fv)}）")
            continue
        givens[sym] = fv
        gsrc[sym] = "题干"

    step_values: dict[str, tuple[float, str]] = {}
    for s in steps:
        sid = s.get("step_id", "?")
        sym, _raw, fv, err = read_value(s.get("value"))
        if err:
            data_errors.append(f"{sid} {sym}：{err}（该量不参与回代）")
            continue
        if not sym or fv is None:
            continue
        if sym in givens and not _close(givens[sym], fv):
            conflicts.append(
                f"{sym}：{gsrc[sym]} 为 {_fmt(givens[sym])}，{sid} 为 {_fmt(fv)}"
                f"（差 {abs(givens[sym] - fv) / max(abs(givens[sym]), abs(fv)):.0%}）")
        step_values[sym] = (fv, sid)
    return givens, step_values, conflicts, data_errors


def all_knowns(givens: dict[str, float], step_values: dict) -> dict[str, float]:
    """题干 + 全部步骤值（chain 用）。"""
    out = dict(givens)
    for sym, (v, _sid) in step_values.items():
        out.setdefault(sym, v)
    return out


# --------------------------------------------------------------------------- 解析

def _skip_status(kind: str) -> str:
    """skip_kind → check.status。

    **只有 degraded 用 skipped**（Schema 里 skipped 专指解析降级）。
    ``identity``（方程化简为 0）与 ``data_error`` 都是「没有判定对象」，判 ``na``——
    空方程不是算错（T12aR2 卡 §2：不许判 fail、不许给 E-10）。
    """
    return "skipped" if kind == "degraded" else "na"


def prepare(answer: dict, symbols: dict | None = None) -> list[StepRec]:
    """把每步解析成 StepRec。degraded / failed / data_error / identity 在这里定掉。"""
    syms = symbols if symbols is not None else U.load_symbols()
    recs: list[StepRec] = []
    for i, s in enumerate(answer.get("steps") or [], start=1):
        sid = str(s.get("step_id") or f"S{i:02d}")
        rec = StepRec(
            step_id=sid,
            step_no=int(s.get("step_no") or i),
            kind=str(s.get("kind") or ""),
            raw=s,
        )
        eq = s.get("equation") or {}
        status = (eq.get("parse_status") or "").strip()
        if status == "degraded":
            rec.skip_kind = "degraded"
            rec.skip_note = "解析降级，本层停用（degraded 不计入 fail）"
        elif status == "failed":
            rec.skip_kind = "failed"
            rec.skip_note = "parse_status=failed，方程不可解析，本层无判定对象"
        else:
            try:
                rec.expr = U.parse_sympy(eq.get("sympy", ""), syms)
            except U.DataError as exc:
                rec.skip_kind = "data_error"
                rec.skip_note = f"data_error({exc.kind}): {exc.message}"

        # ---- 本步取值：唯一入口，按 value.unit 折成 SI
        val = s.get("value") or {}
        rec.val_symbol, rec.val_raw, rec.val_si, err = read_value(val)
        if err:
            rec.val_err = err
            if rec.skip_kind is None:
                rec.skip_kind = "data_error"
                rec.skip_note = (f"{err}（本步值折不成 SI，L1 停用；"
                                 f"方程本身仍由 L2 判）")
        elif rec.val_si is not None and rec.val_raw is not None:
            if not _close(rec.val_si, rec.val_raw):
                rec.val_note = (f"原写 {_fmt(rec.val_raw)} {val.get('unit')}，"
                                f"按 SI 折为 {_fmt(rec.val_si)}")

        # ---- 恒等式：方程化简为 0，没有可比两侧（与 L2 同口径）
        if rec.skip_kind is None and rec.expr is not None and _is_zero(rec.expr):
            rec.skip_kind = "identity"
            rec.skip_note = "方程化简为 0，无可比两侧（与 L2 同口径）"
        recs.append(rec)
    return recs


# --------------------------------------------------------------------------- per_step

def per_step(recs: list[StepRec], givens: dict[str, float]) -> dict[str, Verdict]:
    """逐步回代：**只带前序**已知，算完一步才把它的值并入已知池。"""
    out: dict[str, Verdict] = {}
    prior = dict(givens)
    for rec in recs:
        if rec.skip_kind:
            out[rec.step_id] = Verdict(
                _skip_status(rec.skip_kind), rec.skip_note, None, "per_step")
        else:
            out[rec.step_id] = _per_step_one(rec, prior)
        # 降级步的值仍当已知用（§8-8 已定），但折不成 SI 的值不算
        if rec.val_symbol and rec.val_si is not None:
            prior.setdefault(rec.val_symbol, rec.val_si)
    return out


def _per_step_one(rec: StepRec, prior: dict[str, float]) -> Verdict:
    sym = rec.val_symbol
    num = rec.val_si
    expr = rec.expr
    assert expr is not None
    names = {str(x) for x in expr.free_symbols}

    e = _subs(expr, prior)

    if not sym or num is None:
        return _per_step_no_value(expr, e, prior)

    if sym not in names:
        return Verdict("na", f"方程不含本步符号 {sym}，本步值无法回代", None, "per_step")

    # 本步符号已被前序算过时，``_subs`` 会把它一起代掉，``e`` 退化成常数。
    # 此时 ``solve(常数, x)`` 必返回 ``[]``，旧代码据此判「方程自相矛盾」——
    # 但常数等于 0 恰恰说明方程被前序已知完全满足，逻辑反了（T33 §0.3）。
    # 改为按残差容差判。位置必须在 ``sym not in names`` 之后：否则「方程根本
    # 不含本步符号」的步会被误判 pass。
    #
    # 尺度用**未代入**的 ``expr`` 算，不是 ``e``：``e`` 已折叠成一个数，
    # ``_scale(e)`` 只剩残差自身的量级，相对容差退化成自比自，任何非零残差
    # 都会被判 bad（四位小数近似值就是这么破的）。
    if not e.free_symbols:
        kind, val = _residual(expr, prior)
        if kind == "bad":
            return Verdict(
                "fail",
                f"方程代入前序已知后残差 {_fmt(val or 0)}（非零），"
                f"与本步 {sym}={_fmt(num)} 矛盾",
                "E-10", "per_step")
        if kind == "zero":
            # 方程被前序满足，只能证明「前序那一套值自洽」；本步报的值还得对得上。
            # 否则「方程 x-3=0、前序 x=3、本步却写 x=4」会被放过——那是另一种 E-10
            # （本步值与已确立的值冲突），方向是 fail→pass，必须守住（R6）。
            if sym in prior and not _close(prior[sym], num):
                rel = abs(prior[sym] - num) / max(abs(prior[sym]), abs(num), 1e-12)
                return Verdict(
                    "fail",
                    f"方程已被前序已知满足，但本步 {sym}={_fmt(num)} 与前序 "
                    f"{_fmt(prior[sym])} 不一致（相对差 {rel:.0%}）",
                    "E-10", "per_step")
            return Verdict(
                "pass",
                f"方程已被前序已知完全满足（代入残差 {_fmt(val or 0)}，"
                f"容差 {TOL_REL:.0%}）；本步 {sym}={_fmt(num)} 与前序一致",
                None, "per_step")
        return Verdict("na", "方程代入后含不可数值化的项，本步不判", None, "per_step")

    try:
        sols = sympy.solve(e, Symbol(sym))
    except Exception as exc:  # noqa: BLE001
        return Verdict("na", f"本步方程求解失败（{type(exc).__name__}），本步不判", None, "per_step")

    nums: list[float] = []
    for s in sorted(sols, key=str):
        v = _numeric(s)
        if v is not None:
            nums.append(v)

    if not nums:
        if isinstance(sols, list) and not sols:
            return Verdict("fail", "本步方程对本步符号无解（方程自相矛盾）", "E-10", "per_step")
        return Verdict(
            "na", f"欠定：解含自由符号 {_free(e)}（chain 再判）", None, "per_step")

    if any(_close(v, num) for v in nums):
        got = "、".join(_fmt(v) for v in nums[:3])
        extra = f"；{rec.val_note}" if rec.val_note else ""
        return Verdict("pass", f"回代解得 {sym}={got}，与本步值一致（相对差 ≤2%）{extra}",
                       None, "per_step")

    got = "、".join(_fmt(v) for v in nums[:3])
    best = min(nums, key=lambda v: abs(v - num))
    rel = abs(best - num) / max(abs(best), abs(num), 1e-12)
    extra = f"（{rec.val_note}）" if rec.val_note else ""
    return Verdict(
        "fail",
        f"本步方程解得 {sym}={got}，步骤写 {_fmt(num)}{extra}（相对差 {rel:.0%}）",
        "E-10", "per_step")


def _per_step_no_value(expr: sympy.Expr, e: sympy.Expr,
                       prior: dict[str, float]) -> Verdict:
    """没有 value 的步：只判本步方程在**前序**已知下是否成立。

    ``expr`` 是未代入的原式，``e`` 是代入后的结果。残差容差的尺度必须取
    ``expr``：``e`` 已折叠成一个数，``_scale(e)`` 只剩残差自身，2% 会退化成
    自比自——四位小数近似（残差 3.3e-5）会被误判 fail。自由符号诊断仍用 ``e``。
    """
    kind, val = _residual(expr, prior)
    if kind == "zero":
        if val:
            return Verdict("pass", f"代入前序已知，残差 {_fmt(val)} ≈ 0（容差 2%）", None, "per_step")
        return Verdict("pass", "代入前序已知，残差 0", None, "per_step")
    if kind == "bad":
        return Verdict("fail", f"代入前序已知，残差 {_fmt(val or 0)}（期望 0）", "E-10", "per_step")
    free = sorted({str(x) for x in e.free_symbols})
    if not free:
        return Verdict("na", "方程含不可数值化的项，本步不判", None, "per_step")
    if len(free) == 1:
        return Verdict(
            "na",
            f"本步无 value：方程可直接解出 {free[0]}，但本步没给值，无从比对（chain 再判）",
            None, "per_step")
    return Verdict(
        "na",
        f"欠定：{len(free)} 未知 / 1 方程（chain 可解，本步不判）含 {_free(e)}",
        None, "per_step")


# --------------------------------------------------------------------------- chain

def chain(recs: list[StepRec], knowns: dict[str, float]) -> ChainResult:
    """全题联立：所有已知一起代入 → 是否相容 → 单值归因。"""
    res = ChainResult()

    def evaluate(ks: dict[str, float]) -> dict[str, str]:
        st: dict[str, str] = {}
        for rec in recs:
            if rec.skip_kind or rec.expr is None:
                st[rec.step_id] = "skip"
                continue
            st[rec.step_id] = _residual(rec.expr, ks)[0]
        return st

    cur = dict(knowns)
    states = evaluate(cur)
    first_residual: dict[str, float] = {
        rec.step_id: abs(_residual(rec.expr, knowns)[1] or 0.0)
        for rec in recs if rec.expr is not None
    }
    sym_baseline = {sid for sid, st in states.items() if st == "sym"}
    note_tpl: dict[str, str] = {}

    for _ in range(MAX_FIX):
        bad = [r.step_id for r in recs if states.get(r.step_id) == "bad"]
        if not bad:
            break
        hyps: dict[str, float] = {}
        for rec in recs:
            if rec.skip_kind or rec.expr is None:
                continue
            sym_name = rec.val_symbol
            num = rec.val_si
            if not sym_name or num is None:
                continue
            eq = _subs(rec.expr, {k: v for k, v in cur.items() if k != sym_name})
            try:
                sols = [s for s in sympy.solve(eq, Symbol(sym_name)) if _numeric(s) is not None]
            except Exception:  # noqa: BLE001
                continue
            for s in sorted(sols, key=str):
                fv = float(s)
                if _close(fv, num):
                    continue        # 试一个和原值相同的解，不算假设
                trial = dict(cur)
                trial[sym_name] = fv
                st = evaluate(trial)
                if any(v == "bad" for v in st.values()):
                    continue
                if {sid for sid, v in st.items() if v == "sym"} - sym_baseline:
                    continue        # 修一个值却让别处冒出新的自由符号 → 不是它
                hyps[rec.step_id] = fv
                break

        if len(hyps) != 1:
            if len(hyps) > 1:
                res.ambiguous = sorted(hyps)
                note_tpl["_amb"] = "、".join(sorted(hyps)[:3])
            break

        sid, fv = next(iter(hyps.items()))
        rec = next(r for r in recs if r.step_id == sid)
        sym_name = rec.val_symbol
        old = rec.val_si if rec.val_si is not None else float("nan")
        res.attributed.append({
            "step_id": sid, "symbol": sym_name,
            "stated": old, "solved": fv,
            "residual": first_residual.get(sid, 0.0),
        })
        note_tpl[sid] = f"把 {sym_name} 由 {_fmt(old)} 改为 {_fmt(fv)} 后全题残差归零 → 判该步数值错"
        cur[sym_name] = fv
        states = evaluate(cur)

    # ---- 落 verdict
    attributed = {a["step_id"] for a in res.attributed}
    bad = [r.step_id for r in recs if states.get(r.step_id) == "bad"]
    for rec in recs:
        sid = rec.step_id
        if rec.skip_kind:
            res.verdicts[sid] = Verdict(
                _skip_status(rec.skip_kind), rec.skip_note, None, "chain")
            continue
        if sid in attributed:
            res.verdicts[sid] = Verdict("fail", note_tpl[sid], "E-10", "chain")
            continue
        st = states.get(sid)
        if st == "zero":
            res.verdicts[sid] = Verdict("pass", "全题联立残差 0（chain）", None, "chain")
        elif st == "sym":
            res.verdicts[sid] = Verdict(
                "na", f"全题联立后仍含自由符号 {_free(_subs(rec.expr, cur))}（欠定，chain 不判）",
                None, "chain")
        elif st == "bad":
            if res.ambiguous:
                res.verdicts[sid] = Verdict(
                    "fail",
                    f"方程组不相容；{len(res.ambiguous)} 个单值假设都能解释（{note_tpl.get('_amb')}），"
                    f"归因不唯一，需人工定位",
                    "E-10", "chain")
            else:
                r = first_residual.get(sid, 0.0)
                res.unclassified.append({
                    "step_id": sid, "residual": r,
                    "judgement": "残差非 0 且无法归因到某一步的数值",
                })
                res.verdicts[sid] = Verdict(
                    "fail",
                    f"全题联立残差 {_fmt(r)}（期望 0），改正任一单步数值都不能归零 → 式子结构不成立；"
                    f"L1 不能区分 E-04 项遗漏 / E-06 符号错 / E-13 末态漏项",
                    "E-04", "chain")
        else:
            res.verdicts[sid] = Verdict("na", "无可判定对象", None, "chain")

    return res


# --------------------------------------------------------------------------- 合并

_ORDER = {"E-10": 0, "E-04": 1}


def merge(per: Verdict, ch: Verdict) -> dict:
    """两模式合并成一条 L1 check（卡 §1.2「同一层只出一条」）。"""
    detail = f"per_step：{per.detail}｜chain：{ch.detail}"
    if per.status == "fail" or ch.status == "fail":
        if per.status == "fail" and ch.status == "fail":
            if per.error_code != ch.error_code:
                code = min([per.error_code or "E-10", ch.error_code or "E-10"],
                           key=lambda c: _ORDER.get(c, 9))
                detail += "（两模式错误码不同，按更具体的记，需人工复核）"
            else:
                code = per.error_code
        else:
            code = per.error_code if per.status == "fail" else ch.error_code
            if per.status == "pass" or ch.status == "pass":
                detail += "（两模式不一致，按 fail 报，需人工复核）"
        return _check("fail", detail, code)
    if per.status == "pass" or ch.status == "pass":
        return _check("pass", detail, None)
    if per.status == "skipped" or ch.status == "skipped":
        return _check("skipped", detail, None)
    return _check("na", detail, None)


def _check(status: str, detail: str, error_code: str | None) -> dict:
    return {"layer": "L1", "status": status, "detail": detail,
            "error_code": error_code if status == "fail" else None}

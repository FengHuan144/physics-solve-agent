# -*- coding: utf-8 -*-
"""l2_dimension.py — L2 量纲层（pint）。

输入一步（Schema 的 step 子集），输出 ``checks[]`` 里的 L2 条目。

口径（卡 §1.1）：**L2 = 量纲**。E-11 单位缺失、E-12 量纲不符都归这层。

一步通常只出一条 check（卡「同一层只出一条」的精神）；只有同时踩到
E-11 与 E-12 两个不同错误码时才拆成两条——「一条 check 一个错误码」优先。

边界（卡 §1.4，必须写进报告）：L2 只保证「单位类型对」，**不保证「单位数值对」**。
把 ``L = 5 cm`` 写成 ``L = 5 m`` 代入，两边都是长度，L2 判 pass；数值差 100 倍
由 L1 抓——L1 读值时会按 ``units.to_si()`` 折成 SI 再回代（T12aR2 方案 ①）。
本层**不碰**单位换算：``cm/s²`` 与 ``m/s²`` 同量纲，判 pass 是对的，不是漏判。
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import units as U

SKIP_DEGRADED = "解析降级，本层停用（degraded 不计入 fail）"


def analyze(step: dict, symbols: dict | None = None) -> dict:
    """对一步跑 L2，返回 ``{"checks", "equation_broken", "equation_codes"}``。

    ``checks`` 元素严格对齐 ``schema/answer.schema.json#/definitions/check``：
    四个字段、status 四值、error_code 为 21 条之一或 null。

    ``equation_broken`` 只标**方程本身**量纲不符（E-12 来自两侧比较），供 runner 去重：
    这种情况同一步的 L1 残差是同一个病灶的症状，不该再算一次失败。
    ``value.unit`` 的 E-11 / E-12 **不置**此旗标——那是一个独立缺陷，
    完全可能同时存在一个真算错的数（见 tests C11）。
    """
    syms = symbols if symbols is not None else U.load_symbols()
    eq = step.get("equation") or {}
    status = (eq.get("parse_status") or "").strip()

    # ---- 降级/失败：是状态，不是判错（R6 / 字段清单 §4）
    if status == "degraded":
        return _res([_check("skipped", SKIP_DEGRADED)])
    if status == "failed":
        return _res([_check("na", "parse_status=failed，方程不可解析，L2 无判定对象")])

    # ---- 解析
    try:
        expr = U.parse_sympy(eq.get("sympy", ""), syms)
    except U.DataError as exc:
        return _res([_check("na", f"data_error({exc.kind}): {exc.message}")])

    problems: list[tuple[str, str]] = []   # (error_code, 说明)
    oks: list[str] = []
    data_errors: list[str] = []
    equation_broken = False

    # ---- 方程两侧量纲
    if expr == 0:
        return _res([_check("na", "方程化简为 0，无可比两侧")])
    try:
        q = U.dim_of(expr, units={k: v["unit"] for k, v in syms.items()})
        oks.append(f"两边量纲均为 {U.dim_str(q)}")
    except U.DimError as exc:
        problems.append(("E-12", exc.message))
        equation_broken = True

    # ---- value 的单位（E-11 缺失 / E-12 与符号白名单不符）
    val = step.get("value")
    if isinstance(val, dict):
        raw_unit = val.get("unit")
        sym = (val.get("symbol") or "").strip()
        if raw_unit is None or str(raw_unit).strip() == "":
            problems.append(("E-11", "value.unit 为空（无单位，结果不完整）"))
        else:
            try:
                got = U.parse_unit_text(raw_unit)
            except U.DataError as exc:
                # 有单位但 pint 认不出来：是数据问题，不是量纲不符（R5：报出来，不猜）
                data_errors.append(f"data_error({exc.kind}): {exc.message}（本步值单位未比对）")
                got = None
            if got is not None:
                if sym and sym in syms:
                    want = U.ureg().Unit(syms[sym]["unit"].replace("^", "**"))
                    if got.dimensionality != want.dimensionality:
                        problems.append((
                            "E-12",
                            f"值单位 {raw_unit} 的量纲 {got.dimensionality} "
                            f"与符号 {sym} 的白名单量纲 {want.dimensionality} 不符",
                        ))
                    else:
                        oks.append(f"值单位 {raw_unit} 与符号 {sym} 白名单一致")
                else:
                    oks.append(f"值单位 {raw_unit} 可解析；符号 {sym or '(空)'} 不在白名单，未比对")

    if not problems:
        if data_errors:
            return _res([_check("na", "；".join(oks + data_errors))])
        return _res([_check("pass", "；".join(oks) or "无判定对象")])

    # 同码合并，不同码拆条；数据问题附在第一条里，不吞掉
    by_code: dict[str, list[str]] = {}
    for code, text in problems:
        by_code.setdefault(code, []).append(text)
    out = []
    for i, code in enumerate(sorted(by_code)):
        notes = by_code[code] + (data_errors if i == 0 else [])
        out.append(_check("fail", "；".join(notes), code))
    return _res(out, equation_broken, ["E-12"] if equation_broken else [])


def check_step(step: dict, symbols: dict | None = None) -> list[dict]:
    """兼容入口：只要 ``checks``。"""
    return analyze(step, symbols)["checks"]


def _res(checks: list[dict], equation_broken: bool = False,
         equation_codes: list[str] | None = None) -> dict:
    return {"checks": checks, "equation_broken": equation_broken,
            "equation_codes": equation_codes or []}


def _check(status: str, detail: str, error_code: str | None = None) -> dict:
    return {"layer": "L2", "status": status, "detail": detail,
            "error_code": error_code if status == "fail" else None}


def sweep_formula_lib(path: str | None = None, symbols: dict | None = None) -> dict:
    """把公式库 74 条整体过一遍 L2。

    这是 L2 层唯一的**真数据规模化**验证：74 条真实公式、真实白名单单位。
    任何一条挂了，要么公式库错、要么白名单单位错、要么遍历器错——三者都值得查。
    """
    syms = symbols if symbols is not None else U.load_symbols()
    p = Path(path) if path else U.FORMULA_CSV
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))
    um = {k: v["unit"] for k, v in syms.items()}
    results = []
    for row in rows:
        fid = (row.get("formula_id") or "").strip()
        raw = (row.get("公式_sympy") or "").strip()
        try:
            expr = U.parse_sympy(raw, syms)
            q = U.dim_of(expr, units=um)
            results.append({"formula_id": fid, "sympy": raw,
                            "status": "pass", "detail": U.dim_str(q)})
        except U.DataError as exc:
            results.append({"formula_id": fid, "sympy": raw,
                            "status": "data_error", "detail": f"{exc.kind}: {exc.message}"})
        except U.DimError as exc:
            results.append({"formula_id": fid, "sympy": raw,
                            "status": "fail", "detail": exc.message})
    return {
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "data_error": sum(1 for r in results if r["status"] == "data_error"),
        "rows": results,
    }

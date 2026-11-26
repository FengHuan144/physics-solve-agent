# -*- coding: utf-8 -*-
"""test_l2_coeff.py — L2「带单位的数值系数」盲区的自测。**不用 pytest**：

    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/test_l2_coeff.py

背景（2026-11-25 裁定，用户「按你的来」）：
模型写 ``L - Rational(1,2)*(6-2)*t**2`` 时，``6``/``2`` 是 a 轴读数（m/s²），
``½·4·t² = 2t²`` 量纲是 m，式子正确；但 sympy 串里单位已并入系数 2，
遍历器只看到 ``s²``，于是判 E-12。这是验证器的信息盲区，不是模型的错。

处置分两侧：
  - **判据侧（本文件）**：异常的加减项若含**整数**数值系数，改抛 ``DimUndecidable``，
    L2 落 ``na`` 而不是 ``fail``。
  - **生成侧**：``equation.sympy`` 不许把单位算进系数（规范条款，见
    ``schema/字段清单.md``）。根因在生成侧，这里只是兜底。

**收窄的由来**：最初写成「任何 ≠1 的系数都放过」，回归用例 C03
（``Rational(1,2)*a2*t - L/6``，真错：m/s vs m）当场破。改成「整数才放过」后，
C03 恢复 fail、B-20 的 2 处假 fail 转 na——t04/t05 就是钉这两条的。

任一断言失败即退出码 1。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

import sympy as sp                        # noqa: E402

from 验证器 import l2_dimension as L2     # noqa: E402
from 验证器 import runner as R            # noqa: E402
from 验证器 import units as U             # noqa: E402

_OUT = ROOT / "评测" / "T20" / "out"


def _dim(expr: str):
    """返回 ('pass', 量纲串) / ('undecidable', msg) / ('fail', msg)。"""
    e = sp.sympify(expr)
    try:
        return ("pass", U.dim_str(U.dim_of(e)))
    except U.DimUndecidable as exc:
        return ("undecidable", exc.message)
    except U.DimError as exc:
        return ("fail", exc.message)


def _analyze_step(qid: str, sid: str, *, alias: bool = False) -> dict:
    doc = json.loads((_OUT / f"{qid}_validated.json").read_text(encoding="utf-8"))
    if alias:
        from 验证器 import alias as A
        doc, _ = A.apply_alias(doc, qid=qid)
    # 只对目标步跑 L2，避免依赖 runner 的整题状态
    step = next(s for s in doc["steps"] if s["step_id"] == sid)
    checks = L2.analyze(step)["checks"]
    return next(c for c in checks if c["layer"] == "L2")


# --------------------------------------------------------------------------- 判据侧

def t01_整体系数盲区_判不可判() -> list[str]:
    """B-20 的真实写法：½·(6−2)·t² → 2t²，2 是 a/2（m/s²）。"""
    kind, msg = _dim("L-Rational(1,2)*(6-2)*t**2")
    if kind != "undecidable":
        return [f"应判 undecidable，实为 {kind}: {msg}"]
    return []


def t02_裸整数系数_判不可判() -> list[str]:
    kind, msg = _dim("L-2*t**2")
    return [] if kind == "undecidable" else [f"应判 undecidable，实为 {kind}: {msg}"]


def t03_纯数字项仍按SI值处理() -> list[str]:
    """规则 2 不能被这次改动带坏：``v0-4`` 的 4 视为 4 m/s。"""
    kind, msg = _dim("v0-4")
    return [] if kind == "pass" else [f"应判 pass，实为 {kind}: {msg}"]


def t04_回归C03_半系数仍需判错() -> list[str]:
    """**最要紧的一条**：``½a₂t − L/6`` 是真错（m/s vs m），不许被放过。

    最初版本「任何非 1 系数都放过」，这条当场破。
    """
    kind, msg = _dim("Rational(1,2)*a2*t - L/6")
    return [] if kind == "fail" else [f"应判 fail，实为 {kind}: {msg}"]


def t05_无系数仍判错() -> list[str]:
    for expr in ("x-t**2", "m*v**2-m*g"):
        kind, msg = _dim(expr)
        if kind != "fail":
            return [f"{expr} 应判 fail，实为 {kind}: {msg}"]
    return []


def t06_整式量纲正确时不受影响() -> list[str]:
    for expr in ("m*v**2-m*g*h", "Rational(1,2)*m*v**2-m*g*h", "v0+a*t-v"):
        kind, msg = _dim(expr)
        if kind != "pass":
            return [f"{expr} 应判 pass，实为 {kind}: {msg}"]
    return []


# --------------------------------------------------------------------------- 层侧（整步）

def t07_B20_S11_落na且不置broken() -> list[str]:
    """``equation_broken`` 不能置位——置了 runner 会去重掉 L1，掩盖别的问题。"""
    doc = json.loads((_OUT / "B-20_validated.json").read_text(encoding="utf-8"))
    step = next(s for s in doc["steps"] if s["step_id"] == "B-20-S11")
    res = L2.analyze(step)
    chk = next(c for c in res["checks"] if c["layer"] == "L2")
    errs = []
    if chk["status"] != "na":
        errs.append(f"应落 na，实为 {chk['status']}")
    if chk["error_code"] is not None:
        errs.append(f"na 不该带 error_code，实为 {chk['error_code']}")
    if res["equation_broken"]:
        errs.append("equation_broken 不该置位（方程未必错，盲区在验证器）")
    if "不可判定" not in (chk["detail"] or ""):
        errs.append(f"detail 应写明不可判定，实为：{chk['detail']}")
    return errs


def t08_回归C03整步仍判E12() -> list[str]:
    """用真实 A-06 步复现 C03：把 S04 写成 ½a₂t = L/6，L2 必须 fail+E-12。"""
    src = ROOT / "schema" / "examples" / "A-06.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    step = next(s for s in doc["steps"] if s["step_id"] == "A-06-S04")
    step["equation"]["sympy"] = "Rational(1,2)*a2*t - L/6"
    step["equation"]["parse_status"] = "ok"
    chk = next(c for c in L2.analyze(step)["checks"] if c["layer"] == "L2")
    if chk["status"] != "fail" or chk["error_code"] != "E-12":
        return [f"应 fail/E-12，实为 {chk['status']}/{chk['error_code']}：{chk['detail'][:80]}"]
    return []


def t09_B20全题fail归零() -> list[str]:
    """B-20 未开别名：原 pass6/fail2/na9，改后应 pass6/fail0/na11。"""
    doc, _ = R.run_answer(json.loads((_OUT / "B-20_validated.json").read_text(encoding="utf-8")))
    from collections import Counter
    c = Counter(ch["status"] for s in doc["steps"] for ch in (s.get("checks") or [])
                if ch["layer"] == "L2")
    got = (c["pass"], c["fail"], c["na"])
    return [] if got == (6, 0, 11) else [f"应 (6,0,11)，实为 {got}"]


def t10_其他六题不受影响() -> list[str]:
    """改动必须只动 B-20 这两步——任何别的题变了都是回退。"""
    old = json.loads((ROOT / "临时" / "alias_scan" / "compare.json").read_text(encoding="utf-8"))
    errs = []
    for q in ("A-02", "A-08", "A-10", "B-02", "B-09", "B-12"):
        doc, _ = R.run_answer(json.loads((_OUT / f"{q}_validated.json").read_text(encoding="utf-8")))
        from collections import Counter
        c = Counter(ch["status"] for s in doc["steps"] for ch in (s.get("checks") or [])
                    if ch["layer"] == "L2")
        o = old["questions"][q]["checks_off"]["L2"]
        got, want = (c["pass"], c["fail"], c["na"]), (o["pass"], o["fail"], o["na"])
        if got != want:
            errs.append(f"{q} 变了：{got} ≠ {want}")
    return errs


TESTS = [
    ("t01 盲区：整体系数 ½(6−2)t² → undecidable", t01_整体系数盲区_判不可判),
    ("t02 盲区：裸整数系数 2t² → undecidable", t02_裸整数系数_判不可判),
    ("t03 规则2：v0−4 仍 pass", t03_纯数字项仍按SI值处理),
    ("t04 回归 C03：½a₂t−L/6 仍 fail", t04_回归C03_半系数仍需判错),
    ("t05 回归：无系数不符仍 fail", t05_无系数仍判错),
    ("t06 回归：量纲正确仍 pass", t06_整式量纲正确时不受影响),
    ("t07 层：B-20-S11 落 na、不置 broken", t07_B20_S11_落na且不置broken),
    ("t08 层：C03 整步仍 E-12", t08_回归C03整步仍判E12),
    ("t09 整题：B-20 fail 归零 (6/0/11)", t09_B20全题fail归零),
    ("t10 整题：其他六题零变化", t10_其他六题不受影响),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print("=" * 66)
    print("L2 带单位数值系数 · 自测")
    print("=" * 66)
    bad = 0
    for name, fn in TESTS:
        try:
            errs = fn()
        except Exception as exc:  # noqa: BLE001
            errs = [f"未捕获异常 {type(exc).__name__}: {exc}"]
        if errs:
            bad += 1
            print(f"  [{name}] FAIL")
            for e in errs:
                print(f"      - {e}")
        else:
            print(f"  [{name}] OK")
    print("-" * 66)
    print(f"结论：{len(TESTS) - bad}/{len(TESTS)} passed"
          f"｜{'全部通过' if bad == 0 else '有失败项，见上'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

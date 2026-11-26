"""只读数据缺陷探测器。**不改 L1/L2 判据，不改任何产物。**

做两件确定性的事（规格见 `子agent/T32_生成侧缺陷建档与豁免口径.agent.md` §5.2）：

1. ``scan_dim_merge``   加减项量纲不一致 —— A 类「合步」的一个子集，L2 能抓。
                        用作召回率**下限**，不是全量（B-01-S02 / B-20-S12 量纲合法，本函数抓不到）。
2. ``scan_field_mismatch`` ``equation`` 与 ``value.exact`` 化简后不等 —— B 类字段转写。

**本文件不做「合步语义识别」。** 理由是实测：statement 多等号判据误报 35 处、
多未知量判据误报 49 处，绝大多数是正常移项。合步只能人工登记进 ``判分器/defects_v1.json``。

用法::

    python 验证器/defect_scan.py                      # 扫全部 20 份 canonical
    python 验证器/defect_scan.py --qid A-05 B-07      # 只扫指定题
    python 验证器/defect_scan.py --out 临时/scan.json # 落盘
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sympy as sp  # noqa: E402

from 验证器 import alias as A  # noqa: E402
from 验证器 import l2_dimension as L2  # noqa: E402
from 验证器 import units as U  # noqa: E402

OUT_DIR = Path("评测/T20/out")
DEFAULT_QIDS = ("A-01 A-02 A-03 A-04 A-05 A-06 A-08 A-09 A-10 "
                "B-01 B-02 B-04 B-05 B-07 B-09 B-10 B-12 B-16 B-19 B-20").split()

_CALLS = {"sqrt", "Rational", "sin", "cos", "tan", "pi", "log", "exp", "Abs"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def _load(qid: str) -> dict:
    return json.loads((OUT_DIR / f"{qid}.json").read_text(encoding="utf-8"))


def scan_dim_merge(doc: dict, qid: str) -> list[dict]:
    """加减项量纲不一致的步。直接复用 L2，不重写量纲逻辑。"""
    out = []
    for step in doc.get("steps") or []:
        res = L2.analyze(step)
        for c in res.get("checks") or []:
            if c.get("status") == "fail" and "加减项量纲不一致" in str(c.get("detail") or ""):
                out.append({
                    "qid": qid,
                    "step_id": step.get("step_id"),
                    "signal": "dim_merge",
                    "error_code": c.get("error_code"),
                    "detail": c.get("detail"),
                    "equation": (step.get("equation") or {}).get("sympy"),
                })
    return out


def _canonical_expr(text: str, qid: str, bindings: dict) -> sp.Expr | None:
    """把 value.exact 里的符号按绑定表映射成白名单 id 后解析。失败返回 None。"""
    s = str(text).replace("^", "**").strip()
    if not s:
        return None

    def _repl(m: re.Match) -> str:
        name = m.group(0)
        if name in _CALLS:
            return name
        c = A.canonical(name, qid, bindings)
        return c if c else name

    mapped = _IDENT.sub(_repl, s)
    try:
        syms = U.load_symbols()
        names = _IDENT.findall(mapped)
        if any(n not in syms and n not in _CALLS for n in names):
            return None
        locals_ = {k: sp.Symbol(k) for k in syms}
        locals_.update({"sqrt": sp.sqrt, "Rational": sp.Rational,
                        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
                        "pi": sp.pi, "log": sp.log, "exp": sp.exp, "Abs": sp.Abs})
        expr = sp.sympify(mapped, locals=locals_)
        return expr if isinstance(expr, sp.Expr) else None
    except Exception:  # noqa: BLE001
        return None


def scan_field_mismatch(doc: dict, qid: str, bindings: dict) -> list[dict]:
    """``equation`` 解出的值 ≠ ``value.exact``。

    只比「两边都是符号表达式」的情形：若 ``value.exact`` 是纯数值（如 ``7400``），
    要比就得先把 given 代进去——那属于 L1 的活，本探测器不做，归 skip。
    """
    out = []
    for step in doc.get("steps") or []:
        eq = (step.get("equation") or {}).get("sympy") or ""
        val = step.get("value") or {}
        sym = (val.get("symbol") or "").strip()
        ex = val.get("exact")
        if not eq or not sym or ex in (None, ""):
            continue
        target = _canonical_expr(ex, qid, bindings)
        if target is None:
            continue
        if not target.free_symbols:
            continue          # 纯数值，本探测器无权判（要代 given）
        try:
            expr = U.parse_sympy(eq)
        except U.DataError as exc:
            out.append({"qid": qid, "step_id": step.get("step_id"),
                        "signal": "field_unparsed", "detail": str(exc)})
            continue
        x = sp.Symbol(sym)
        if not expr.has(x):
            continue
        try:
            sols = sp.solve(sp.Eq(expr, 0), x)
        except Exception:  # noqa: BLE001
            continue
        if not sols:
            continue
        # 解里若出现 exact 没有的符号，说明这一步还没代完 given（如 A-05-S07 解出
        # H = -R + v0²/(2g) 而 exact 写 5R/4，要靠 v0²=9gR/2 才等）——不可直接比，skip。
        extra: set = set()
        for s in sols:
            extra |= s.free_symbols
        extra -= target.free_symbols
        if extra:
            continue
        same = False
        for s in sols:
            try:
                if sp.simplify(s - target) == 0:
                    same = True
                    break
            except Exception:  # noqa: BLE001
                pass
        if not same:
            out.append({
                "qid": qid,
                "step_id": step.get("step_id"),
                "signal": "field_mismatch",
                "equation": eq,
                "value_exact": ex,
                "equation_solves_to": [str(s) for s in sols[:3]],
            })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="只读数据缺陷探测器")
    ap.add_argument("--qid", nargs="*", default=None, help="只扫指定题号")
    ap.add_argument("--out", default=None, help="结果落盘路径（JSON）")
    args = ap.parse_args(argv)

    qids = args.qid or DEFAULT_QIDS
    bindings = A.load_bindings()
    dim_hits: list[dict] = []
    field_hits: list[dict] = []

    for qid in qids:
        raw = _load(qid)
        # 两类探测都走别名改写后的 doc——方程里的模型符号要先映射成白名单 id，
        # 否则 parse_sympy 会因 unknown_symbol 直接拒（实测 16 处假"解析失败"）。
        doc_a, _ = A.apply_alias(raw, qid=qid)
        dim_hits += scan_dim_merge(doc_a, qid)
        # value.exact 不被 apply_alias 改写，故 scan_field_mismatch 内部自行按绑定表映射符号
        field_hits += scan_field_mismatch(doc_a, qid, bindings)

    report = {
        "scanned": len(qids),
        "qids": qids,
        "dim_merge": dim_hits,
        "field_mismatch": [h for h in field_hits if h["signal"] == "field_mismatch"],
        "field_unparsed": [h for h in field_hits if h["signal"] == "field_unparsed"],
    }

    print(f"扫描 {len(qids)} 份")
    print(f"\n[1] 加减项量纲不一致（合并步召回下限）: {len(dim_hits)} 处")
    for h in dim_hits:
        print(f"    {h['step_id']:10s} {h['error_code']}  {str(h['detail'])[:70]}")
    fm = report["field_mismatch"]
    print(f"\n[2] equation 与 value.exact 不一致: {len(fm)} 处")
    for h in fm:
        print(f"    {h['step_id']:10s} eq解={h['equation_solves_to']}  标称={h['value_exact']}")
    up = report["field_unparsed"]
    if up:
        print(f"\n[3] equation 解析失败（另案）: {len(up)} 处")
        for h in up:
            print(f"    {h['step_id']:10s} {h['detail'][:80]}")

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已落盘 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

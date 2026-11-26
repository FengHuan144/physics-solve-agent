# -*- coding: utf-8 -*-
"""test_l1_prior_subs.py — L1「本步符号已被前序算过」缺陷的守卫测试（T33 段 A）。

    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/test_l1_prior_subs.py

缺陷（T33 卡 §0.3）：``_per_step_one()`` 先 ``_subs`` 代前序，再无条件 ``solve``。
本步符号在前序已算过时，``e`` 退化成常数，``solve(常数, x)`` 必返回 ``[]``，
于是判「方程自相矛盾」。

**但这个常数等于 0 恰恰说明方程被前序已知完全满足。逻辑反了。**

三条红线（卡 §1.2）：
- R1 前序 x=3、本步 x−5、value 4 → **fail**（残差 −2，真矛盾，不许放过）
- R2 前序 x=3、本步 x−3、value 3 → **pass**（这就是本次修的那条）
- R3 无前序、本步 x−5、value 4 → **fail**（走原 solve 路径）

R1 与 R3 是「不许把 fail 全改成 pass」的守卫。只写 R2 不算测试。

另加四条（不在卡的三条里，但同样是这次改动会碰到的边界）：
- R4 方程不含本步符号 → **na**（守住「新分支必须在 ``if sym not in names`` 之后」）
- R5 四位小数近似值（残差 3.3e-5）→ **pass**（容差判，不是严格等于 0）
- R6 方程被前序满足、但本步值与前序不同（x=3 vs 4）→ **fail**
- R7 无 value 步 + 四位小数近似 → **pass**（E1 补丁：``_per_step_no_value``
  的尺度也必须取未代入的 ``expr``，否则同一个「自比自」缺陷只是换了个入口）

R6 是写完之后自测发现的：只判「方程残差」会把这步判 pass，而它其实是
「本步值与已确立的值冲突」的 E-10。方向是 fail→pass，必须守住。

任一断言失败即退出码 1。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 验证器 import l1_deduce as L1   # noqa: E402


def _doc(eq: str, sym: str, num: float, unit: str = "m",
         given: list[dict] | None = None) -> dict:
    """最小 answer 骨架：一步、一条 equation、一个 value。"""
    return {
        "meta": {"question_id": "R", "answer_id": "R"},
        "situation": {"given": given or []},
        "steps": [{
            "step_id": "R-S01",
            "step_no": 1,
            "kind": "equation",
            "statement": "红测构造步",
            "equation": {"sympy": eq, "parse_status": "ok"},
            "value": {"symbol": sym, "number": num, "unit": unit},
        }],
    }


def _run(doc: dict) -> L1.Verdict:
    """只走 per_step，不掺 chain（本次改的就是 per_step 一支）。"""
    recs = L1.prepare(doc)
    givens, _sv, _cf, _de = L1.collect_knowns(doc)
    return L1.per_step(recs, givens)["R-S01"]


def _doc_novalue(eq: str, given: list[dict] | None = None) -> dict:
    """最小 answer 骨架：一步、一条 equation、**没有 value**（走 no_value 分支）。"""
    doc = _doc(eq, "x", 0, given=given)
    doc["steps"][0].pop("value")
    return doc


def _expect(v: L1.Verdict, status: str, code: str | None, must: tuple[str, ...]) -> list[str]:
    errs = []
    if v.status != status:
        errs.append(f"应判 {status}，实为 {v.status}：{v.detail}")
    if v.error_code != code:
        errs.append(f"error_code 应为 {code}，实为 {v.error_code}")
    for m in must:
        if m not in v.detail:
            errs.append(f"detail 应含「{m}」，实为：{v.detail}")
    return errs


# --------------------------------------------------------------------------- 三条红线

def r1_前序矛盾_必须判fail() -> list[str]:
    doc = _doc("x - 5", "x", 4, given=[{"symbol": "x", "value": 3, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "fail", "E-10", ("前序", "-2"))


def r2_前序已满足_必须判pass() -> list[str]:
    doc = _doc("x - 3", "x", 3, given=[{"symbol": "x", "value": 3, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "pass", None, ("前序",))


def r3_无前序_走solve仍判fail() -> list[str]:
    doc = _doc("x - 5", "x", 4)
    v = _run(doc)
    return _expect(v, "fail", "E-10", ("解得",))


# --------------------------------------------------------------------------- 两条边界

def r4_方程不含本步符号_必须判na() -> list[str]:
    """位置守卫：新分支若放在 ``if sym not in names`` 之前，这步会被误判 pass。"""
    doc = _doc("t - 2", "x", 4, given=[{"symbol": "x", "value": 3, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "na", None, ("不含本步符号",))


def r5_四位小数近似_容差内判pass() -> list[str]:
    """前序写 0.3333、方程要求 1/3：残差 3.3e-5，按 2% 容差应放过。"""
    doc = _doc("x - Rational(1,3)", "x", 0.3333,
               given=[{"symbol": "x", "value": 0.3333, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "pass", None, ("残差",))


def r6_方程满足但值与前序不一致_必须判fail() -> list[str]:
    """方程 x−3=0 被前序 x=3 满足，但本步写 x=4：值本身与前序冲突，是 E-10。"""
    doc = _doc("x - 3", "x", 4, given=[{"symbol": "x", "value": 3, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "fail", "E-10", ("不一致", "前序"))


def r7_无value步_近似残差_容差内判pass() -> list[str]:
    """E1：no_value 分支的尺度若取已代入的 e，3.3e-5 的残差会自比自判 fail。"""
    doc = _doc_novalue("x - Rational(1,3)",
                       given=[{"symbol": "x", "value": 0.3333, "unit": "m"}])
    v = _run(doc)
    return _expect(v, "pass", None, ("残差",))


TESTS = [
    ("R1 前序 x=3 / 本步 x−5=0 却写 x=4 → fail", r1_前序矛盾_必须判fail),
    ("R2 前序 x=3 / 本步 x−3=0 写 x=3 → pass", r2_前序已满足_必须判pass),
    ("R3 无前序 / 本步 x−5=0 写 x=4 → fail", r3_无前序_走solve仍判fail),
    ("R4 方程不含本步符号 → na（位置守卫）", r4_方程不含本步符号_必须判na),
    ("R5 四位小数近似（残差 3.3e-5）→ pass", r5_四位小数近似_容差内判pass),
    ("R6 方程满足但值与前序不一致（3 vs 4）→ fail", r6_方程满足但值与前序不一致_必须判fail),
    ("R7 无 value 步 + 近似残差（E1）→ pass", r7_无value步_近似残差_容差内判pass),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print("=" * 70)
    print("L1 前序代入后无自由符号 · 守卫测试（T33 段 A + E1）")
    print("=" * 70)
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
    print("-" * 70)
    print(f"结论：{len(TESTS) - bad}/{len(TESTS)} passed"
          f"｜{'全部通过' if bad == 0 else '有失败项，见上'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

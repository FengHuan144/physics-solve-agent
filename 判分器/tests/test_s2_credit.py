# -*- coding: utf-8 -*-
"""test_s2_credit.py — T31 段 1 的守卫测试（C03 / 缺陷豁免 / 槽位碰撞 / 幂等）。

    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 判分器/tests/test_s2_credit.py

四条：
- C03：``½a₂t − L/6`` 是量纲真错（m/s vs m），credit 必须 **miss**，不许 hit。
- 缺陷豁免：A-05-S11 / A-06-S01 / B-07-S11 命中的点必须 **na + 对应标签**，不许 miss。
- 豁免不掩盖 pass：开/关豁免，hit 数必须相同（闸 6）。
- 槽位碰撞：A-05 的 ``M`` 在题内被赋 2 个不同值，相关点必须 na/slot_collision。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 判分器 import grader as G   # noqa: E402

ANS = ROOT / "评测" / "T20" / "out"


def _point(prod: dict, pid: str) -> dict:
    return next(r for r in prod["points"] if r["point_id"] == pid)


def _c03() -> list[str]:
    src = json.loads((ROOT / "schema" / "examples" / "A-06.json").read_text(encoding="utf-8"))
    src.setdefault("meta", {})["mode"] = "free"
    step = next(s for s in src["steps"] if s["step_id"] == "A-06-S04")
    step["equation"]["sympy"] = "Rational(1,2)*a2*t - L/6"
    step["equation"]["parse_status"] = "ok"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(src, f, ensure_ascii=False)
        p = Path(f.name)
    try:
        prod = G.grade(p, None)
    finally:
        p.unlink(missing_ok=True)
    r = _point(prod, "A-06-S04")
    errs = []
    if r["credit"] != "miss":
        errs.append(f"C03 应判 miss，实为 {r['credit']}：{r['basis']}")
    if "L2" not in r["basis"] or "fail" not in r["basis"]:
        errs.append(f"C03 basis 应写明 L2 fail，实为：{r['basis']}")
    if r["score"] != 0:
        errs.append(f"C03 应 0 分，实为 {r['score']}")
    return errs


def _defect(step_id: str) -> list[str]:
    qid = "-".join(step_id.split("-")[:2])
    prod = G.grade(ANS / f"{qid}.json", None)
    rows = [r for r in prod["points"] if step_id in r["by"]]
    if not rows:
        return [f"{step_id} 没有被任何点承载，无法验豁免"]
    errs = []
    for r in rows:
        if r["credit"] != "na":
            errs.append(f"{step_id} 承载的 {r['point_id']} 应 na，实为 {r['credit']}")
        if not any(k in r["basis"] for k in ("merged_step", "field_mismatch")):
            errs.append(f"{r['point_id']} basis 缺缺陷标签：{r['basis']}")
    return errs


def _exempt_not_mask_pass() -> list[str]:
    errs = []
    for qid in ("A-05", "A-06", "B-07"):
        a = G.grade(ANS / f"{qid}.json", None, use_defects=True)
        b = G.grade(ANS / f"{qid}.json", None, use_defects=False)
        ha, hb = a["summary"]["hit"], b["summary"]["hit"]
        if ha != hb:
            errs.append(f"{qid}: 开豁免 hit={ha}，关豁免 hit={hb}（豁免吞了 pass）")
    return errs


def _slot_collision() -> list[str]:
    prod = G.grade(ANS / "A-05.json", None)
    if prod["na_reasons"].get("slot_collision", 0) < 1:
        return [f"A-05 应至少 1 个 slot_collision，实为 {prod['na_reasons']}"]
    rows = [r for r in prod["points"] if r["basis"].startswith("slot_collision")]
    if any(r["credit"] != "na" for r in rows):
        return ["slot_collision 的点必须全部 na"]
    return []


def _idempotent() -> list[str]:
    a = G.grade(ANS / "B-12.json", None)
    b = G.grade(ANS / "B-12.json", None)
    return [] if json.dumps(a, ensure_ascii=False, sort_keys=True) == \
        json.dumps(b, ensure_ascii=False, sort_keys=True) else ["两次判分产物不一致"]


TESTS = [
    ("C03 ½a₂t−L/6 必须 miss（不许 hit）", _c03),
    ("缺陷豁免 A-05-S11", lambda: _defect("A-05-S11")),
    ("缺陷豁免 A-06-S01", lambda: _defect("A-06-S01")),
    ("缺陷豁免 B-07-S11", lambda: _defect("B-07-S11")),
    ("豁免不掩盖 pass（闸 6）", _exempt_not_mask_pass),
    ("槽位碰撞 A-05 守卫", _slot_collision),
    ("幂等（同输入两次 md5 级一致）", _idempotent),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print("=" * 70)
    print("S2 credit 守卫测试（T31 段 1）")
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
    raise SystemExit(main())

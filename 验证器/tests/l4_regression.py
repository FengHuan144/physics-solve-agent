# -*- coding: utf-8 -*-
"""l4_regression.py — L4 条件一致层的回归（2026-11-25 13:20）

用法：
    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/l4_regression.py; echo "exit=$?"

两段，退出码说话：

  1. 校准：4 份人工核过的正确样例，**不许出现判错**。
     出现即说明规则太严 —— 改规则，不许改样例。
  2. 反例：在 A-06 金标上做单点变异，5 条，每条断言「哪一步、什么状态、什么码」。

为什么不放在 cases.json 里：那是 L1/L2 的用例格式（含 expect_stats 等），
L4 的判据是「符号来源 + 小问归属」，断言对象不同，混在一起会互相绑死。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 验证器 import l4_condition as L4   # noqa: E402
from 验证器 import runner as R          # noqa: E402

SAMPLES = [ROOT / "schema" / "example_A-06.json",
           ROOT / "schema" / "examples" / "A-08.json",
           ROOT / "schema" / "examples" / "B-09.json",
           ROOT / "schema" / "examples" / "B-12.json"]
BASE = ROOT / "schema" / "example_A-06.json"

# 样例的四段统计（通过/判错/无法判）。判错恒为 0；na 只允许出现在有据可查的数据缺口上。
EXPECT_SAMPLES = {
    "example_A-06.json": (10, 0, 0),
    "A-08.json": (10, 0, 1),
    "B-09.json": (7, 0, 0),
    "B-12.json": (9, 0, 0),
}


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def find(doc: dict, sid: str) -> dict:
    return next(s for s in doc["steps"] if s.get("step_id") == sid)


def check_of(res: dict, sid: str) -> dict:
    return res["steps"][sid][0]


def expect(res: dict, sid: str, status: str, code: str | None = None,
           must_contain: tuple[str, ...] = ()) -> list[str]:
    c = check_of(res, sid)
    errs = []
    if c["status"] != status:
        errs.append(f"{sid} 期望 {status}，实得 {c['status']}（{c['error_code']}）")
    if code is not None and c.get("error_code") != code:
        errs.append(f"{sid} 期望错误码 {code}，实得 {c.get('error_code')}")
    for kw in must_contain:
        if kw not in (c.get("detail") or ""):
            errs.append(f"{sid} detail 里没提到「{kw}」：{c.get('detail')[:60]}")
    return errs


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    sub_map = L4.load_sub_map()
    total = 0
    print("== 1. 校准：4 份正确样例不许有判错 ==")
    if not sub_map:
        print("  ! 采分点总表读不到，规则 B 会全线 na —— 先查 原始资料/*.xlsx")
        total += 1
    for p in SAMPLES:
        doc = load(p)
        before = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        res = L4.analyze(doc, sub_map)
        after = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        st = res["stats"]
        want = EXPECT_SAMPLES.get(p.name)
        got = (st.get("pass", 0), st.get("fail", 0), st.get("na", 0))
        errs = []
        if before != after:
            errs.append("analyze() 改动了入参（必须只读）")
        if got != want:
            errs.append(f"统计 {got} ≠ 期望 {want}")
        if st.get("fail"):
            for sid, chks in res["steps"].items():
                if chks[0]["status"] == "fail":
                    errs.append(f"判错 {sid} {chks[0]['error_code']}：{chks[0]['detail'][:70]}")
        tag = f"{p.name:<20} 通过 {got[0]:>2} / 判错 {got[1]} / 无法判 {got[2]}"
        print(f"  {tag}  {'OK' if not errs else 'FAIL'}")
        for e in errs:
            print(f"      - {e}")
        total += len(errs)

    # 观察项也要如实：A-08 的两处缺口是真问题，不能悄悄消失
    res08 = L4.analyze(load(SAMPLES[1]), sub_map)
    kinds = {(f["kind"], f.get("symbol")) for f in res08["findings"]}
    for need in (("data_gap", "s1"), ("no_source", "ds")):
        if need not in kinds:
            print(f"  ! A-08 的观察项缺失：{need}（应如实报出）")
            total += 1

    print("\n== 2. 反例（A-06 金标单点变异）==")
    base = load(BASE)

    def run(mut) -> dict:
        d = copy.deepcopy(base)
        mut(d)
        return L4.analyze(d, sub_map)

    cases = []

    # R1a 单符号注入（加在产出步上）
    def m1a(d):
        s = find(d, "A-06-S02")
        s["equation"]["sympy"] = "mu*m*g - m*a1 + k"
        s["equation"]["symbols"] = ["mu", "m", "g", "a1", "k"]
    cases.append(("R1a 单符号 k 注入产出步", m1a,
                  lambda r: expect(r, "A-06-S02", "na", None, ("k",))))

    # R1b 两步都不会有的符号同时出现 → 一步定义不了两个
    def m1b(d):
        s = find(d, "A-06-S02")
        s["equation"]["sympy"] = "mu*m*g - m*a1 + k + r1"
        s["equation"]["symbols"] = ["mu", "m", "g", "a1", "k", "r1"]
    cases.append(("R1b 一步引入 2 个无来源量", m1b,
                  lambda r: expect(r, "A-06-S02", "fail", "E-04", ("k", "r1"))))

    # R2 第(1)问的步引用第(2)问才出现的量
    def m2(d):
        s = find(d, "A-06-S06")
        s["equation"]["sympy"] = "v0 - 4 - v2"
        s["equation"]["symbols"] = ["v0", "v2"]
    cases.append(("R2 引用了后问才出现的量", m2,
                  lambda r: expect(r, "A-06-S06", "fail", "E-14", ("v2",))))

    # R3 point_id 挂错小问
    def m3(d):
        find(d, "A-06-S03")["point_id"] = "A-06-S07"
    cases.append(("R3 point_id 挂到错的小问", m3,
                  lambda r: expect(r, "A-06-S03", "fail", "E-03", ("第(2)问",))))

    # R4 已知漏判：加在「无 value 的定义步」上，语法上与「本步定义一个新量」不可区分
    def m4(d):
        s = find(d, "A-06-S05")
        s["equation"]["sympy"] = "v0*t - Rational(1,2)*a1*t**2 - L - s2 + k"
        s["equation"]["symbols"] = ["v0", "t", "a1", "L", "s2", "k"]
    cases.append(("R4【已知漏判】定义步上的单符号", m4,
                  lambda r: expect(r, "A-06-S05", "pass")))

    for i, (name, mut, verify) in enumerate(cases, 1):
        try:
            res = run(mut)
            errs = verify(res)
        except Exception as exc:  # noqa: BLE001
            errs = [f"未捕获异常 {type(exc).__name__}: {exc}"]
        print(f"  [{i}/{len(cases)}] {name:<34} {'OK' if not errs else 'FAIL'}")
        for e in errs:
            print(f"      - {e}")
        total += len(errs)

    # R3 不许误伤同 point_id 的那一步
    res3 = run(m3)
    for sid in ("A-06-S07",):
        c = check_of(res3, sid)
        if c["status"] == "fail":
            print(f"  ! R3 误伤：{sid} 也被判错（{c['error_code']}）")
            total += 1

    # 幂等 + 输出过 Schema 的 check 契约
    doc = load(BASE)
    a = json.dumps(L4.analyze(doc, sub_map), ensure_ascii=False, sort_keys=True)
    b = json.dumps(L4.analyze(doc, sub_map), ensure_ascii=False, sort_keys=True)
    ok_idem = a == b
    print(f"  {'-' * 50}")
    print(f"  幂等：{'是' if ok_idem else '否'}")
    if not ok_idem:
        total += 1

    probe = copy.deepcopy(doc)
    res = L4.analyze(probe, sub_map)
    for s in probe["steps"]:
        sid = s.get("step_id")
        s["checks"] = [c for c in (s.get("checks") or []) if c.get("layer") != "L4"] + res["steps"][sid]
    viol = R.validate_checks(probe)      # 只读复用 L1/L2 的契约校验器
    print(f"  check 契约（definitions.check）：{'0 违约' if not viol else f'{len(viol)} 处违约'}")
    for v in viol[:3]:
        print(f"      - {v}")
    total += len(viol)

    print("\n" + "-" * 66)
    print(f"结论：{'全部通过' if total == 0 else f'{total} 项不通过，见上'}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

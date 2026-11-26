# -*- coding: utf-8 -*-
"""T00 独立审核回归测试（2026-11-25 10:26）

用法：
    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/audit_regression.py

本文件由 **审核方** 提供，不修改 T12a 的任何现有文件。它把审核报告 §2 的
两个漏判固化为红测：

  D 恒等式方程   equation.sympy = "0"     → L1 应为 na（与 L2 对齐），当前是 pass
  C 非 SI 单位   value.unit = "cm/s^2"     → 不许 L1/L2 双层全 pass，当前双层全过

设计意图：
- **当前这两个断言都应失败（退出码 1）**，这是如实记录「漏洞还在」。
- T12a 修完后本脚本应转绿（退出码 0）。这样验收不靠作者自述，靠审核方的红测。
- C 的断言只要求「双层不许同时 pass」，不指定由哪层以什么码抓。
  原因：修法三选一（L1 换算 SI / L2 对词头报 warn / Schema 约定 unit 必须 SI）
  属口径层，须由用户裁定，审核方不静默选。任一方案都能让本断言转绿。

对应报告：`审核报告_20261125_T05_T12a_T06a.md` §2.2 / §2.3 / §6 处置 2。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 验证器 import runner as R  # noqa: E402

BASE = HERE / "A-06.json"
B12 = HERE.parents[1] / "schema" / "examples" / "B-12.json"


def checks_of(out: dict, sid: str, layers=("L1", "L2")) -> list[dict]:
    for s in out.get("steps") or []:
        if s.get("step_id") == sid:
            return [c for c in s.get("checks") or [] if c.get("layer") in layers]
    return []


def statuses_of(out: dict, sid: str) -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    for c in checks_of(out, sid):
        d.setdefault(c["layer"], []).append(c["status"])
    return d


def statuses_all(out: dict) -> dict[str, dict[str, str]]:
    """``{step_id: {layer: status}}``，用于「改完必须和基线逐条相同」的比较。"""
    return {s["step_id"]: {c["layer"]: c["status"]
                           for c in (s.get("checks") or []) if c.get("layer") in ("L1", "L2")}
            for s in out.get("steps") or []}


def _detail_of(out: dict, sid: str, layer: str = "L1") -> str:
    for c in checks_of(out, sid, (layer,)):
        return c.get("detail") or ""
    return ""


def non_si_cases() -> list[str]:
    """T12aR2 卡 §4：自造 4 条非 SI 单位反例（2 条抓错 + 2 条不误杀）。

    审核方的 C 只压了一个词头（cm/s^2）；这里补 g / mm / cm→m 三个方向，
    并且**两个方向都测**：只证明「能抓错」不够，还要证明「换算后不误杀」。

    | # | 反例 | 期望 |
    |---|---|---|
    | E1 | B-12 题干 `m: 0.2 kg → 200 g`（真值 0.2 kg） | 与基线逐条相同（旧行为 3 步误判 fail） |
    | E2 | B-12 题干 `M: 0.6 kg → 800 g`（真值 0.8 kg，值真变了） | S02 不许 pass |
    | E3 | A-06 `S10 h: 0.5556 m → 5 mm`（真值 0.005 m） | S10 不许 pass |
    | E4 | A-06 题干 `L: 1.0 m → 100 cm`（真值 1.0 m） | 与基线逐条相同（旧行为 S04 误判 fail） |

    **只加不改**：上面 D / C 两条原有断言原样保留。
    """
    bad: list[str] = []
    a06 = json.loads(BASE.read_text(encoding="utf-8"))
    b12 = json.loads(B12.read_text(encoding="utf-8"))
    base_a06 = statuses_all(R.run_answer(copy.deepcopy(a06))[0])
    base_b12 = statuses_all(R.run_answer(copy.deepcopy(b12))[0])

    def same_as_baseline(tag: str, doc, base) -> None:
        out, _ = R.run_answer(doc)
        got = statuses_all(out)
        diff = {k: (base.get(k), got.get(k)) for k in base if base.get(k) != got.get(k)}
        if diff:
            bad.append(f"{tag}: 换算后结果变了 {len(diff)} 处（{diff}）")
        else:
            print(f"   [{tag}] 与基线逐条相同（{len(base)} 步）")

    def not_pass(tag: str, doc, sid: str) -> None:
        out, _ = R.run_answer(doc)
        st = statuses_of(out, sid).get("L1", [])
        if st == ["pass"] or not st:
            bad.append(f"{tag}: {sid} L1 判 {st or '无结果'}，期望非 pass")
        else:
            print(f"   [{tag}] {sid} L1 {st[0]} → {_detail_of(out, sid)[:96]}")

    print("\n== E1 千倍前缀·克（不误杀）：B-12 题干 m 0.2 kg → 200 g ==")
    d = copy.deepcopy(b12)
    for g in d["situation"]["given"]:
        if g["symbol"] == "m":
            g["value"], g["unit"] = 200, "g"
    same_as_baseline("E1", d, base_b12)

    print("\n== E2 千倍前缀·克（抓错）：B-12 题干 M 0.6 kg → 800 g（真值 0.8 kg）==")
    d = copy.deepcopy(b12)
    for g in d["situation"]["given"]:
        if g["symbol"] == "M":
            g["value"], g["unit"] = 800, "g"
    not_pass("E2", d, "B-12-S02")

    print("\n== E3 毫米步值（抓错）：A-06 S10 h 0.5556 m → 5 mm ==")
    d = copy.deepcopy(a06)
    for s in d["steps"]:
        if s["step_id"] == "A-06-S10":
            s["value"]["number"], s["value"]["unit"] = 5, "mm"
    not_pass("E3", d, "A-06-S10")

    print("\n== E4 厘米题干（不误杀）：A-06 题干 L 1.0 m → 100 cm ==")
    d = copy.deepcopy(a06)
    for g in d["situation"]["given"]:
        if g["symbol"] == "L":
            g["value"], g["unit"] = 100, "cm"
    same_as_baseline("E4", d, base_a06)

    print("\n新增 4 条：%s" % ("全部通过" if not bad else "%d 条未通过" % len(bad)))
    return bad


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    base = json.loads(BASE.read_text(encoding="utf-8"))
    failures: list[str] = []

    # ---------------------------------------------------------------- D 恒等式
    d = copy.deepcopy(base)
    target_d = None
    for s in d["steps"]:
        if s["step_id"] == "A-06-S05":
            s["equation"]["sympy"] = "0"
            target_d = s
    assert target_d is not None, "A-06.json 里找不到 A-06-S05"

    out_d, _ = R.run_answer(d)
    st_d = statuses_of(out_d, "A-06-S05")
    print("== D 恒等式方程（equation.sympy = \"0\"）==")
    for c in checks_of(out_d, "A-06-S05"):
        print("   %-3s %-8s %-6s %s" % (
            c["layer"], c["status"], c.get("error_code") or "-",
            (c.get("detail") or "")[:64]))
    l1_d = st_d.get("L1", [])
    if not l1_d or l1_d[0] != "na":
        failures.append(
            "D: L1 判 %s，期望 na（方程化简为 0，无可比两侧；须与 L2 对齐）"
            % (l1_d or "无 L1 结果"))
    else:
        print("   -> PASS：L1 已判 na")

    # ---------------------------------------------------------------- C 非 SI 单位
    c = copy.deepcopy(base)
    target_c = None
    for s in c["steps"]:
        if s["step_id"] == "A-06-S02":
            s["value"]["unit"] = "cm/s^2"   # number 仍为 3；真值 3 m/s²，差 100 倍
            target_c = s
    assert target_c is not None, "A-06.json 里找不到 A-06-S02"

    out_c, _ = R.run_answer(c)
    st_c = statuses_of(out_c, "A-06-S02")
    print("\n== C 非 SI 单位（number=3, unit=cm/s^2，实为 0.03 m/s²）==")
    for ck in checks_of(out_c, "A-06-S02"):
        print("   %-3s %-8s %-6s %s" % (
            ck["layer"], ck["status"], ck.get("error_code") or "-",
            (ck.get("detail") or "")[:64]))
    all_pass = bool(st_c) and all(
        all(v == "pass" for v in vs) for vs in st_c.values())
    if all_pass:
        failures.append(
            "C: L1/L2 双层全 pass（%s），100 倍数值差未被任何一层标记"
            % st_c)
    else:
        print("   -> PASS：至少一层未判 pass（%s）" % st_c)

    # ---------------------------------------------------------------- 本卡新增 4 条
    failures += non_si_cases()

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 66)
    if failures:
        print("红测结果：%d 项仍为缺陷（预期内，修完应转绿）" % len(failures))
        for f in failures:
            print("   [FAIL] " + f)
        print("\n退出码 1 = 漏洞仍在。T12a 修完后重跑本脚本，应输出「全部通过」+ 退出码 0。")
        return 1
    print("全部通过：两个漏判均已修复（退出码 0）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

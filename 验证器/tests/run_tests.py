# -*- coding: utf-8 -*-
"""run_tests.py — 验证器的四段自测。

用法：
    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/run_tests.py
    python 验证器/tests/run_tests.py --alias     # 开 T23 别名层（金标应零改写）

四段：
  1. 人造反例（tests/cases.json）：E-10 / E-12 / E-11 / E-04 可抓 / E-04 抓不到 /
     欠定 / degraded，每条断言「哪层、什么码、哪些步失败」
  2. A-06 真数据（10 步金标）：不许有假阳性
  3. 公式库 L2 扫描（74 条真公式 + 真白名单单位）：L2 的规模化验证
  4. 采分点总表可判性审计：把「61 步为什么跑不了」变成可核对的数字

任一断言失败即退出码 1。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 验证器 import l2_dimension as L2          # noqa: E402
from 验证器 import runner as R                 # noqa: E402


def find_step(doc: dict, sid: str) -> dict | None:
    for s in doc.get("steps") or []:
        if s.get("step_id") == sid:
            return s
    return None


def apply_mutations(doc: dict, muts: list[dict]) -> dict:
    doc = copy.deepcopy(doc)
    for m in muts:
        op = m["op"]
        if op == "given":
            doc.setdefault("situation", {})["given"] = copy.deepcopy(m["value"])
        elif op == "steps":
            doc["steps"] = copy.deepcopy(m["value"])
        else:
            step = find_step(doc, m["step"])
            if step is None:
                raise KeyError(f"变异目标不存在：{m['step']}")
            if op == "value_number":
                step["value"]["number"] = m["value"]
            elif op == "value_unit":
                step["value"]["unit"] = m["value"]
            elif op == "sympy":
                step["equation"]["sympy"] = m["value"]
                if "symbols" in m:
                    step["equation"]["symbols"] = m["symbols"]
            elif op == "parse_status":
                step["equation"]["parse_status"] = m["value"]
            else:
                raise ValueError(f"未知变异操作：{op}")
    return doc


def fail_steps(doc: dict) -> list[str]:
    return sorted({s["step_id"] for s in doc.get("steps") or []
                   for c in s.get("checks") or [] if c.get("status") == "fail"})


def check_case(out: dict, rep: dict, case: dict) -> list[str]:
    errs: list[str] = []
    for exp in case.get("expect") or []:
        step = find_step(out, exp["step"])
        if step is None:
            errs.append(f"{exp['step']} 不存在")
            continue
        cands = [c for c in step.get("checks") or [] if c.get("layer") == exp["layer"]]
        hit = [c for c in cands
               if c.get("status") == exp["status"]
               and ("error_code" not in exp or c.get("error_code") == exp["error_code"])]
        if not hit:
            got = "；".join(f"{c['status']}/{c.get('error_code')}" for c in cands) or "无"
            errs.append(f"{exp['step']} {exp['layer']} 期望 "
                        f"{exp['status']}/{exp.get('error_code')}，实得 {got}")
    got_fail = fail_steps(out)
    want_fail = sorted(case.get("expect_fail_steps") or [])
    if got_fail != want_fail:
        errs.append(f"失败步集合不符：期望 {want_fail}，实得 {got_fail}")
    if "expect_stats" in case:
        for layer, want in case["expect_stats"].items():
            got = rep["checks"].get(layer) or {}
            norm = {k: got.get(k, 0) for k in ("pass", "fail", "na", "skipped")}
            if norm != want:
                errs.append(f"{layer} 统计不符：期望 {want}，实得 {norm}")
    if "expect_data_errors" in case:
        got = sorted({d["step_id"] for d in rep.get("data_errors") or []})
        want = sorted(case["expect_data_errors"])
        if got != want:
            errs.append(f"data_error 步不符：期望 {want}，实得 {got}")
    viol = R.validate_checks(out)
    if viol:
        errs.append(f"check 契约违约 {len(viol)} 处：{viol[:2]}")
    return errs


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    # T23：--alias 开别名层。金标（A-06）用的是白名单符号，开了应当零改写、数字不变。
    ALIAS = "--alias" in sys.argv[1:]
    print(f"别名层：{'开（--alias）' if ALIAS else '关（默认）'}")

    cases_doc = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    base = json.loads((HERE / cases_doc["base"]).read_text(encoding="utf-8"))

    total_fail = 0
    crashes = 0

    # ---------------------------------------------------------------- 1. cases
    print("== 1. 人造反例 ==")
    cases = cases_doc["cases"]
    passed = 0
    for i, case in enumerate(cases, 1):
        try:
            mutated = apply_mutations(base, case["mutations"])
            out, rep = R.run_answer(mutated, alias=ALIAS)
            errs = check_case(out, rep, case)
        except Exception as exc:  # noqa: BLE001
            crashes += 1
            errs = [f"未捕获异常 {type(exc).__name__}: {exc}"]
        tag = f"[{i}/{len(cases)}] {case['id']} {case['name']}"
        if errs:
            print(f"  {tag:<52} FAIL")
            for e in errs:
                print(f"        - {e}")
        else:
            passed += 1
            print(f"  {tag:<52} OK")
    print(f"  {passed}/{len(cases)} cases passed")
    if passed != len(cases):
        total_fail += 1

    # ---------------------------------------------------------------- 2. 真数据
    print("\n== 2. 真数据（A-06 金标 10 步）==")
    src = ROOT / "schema" / "example_A-06.json"
    copy = HERE / "A-06.json"
    if src.exists() and src.read_bytes() != copy.read_bytes():
        print(f"  ! 注意：{copy.name} 与 schema/example_A-06.json 已不一致（副本被改过或源已更新）")
    out, rep = R.run_answer(base, alias=ALIAS)
    l1, l2 = rep["checks"].get("L1", {}), rep["checks"].get("L2", {})
    print(f"  L1  pass {l1.get('pass', 0)} / fail {l1.get('fail', 0)} / "
          f"na {l1.get('na', 0)} / skipped {l1.get('skipped', 0)}")
    print(f"  L2  pass {l2.get('pass', 0)} / fail {l2.get('fail', 0)} / "
          f"na {l2.get('na', 0)} / skipped {l2.get('skipped', 0)}")
    if rep["failures"]:
        total_fail += 1
        print(f"  FAIL：金标出现 {len(rep['failures'])} 处 fail（假阳性）")
        for f in rep["failures"]:
            print(f"        - {f['step_id']} {f['layer']}/{f['error_code']} {f['detail'][:80]}")
    else:
        print("  假阳性：0（金标不应有任何 fail）")

    # 幂等
    out2, _ = R.run_answer(base, alias=ALIAS)
    a = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=False)
    b = json.dumps(out2, ensure_ascii=False, indent=2, sort_keys=False)
    print(f"  幂等：{'是（两次输出逐字节一致）' if a == b else '否'}")
    if a != b:
        total_fail += 1
    out3, _ = R.run_answer(out, alias=ALIAS)      # 对自己的输出再跑一次（幂等的强形式）
    c = json.dumps(out3, ensure_ascii=False, indent=2, sort_keys=False)
    print(f"  幂等（对自己的输出再跑）：{'是' if c == a else '否'}")
    if c != a:
        total_fail += 1

    # ---------------------------------------------------------------- 3. 公式库
    print("\n== 3. 公式库 L2 扫描（74 条真公式）==")
    sweep = L2.sweep_formula_lib()
    print(f"  {sweep['pass']}/{sweep['total']} pass，{sweep['fail']} fail，"
          f"{sweep['data_error']} data_error")
    for row in sweep["rows"]:
        if row["status"] != "pass":
            print(f"        - {row['formula_id']} {row['sympy']} → {row['detail']}")
    if sweep["fail"] or sweep["data_error"]:
        total_fail += 1

    # ---------------------------------------------------------------- 4. 台账
    print("\n== 4. 采分点总表可判性 ==")
    audit = R.audit_xlsx()
    print(f"  台账 {audit['rows']} 行 / {audit['questions']} 题 / {audit['score']:g} 分"
          f"（A-01~A-06 段 {audit['first_six_rows']} 行 / {audit['first_six_score']:g} 分）")
    print(f"  equation.sympy 列：{audit['has_sympy_column']}｜value 数值列：{audit['has_value_column']}")
    print(f"  含等号的式子型文本：全表 {audit['rows_with_equal_sign']} 行"
          f"（A-01~A-06 段 {audit['first_six_with_equal_sign']} / {audit['first_six_rows']} 行）"
          f"——散文里的符号，不是可解析表达式")
    print(f"  可判步：0 / {audit['rows']} → 卡 R1 的「61 步」结构性 BLOCKED（详见 说明.md §6）")

    print("\n" + "-" * 66)
    ok = total_fail == 0 and crashes == 0
    print(f"结论：cases {passed}/{len(cases)}｜未捕获异常 {crashes}｜"
          f"{'全部通过' if ok else '有失败项，见上'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

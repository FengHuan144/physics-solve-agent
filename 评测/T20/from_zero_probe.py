#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""from_zero_probe.py — 「题库外新题」可行性探针（一次性，不接产品）

目的：只回答一个问题——不给金标（schema/examples/{qid}.json）、不给采分点表，
只给一段题干文字，模型能不能独立产出一份结构完整、公式可解析的解析？

与 run_solve 的差别（这就是「从零」的全部差别）：
  1. 题干硬编码在本文件里（自编题，题库与金标中都不存在）
  2. prompt 的【分值】行不写死，改为「见题干小问标注」——现有模板把 B-20 的
     「14 分 (1)4 (2)(ⅰ)4 (2)(ⅱ)6」套给了所有题，A-01 实际 12 分 3/6/3
  3. 额外要求模型输出 objects（物体表）与 sub_scores（小问分值），
     因为现有 draft_to_schema.build() 这两块是从金标 deepcopy 的，新题没有

只落盘、只自检，不写 schema、不跑验证器、不渲染页面。

    python 评测/T20/from_zero_probe.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(HERE))
import run_solve as R                                    # noqa: E402

OUT = HERE / "logs"
TZ = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 新题（自编）

STEM = """一质量 m = 1 kg 的物块（可视为质点）放在水平桌面上，桌面右端 B 与一倾角 θ = 37° 的斜面平滑连接。物块与桌面、斜面间的动摩擦因数均为 μ = 0.5。物块在桌面上从 A 点以 v0 = 6 m/s 的初速度向右运动，A、B 间距离 L = 1.6 m。物块经 B 点滑上斜面，沿斜面向上运动一段距离后速度减为零。已知 sin37° = 0.6，cos37° = 0.8，重力加速度 g = 10 m/s²。

(1) 求物块到达 B 点时的速度大小；（4 分）
(2) 求物块沿斜面向上滑行的最大距离；（5 分）
(3) 通过计算判断物块能否从斜面上滑回，若能，求它回到桌面上后还能滑行的距离。（5 分）"""

# 手算答案，用于核对（不作为输入给模型）
EXPECT = {
    "(1)": "vB = sqrt(20) ≈ 4.47 m/s（2√5）",
    "(2)": "s = 1 m",
    "(3)": "tan37°=0.75 > μ=0.5，会滑回；回到 B 时 v=2 m/s，桌面再滑 0.4 m",
}

EXTRA_RULES = """- `objects`：本题涉及的物体清单，每项 {"name": "…", "mass_symbol": "…"}；只列有质量的物体，没有质量的（桌面、斜面）不要列。
- `sub_scores`：每个小问的分值，[{"no": "(1)", "score": 4}, …]，必须与题干标注一致。
"""


def build_prompt() -> str:
    tpl = (HERE / "prompt_v1.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- TEMPLATE_START -->(.*?)<!-- TEMPLATE_END -->", tpl, re.S)
    if not m:
        raise SystemExit("prompt_v1.md 缺 TEMPLATE_START/END")
    body = m.group(1).strip()

    # 1) 分值行不写死：换成指向题干
    body = re.sub(r"【分值】[^\n]*\n",
                  "【分值】每个小问的分值已标注在题干里，照它分配；每个小问内所有步的 `score` 之和必须等于该问分值。\n",
                  body, count=1)
    # 2) 追加 objects / sub_scores 要求
    body = body.replace("- `point`：", EXTRA_RULES + "- `point`：", 1)
    # 3) 题干
    return body.replace("{题干}", STEM)


# ---------------------------------------------------------------- 自检

FUNC = {"Rational", "sqrt", "sin", "cos", "tan", "pi", "log", "exp", "Piecewise", "Eq"}
TOK = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def check(draft: dict) -> list[tuple[str, bool, str]]:
    """返回 [(检查项, 通过?, 说明)]"""
    out = []
    steps = draft.get("steps") or []
    out.append(("JSON 有 steps", bool(steps), "步数 %d" % len(steps)))

    # 编号连续
    nos = [int(s.get("no") or 0) for s in steps]
    out.append(("步骤编号 1..n 连续", nos == list(range(1, len(steps) + 1)),
                str(nos[:12])))

    # sympy 可解析
    import sympy
    bad_eq, n_eq = [], 0
    for s in steps:
        eq = s.get("eq")
        if not eq:
            continue
        n_eq += 1
        try:
            sympy.sympify(eq, locals={"Rational": sympy.Rational})
        except Exception as e:                            # noqa: BLE001
            bad_eq.append((s.get("no"), str(e)[:60]))
    out.append(("eq 全部可被 sympy 解析", not bad_eq, "%d 条式子，失败 %s" % (n_eq, bad_eq[:3])))

    # 小数违规（prompt 禁止 0.5 等小数系数）
    dec = [s.get("no") for s in steps if s.get("eq") and re.search(r"\d\.\d", s["eq"])]
    out.append(("eq 内无小数字面量", not dec, "违规步 %s" % (dec[:5] or "无")))

    # 分值
    tot = sum(float(s.get("score") or 0) for s in steps)
    ss = {x.get("no"): float(x.get("score") or 0) for x in draft.get("sub_scores") or []}
    out.append(("总步分 = 14", abs(tot - 14) < 1e-6, "合计 %.1f" % tot))
    out.append(("小问分 = 4/5/5", [ss.get(k) for k in ("(1)", "(2)", "(3)")] == [4.0, 5.0, 5.0],
                str(ss)))

    # 公式里的符号是否在 stmt 出现过（旧缺陷）
    miss = []
    for s in steps:
        if not s.get("eq"):
            continue
        stmt = s.get("stmt") or ""
        ids = {t for t in TOK.findall(s["eq"]) if t not in FUNC}
        left = sorted(t for t in ids if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) +
                                                      r"(?![A-Za-z0-9_])", stmt))
        if left:
            miss.append((s.get("no"), left))
    out.append(("公式符号都在正文出现", not miss, "残留 %s" % (miss[:4] or "无")))

    # objects
    objs = draft.get("objects") or []
    out.append(("有 objects", bool(objs), json.dumps(objs, ensure_ascii=False)[:120]))
    return out


def main() -> int:
    if not R.os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY 不存在")
    OUT.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt()
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    (OUT / f"fromzero_prompt_{stamp}.txt").write_text(prompt, encoding="utf-8")

    bal = R.balance()
    print("[余额] %.2f CNY" % bal)
    if bal < R.MIN_BALANCE:
        raise SystemExit("[停止] 余额不足")

    print("[调用] model=%s  prompt=%d 字（无图）" % (R.MODEL, len(prompt)))
    t0 = time.time()
    res = R.call(prompt, [])
    el = time.time() - t0
    if not res.get("ok"):
        print("[失败]", res.get("status"), str(res.get("error"))[:400])
        return 1
    u = res.get("usage") or {}
    print("[返回] %.1fs  in=%s out=%s reasoning=%s finish=%s"
          % (el, u.get("prompt_tokens"), u.get("completion_tokens"),
             (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
             res.get("finish_reason")))

    (OUT / f"fromzero_raw_{stamp}.txt").write_text(
        res.get("content") or "", encoding="utf-8")
    draft, err = R.parse_draft(res.get("content") or "")
    if not draft:
        print("[JSON 解析失败]", err)
        return 1
    (OUT / f"fromzero_draft_{stamp}.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 68)
    for name, ok, note in check(draft):
        print("%s %-22s %s" % ("PASS" if ok else "FAIL", name, note))

    print("\n" + "=" * 68)
    print("模型自答：")
    for sr in draft.get("sub_results") or []:
        print("  %s %s" % (sr.get("no"), sr.get("result")))
    print("\n手算期望：")
    for k, v in EXPECT.items():
        print("  %s %s" % (k, v))

    print("\n" + "=" * 68)
    print("逐步（no | kind | score | title | eq | value）")
    for s in draft.get("steps") or []:
        v = s.get("value") or {}
        print("%2s | %-10s | %-4s | %-16s | %s | %s"
              % (s.get("no"), s.get("kind"), s.get("score"),
                 (s.get("title") or "")[:16], (s.get("eq") or "—")[:58],
                 (v.get("symbol") or "") + "=" + str(v.get("number") or v.get("exact") or "")))
    print("\n落盘：%s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

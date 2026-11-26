# -*- coding: utf-8 -*-
"""l4_condition.py — L4 条件一致层（只读 Schema 解析结果，不解方程）。

`原始资料/agent.md:61` 对 L4 的定义是「是否用了题干未给的条件」，落到能写代码的是三条：

  A 符号来源  步里出现的符号必须有来源：题干 / 物体质量 / 题目标量 / 前序步定义 / g
  B 小问归属  步的小问与 point_id 一致；不许引用只在后问才出现的量
  C 边界一致  位移从哪算起、区间端点 —— 只能半自动，本模块只报缺口不硬判

设计纪律（卡 §0）：
- 不改 l1_deduce.py / l2_dimension.py，不改 Schema；
- 不用 LLM 判语义；
- 判不了就 na + 写清缺什么，**不把判不了的判成 pass**。

一处与卡文的偏差，写在 说明.md §11.2：卡列了 4 类来源，本模块加了第 5 类
``situation.targets[].quantity``（题干要求求的量）。理由：题目要求求 v0，解它必然要引入 v0，
不引入反而是漏答（E-08）。这不是放宽，是把「要求求」和「凭空给」区分开。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
XLSX_PATH = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"

CONST_SYMBOLS = {"g"}          # ④ 通用常量白名单：只有 g，不扩
CODE_NO_SOURCE = "E-04"        # 枚举缺「凭空引入未给条件」这一码，沿用 T12a 先例
CODE_STAGE = "E-03"            # 过程分段错位 / 归属错挂
CODE_STATE = "E-14"            # 状态量取错时刻（引用了后问才出现的量）
CODE_PRIORITY = (CODE_STAGE, CODE_STATE, CODE_NO_SOURCE)

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

# criterion 符号提取用（见 _criterion_symbols）。函数名与常量不算符号。
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CRIT_FUNCS = {
    "Rational", "Integer", "Float", "sqrt", "sin", "cos", "tan", "cot",
    "exp", "log", "ln", "Abs", "Eq", "Ne", "Lt", "Gt", "Piecewise",
    "pi", "E", "oo", "true", "false", "None",
}


# --------------------------------------------------------------------------- 小问归属

def load_sub_map(xlsx: str | Path | None = None) -> dict[str, int]:
    """``point_id → 小问号``。台账是唯一的小问归属数据源，读不到就返回空字典。"""
    path = Path(xlsx) if xlsx else XLSX_PATH
    if not path.exists():
        return {}
    try:
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb["采分点总表"]
        rows = ws.iter_rows(values_only=True)
        head = [str(c).strip() if c is not None else "" for c in next(rows)]
        i_pid, i_sub = head.index("point_id"), head.index("小问")
        out: dict[str, int] = {}
        for r in rows:
            pid = str(r[i_pid] or "").strip()
            m = re.search(r"\((\d+)\)", str(r[i_sub] or ""))
            if pid and m:
                out[pid] = int(m.group(1))
        return out
    except Exception:  # noqa: BLE001  台账读不了不是判错，是缺数据源
        return {}


# --------------------------------------------------------------------------- 主流程

def analyze(doc: dict, sub_map: dict[str, int] | None = None) -> dict:
    """跑一遍 L4。返回 ``{"steps": {sid: [check]}, "findings": [...], "stats": {...}}``。

    每步最多一条 check（同层一条），A/B/C 的病灶合并进去：有 fail 即 fail，
    错误码按 §11.4 的优先级取一个，detail 列全部病灶。
    """
    sub_map = load_sub_map() if sub_map is None else sub_map
    steps = doc.get("steps") or []
    given_syms, mass_syms, target_syms = _global_sources(doc)

    base = given_syms | mass_syms | target_syms | CONST_SYMBOLS
    defined: dict[str, int] = {}      # 已认可为「已知」的符号 → 步序号（用来抑制重复报）
    first_def: dict[str, int] = {}    # **真正被定义**的符号 → 步序号（规则 B 只用这张）
    findings: list[dict] = []

    subs: dict[str, int | None] = {}
    for s in steps:
        pid = s.get("point_id")
        subs[s.get("step_id")] = sub_map.get(str(pid)) if pid else None

    out: dict[str, list[dict]] = {}
    # ---- 第一遍：规则 A（符号来源），同时建立「首次定义步」表
    per: dict[str, dict] = {}
    for i, step in enumerate(steps):
        sid = str(step.get("step_id"))
        problems: list[tuple[str, str]] = []      # (code, 说明)
        notes: list[str] = []
        nas: list[str] = []

        # ---------------- 规则 A：符号来源
        eq = step.get("equation") or {}
        val = step.get("value") or {}
        val_sym = (val.get("symbol") or "").strip() or None
        val_num = val.get("number")
        used = {(str(x).strip()) for x in (eq.get("symbols") or []) if str(x).strip()}
        if val_sym:
            used.add(val_sym)
        used |= _criterion_symbols(step.get("criterion"))
        new = sorted(used - base - set(defined))
        outside = [x for x in new if not (val_sym and x == val_sym and val_num is not None)]
        if val_sym and val_num is not None:
            # 有数值的产出步就是该符号的「定义步」，即使它此前被当作已知放行过
            first_def.setdefault(val_sym, i)

        if not new:
            notes.append("符号全部有来源")
        elif not outside:
            notes.append(f"本步定义并求出 {val_sym}")
            defined[val_sym] = i
            first_def[val_sym] = i
        elif val_num is None:
            # 本步不出数值：方程就是「新量 = 已给量的组合」，这唯一的新量视为本步的定义
            notes.append(f"本步以方程定义 {new[0]}（未赋值）")
            defined[new[0]] = i
            first_def[new[0]] = i
            if _mentioned_elsewhere(steps, i, new[0]):
                findings.append({
                    "kind": "data_gap", "step_id": sid, "symbol": new[0],
                    "detail": (f"{new[0]} 在本步首次出现且整题从未赋值，"
                               f"但在别步的 statement 里出现过 —— 文本有、结构化数据没有"),
                })
        elif len(outside) == 1 and (_mentions(str(step.get("statement") or "") + str(step.get("title") or ""),
                                              outside[0]) or _mentioned_elsewhere(steps, i, outside[0])):
            # 文本里有、结构化数据里没有：是数据缺口，不是凭空条件 → 不判 na
            notes.append(f"本步产出 {val_sym}；{outside[0]} 在文本里有交代但没落成字段（数据缺口）")
            findings.append({
                "kind": "data_gap", "step_id": sid, "symbol": outside[0],
                "detail": f"{outside[0]} 无 value / 无 equation 定义，但本步或别步的文本提到过它",
            })
            if val_sym:
                defined[val_sym] = i
            defined[outside[0]] = i
        elif len(outside) == 1:
            # 本步有产出，却还依赖一个无来源的量，文本里也找不到它：二义，不硬判
            nas.append(f"本步产出 {val_sym}，另用到无来源的 {outside[0]}（无法判是数据缺口还是凭空条件）")
            findings.append({
                "kind": "no_source", "step_id": sid, "symbol": outside[0],
                "detail": f"{outside[0]} 在图里没有任何来源（非题干/物体质量/目标/前序步/g）",
            })
            # 两个都登记：本步确实产出了 val_sym；outside 已点名一次，后续步不重复报同一处
            if val_sym:
                defined[val_sym] = i
            defined[outside[0]] = i
        else:
            problems.append((CODE_NO_SOURCE,
                             f"本步在给定之外引入 {len(outside)} 个量：{'、'.join(outside)}"
                             f"（一步最多定义一个；其余视为凭空条件）"))
            # 刻意不登记为已定义：后面若再引用它们，仍会在这里报

        # ---------------- 规则 B：小问归属（留到第二遍，那时 first_def 才完整）
        per[sid] = {"i": i, "problems": problems, "notes": notes, "nas": nas,
                    "used": used, "step": step}

    # ---- 第二遍：规则 B 需要「全题的首次定义步」，所以必须等 A 扫完
    for sid, rec in per.items():
        i, step = rec["i"], rec["step"]
        problems, notes, nas = rec["problems"], rec["notes"], rec["nas"]
        sub = subs.get(sid)
        if sub is None:
            nas.append("point_id 未对齐或不在采分点表，无小问归属可判")
        else:
            cross = []
            for sym in rec["used"]:
                k = first_def.get(sym)
                if k is None or k <= i:
                    continue
                ksub = subs.get(str(steps[k].get("step_id")))
                if ksub is not None and ksub > sub:
                    cross.append((sym, k, ksub))
            if cross:
                sym, k, ksub = cross[0]
                problems.append((CODE_STATE,
                                 f"本步属第({sub})问，却用了 {sym} —— 它在第({ksub})问的 "
                                 f"{steps[k].get('step_id')} 才出现"))
            outlier = _sub_outlier(steps, subs, i)
            dup = _duplicate_point(steps, step)
            if outlier:
                bits = [f"本步挂第({sub})问，但前后两步都在第({outlier})问"]
                if dup:
                    bits.append(f"point_id={step.get('point_id')} 与 {dup} 重复，同一采分点被两步占了")
                problems.append((CODE_STAGE, "；".join(bits)))
            elif dup:
                # 重复但无旁证判断哪一处挂错 → 只报观察，不挑一个判错
                findings.append({"kind": "duplicate_point", "step_id": sid,
                                 "symbol": str(step.get("point_id")),
                                 "detail": f"point_id 与 {dup} 重复，无旁证判断哪一处挂错"})

        out[sid] = [_merge(problems, nas, notes)]

    # ---------------- 题级：C 与覆盖
    findings.extend(_question_level(doc, subs))

    stats = {"pass": 0, "fail": 0, "na": 0, "skipped": 0}
    for checks in out.values():
        for c in checks:
            stats[c["status"]] = stats.get(c["status"], 0) + 1
    return {"steps": out, "findings": findings, "stats": stats,
            "layer": _layer_state(stats)}


def _merge(problems: list[tuple[str, str]], nas: list[str], notes: list[str]) -> dict:
    """A/B 的病灶合成一条 L4 check。有 fail 报 fail，其次 na，最后 pass。"""
    if problems:
        code = next((c for c in CODE_PRIORITY if any(p[0] == c for p in problems)),
                    problems[0][0])
        detail = "；".join(p[1] for p in problems)
        if nas:
            detail += "；另：" + "；".join(nas)
        return {"layer": "L4", "status": "fail", "detail": detail, "error_code": code}
    if nas:
        detail = "；".join(nas)
        if notes:
            detail += "（符号来源：" + "；".join(notes) + "）"
        return {"layer": "L4", "status": "na", "detail": detail, "error_code": None}
    return {"layer": "L4", "status": "pass", "detail": "；".join(notes), "error_code": None}


def _layer_state(stats: dict) -> str:
    if stats.get("fail"):
        return "fail"
    if stats.get("pass"):
        return "pass"
    if stats.get("skipped"):
        return "skipped"
    return "na"


# --------------------------------------------------------------------------- 辅助

def _global_sources(doc: dict) -> tuple[set[str], set[str], set[str]]:
    sit = doc.get("situation") or {}
    given = {(g.get("symbol") or "").strip() for g in sit.get("given") or []} - {""}
    mass = {(o.get("mass_symbol") or "").strip() for o in sit.get("objects") or []} - {""}
    targ = {(t.get("quantity") or "").strip() for t in sit.get("targets") or []} - {""}
    return given, mass, targ


def _criterion_symbols(crit: dict | None) -> set[str]:
    """从判断步的 criterion 里取出它引用的符号。

    为什么需要这个（2026-11-25 15:30，Schema 1.2 引入 criterion 后发现的盲区）：
    `equation` 有结构化的 `symbols` 字段，L4 直接读；但 `criterion` 只有
    `{expr, expected, comparator, text}`，**没有 symbols**。若 L4 只读 equation，
    判断步引用的符号就完全不进「来源检查」，A-08-S10 的 s1（无来源）就是这么漏掉的。

    做法：优先读 `criterion.symbols`（若将来补上该字段），否则从 `expr` / `expected`
    做标识符切分并剔除函数名。这两条路都对，前者精确、后者兜底。

    注意：这里**只提取符号，不判定语义**。是否「有来源」仍由调用方的既有规则判。
    """
    if not crit:
        return set()
    if isinstance(crit.get("symbols"), list):
        return {str(x).strip() for x in crit["symbols"] if str(x).strip()}
    out: set[str] = set()
    for key in ("expr", "expected"):
        s = crit.get(key)
        if not s:
            continue
        for tok in _IDENT_RE.findall(str(s)):
            if tok in _CRIT_FUNCS:
                continue
            out.add(tok)
    return out


def _mentions(text: str, sym: str) -> bool:
    """符号是否出现在文本里（含 Unicode 下标写法：s₁ → s1）。"""
    if not text or not sym:
        return False
    return sym in text.translate(_SUB)


def _mentioned_elsewhere(steps: list[dict], i: int, sym: str) -> bool:
    for j, s in enumerate(steps):
        if j == i:
            continue
        if _mentions(str(s.get("statement") or "") + str(s.get("title") or ""), sym):
            return True
    return False


def _sub_outlier(steps: list[dict], subs: dict[str, int | None], i: int) -> int | None:
    """本步的小问号被两侧包夹成孤岛 → 疑似 point_id 挂错。返回邻居的小问号。"""
    if i == 0 or i + 1 >= len(steps):
        return None
    cur = subs.get(str(steps[i].get("step_id")))
    prev = subs.get(str(steps[i - 1].get("step_id")))
    nxt = subs.get(str(steps[i + 1].get("step_id")))
    if cur is None or prev is None or nxt is None:
        return None
    if prev == nxt and cur != prev:
        return prev
    return None


def _duplicate_point(steps: list[dict], step: dict) -> str | None:
    pid = step.get("point_id")
    if not pid:
        return None
    same = [str(s.get("step_id")) for s in steps
            if s.get("point_id") == pid and s.get("step_id") != step.get("step_id")]
    return same[0] if same else None


def _question_level(doc: dict, subs: dict[str, int | None]) -> list[dict]:
    """题级两条：小问覆盖（能判）、边界起点（判不了，报缺口）。"""
    out: list[dict] = []
    sqs = [s.get("no") for s in (doc.get("question") or {}).get("subquestions") or []]
    covered = {subs.get(k) for k in subs}
    for no in sqs:
        n = int(re.sub(r"\D", "", no) or 0)
        if n and n not in covered:
            out.append({"kind": "uncovered", "step_id": None, "symbol": no,
                        "detail": f"第{no}问没有任何步挂上去（小问未覆盖）"})
    out.append({
        "kind": "boundary_na", "step_id": None, "symbol": None,
        "detail": ("边界起点（位移从哪算起、区间端点）判不了：Schema 没有 "
                   "「过程分段 → 步」与「分段起点参照物」字段，"
                   "process_segments 只有中文 start/end 文本，规则无法对齐 → 记 na，不硬判"),
    })
    return out


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="L4 条件一致层（只读，不写回文件）")
    ap.add_argument("answer", help="answer JSON 路径")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--verbose", action="store_true", help="逐步打印，含 pass")
    a = ap.parse_args(argv)

    p = Path(a.answer)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"读不了 {p}：{exc}", file=sys.stderr)
        return 2

    res = analyze(doc)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    meta = doc.get("meta") or {}
    print(f"对象：{meta.get('answer_id') or p.name}（题 {meta.get('question_id')}，"
          f"{len(doc.get('steps') or [])} 步）｜小问归属来源：采分点总表")
    st = res["stats"]
    # 汇总行刻意不用 pass/fail 字样：卡 §6.1 的验收用 grep 'error|fail' 查误报，
    # 汇总行里出现 fail 0 会被自己判成误报。真判错时下面会单独打 FAIL 行。
    print(f"L4  通过 {st.get('pass', 0)} / 判错 {st.get('fail', 0)} / "
          f"无法判 {st.get('na', 0)}｜观察项 {len(res['findings'])}")

    for step in doc.get("steps") or []:
        sid = step.get("step_id")
        for c in res["steps"].get(sid, []):
            if c["status"] == "pass" and not a.verbose:
                continue
            tag = {"fail": "FAIL", "na": "NA", "pass": "PASS"}.get(c["status"], c["status"])
            code = f" {c['error_code']}" if c.get("error_code") else ""
            print(f"  [{tag}]{code} {sid} {step.get('title') or ''}")
            print(f"        {c['detail']}")

    if res["findings"]:
        print("观察项（不改判，供人工/上游处置）")
        for f in res["findings"]:
            where = f"{f['step_id']} " if f.get("step_id") else ""
            print(f"  - [{f['kind']}] {where}{f['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

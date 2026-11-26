# -*- coding: utf-8 -*-
"""test_alias.py — 别名层（T23）的独立自测。**不用 pytest，跑法同 run_tests.py**：

    cd "D:/峤的个人档案/做点东西/物理解题agent"
    python 验证器/tests/test_alias.py

覆盖三类：
  1. 词法归一（``normalize_lexical``）——纯函数，无状态
  2. 查表（``canonical``）——题内隔离、保留名、未登记不猜、不兜底
  3. 绑定表契约 + 改写（``apply_alias``）——不许链式改名、不许改入参、撞车要报

任一断言失败即退出码 1。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from 验证器 import alias as A          # noqa: E402
from 验证器 import runner as R         # noqa: E402
from 验证器 import units as U          # noqa: E402

QIDS = ["A-02", "A-08", "A-10", "B-02", "B-09", "B-12", "B-20"]
_OUT = ROOT / "评测" / "T20" / "out"


def _model(qid: str) -> dict:
    return json.loads((_OUT / f"{qid}_validated.json").read_text(encoding="utf-8"))


def _step(doc: dict, sid: str) -> dict:
    return next(s for s in doc["steps"] if s["step_id"] == sid)


# --------------------------------------------------------------------------- 1. 词法

def t01_lexical_underscore() -> list[str]:
    got = A.normalize_lexical("v_0")
    return [] if got == "v0" else [f"v_0 → {got!r}，应为 'v0'"]


def t02_lexical_subscript() -> list[str]:
    errs = []
    if A.normalize_lexical("v₀") != "v0":
        errs.append(f"v₀ → {A.normalize_lexical('v₀')!r}，应为 'v0'")
    if A.normalize_lexical("v₀") != A.normalize_lexical("v_0"):
        errs.append("v₀ 与 v_0 归一后不相等")
    if A.normalize_lexical("t₁") != "t1":
        errs.append(f"t₁ → {A.normalize_lexical('t₁')!r}，应为 't1'")
    return errs


def t03_lexical_mu() -> list[str]:
    got = A.normalize_lexical("μ")
    return [] if got == "mu" else [f"μ → {got!r}，应为 'mu'"]


def t04_lexical_case() -> list[str]:
    errs = []
    if A.normalize_lexical("M") != "M":
        errs.append("M 被改了大小写")
    if A.normalize_lexical("M") == A.normalize_lexical("m"):
        errs.append("M 与 m 被归一到一起（严禁：大小写不同、物理量不同）")
    if A.normalize_lexical("L") == A.normalize_lexical("l"):
        errs.append("L 与 l 被归一到一起（严禁：大小写差不是词法问题）")
    return errs


# --------------------------------------------------------------------------- 2. 查表

def t05_bind_a08() -> list[str]:
    got = A.canonical("m_a", "A-08")
    return [] if got == "m1" else [f"A-08 m_a → {got!r}，应为 'm1'"]


def t06_isolation() -> list[str]:
    errs = []
    for qid in ("B-09", "B-12", "A-10"):
        got = A.canonical("m_a", qid)
        if got is not None:
            errs.append(f"{qid} 的 m_a 命中了 {got!r}（绑定必须题内隔离）")
    return errs


def t07_reserved_a08() -> list[str]:
    errs = []
    for raw, want in (("N", "Nf"), ("Q", "Qheat"), ("I", "Iimp")):
        got = A.canonical(raw, "A-08")
        if got != want:
            errs.append(f"A-08 {raw} → {got!r}，应为 {want!r}")
    return errs


def t08_reserved_b20() -> list[str]:
    got = A.canonical("N", "B-20")
    return [] if got == "Nf" else [f"B-20 N → {got!r}，应为 'Nf'"]


def t09_unknown_none() -> list[str]:
    try:
        got = A.canonical("zeta_x", "A-08")
    except Exception as exc:  # noqa: BLE001
        return [f"未登记符号不该抛错：{type(exc).__name__}: {exc}"]
    return [] if got is None else [f"未登记符号 → {got!r}，应为 None"]


def t10_no_fallback() -> list[str]:
    errs = []
    for raw in ("w_x", "vv", "S_x"):
        got = A.canonical(raw, "A-02")
        if got is not None:
            errs.append(f"{raw} → {got!r}，不许兜底成任何已有符号")
    return errs


def t11_identity() -> list[str]:
    errs = []
    if A.canonical("mu", "A-08") != "mu":
        errs.append("已是白名单 id 的符号应原样返回")
    if A.canonical("vb", "B-12") != "vb":
        errs.append("B-12 的 vb 未被绑定，应恒等返回 vb（不许被 A-08 的行影响）")
    return errs


# --------------------------------------------------------------------------- 3. 绑定表契约

def t12_table_types() -> list[str]:
    b = A.load_bindings()
    bad = {f"{r['qid']}/{r['model_symbol']}": r["map_type"] for r in b.values()
           if r["map_type"] not in A.MAP_TYPES}
    return [f"非法 map_type：{bad}"] if bad else []


def t13_table_targets() -> list[str]:
    syms = U.load_symbols()
    b = A.load_bindings()
    bad = [f"{r['qid']}/{r['model_symbol']}→{r['symbol_id']}" for r in b.values()
           if r["symbol_id"] not in syms]
    return [f"目标不在白名单：{bad[:3]}（共 {len(bad)}）"] if bad else []


def t14_table_no_dup() -> list[str]:
    """同一 (qid, model_symbol) 只有一条；且同题同形（词法归一后）不许绑两个 id。"""
    import csv
    rows = list(csv.DictReader(open(A.BIND_CSV, encoding="utf-8-sig", newline="")))
    keys = [(r["qid"], r["model_symbol"]) for r in rows]
    errs = []
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        errs.append(f"重复绑定：{sorted(dup)[:3]}")
    groups: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        groups.setdefault((r["qid"], A.normalize_lexical(r["model_symbol"])), set()).add(r["symbol_id"])
    bad = {k: v for k, v in groups.items() if len(v) > 1}
    if bad:
        errs.append(f"同题同形绑到多个 id：{bad}")
    return errs


def t15_table_evidence() -> list[str]:
    """每行都要有 basis + evidence_step，且 evidence 里的 step_id 在该题里真实存在。"""
    b = A.load_bindings()
    errs = []
    for r in b.values():
        if not r["basis"].strip() or not r["evidence_step"].strip():
            errs.append(f"{r['qid']}/{r['model_symbol']} 缺 basis 或 evidence_step")
            continue
        m = re.match(r"([A-Z]-\d{2}-S\d{2})", r["evidence_step"])
        if not m:
            errs.append(f"{r['qid']}/{r['model_symbol']} evidence_step 不是 step_id：{r['evidence_step']!r}")
            continue
        try:
            doc = _model(r["qid"])
        except FileNotFoundError:
            errs.append(f"{r['qid']} 的模型产物不存在，无法核 evidence")
            continue
        if not any(s["step_id"] == m.group(1) for s in doc["steps"]):
            errs.append(f"{r['qid']}/{r['model_symbol']} 的 evidence {m.group(1)} 在产物里不存在")
    return errs


def t16_table_covers_surfaces() -> list[str]:
    """表要覆盖「进方程或有数值」的未登记符号。

    例外是**已知缺口**（白名单没有对应槽位，卡 §7-3 要求不猜、留 na）。
    这份清单与 `评测/别名层_效果对照_20261125.md` §3.2 一一对应：
    新冒出一个未覆盖符号 → 测试失败；清单里有符号已消失 → 也失败（防止陈旧）。
    """
    UNMAPPED = {
        # 末段相对路程 / 末段历时：白名单只有全过程 ds 与「第二段过程时间」，粒度不合
        "A-08": {"s_e", "se", "t_e"},
        # 同一物体在两个位置的速率：白名单每物体只有一个速度槽，绑任一处都会合流
        "A-10": {"v_R", "v_n"},
        # 速度的水平分量（带符号）：白名单无分量槽；绑到 v2 会抹平正负号（红线 4）
        "B-02": {"vBx"},
        # 轨道/物块在 P、Q 两点的速度（同上）+ 相对速度（白名单无槽）
        "B-20": {"V_P", "V_Q", "v_P", "u_rel"},
    }
    b = A.load_bindings()
    syms = U.load_symbols()
    tok = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
    errs = []
    for qid in QIDS:
        doc = _model(qid)
        used: set[str] = set()
        for s in doc["steps"]:
            eq = (s.get("equation") or {}).get("sympy") or ""
            used |= {t for t in tok.findall(eq) if t not in U.ALLOWED_CALLS}
            v = s.get("value") or {}
            if v.get("symbol"):
                used.add(v["symbol"])
        for g in (doc.get("situation") or {}).get("given") or []:
            if g.get("symbol") and g.get("value") is not None:
                used.add(g["symbol"])          # 带值的 given 必须能落地
        unregistered = {x for x in used if x not in syms}
        missing = sorted(x for x in unregistered if (qid, x) not in b)
        unexpected = [x for x in missing if x not in UNMAPPED.get(qid, set())]
        if unexpected:
            errs.append(f"{qid} 有未登记符号既不在白名单也不在绑定表：{unexpected}")
        stale = sorted(UNMAPPED.get(qid, set()) - unregistered)
        if stale:
            errs.append(f"{qid} 的已知缺口清单里 {stale} 已不在产物中，清单该更新")
    return errs


# --------------------------------------------------------------------------- 4. 改写

def t17_no_chain_rename() -> list[str]:
    """A-08 S02 的 value.symbol=vP 必须先变 v1；那个新的 v1 不许再被 v1→v2b 二次命中。"""
    doc, stats = A.apply_alias(_model("A-08"))
    errs = []
    got = _step(doc, "A-08-S02")["value"]["symbol"]
    if got != "v1":
        errs.append(f"S02 value.symbol → {got!r}，应为 'v1'（若为 v2b 即链式改名）")
    got2 = _step(doc, "A-08-S11")["value"]["symbol"]
    if got2 != "v2b":
        errs.append(f"S11 value.symbol → {got2!r}，应为 'v2b'")
    if stats["collisions"]:
        errs.append(f"出现撞车：{stats['collisions'][:2]}")
    return errs


def t18_apply_all_surfaces() -> list[str]:
    doc, _ = A.apply_alias(_model("A-08"))
    errs = []
    giv = {g["symbol"] for g in doc["situation"]["given"]}
    for want in ("m1", "m2", "dt", "Iimp"):
        if want not in giv:
            errs.append(f"given 里没有 {want}（说明 given 侧符号没被改写）：{sorted(giv)}")
    eq = _step(doc, "A-08-S03")["equation"]["sympy"]
    if "Nf" not in eq:
        errs.append(f"S03 方程未改写成 Nf：{eq}")
    if "m1" not in eq:
        errs.append(f"S03 方程未改写成 m1：{eq}")
    if "v1" not in eq:
        errs.append(f"S03 方程里的 v_P 未改写成 v1：{eq}")
    return errs


def t19_unresolved_kept() -> list[str]:
    doc, stats = A.apply_alias(_model("A-08"))
    errs = []
    eq = _step(doc, "A-08-S18")["equation"]["sympy"]
    if "s_e" not in eq:
        errs.append(f"未识别的 s_e 应原样保留：{eq}")
    un = A.unresolved_by_step(stats)
    if "s_e" not in un.get("A-08-S18", []):
        errs.append(f"未识别符号没进报告：{un.get('A-08-S18')}")
    if "t_e" not in un.get("A-08-S16", []):
        errs.append(f"S16 的 t_e 没进报告：{un.get('A-08-S16')}")
    return errs


def t20_no_mutation() -> list[str]:
    src = _model("A-08")
    before = json.dumps(src, ensure_ascii=False, sort_keys=True)
    A.apply_alias(src)
    after = json.dumps(src, ensure_ascii=False, sort_keys=True)
    return [] if before == after else ["apply_alias 改了入参（必须传副本）"]


def t21_collision_reported() -> list[str]:
    """B-12 只登记了 l→L。若同一式子里本来就有 L，必须报撞车而不是静默合并。"""
    doc = _model("B-12")
    _step(doc, "B-12-S05")["equation"]["sympy"] = "m*g*l + f*l - L*m*g"
    _out, stats = A.apply_alias(doc)
    hits = [c for c in stats["collisions"] if c["target"] == "L"]
    return [] if hits else ["l→L 与式内已有的 L 相撞，但没报撞车"]


def t22_switch_off_is_noop() -> list[str]:
    """关别名：符号一个都不许变，报告里也不许多出 alias 字段。"""
    src = _model("A-08")
    out, rep = R.run_answer(src)
    errs = []
    for s0, s1 in zip(src["steps"], out["steps"]):
        if (s0.get("equation") or {}).get("sympy") != (s1.get("equation") or {}).get("sympy"):
            errs.append(f"{s0['step_id']} 方程被改了（关别名不该动）")
        if (s0.get("value") or {}).get("symbol") != (s1.get("value") or {}).get("symbol"):
            errs.append(f"{s0['step_id']} 值符号被改了（关别名不该动）")
    if "alias" in rep:
        errs.append("关别名时报告里不该出现 alias 字段")
    return errs


def t23_a08_bar() -> list[str]:
    """卡 §8.3：A-08 开别名后至少 12 步拿到 L1 结论（pass 或 fail）。"""
    _out, rep = R.run_answer(_model("A-08"), alias=True)
    d = rep["checks"]["L1"]
    got = d["pass"] + d["fail"]
    return [] if got >= 12 else [f"A-08 L1 结论只有 {got} 步（<12）"]


# --------------------------------------------------------------------------- 跑

TESTS = [
    ("t01 词法：去下划线", t01_lexical_underscore),
    ("t02 词法：Unicode 下标", t02_lexical_subscript),
    ("t03 词法：μ→mu", t03_lexical_mu),
    ("t04 词法：大小写不动（M≠m、L≠l）", t04_lexical_case),
    ("t05 绑定：A-08 m_a→m1", t05_bind_a08),
    ("t06 题内隔离：m_a 在别题不命中", t06_isolation),
    ("t07 保留名：N/Q/I→Nf/Qheat/Iimp", t07_reserved_a08),
    ("t08 保留名：B-20 N→Nf", t08_reserved_b20),
    ("t09 未登记→None，不抛错", t09_unknown_none),
    ("t10 未登记不兜底成 v", t10_no_fallback),
    ("t11 恒等：已在白名单的原样返回", t11_identity),
    ("t12 表契约：map_type 三值", t12_table_types),
    ("t13 表契约：目标都在白名单", t13_table_targets),
    ("t14 表契约：无重复、同形同去", t14_table_no_dup),
    ("t15 表契约：basis/evidence 齐全且 step 存在", t15_table_evidence),
    ("t16 表契约：覆盖所有进方程/带值的未登记符号", t16_table_covers_surfaces),
    ("t17 改写：不做链式改名", t17_no_chain_rename),
    ("t18 改写：given/value/equation 三面同改", t18_apply_all_surfaces),
    ("t19 改写：未识别符号原样保留并上报", t19_unresolved_kept),
    ("t20 改写：不改入参", t20_no_mutation),
    ("t21 改写：撞车要报（l 与 L 并存）", t21_collision_reported),
    ("t22 开关：关别名逐字不动", t22_switch_off_is_noop),
    ("t23 验收：A-08 L1 结论≥12 步", t23_a08_bar),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

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

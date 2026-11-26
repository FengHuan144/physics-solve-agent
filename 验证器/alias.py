# -*- coding: utf-8 -*-
"""alias.py — 符号别名层（T23）。

**只做一件事**：把模型给量起的名字，翻译成符号白名单里的 ``symbol_id``。
不动数值、不动单位、不动正负号、不改方程结构。

三条硬约束（T23 卡 §5 / §7）：

1. **查表，不猜。** 表里没有 → 返回 ``None``，该步保持 ``na``。
2. **题内隔离。** 绑定按 ``(qid, model_symbol)`` 存储，A-08 的 ``m_a``
   不会让 B-09 的 ``m_a`` 命中。
3. **不许链式改名。** 一次替换、同时生效：``vP → v1`` 之后，那个新的
   ``v1`` 不会再被 ``v1 → v2b`` 二次命中。做法是一次正则替换 + 原 token 查表，
   而不是逐条 ``str.replace``。

为什么不是「先做词法归一、再查表」：本题组实测有两处会因此改错含义——
``v_b``（b 碰后速度）词法归一是 ``vb``，而白名单的 ``vb`` 是**传送带速度**；
``v_1``（冲量后 b 的速度）归一成 ``v1``，而白名单的 ``v1`` 是**物体1的速度**。
所以运行时的第一跳必须是**逐字查表**，``normalize_lexical()`` 只用于
一致性校验（同一题里归一后相同的形式不许绑到两个 id），不参与改写。
"""

from __future__ import annotations

import copy
import csv
import re
from functools import lru_cache
from pathlib import Path

try:  # 以包方式运行
    from . import units as U
except ImportError:  # 以脚本方式运行
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 验证器 import units as U

BIND_CSV = U.PROJECT_ROOT / "知识表" / "别名绑定_v1.csv"

#: 只许这三种，不许自创第四种（T23 卡 §5）
MAP_TYPES = ("lexical", "bind", "reserved")
#: 一个符号只能命中一条；冲突时优先级高者胜，且必须报出来（卡 §5）
PRIORITY = {"reserved": 3, "bind": 2, "lexical": 1}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

#: Unicode 下标 → ASCII（``v₀`` → ``v0``）
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")
#: 希腊字母 → 拼音名。当前 7 题数据里没有（units.py 的字符集先拦掉了），
#: 这里只为将来模型直接写 ``μ`` 时能归一。
_GREEK = (("μ", "mu"), ("ρ", "rho"), ("ω", "omega"), ("θ", "theta"))


# --------------------------------------------------------------------------- 词法归一

def normalize_lexical(s) -> str:
    """纯写法归一：去下划线、Unicode 下标转 ASCII、希腊字母转名。**大小写不动。**

    只做这一件事，不改含义、不查表、不知道白名单。无状态，可单测。

    >>> normalize_lexical("v_0") == normalize_lexical("v₀") == "v0"
    True
    >>> normalize_lexical("M") == "M"          # 不许把 M 与 m 归一
    True
    """
    if s is None:
        return ""
    t = str(s).strip()
    if not t:
        return ""
    t = t.translate(_SUBSCRIPT)
    for greek, name in _GREEK:
        t = t.replace(greek, name)
    return t.replace("_", "")


# --------------------------------------------------------------------------- 绑定表

@lru_cache(maxsize=1)
def load_bindings(path: str | None = None) -> dict[tuple[str, str], dict]:
    """读 ``知识表/别名绑定_v1.csv``，返回 ``{(qid, model_symbol): 行}``。

    加载即校验，坏表直接抛错（不带着病表跑）：

    - ``map_type`` 只能是三种之一
    - 目标 ``symbol_id`` 必须在白名单里
    - ``(qid, model_symbol)`` 不许重复
    - ``basis`` 与 ``evidence_step`` 不许为空（卡 §8.5：空一行即退回）
    - 同一题里，词法归一后相同的形式**不许绑到两个不同 id**
      （``m_a`` 与 ``ma`` 归一后都是 ``ma``，必须同去一处）
    """
    p = Path(path) if path else BIND_CSV
    if not p.exists():
        raise FileNotFoundError(f"别名绑定表不存在：{p}")

    syms = U.load_symbols()
    out: dict[tuple[str, str], dict] = {}
    groups: dict[tuple[str, str], set[str]] = {}

    with open(p, encoding="utf-8-sig", newline="") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            get = lambda k: (row.get(k) or "").strip()  # noqa: E731
            qid, raw, sid, mtype = get("qid"), get("model_symbol"), get("symbol_id"), get("map_type")
            if not any((qid, raw, sid, mtype)):
                continue  # 空行
            where = f"{p.name}:{lineno}"
            if not qid or not raw or not sid:
                raise ValueError(f"{where} qid / model_symbol / symbol_id 不许为空")
            if mtype not in MAP_TYPES:
                raise ValueError(f"{where} map_type={mtype!r} 不在 {MAP_TYPES}")
            if sid not in syms:
                raise ValueError(f"{where} 目标 {sid!r} 不在符号白名单")
            if not get("basis") or not get("evidence_step"):
                raise ValueError(f"{where} {qid}/{raw} 缺 basis 或 evidence_step（卡 §8.5）")

            key = (qid, raw)
            if key in out:
                raise ValueError(f"{where} 重复绑定：{qid}/{raw}")
            out[key] = {
                "qid": qid, "model_symbol": raw, "symbol_id": sid, "map_type": mtype,
                "basis": get("basis"), "evidence_step": get("evidence_step"), "risk": get("risk"),
            }
            groups.setdefault((qid, normalize_lexical(raw)), set()).add(sid)

    bad = {k: v for k, v in groups.items() if len(v) > 1}
    if bad:
        raise ValueError(f"同题同形绑到多个 id（会自相矛盾）：{bad}")
    if not out:
        raise ValueError(f"别名绑定表为空：{p}")
    return out


def rows_for(qid: str, bindings: dict | None = None) -> list[dict]:
    """某题用了哪些绑定行（供报告统计）。"""
    b = bindings if bindings is not None else load_bindings()
    return [v for (q, _s), v in sorted(b.items()) if q == qid]


# --------------------------------------------------------------------------- 查询

def canonical(symbol, qid: str | None = None, bindings: dict | None = None) -> str | None:
    """``model_symbol → symbol_id``。未命中返回 ``None``——**不猜、不兜底**。

    三级：① ``(qid, symbol)`` 精确命中；② 全局行 ``("*", symbol)``；
    ③ 本身已是白名单 id → 原样返回（恒等，不是映射）。都没有 → ``None``。
    """
    if symbol is None:
        return None
    s = str(symbol).strip()
    if not s:
        return None
    b = bindings if bindings is not None else load_bindings()
    if qid:
        row = b.get((qid, s))
        if row:
            return row["symbol_id"]
    row = b.get(("*", s))
    if row:
        return row["symbol_id"]
    return s if s in U.load_symbols() else None


def explain(symbol, qid: str | None = None, bindings: dict | None = None) -> dict | None:
    """给报告用：这个符号为什么映射到那个 id。未命中返回 ``None``。"""
    b = bindings if bindings is not None else load_bindings()
    s = str(symbol or "").strip()
    return b.get((qid, s)) or b.get(("*", s))


# --------------------------------------------------------------------------- 改写

def _map_name(name: str, qid: str, where: str, sid: str, b: dict, stats: dict) -> str:
    tgt = canonical(name, qid, b)
    if tgt is None:
        stats["unresolved"].append({"where": where, "step_id": sid, "symbol": name})
        return name
    if tgt != name:
        row = explain(name, qid, b) or {}
        stats["rewrites"].append({
            "where": where, "step_id": sid, "from": name, "to": tgt,
            "map_type": row.get("map_type"),
        })
        stats["by_type"][row.get("map_type") or "identity"] = \
            stats["by_type"].get(row.get("map_type") or "identity", 0) + 1
    return tgt


def _rewrite_expr(expr: str, qid: str, sid: str, b: dict, stats: dict) -> str:
    """方程串按 token 一次性替换。函数名（sqrt/Rational/…）不动。"""
    toks = set(TOKEN_RE.findall(expr))
    mapping: dict[str, str] = {}
    for t in toks:
        if t in U.ALLOWED_CALLS:      # sqrt / Rational / sin / pi …
            continue
        mapping[t] = _map_name(t, qid, "equation.sympy", sid, b, stats)

    # 撞车检测：两个不同原符号落到同一目标，或目标本来就在式子里
    seen: dict[str, str] = {}
    for src, dst in mapping.items():
        if dst in seen and seen[dst] != src:
            stats["collisions"].append({
                "step_id": sid, "target": dst, "sources": sorted([seen[dst], src]),
                "why": "两个原符号映射到同一 symbol_id，会把两个量合并",
            })
        seen[dst] = src
        if dst != src and dst in toks:
            stats["collisions"].append({
                "step_id": sid, "target": dst, "sources": sorted([src, dst]),
                "why": "映射目标在同一个式子里已作为另一个符号出现",
            })

    return TOKEN_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), expr)


def apply_alias(answer: dict, qid: str | None = None,
                bindings: dict | None = None) -> tuple[dict, dict]:
    """把一份 answer 里的符号名翻译成白名单 id。返回 ``(新 doc, 统计)``，不改入参。

    改三处（验证器实际读的三处）：``situation.given[].symbol``、
    ``steps[].value.symbol``、``steps[].equation.sympy``。

    **不改** ``equation.symbols[]``：它是 ``draft_to_schema.py`` 按 ``_`` 切碎的产物
    （``m_a`` 被拆成 ``["a","m"]``），本卡只报不修（卡 §2）。验证器不读它。
    """
    b = bindings if bindings is not None else load_bindings()
    q = qid or ((answer.get("meta") or {}).get("question_id") or "")
    doc = copy.deepcopy(answer)
    stats = {"qid": q, "rewrites": [], "unresolved": [], "collisions": [], "by_type": {}}

    for g in ((doc.get("situation") or {}).get("given") or []):
        if g.get("symbol"):
            g["symbol"] = _map_name(g["symbol"], q, "situation.given", "-", b, stats)

    for step in doc.get("steps") or []:
        sid = str(step.get("step_id") or "?")
        val = step.get("value")
        if isinstance(val, dict) and val.get("symbol"):
            val["symbol"] = _map_name(val["symbol"], q, "value.symbol", sid, b, stats)
        eq = step.get("equation")
        if isinstance(eq, dict) and isinstance(eq.get("sympy"), str) and eq["sympy"].strip():
            eq["sympy"] = _rewrite_expr(eq["sympy"], q, sid, b, stats)

    stats["rewrites"] = _dedupe(stats["rewrites"])
    stats["unresolved"] = _dedupe(stats["unresolved"])
    stats["collisions"] = _dedupe(stats["collisions"])
    # by_type 按去重后的条数重算（同一步里方程与值各出现一次只算一条）
    stats["by_type"] = {}
    for r in stats["rewrites"]:
        k = r.get("map_type") or "identity"
        stats["by_type"][k] = stats["by_type"].get(k, 0) + 1
    return doc, stats


def _dedupe(items: list[dict]) -> list[dict]:
    """同一 (where, step_id, from) 只记一次——值符号与方程 token 常同时出现。"""
    seen, out = set(), []
    for it in items:
        key = (it.get("where"), it.get("step_id"), it.get("from") or it.get("symbol")
               or it.get("target"), it.get("to"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def unresolved_by_step(stats: dict) -> dict[str, list[str]]:
    """``{step_id: [未识别符号]}``，供报告列清单。"""
    out: dict[str, list[str]] = {}
    for u in stats.get("unresolved") or []:
        sid = u.get("step_id") or "-"
        out.setdefault(sid, [])
        if u["symbol"] not in out[sid]:
            out[sid].append(u["symbol"])
    return {k: sorted(v) for k, v in out.items()}

# -*- coding: utf-8 -*-
"""align.py — S2 运行时归属：把模型的步映射到采分点（不读人工对齐表）。

来源：``临时/proto_s2b.py`` 的打分 + ``临时/proto_s2d.py`` 的单调 DP +
``临时/proto_s2h.py`` 的空点补齐（S2 报告 52/64 的那一版）。参数原样搬过来，
**没有在运行时数据上重新调参**。

用途边界（T25 卡 D2）：
- 金标步只用于**定位/对照**（这点在说什么），不作 hit 的充分条件；
- 本模块只产出 ``by``（哪个模型步承载哪个点），不产出 credit。

运行时不读 ``评测/对齐/T20步点对齐_v2.json``；那份表只给 ``diff_align.py`` 验收用。
"""

from __future__ import annotations

import math
import re
from collections import Counter

# proto_s2d 网格最优（52/64 那一版），原样固定，不在运行时调
W = {"text": 0.674, "eq": 0.163, "val": 0.054, "kind": 0.109}
THETA = 0.12
SKIP_COST = 0.0      # proto_s2h 的 SKIP（52/64 那一版就是 0.0，不是 proto_s2d 的 -0.02）

# ``map_steps(fill=True)`` 兜底填步的下限（T36）。DP 之后仍为空的点，原来无条件
# 取相似度最高的模型步——相似度 0.03 也照填，于是「没配上的点」被硬塞一个不相干的步，
# 下一步 credit 再拿这个步去判 hit，就出现假 hit（A-09-S02/S03）。
# 0.0 = 原行为（52/64 那一版），不改变默认产物；>0 时才要求兜底步真的沾点边。
FILL_MIN = 0.0


def clean(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"[，。；：、（）()【】\[\]“”\"'.,;:!?？!·—\-+*/=<>≤≥≈⇒→]", "", s)
    return s


def grams(s: str, n: int = 2) -> Counter:
    c = Counter()
    for i in range(len(s) - n + 1):
        c[s[i:i + n]] += 1
    return c


def cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b[k] for k, v in a.items() if k in b)
    return dot / math.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))


def txt(s: dict) -> str:
    return clean((s.get("statement") or "") + " " + (s.get("title") or "") + " "
                 + ((s.get("criterion") or {}).get("text") or ""))


_EQ_CACHE: dict[tuple[str, str], float] = {}


def eqsim(e1: str | None, e2: str | None) -> float:
    """1.0 = 化简后同式；0.9 = 只差一个常数因子；0 = 不可比。"""
    if not e1 or not e2:
        return 0.0
    key = (e1, e2) if e1 <= e2 else (e2, e1)
    if key in _EQ_CACHE:
        return _EQ_CACHE[key]
    val = 0.0
    try:
        import sympy as sp
        a, b = sp.sympify(e1), sp.sympify(e2)
        if sp.simplify(a - b) == 0:
            val = 1.0
        else:
            q = sp.simplify(a / b)
            if not q.free_symbols:
                val = 0.9
    except Exception:  # noqa: BLE001
        val = 0.0
    _EQ_CACHE[key] = val
    return val


def valsim(v1: dict | None, v2: dict | None) -> float:
    if not v1 or not v2:
        return 0.0
    n1, n2 = v1.get("number"), v2.get("number")
    if n1 is None or n2 is None:
        return 0.0
    try:
        f1, f2 = float(n1), float(n2)
    except Exception:  # noqa: BLE001
        return 0.0
    u1, u2 = (v1.get("unit") or "").strip(), (v2.get("unit") or "").strip()
    if abs(f1 - f2) <= 1e-9 * max(1, abs(f1)):
        return 1.0 if u1 == u2 else 0.7
    return 0.0


def kindsim(k1: str | None, k2: str | None) -> float:
    if not k1 or not k2:
        return 0.0
    if k1 == k2:
        return 1.0
    if k1 in ("equation", "value") and k2 in ("equation", "value"):
        return 0.5
    return 0.0


def score_matrix(points: list[dict], gold_steps: list[dict],
                 model_steps: list[dict]) -> list[list[float]]:
    """行 = 采分点（按总表序），列 = 模型步（按答案序）。"""
    gmap = {s["point_id"]: s for s in gold_steps if s.get("point_id")}
    sim: list[list[float]] = []
    for p in points:
        gs = gmap.get(p["point_id"]) or {}
        gt = grams(txt(gs))
        row = []
        for s in model_steps:
            f = {
                "text": cos(gt, grams(txt(s))),
                "eq": eqsim((gs.get("equation") or {}).get("sympy"),
                            (s.get("equation") or {}).get("sympy")),
                "val": valsim(gs.get("value") or {}, s.get("value") or {}),
                "kind": kindsim(gs.get("kind"), s.get("kind")),
            }
            row.append(sum(W[k] * f[k] for k in W))
        sim.append(row)
    return sim


def dp_align(sim: list[list[float]], theta: float = THETA,
             skip_cost: float = SKIP_COST) -> list[list[int]]:
    """单调、不重叠地把模型步分段给采分点；返回每点吃到的列下标。"""
    n, m = len(sim), len(sim[0]) if sim else 0
    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    bk = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == NEG:
                continue
            if j < m and cur + skip_cost > dp[i][j + 1]:
                dp[i][j + 1] = cur + skip_cost
                bk[i][j + 1] = ("skip", i, j)
            if i < n:
                if cur > dp[i + 1][j]:
                    dp[i + 1][j] = cur
                    bk[i + 1][j] = ("none", i, j)
                gain = 0.0
                for k in range(1, m - j + 1):
                    gain += sim[i][j + k - 1] - theta
                    if cur + gain > dp[i + 1][j + k]:
                        dp[i + 1][j + k] = cur + gain
                        bk[i + 1][j + k] = ("take", i, j, k)
    out: list[list[int]] = [[] for _ in range(n)]
    i, j = n, m
    while i > 0 or j > 0:
        b = bk[i][j]
        if b is None:
            break
        if b[0] in ("skip", "none"):
            i, j = b[1], b[2]
        else:
            out[b[1]] = list(range(b[2], b[2] + b[3]))
            i, j = b[1], b[2]
    return out


def map_steps(points: list[dict], gold_steps: list[dict],
              model_steps: list[dict], fill: bool = True,
              fill_min: float | None = None) -> dict[str, list[str]]:
    """返回 ``{point_id: [step_id, ...]}``。

    ``fill=True`` 时，DP 后仍为空的点取相似度最高的模型步，但要求该相似度
    ``>= fill_min``（默认读模块级 ``FILL_MIN``，0.0 即原行为）。
    """
    if fill_min is None:
        fill_min = FILL_MIN
    sim = score_matrix(points, gold_steps, model_steps)
    seg = dp_align(sim)
    mids = [str(s.get("step_id")) for s in model_steps]
    out: dict[str, list[str]] = {}
    for i, p in enumerate(points):
        idx = seg[i]
        if fill and not idx and mids:
            t = max(range(len(mids)), key=lambda k: sim[i][k])
            if sim[i][t] >= fill_min:
                idx = [t]
        out[str(p["point_id"])] = [mids[t] for t in idx]
    return out

# -*- coding: utf-8 -*-
"""_build_model.py — 把「模型解出来的 20 题」注入 模型解析_20题.html。

与 `_build.py` 的区别只有一个：数据源。
    _build.py        schema/examples/*.json      → 7 道金标（人工解）
    _build_model.py  评测/T20/out/*_validated.json → 20 道模型解（deepseek-flash）

模型产物的 `grading` 是空壳（point_hits: []，score_awarded: 0），这里用
`判分器/out/{qid}.json` 的三态结果填进去，页面才能显示每步分值与总分。

映射规则（写死，不猜）：
- 每个采分点挂到它的**主承载步** ``by[0]``；`by` 为空则不挂（点仍计入总分）。
- 同一步被多个采分点共用时合并成一条，`score_possible` 累加，`hit` 取「全中」。
- ``hit`` = 判分器 ``credit == "hit"``；`na` / `miss` 都记 false，并在 note 里写原因。

    python 原型/_build_model.py
"""
import datetime
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ANS_DIR = ROOT / "评测" / "T20" / "out"
GRADE_DIR = ROOT / "判分器" / "out"
TARGET = HERE / "模型解析_20题.html"

#: 展示层按「模型自己写的符号」渲染，不用校验后的白名单 id。
#: 个别步模型正文和公式自己就不一致（例：A-02-S10 正文 x_max、公式 x），
#: 只在这个表里点名改正，不做全局猜测。
DISPLAY_FIX = {
    ("A-02", "A-02-S10"): {"x": "x_max"},
    ("A-03", "A-03-S08"): {"d": "dmax"},
    ("A-08", "A-08-S10"): {"ttotal": "t", "t_total": "t"},
    ("A-08", "A-08-S12"): {"v_1": "v1"},
    ("A-08", "A-08-S13"): {"v_1": "v1"},
    ("A-08", "A-08-S14"): {"v_1": "v1"},
    ("A-08", "A-08-S16"): {"v_1": "v1"},
    ("A-08", "A-08-S18"): {"v_1": "v1"},
    ("A-09", "A-09-S06"): {"T": "Tmax"},
}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FUNC_NAMES = {"Rational", "sqrt", "sin", "cos", "tan", "pi", "log", "exp",
              "Piecewise", "Eq"}

sys.path.insert(0, str(HERE))
from _build import load_errors, load_laws, load_images   # noqa: E402

QIDS = ("A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-08", "A-09", "A-10",
        "B-01", "B-02", "B-04", "B-05", "B-07", "B-09", "B-10", "B-12", "B-16",
        "B-19", "B-20")

DATA_RE = re.compile(r'(<script id="DATA" type="application/json">)[\s\S]*?(</script>)')


def _skel(expr: str) -> str:
    """把表达式里的变量名抹掉，只留结构；用来确认原始产物与校验产物是同一条式子。"""
    return TOKEN_RE.sub(lambda m: m.group(0) if m.group(0) in FUNC_NAMES else "§", expr or "")


def _tokens(expr: str) -> list:
    return [t for t in TOKEN_RE.findall(expr or "") if t not in FUNC_NAMES]


def _rename(expr: str, pairs: dict) -> str:
    """按整词替换符号；一次替换，不链式。"""
    if not expr or not pairs:
        return expr
    keys = sorted(pairs, key=len, reverse=True)
    pat = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(k) for k in keys) +
                     r")(?![A-Za-z0-9_])")
    return pat.sub(lambda m: pairs[m.group(0)], expr)


def build_display(qid: str, doc: dict, raw_path=None) -> dict:
    """生成展示层用的符号数据（不改判定、不改分数）。

    为什么另起一份：``*_validated.json`` 里的符号是白名单 id（``Nf``/``Gc``/
    ``Iimp``/``v1p``），给人看会变成题面里根本没有的符号。原始产物 ``{qid}.json``
    里是模型自己写的 ``N``/``G``/``I``/``v_after``，与正文一致。

    返回：
    - ``steps[sid]``：该步展示用的式子与结果符号（原始产物，结构须与校验产物一致）
    - ``givens[i]``：第 i 条已知量的展示符号
    - ``maps[sid]``：``白名单 id → 原始符号``，只给采分点依据的悬停文字用
    """
    raw = None
    if raw_path is not None:
        p = pathlib.Path(raw_path)
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raw = None

    steps: dict[str, dict] = {}
    maps: dict[str, dict] = {}
    if raw:
        rs = raw.get("steps") or []
        vs = doc.get("steps") or []
        rby = {s.get("step_id"): s for s in rs}
        if any(v.get("step_id") in rby for v in vs):
            for v in vs:
                r = rby.get(v.get("step_id"))
                if not r:
                    continue
                sid = v["step_id"]
                fixes = DISPLAY_FIX.get((qid, sid), {})
                veq = (v.get("equation") or {}).get("sympy") or ""
                req = (r.get("equation") or {}).get("sympy") or ""
                item = {}
                if req and _skel(req) == _skel(veq):
                    item["eq"] = _rename(req, fixes)
                rv = r.get("value") or {}
                if rv.get("symbol"):
                    item["vsym"] = _rename(str(rv["symbol"]), fixes)
                if rv.get("exact"):
                    item["vexact"] = _rename(str(rv["exact"]), fixes)
                if item:
                    steps[sid] = item
                ta, tb = _tokens(req), _tokens(veq)
                if req and len(ta) == len(tb):
                    m = {}
                    for shown, canon in zip(tb, ta):
                        if shown != canon:
                            m.setdefault(shown, canon)
                    if m:
                        maps[sid] = m

    givens: list = []
    if raw:
        rg = ((raw.get("situation") or {}).get("given") or [])
        vg = ((doc.get("situation") or {}).get("given") or [])
        if len(rg) == len(vg):
            givens = [str(g.get("symbol") or "") for g in rg]
    return {"steps": steps, "givens": givens, "maps": maps}


def human_reason(basis: str, credit: str) -> str:
    """把判分器的机器话翻成学生能读的一句。"""
    if credit == "hit":
        return "已判为命中"
    b = basis or ""
    if "无锚点" in b:
        return "这一步的写法对不上给分要求，判不了"
    if "欠定" in b:
        return "单独看这步条件不够，要等后面的式子联立才能判"
    if "unknown_symbol" in b or "不在白名单" in b:
        return "式子里有不认识的符号，判不了"
    if "slot_collision" in b or "槽位" in b:
        return "同一个符号在题内被赋了两个不同的值，判不了"
    if "field_mismatch" in b:
        return "模型产物字段不合规，判不了"
    if "empty" in b:
        return "这步是判断/说明，没有式子可验，不参与量纲判定"
    if "量纲不可判定" in b:
        return "量纲对不上，但可能单位已并进系数，判分器无权判错"
    if credit == "miss":
        return "判为未命中"
    return "判不了"


def build_grading(qid: str, grade: dict, steps: list[dict]) -> dict:
    """把判分器的点级三态压成页面要的结构。

    返回三类信息：
    - ``point_hits``：按**承载步**聚合，供右侧步骤区显示「这一步值几分」
    - ``points``    ：点级明细（含人话原因），供左侧采分点表逐条列出
    - ``unattached``：没有承载步的点。以前整条丢弃 → 页面分母少 2 分加不出来，
                      现在单列出来由页脚说明，保证「分母 = 各点满分之和」恒成立。
    """
    buckets: dict[str, dict] = {}
    detail: list[dict] = []
    unattached = {"count": 0, "score_possible": 0.0, "points": []}

    for p in grade.get("points") or []:
        by = p.get("by") or []
        credit = str(p.get("credit") or "na")
        basis = str(p.get("basis") or "")
        poss = float((p.get("score_range") or [0, 0])[1])
        award = float(p.get("score") or 0)

        detail.append({
            "point_id": p["point_id"],
            "credit": credit,
            "score": award,
            "possible": poss,
            "by": [str(x) for x in by],
            "human": human_reason(basis, credit),
            "basis": basis[:200],
        })

        if not by:
            unattached["count"] += 1
            unattached["score_possible"] += poss
            unattached["points"].append(p["point_id"])
            continue

        sid = str(by[0])
        hit = credit == "hit"
        cur = buckets.get(sid)
        if not cur:
            buckets[sid] = {
                "point_id": p["point_id"],
                "step_id": sid,
                "score_awarded": award,
                "score_possible": poss,
                "hit": hit,
                "n": 1,
                "n_hit": 1 if credit == "hit" else 0,
                "n_na": 1 if credit == "na" else 0,
                "n_miss": 1 if credit == "miss" else 0,
                "note": basis[:180],
                "points": [p["point_id"]],
            }
        else:
            cur["score_possible"] += poss
            cur["score_awarded"] += award
            cur["hit"] = cur["hit"] and hit
            cur["n"] += 1
            cur["n_hit"] += 1 if credit == "hit" else 0
            cur["n_na"] += 1 if credit == "na" else 0
            cur["n_miss"] += 1 if credit == "miss" else 0
            cur["points"].append(p["point_id"])
            cur["note"] = (cur["note"] + "｜" + basis)[:180]

    for v in buckets.values():
        if len(v["points"]) > 1:
            v["point_id"] = "、".join(v["points"])

    s = grade.get("summary") or {}
    return {
        "point_hits": list(buckets.values()),
        "points": detail,
        "unattached": unattached,
        "score_awarded": float(s.get("score") or 0),
        "score_total": float(s.get("score_total") or 0),
        "grader": str(grade.get("grader_version") or ""),
        "summary": {k: s.get(k) for k in ("total", "hit", "miss", "na", "judged_rate")},
    }


def main() -> None:
    answers = {}
    stats = []
    for qid in QIDS:
        ap = ANS_DIR / f"{qid}_validated.json"
        gp = GRADE_DIR / f"{qid}.json"
        if not ap.exists():
            sys.exit(f"缺答案 {ap}")
        d = json.loads(ap.read_text(encoding="utf-8"))
        if gp.exists():
            g = json.loads(gp.read_text(encoding="utf-8"))
            d["grading"] = build_grading(qid, g, d.get("steps") or [])
        else:
            sys.exit(f"缺判分产物 {gp}")
        d["symbols"] = build_display(qid, d, ANS_DIR / f"{qid}.json")
        answers[qid] = d
        s = (d.get("grading") or {}).get("summary") or {}
        stats.append((qid, s.get("hit"), s.get("na"), s.get("total")))

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": "model",
        "answers": answers,
        "error_codes": load_errors(),
        "laws": load_laws(),
        "images": load_images(set(answers)),
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = TARGET.read_text(encoding="utf-8")
    new, n = DATA_RE.subn(lambda m: m.group(1) + blob + m.group(2), html, count=1)
    if n != 1:
        sys.exit("模板里没找到 DATA 占位块。")
    TARGET.write_text(new, encoding="utf-8")

    H = sum(x[1] or 0 for x in stats)
    N = sum(x[2] or 0 for x in stats)
    T = sum(x[3] or 0 for x in stats)
    print(f"[ok] {TARGET.name}  {TARGET.stat().st_size / 1024:.0f} KB")
    print(f"     题目 {len(answers)} 道 · 步骤 {sum(len(a.get('steps') or []) for a in answers.values())} 步")
    print(f"     hit {H} / na {N} / 点 {T}（20 题合计）")
    print(f"     数据源：{ANS_DIR.name}/*_validated.json + {GRADE_DIR.name}/*.json")


if __name__ == "__main__":
    main()

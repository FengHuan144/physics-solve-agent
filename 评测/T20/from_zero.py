#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""from_zero.py — 题库外新题的「草稿 → Schema」转换。

与 draft_to_schema.build() 的唯一区别：**不需要金标**。

build() 有四处 deepcopy(gold[...])：question / meta.full_score /
situation.objects / situation.targets。那是「只支持 20 题」的根因。
本模块把这三块改为由「题干文本 + 模型本轮输出」提供：

    question.stem_text      ← 题干原文（用户粘贴）
    question.subquestions   ← 题干里的小问文本 + 分值（分值优先取模型 sub_scores，
                              缺失时从题干「（N 分）」抓；都对不上则记 issue 留 null）
    situation.objects       ← 模型输出的 objects
    situation.targets       ← 空（L4 少一项对照，不崩；见 l4_condition.py:248）
    meta.full_score         ← 小问分值之和

步骤字段（kind/eq/value/criterion/outline）完全沿用 build() 的规则与
draft_to_schema 里的归一函数，保证同一份草稿在两条路径下产出的 step 结构一致。

用法（库）：
    from from_zero import build_from_zero
    doc, issues = build_from_zero("Z-001", draft, stem, figures=[...])
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(HERE))
import draft_to_schema as D                              # noqa: E402

TZ = timezone(timedelta(hours=8))
SUB_PAT = re.compile(r"[（(]\s*(\d{1,2}|[ivxIVXⅠⅡⅢⅣⅤ]+)\s*[）)]")
SCORE_PAT = re.compile(r"[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[）)]")


def _norm_no(raw: str) -> str:
    """小问编号统一成半角括号：(1)、（ⅰ）→(ⅰ)。"""
    s = str(raw or "").strip().replace("（", "(").replace("）", ")")
    if not s.startswith("("):
        s = "(" + s.strip("()") + ")"
    return s


def split_subquestions(stem: str) -> list[dict]:
    """按「(1) …（4 分）」把小问切开。切不出就返回空列表，由调用方兜底。"""
    s = stem or ""
    hits = list(SUB_PAT.finditer(s))
    if not hits:
        return []
    out = []
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(s)
        body = s[start:end].strip()
        sc = SCORE_PAT.search(body)
        score = float(sc.group(1)) if sc else None
        if sc:
            body = (body[:sc.start()] + body[sc.end():]).strip()
        body = body.strip("；;，,。 \n")
        out.append({"no": _norm_no(m.group(1)), "text": body, "score": score})
    return out


def _subquestions(stem: str, given_scores: list, issues: list,
                  model_subs: list | None = None) -> list[dict]:
    """小问文本优先取题干原文；题干切不出时用模型读图转写的原文（T41）。"""
    subs = split_subquestions(stem)
    score_map = {}
    for x in given_scores or []:
        try:
            score_map[_norm_no(x.get("no"))] = float(x.get("score"))
        except (TypeError, ValueError):
            continue

    text_map: dict[str, str] = {}
    for x in model_subs or []:
        no = _norm_no(x.get("no"))
        t = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()
        if no not in text_map and len(t) >= 2:
            text_map[no] = t

    if not subs:
        if text_map:
            issues.append("题干里切不出小问编号；小问文本取自模型读图转写（%d 个）" % len(text_map))
            subs = [{"no": k, "text": v, "score": None} for k, v in text_map.items()]
        else:
            issues.append("题干里切不出小问编号，模型也没给小问原文；只能放占位（Schema 会报 text 过短）")
            subs = [{"no": k, "text": "（小问原文缺失）", "score": None} for k in score_map] or \
                   [{"no": "(1)", "text": "（小问原文缺失）", "score": None}]
    else:
        for q in subs:
            if len(q["text"]) >= 2:
                continue
            t = text_map.get(q["no"]) or ""
            q["text"] = t if len(t) >= 2 else "（小问原文缺失）"
            issues.append("%s 题干文本为空，改用%s" % (q["no"], "模型转写" if len(t) >= 2 else "占位"))

    for q in subs:
        g = score_map.get(q["no"])
        if g is not None:
            if q["score"] is not None and abs(g - q["score"]) > 1e-6:
                issues.append("%s 分值：题干写 %g，模型报 %g（采用题干）"
                              % (q["no"], q["score"], g))
            else:
                q["score"] = g
        if q["score"] is None:
            issues.append("%s 没拿到分值，留 null（卷面总分不可信）" % q["no"])
    return subs


def _resolve_stem(stem: str, draft: dict, issues: list) -> tuple[str, str]:
    """决定用哪份题干：用户贴的原文，还是模型读图转写的。

    判据是「能不能切出小问」——完整题干一定带 (1)(2)；贴一句「题干在图里」切不出，
    就该退回模型转写，而不是把占位话当题干写进 Schema（那是 Z-03 首跑的坑）。
    """
    s = (stem or "").strip()
    if split_subquestions(s):
        return s, "user_paste"
    ms = str(draft.get("stem_text") or "").strip()
    # 模型转写不一定也带 (1)(2)：单问的题它常常只抄题干、或把编号抄丢（Z-06 就是）。
    # 所以除「转写能切出小问」外，再加一条「用户那段像占位话」：
    # 一个数字都没有、比转写短得多。真实题干几乎总带数字或单位，占位话不会。
    looks_placeholder = bool(ms) and len(ms) >= 40 and len(ms) >= 1.5 * max(len(s), 1) \
        and not re.search(r"[0-9０-９]", s)
    if ms and (split_subquestions(ms) or looks_placeholder):
        issues.append("用户题干里切不出小问；改用模型读图转写的题干（%d 字）" % len(ms))
        return ms, "model_ocr"
    return s, "user_paste"


def build_from_zero(qid: str, draft: dict, stem: str, *,
                    figures: list[dict] | None = None,
                    source: str = "题库外新题（用户粘贴）",
                    call_meta: dict | None = None,
                    info: dict | None = None) -> tuple[dict, list[str]]:
    issues: list[str] = []
    call_meta = call_meta or {}
    stem, stem_src = _resolve_stem(stem, draft, issues)
    if stem_src == "model_ocr" and source == "题库外新题（用户粘贴）":
        source = "题库外新题（题图转写）"     # 别让页面把转写题干说成用户原文
    steps_in = draft.get("steps") or []
    if not steps_in:
        raise ValueError("草稿没有 steps")
    steps_in = sorted(steps_in, key=lambda s: int(s.get("no") or 0))

    subs = _subquestions(stem, draft.get("sub_scores") or [], issues,
                         draft.get("sub_questions") or [])
    if info is not None:
        info.update({
            "stem_source": stem_src,
            # 题干里真有「（N 分）」就以题干为准，模型说的不算
            "scores_printed": True if SCORE_PAT.search(stem) else draft.get("scores_printed"),
            "sub_text_from": "model_ocr" if any(
                "模型读图转写" in x or "模型转写" in x for x in issues) else "stem",
            # 每步给分点：产物 schema 没有这两格，随 zero_meta 存一份，页面按 step_no 取。
            "points": [{"step_no": i,
                        "score": s.get("score"),
                        "text": str(s.get("point") or "").strip()}
                       for i, s in enumerate(steps_in, 1)],
        })
    full = sum(q["score"] for q in subs if q["score"] is not None)
    if not full:
        full = None
        issues.append("小问分值全缺，full_score 置 null")

    stem_sha = hashlib.sha256((stem or "").strip().encode("utf-8")).hexdigest()
    # 与 validate_schema.input_sha256_of 逐字一致：题干 + 固定分隔 + 规范化图读数。
    # 新题没有 provides 时后半段为空串，但分隔符必须保留，否则指纹对不上（R12）。
    input_sha = hashlib.sha256(
        ((stem or "").strip() + "\n\n#provides\n").encode("utf-8")).hexdigest()

    doc = {
        "schema_version": D.SCHEMA_VERSION,
        "meta": {
            "answer_id": qid,
            "question_id": qid,
            "group": "Z",
            "source": source,
            "question_no": None,
            "full_score": full,
            "mode": "zero",                       # 新题型：题库外、无金标、无采分点
            "model": call_meta.get("model", "deepseek-flash"),
            "prompt_version": "p1",
            "temperature": call_meta.get("temperature", 0.2),
            "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "latency_ms": int(call_meta.get("latency_ms") or 0),
            "tokens": {"in": int(call_meta.get("tokens_in") or 0),
                       "out": int(call_meta.get("tokens_out") or 0)},
            "stem_source": stem_src,
        },
        "question": {
            "stem_text": (stem or "").strip(),
            "figures": figures or [],
            "subquestions": subs,
            "stem_sha256": stem_sha,
            "input_sha256": input_sha,
        },
        "situation": {},
        "outline": [],
        "steps": [],
        "grading": {},
        "validation": {"layers": {"L1": "na", "L2": "na", "L3": "na", "L4": "na"},
                       "failures": [], "zero_point_hit": False, "rewrite_rounds": 0},
        "triage": {},
        "review": {"verdict": "pending", "rejected_steps": [], "reason_codes": [],
                   "diffs": [], "added_steps": [], "reordered": False},
    }

    # ---- situation：模型给的物体表 + 已知量；targets 空
    objs = []
    for i, o in enumerate(draft.get("objects") or [], 1):
        name = str(o.get("name") or "").strip()
        if not name:
            continue
        ms, _ = D.norm_symbol(o.get("mass_symbol") or "")
        objs.append({"id": "obj%d" % i, "name": name[:40],
                     "mass_symbol": ms if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", ms or "") else None,
                     "note": str(o.get("note") or "")[:120]})
    if not objs:
        issues.append("模型未给 objects；置空（L4 的物体对照将跳过）")

    given = []
    for g in draft.get("givens") or []:
        sym, chg = D.norm_symbol(g.get("symbol"))
        if chg:
            issues.append("givens.symbol 归一：%r → %r" % (g.get("symbol"), sym))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", sym or ""):
            issues.append("givens.symbol 不合规，已丢弃：%r" % (g.get("symbol"),))
            continue
        try:
            val = None if g.get("value") is None else float(g["value"])
        except (TypeError, ValueError):
            issues.append("givens.%s 的 value 非数值，置 null" % sym)
            val = None
        given.append({"symbol": sym, "value": val, "unit": D.norm_unit(g.get("unit")),
                      "text": str(g.get("text") or "").strip()[:120] or "（模型未写说明）"})
    if not given:
        issues.append("模型未给 givens；Schema 要求 given≥1，插入占位行")
        given = [{"symbol": "g", "value": 10, "unit": "m/s^2",
                  "text": "[占位] 模型未给已知量清单"}]

    # ---- targets：从小问摘要里取「求的是什么量」，L4 用它对照答案指向
    targets = []
    for i, sr in enumerate(draft.get("sub_results") or [], 1):
        m = re.search(r"([A-Za-z][A-Za-z0-9_′']*)\s*[=＝]", str(sr.get("result") or ""))
        q = next((x for x in subs if x["no"] == _norm_no(sr.get("no") or i)), {})
        tq, _ = D.norm_symbol(m.group(1) if m else "T%d" % i)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", tq or ""):
            tq = "T%d" % i
        targets.append({
            "no": _norm_no(sr.get("no") or i),
            "quantity": tq,
            "text": (q.get("text") or "第 %d 问所求量" % i)[:80],
        })
    if not targets:
        targets = [{"no": q["no"], "quantity": "T%d" % i, "text": (q["text"] or "所求量")[:80]}
                   for i, q in enumerate(subs, 1)]

    doc["situation"] = {
        "objects": objs,
        "given": given,
        "process_segments": [{
            "no": 1, "name": "整题（新题首跑不分段）",
            "start": "题设初始状态", "end": "各小问所求量全部求出",
            "segment_id": "SEG-01",
            "boundary_reference": "新题模式统一 SEG-01",
        }],
        "targets": targets,
        "assumptions": [],
    }

    # ---- steps：与 build() 同一套规则
    n = 0
    for s in steps_in:
        n += 1
        sid = "%s-S%02d" % (qid, n)
        kind = str(s.get("kind") or "").strip()
        if kind not in ("equation", "value", "judgment", "discussion", "critical"):
            issues.append("%s kind 非法（%r），按 judgment 处理" % (sid, kind))
            kind = "judgment"
        eq_raw, eq_issues = D.norm_eq(s.get("eq"))
        issues.extend("%s %s" % (sid, it) for it in eq_issues)
        val, v_issues = D.norm_value(s.get("value"))
        issues.extend("%s %s" % (sid, it) for it in v_issues)

        if kind in ("judgment", "critical"):
            if eq_raw is not None:
                issues.append("%s 是 %s 步却给了 eq，已置 null" % (sid, kind))
            eq_obj = None
        elif eq_raw is None:
            issues.append("%s 是 %s 步但 eq 归一失败（要求非空）" % (sid, kind))
            eq_obj = None
        else:
            eq_obj = {"latex": D.to_latex(eq_raw), "sympy": eq_raw,
                      "symbols": D.syms_of(eq_raw), "parse_status": "ok"}

        crit = None
        if kind in ("judgment", "critical", "discussion"):
            txt = str(s.get("point") or s.get("stmt") or "").strip()
            if len(txt) < 6:
                txt = (txt + "（模型原文过短）")[:200]
            crit = {"expr": "True", "expected": None,
                    "comparator": "qualitative", "text": txt[:200]}

        st = {
            "step_id": sid,
            "step_no": n,
            "title": str(s.get("title") or "未命名")[:40],
            "point_id": None,
            "kind": kind,
            "statement": str(s.get("stmt") or "")[:600],
            "equation": eq_obj,
            "segment_id": "SEG-01",
            "value": val,
            "law_ids": [],
            "checks": [],
            "confidence": 3,
            "status": "draft",
        }
        if crit is not None:
            st["criterion"] = crit
        doc["steps"].append(st)
        doc["outline"].append({"step_no": n,
                               "title": str(s.get("title") or "未命名")[:40],
                               "depends_on": [], "expanded": True, "point_hint": None})

    # ---- grading：结构齐全但分数为 null。
    # 新题没有人工采分点，模型自出的 point 判自己 = 自证，所以不判分。
    # 用 null 而不是 0：0 会被读成「全错」，null 才是「未判」。
    doc["grading"] = {
        "point_hits": [],
        "missing_points": [],
        "extra_steps": [],
        "score_awarded": None,
        "score_total": None,
        "weighted_rate": None,
    }
    doc["triage"] = {
        "level": "yellow",
        "signals": {"hard_check": "partial", "question_type_prior": "mid",
                    "self_rank": None, "rework_rate": None},
        "reason": "题库外新题：无金标、无采分点，只出解析与自洽检查，不判分",
    }
    return doc, issues


def display_map(qid: str, draft: dict) -> dict:
    """模型原始符号 → 归一后符号的对照（只收被改过的）。

    norm_value() 会把 `v_B` 归一成 `vB`（符号白名单不许下划线）。20 题靠
    symbols.steps[sid].vsym 还原成题面写法；新题没有 build_display()，
    这里从草稿直接生成同一份结构，供页面渲染用。

    **不进 schema**（additionalProperties:false），由 run_zero 单独落盘，
    render_result 读它塞进渲染 payload。
    """
    out = {}
    steps = sorted(draft.get("steps") or [], key=lambda s: int(s.get("no") or 0))
    for i, s in enumerate(steps, 1):
        raw = str((s.get("value") or {}).get("symbol") or "").strip()
        if not raw:
            continue
        norm, _ = D.norm_symbol(raw)
        if norm and norm != raw:
            out["%s-S%02d" % (qid, i)] = {"vsym": raw}
    return out


def main() -> int:
    """把一份 draft 转成 schema 并落盘，供调试。"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", help="模型草稿 JSON")
    ap.add_argument("--stem", required=True, help="题干文本文件（UTF-8）")
    ap.add_argument("--qid", default="Z-001")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
    stem = Path(a.stem).read_text(encoding="utf-8")
    doc, issues = build_from_zero(a.qid, draft, stem)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("steps %d · issues %d" % (len(doc["steps"]), len(issues)))
    for x in issues:
        print("  -", x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

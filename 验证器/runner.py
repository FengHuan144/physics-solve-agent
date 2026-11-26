# -*- coding: utf-8 -*-
"""runner.py — 读 answer JSON → 产 ``checks[]`` → 写回 JSON。

只动两处（卡 §5）：``steps[].checks[]`` 里的 L1 / L2 条目，和
``validation.layers`` / ``validation.failures`` 里属于 L1 / L2 的部分。
L3 / L4 的既有 check、grading、triage、review 一律不碰。

输出必须是合法 answer JSON：除 L1/L2 外，其余字段与输入逐字一致。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

from . import alias as A
from . import l1_deduce as L1
from . import l2_dimension as L2
from . import units as U

PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = U.PROJECT_ROOT / "schema" / "answer.schema.json"
XLSX_PATH = U.PROJECT_ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
OUR_LAYERS = ("L1", "L2")


# --------------------------------------------------------------------------- 主流程

def run_answer(answer: dict, symbols: dict | None = None,
               alias: bool = False, alias_qid: str | None = None) -> tuple[dict, dict]:
    """跑一遍 L1+L2。返回 ``(新的 answer, 报告)``，不修改入参。

    ``alias``（T23 开关）：默认 **False**。关闭时不做任何符号改写，行为与本卡之前
    逐字节一致；打开时先把模型符号翻译成白名单 id（``alias.apply_alias``），
    再交给 L1/L2。翻译只改名字，不改数值/单位/正负号。
    """
    syms = symbols if symbols is not None else U.load_symbols()
    doc = copy.deepcopy(answer)
    alias_stats = None
    if alias:
        doc, alias_stats = A.apply_alias(doc, qid=alias_qid)

    recs = L1.prepare(doc, syms)
    givens, step_values, conflicts, known_errors = L1.collect_knowns(doc)
    knowns_all = L1.all_knowns(givens, step_values)
    per = L1.per_step(recs, givens)
    ch = L1.chain(recs, knowns_all)

    by_id = {r.step_id: r for r in recs}
    for i, step in enumerate(doc.get("steps") or []):
        sid = str(step.get("step_id") or recs[i].step_id)
        rec = by_id.get(sid) or recs[i]
        kept = [c for c in (step.get("checks") or []) if c.get("layer") not in OUR_LAYERS]
        l1 = L1.merge(per.get(sid, L1.Verdict("na", "无判定结果")),
                      ch.verdicts.get(sid, L1.Verdict("na", "无判定结果")))
        l2 = L2.analyze(step, syms)
        l1 = _dedupe_symptom(l1, l2)
        step["checks"] = [l1] + l2["checks"] + kept

    _write_layers(doc)
    report = _build_report(doc, recs, conflicts, known_errors, ch)
    if alias_stats is not None:      # 只在开别名时出现，关别名时报告形状不变
        report["alias"] = alias_stats
    _write_failures(doc, report)
    return doc, report


def _dedupe_symptom(l1: dict, l2: dict) -> dict:
    """方程本身量纲不符时，同一步 L1 的失败是症状，降 na 指向根因（§10-4 已定）。

    只在 ``l2["equation_broken"]`` 为真时生效。``value.unit`` 的问题不触发——
    那时方程可能完全正确，而数值是真错的，吞掉 L1 会漏掉一个独立缺陷。
    """
    if l1.get("status") != "fail" or not l2.get("equation_broken"):
        return l1
    codes = "/".join(l2.get("equation_codes") or ["E-12"])
    return {
        "layer": "L1",
        "status": "na",
        "detail": (f"不重复计数：根因见 L2/{codes}（方程两侧量纲不符）。"
                   f"本步 L1 原判 {l1.get('error_code')}：{l1.get('detail')}"),
        "error_code": None,
    }


def _write_layers(doc: dict):
    """整题层状态由步级 checks 聚合，L3/L4/L5/L6 保持原值。

    聚合口径（T08d 缺陷 ② 统一）：fail > na > skipped > pass 优先，
    全 pass 才 pass。旧口径是「有一个 pass 就 pass」，会把 B-09/B-12 那种
    「个别步 L1=na」的题报成整题 pass —— 这正是缺陷 ② 的成因，
    schema/validate_schema.py 的 R13 已按新口径设卡。
    """
    layers = (doc.get("validation") or {}).get("layers") or {}
    for layer in OUR_LAYERS:
        st = [c.get("status") for s in doc.get("steps") or []
              for c in (s.get("checks") or []) if c.get("layer") == layer]
        if "fail" in st:
            layers[layer] = "fail"
        elif "na" in st:
            layers[layer] = "na"
        elif "skipped" in st:
            layers[layer] = "skipped"
        elif "pass" in st:
            layers[layer] = "pass"
        else:
            layers[layer] = "na"
    doc.setdefault("validation", {})["layers"] = layers


def _build_report(doc: dict, recs, conflicts, known_errors: list[str],
                  ch: L1.ChainResult) -> dict:
    stats: dict[str, dict[str, int]] = {}
    fails: list[dict] = []
    data_errors: list[dict] = []
    degraded: list[str] = []
    for step in doc.get("steps") or []:
        sid = step.get("step_id")
        if (step.get("equation") or {}).get("parse_status") == "degraded":
            degraded.append(sid)
        for c in step.get("checks") or []:
            layer = c.get("layer")
            if layer not in OUR_LAYERS:
                continue
            d = stats.setdefault(layer, {"pass": 0, "fail": 0, "na": 0, "skipped": 0})
            d[c.get("status")] = d.get(c.get("status"), 0) + 1
            if c.get("status") == "fail":
                fails.append({"step_id": sid, "layer": layer,
                              "error_code": c.get("error_code"),
                              "detail": c.get("detail")})
            if c.get("status") == "na" and "data_error" in (c.get("detail") or ""):
                data_errors.append({"step_id": sid, "layer": layer,
                                    "detail": c.get("detail")})

    judged: dict[str, str] = {}
    na_ratio: dict[str, str] = {}
    for layer, d in stats.items():
        denom = d["pass"] + d["fail"]
        judged[layer] = f"{d['pass'] / denom:.1%}" if denom else "—"
        denom2 = d["pass"] + d["fail"] + d["na"]
        na_ratio[layer] = f"{d['na'] / denom2:.1%}" if denom2 else "—"

    return {
        "question_id": (doc.get("meta") or {}).get("question_id"),
        "answer_id": (doc.get("meta") or {}).get("answer_id"),
        "steps": len(doc.get("steps") or []),
        "checks": stats,
        "judged_rate": judged,
        "na_ratio": na_ratio,
        "failures": fails,
        "data_errors": data_errors,
        "degraded_steps": degraded,
        "known_conflicts": conflicts,
        "known_data_errors": known_errors,
        "chain_attributed": ch.attributed,
        "chain_ambiguous": ch.ambiguous,
        "chain_unclassified": ch.unclassified,
        "layers": (doc.get("validation") or {}).get("layers"),
    }


def _write_failures(doc: dict, report: dict):
    """failures[] 里 L1/L2 的部分按本次结果重写，其它层原样保留。"""
    val = doc.setdefault("validation", {})
    kept = [f for f in (val.get("failures") or []) if f.get("layer") not in OUR_LAYERS]
    new = [{"step_id": f["step_id"], "layer": f["layer"],
            "error_code": f["error_code"], "detail": f["detail"]}
           for f in report["failures"]]
    order = {s.get("step_id"): i for i, s in enumerate(doc.get("steps") or [])}
    kept.sort(key=lambda f: (order.get(f.get("step_id"), 999), f.get("layer", "")))
    val["failures"] = kept + new


# --------------------------------------------------------------------------- 契约

def validate_checks(doc: dict, schema_path: str | None = None) -> list[str]:
    """用 jsonschema 对 ``definitions.check`` 逐条验证（卡 R3）。返回违约列表。"""
    path = Path(schema_path) if schema_path else SCHEMA_PATH
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    # check 里有 $ref: #/definitions/error_code，必须带着 definitions 一起验，
    # 否则 $ref 解析不到（不是 check 违约，是引用根丢了）
    wrapper = {"$ref": "#/definitions/check", "definitions": schema["definitions"]}
    checker = jsonschema.Draft7Validator(wrapper)
    bad: list[str] = []
    for step in doc.get("steps") or []:
        for i, c in enumerate(step.get("checks") or []):
            errs = sorted(checker.iter_errors(c), key=lambda e: list(e.absolute_path))
            for e in errs:
                bad.append(f"{step.get('step_id')} checks[{i}]: {e.message}")
    return bad


# --------------------------------------------------------------------------- 台账审计

def audit_xlsx(path: str | None = None) -> dict:
    """审计采分点总表：它到底能给验证器提供多少可判的步。

    这不是「跑一遍 61 步」，而是把「为什么跑不了」变成可核对的数字：
    台账是**采分点文本**，没有 ``equation.sympy``、没有 ``value.number/unit``。
    """
    import openpyxl

    p = Path(path) if path else XLSX_PATH
    wb = openpyxl.load_workbook(p, data_only=True)
    ws = wb["采分点总表"]
    header = [str(c).strip() if c is not None else "" for c in next(ws.iter_rows(values_only=True))]
    idx = {h: i for i, h in enumerate(header)}
    need = ["point_id", "采分点（必须出现的式子或判断）", "采分类别", "分值"]
    missing = [h for h in need if h not in idx]

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        pid = row[idx["point_id"]] if not missing else None
        if not pid:
            continue
        rows.append({
            "point_id": str(pid).strip(),
            "text": str(row[idx["采分点（必须出现的式子或判断）"]] or ""),
            "category": str(row[idx["采分类别"]] or "").strip(),
            "score": float(row[idx["分值"]] or 0),
        })

    def has_eq(text: str) -> bool:
        return "=" in text or "＝" in text

    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1

    six = [r for r in rows if r["point_id"].split("-S")[0] in
           {f"A-{i:02d}" for i in range(1, 7)}]
    return {
        "path": str(p),
        "columns_missing": missing,
        "rows": len(rows),
        "questions": len({r["point_id"].split("-S")[0] for r in rows}),
        "score": sum(r["score"] for r in rows),
        "first_six_rows": len(six),
        "first_six_score": sum(r["score"] for r in six),
        "has_sympy_column": "equation.sympy" in header or "sympy" in header,
        "has_value_column": any(h in header for h in ("value.number", "number", "value")),
        "rows_with_equal_sign": sum(1 for r in rows if has_eq(r["text"])),
        "first_six_with_equal_sign": sum(1 for r in six if has_eq(r["text"])),
        "by_category": dict(sorted(by_cat.items())),
        "verdict": ("台账无 equation.sympy / value.number / value.unit 三列 → "
                    "无法构造 answer 步，L1/L2 对台账行全部不可判（结构性，不是判 fail）"),
    }

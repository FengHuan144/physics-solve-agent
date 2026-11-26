#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_zero.py — 题库外新题：题干 → 解题 → 转换 → Schema 校验 → 验证器。

不涉判分（无采分点），不涉金标（无 examples）。这是 app.py 新题模式的第 1–3 步。

    python 评测/T20/run_zero.py --stem 临时/q.txt --out 临时/t40
    python 评测/T20/run_zero.py --stem 临时/q.txt --fig 临时/a.png --fig 临时/b.png --out 临时/t40

产物落 <out>/：
    {qid}_draft.json       模型原样返回
    {qid}.json             转换后的 schema doc（mode=zero）
    {qid}_validated.json   验证器输出
    zero_meta.json         本次调用元信息（耗时/token/成本/issues）
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
sys.path.insert(0, str(HERE))
import run_solve as R                                    # noqa: E402
import from_zero as Z                                    # noqa: E402

TZ = timezone(timedelta(hours=8))
FIG_LABEL = ["图甲", "图乙", "图丙", "图丁", "图戊"]
EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".bmp": "image/bmp"}


def build_prompt(stem: str) -> str:
    tpl = (HERE / "prompt_zero.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- TEMPLATE_START -->(.*?)<!-- TEMPLATE_END -->", tpl, re.S)
    if not m:
        raise SystemExit("prompt_zero.md 缺 TEMPLATE_START/END")
    body = m.group(1).strip()
    if body.count("{题干}") != 1:
        raise SystemExit("prompt_zero.md 的 {题干} 占位符数量异常")
    return body.replace("{题干}", stem.strip())


def figure_parts(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    """返回（发给 API 的 parts，写进 schema 的 figures）。"""
    parts, figs = [], []
    for i, p in enumerate(paths[:len(FIG_LABEL)], 1):
        mt = EXTS.get(p.suffix.lower())
        if not mt:
            raise SystemExit("不支持的图片格式：%s" % p.name)
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        parts.append({"type": "text", "text": FIG_LABEL[i - 1] + "："})
        parts.append({"type": "image_url",
                      "image_url": {"url": "data:%s;base64,%s" % (mt, b64)}})
        figs.append({"fig_no": i, "caption": p.name,
                     "caption_source": "none", "is_required": True,
                     "file": None, "file_sha256": None})
    return parts, figs


def run_schema_check(doc_path: Path) -> dict:
    p = subprocess.run([sys.executable, "schema/validate_schema.py", str(doc_path)],
                       cwd=str(PROJ), capture_output=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    tail = [ln for ln in out.splitlines() if "通过：" in ln or "失败：" in ln
            or ln.startswith("[E]")]
    return {"rc": p.returncode, "errors": tail[:12], "raw_tail": out[-1500:]}


def run_validator(doc_path: Path, out_path: Path) -> dict:
    p = subprocess.run([sys.executable, "-m", "验证器.cli", str(doc_path),
                        "--out", str(out_path)],
                       cwd=str(PROJ), capture_output=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"整题层状态：(\{.*?\})", out)
    layers = None
    if m:
        try:
            layers = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {"rc": p.returncode, "layers": layers, "raw_tail": out[-1200:]}


def solve_zero(stem: str, out_dir: Path, figures: list[Path] | None = None,
               qid: str = "Z-01", log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = figures or []

    prompt = build_prompt(stem)
    parts, fig_meta = figure_parts(figures)
    log("prompt %d 字 · 图 %d 张" % (len(prompt), len(figures)))

    t0 = time.time()
    res = R.call(prompt, parts)
    el = time.time() - t0
    if not res.get("ok"):
        raise RuntimeError("解题调用失败：%s %s" % (res.get("status"), str(res.get("error"))[:300]))

    u = res.get("usage") or {}
    tin = int(u.get("prompt_tokens") or 0)
    tout = int(u.get("completion_tokens") or 0)
    reasoning = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    cost = round(tout * R.PRICE_OUT + tin * 0.5e-6, 4)     # 粗估，与 run_solve 同口径
    log("返回 %.1fs · in %d / out %d（思维 %d）· 约 %.2f 元"
        % (el, tin, tout, reasoning, cost))

    draft, err = R.parse_draft(res.get("content") or "")
    if not draft:
        (out_dir / f"{qid}_raw.txt").write_text(res.get("content") or "", encoding="utf-8")
        raise RuntimeError("JSON 解析失败：%s" % err)
    (out_dir / f"{qid}_draft.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

    info: dict = {}
    doc, issues = Z.build_from_zero(
        qid, draft, stem, figures=fig_meta, info=info,
        call_meta={"model": R.MODEL, "temperature": R.TEMPERATURE,
                   "latency_ms": int(el * 1000), "tokens_in": tin, "tokens_out": tout})
    doc_path = out_dir / f"{qid}.json"
    doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    # 展示用符号对照：schema 不许额外字段，单独一份给页面
    dmap = Z.display_map(qid, draft)
    (out_dir / f"{qid}_symbols.json").write_text(
        json.dumps({"steps": dmap}, ensure_ascii=False, indent=2), encoding="utf-8")
    log("转换：%d 步 · %d 条 issue · %d 个符号还原" % (len(doc["steps"]), len(issues), len(dmap)))

    sch = run_schema_check(doc_path)
    log("Schema：%s" % (sch["errors"][-1] if sch["errors"] else "rc=%d" % sch["rc"]))

    val_path = out_dir / f"{qid}_validated.json"
    val = run_validator(doc_path, val_path)
    log("验证器：%s" % (val["layers"] or "rc=%d" % val["rc"]))

    meta = {"qid": qid, "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "elapsed_s": round(el, 1), "tokens": {"in": tin, "out": tout, "reasoning": reasoning},
            "cost_cny": cost, "n_steps": len(doc["steps"]), "issues": issues,
            "schema": {"rc": sch["rc"], "errors": sch["errors"]},
            "validation": {"rc": val["rc"], "layers": val["layers"]},
            "display": info,
            "figures": [str(p) for p in figures]}
    (out_dir / "zero_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", required=True, help="题干文本文件（UTF-8）。也可以用 --stdin")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读题干")
    ap.add_argument("--fig", action="append", default=[], help="图片路径，可重复")
    ap.add_argument("--out", required=True, help="产物目录")
    ap.add_argument("--qid", default="Z-01")
    a = ap.parse_args()

    if a.stdin:
        stem = sys.stdin.read()
    else:
        stem = Path(a.stem).read_text(encoding="utf-8")
    if len(stem.strip()) < 20:
        raise SystemExit("题干太短（<20 字），不跑")

    meta = solve_zero(stem, Path(a.out), [Path(x) for x in a.fig], a.qid)
    print(json.dumps({k: v for k, v in meta.items() if k != "issues"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

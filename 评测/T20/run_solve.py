#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_solve.py — T20 整题解题首跑：读题 → 发请求（含图）→ 草稿 → 转换 → 落盘 → 调校验

用法：
    python 评测/T20/run_solve.py --qid B-20                 # 阶段 A（1 题）
    python 评测/T20/run_solve.py --all                      # 阶段 B（7 题）
    python 评测/T20/run_solve.py --qid B-20 --dry-run        # 只拼 prompt，不花钱

硬规则（卡 §5/§8）：
    - model 固定 deepseek-flash（唯一收图），不许换 v4-pro
    - temperature 0.2、max_tokens 16000
    - 只在「JSON 解析失败」时重试 1 次；答案错不重试
    - 余额 < 1 CNY 或 402 → 立即终止，不空跑
    - raw 原样落盘，不手工修
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
STEM_DIR = PROJ / "采分点" / "题干原文"
EX_DIR = PROJ / "schema" / "examples"
FIG_DIR = PROJ / "原始资料" / "题图"
sys.path.insert(0, str(HERE))
import draft_to_schema as D2S                    # noqa: E402

API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-flash"
TEMPERATURE = 0.2
MAX_TOKENS = 40000   # 卡给 16000；实测 flash 单题推理就要 16k，故上调（见报告）
MAX_RETRIES = 1                                   # 只对 JSON 解析失败

# 成本对照实验用：透传额外请求参数（如 effort），输出加后缀，不覆盖基线
EXTRA_PARAMS: dict = {}
SUFFIX = ""
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_M", "7.0")) / 1e6   # 元/token（估算，见报告）
TZ = timezone(timedelta(hours=8))
FIG_LABEL = ["图甲", "图乙", "图丙", "图丁"]
MIN_BALANCE = 1.0

ALL_QIDS = ["A-02", "A-08", "A-10", "B-02", "B-09", "B-12", "B-20"]


# ------------------------------------------------------------------ 题干与图

def split_sections(text: str) -> dict[int, str]:
    out = {}
    parts = re.split(r"^## (\d+)\..*?$", text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        out[int(parts[i])] = parts[i + 1].strip()
    return out


def load_stem(qid: str) -> str:
    files = sorted(STEM_DIR.glob("%s_*.md" % qid))
    if not files:
        raise SystemExit("找不到题干 %s" % qid)
    sec = split_sections(files[0].read_text(encoding="utf-8"))
    return sec[2].rstrip() + "\n\n" + sec[5].strip()


def load_prompt(qid: str) -> str:
    tpl = (HERE / "prompt_v1.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- TEMPLATE_START -->(.*?)<!-- TEMPLATE_END -->", tpl, re.S)
    if not m:
        raise SystemExit("prompt_v1.md 缺 TEMPLATE_START/END 标记")
    body = m.group(1).strip()
    if body.count("{题干}") != 1:
        raise SystemExit("prompt_v1.md 的 {题干} 占位符数量异常：%d" % body.count("{题干}"))
    return body.replace("{题干}", load_stem(qid))


def figure_parts(qid: str) -> tuple[list[dict], list[str]]:
    gold = json.loads((EX_DIR / ("%s.json" % qid)).read_text(encoding="utf-8"))
    parts, used = [], []
    for fig in gold["question"].get("figures") or []:
        if not fig.get("is_required"):
            continue
        rel = fig.get("file")
        if not rel:
            continue
        p = PROJ / rel
        if not p.exists():
            raise SystemExit("必需图不存在：%s" % rel)
        b64 = base64.b64encode(p.read_bytes()).decode()
        lab = FIG_LABEL[fig["fig_no"] - 1]
        parts.append({"type": "text", "text": lab + "："})
        parts.append({"type": "image_url",
                      "image_url": {"url": "data:image/png;base64," + b64}})
        used.append(rel)
    return parts, used


# ------------------------------------------------------------------ API

def balance() -> float:
    r = requests.get(API_BASE + "/user/balance", timeout=30,
                     headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]})
    r.raise_for_status()
    d = r.json()
    infos = d.get("balance_infos") or []
    return float(infos[0]["total_balance"]) if infos else 0.0


def call(prompt: str, figs: list[dict]) -> dict:
    key = os.environ["DEEPSEEK_API_KEY"]
    content = [{"type": "text", "text": prompt}] + figs
    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": content}],
               "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
               "stream": False}
    payload.update(EXTRA_PARAMS)
    t0 = time.time()
    try:
        r = requests.post(API_BASE + "/chat/completions", json=payload, timeout=900,
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
    except requests.RequestException as e:
        return {"ok": False, "status": "exc", "elapsed_s": time.time() - t0,
                "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
    el = time.time() - t0
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "elapsed_s": el,
                "error": r.text[:800]}
    d = r.json()
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return {"ok": True, "elapsed_s": el, "content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "finish_reason": ch.get("finish_reason"), "usage": d.get("usage") or {},
            "model_returned": d.get("model"), "id": d.get("id")}


def parse_draft(text: str) -> tuple[dict | None, str]:
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            s = s[i:j + 1]
    try:
        return json.loads(s), ""
    except json.JSONDecodeError as e:
        return None, str(e)


# ------------------------------------------------------------------ 校验

def run_cmd(cmd: list[str], log_path: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(PROJ), capture_output=True,
                       encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
    log_path.write_text("$ " + " ".join(cmd) + "\n\n" + out, encoding="utf-8")
    return p.returncode, out


def validate(qid: str, out_json: Path, stamp: str) -> dict:
    logs = HERE / "logs"
    rc1, o1 = run_cmd([sys.executable, "schema/validate_schema.py", str(out_json)],
                      logs / ("validate_%s_%s.txt" % (qid, stamp)))
    rc2, o2 = run_cmd([sys.executable, "-m", "验证器.cli", str(out_json),
                       "--out", str(out_json.with_name(out_json.stem + "_validated.json"))],
                      logs / ("runner_%s_%s.txt" % (qid, stamp)))
    e_lines = [l for l in o1.splitlines() if "[E]" in l]
    w_lines = [l for l in o1.splitlines() if "[W]" in l]
    return {"schema_rc": rc1, "n_e": len(e_lines), "n_w": len(w_lines),
            "e_lines": e_lines[:12], "schema_out": o1, "runner_rc": rc2,
            "runner_out": o2}


# ------------------------------------------------------------------ 单题

def solve(qid: str, stamp: str, dry: bool) -> dict:
    prompt = load_prompt(qid)
    figs, used = figure_parts(qid)
    gold = json.loads((EX_DIR / ("%s.json" % qid)).read_text(encoding="utf-8"))
    rec = {"qid": qid, "model": MODEL, "temperature": TEMPERATURE,
           "max_tokens": MAX_TOKENS, "prompt_chars": len(prompt),
           "figures": used, "created_at": datetime.now(TZ).isoformat(timespec="seconds")}
    print("[题] %s  题干 %d 字  图 %d 张  金标 %d 步"
          % (qid, len(prompt), len(used), len(gold["steps"])))
    if dry:
        (HERE / "logs" / ("prompt_%s.txt" % qid)).write_text(prompt, encoding="utf-8")
        print("[dry-run] prompt 落盘 logs/prompt_%s.txt；未调用 API" % qid)
        return rec

    res, draft, perr, tries = None, None, "", 0
    while tries <= MAX_RETRIES:
        tries += 1
        res = call(prompt, figs)
        if res.get("ok"):
            (HERE / "raw").mkdir(parents=True, exist_ok=True)
            (HERE / "raw" / ("%s_att%d%s.txt" % (qid, tries, SUFFIX))).write_text(
                res["content"], encoding="utf-8")
        if not res["ok"]:
            print("  [API 失败] %s %s" % (res["status"], str(res.get("error"))[:200]))
            if res["status"] == 402:
                raise SystemExit("[致命] 402 余额不足，立即终止整批")
            break
        draft, perr = parse_draft(res["content"])
        print("  [返回] %.1fs  finish=%s  tok=%s+%s  解析=%s"
              % (res["elapsed_s"], res.get("finish_reason"),
                 res["usage"].get("prompt_tokens"), res["usage"].get("completion_tokens"),
                 "ok" if draft else "FAIL:%s" % perr[:80]))
        if draft:
            break
        if res.get("finish_reason") == "length":
            print("  [不重试] finish_reason=length：是预算不足，不是 JSON 问题")
            break
        if tries <= MAX_RETRIES:
            print("  [重试 %d] 仅因 JSON 解析失败" % tries)

    (HERE / "raw").mkdir(parents=True, exist_ok=True)
    if res and res["ok"]:
        (HERE / "raw" / ("%s_raw%s.txt" % (qid, SUFFIX))).write_text(res["content"], encoding="utf-8")
        if draft:
            (HERE / "raw" / ("%s_draft%s.json" % (qid, SUFFIX))).write_text(
                json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cm = {"model": res.get("model_returned") if res else MODEL,
          "temperature": TEMPERATURE,
          "latency_ms": int((res or {}).get("elapsed_s", 0) * 1000),
          "tokens_in": ((res or {}).get("usage") or {}).get("prompt_tokens", 0),
          "tokens_out": ((res or {}).get("usage") or {}).get("completion_tokens", 0)}
    (HERE / "raw" / ("%s_call%s.json" % (qid, SUFFIX))).write_text(
        json.dumps({**rec, **(res or {}), "content": None}, ensure_ascii=False,
                   indent=2, default=str) + "\n", encoding="utf-8")

    det = ((res or {}).get("usage") or {}).get("completion_tokens_details") or {}
    r_tok = det.get("reasoning_tokens", 0)
    rec.update({"ok": bool(draft), "attempts": tries, "parse_error": perr,
                "finish_reason": (res or {}).get("finish_reason"),
                "tokens_in": cm["tokens_in"], "tokens_out": cm["tokens_out"],
                "reasoning_tokens": r_tok,
                "cost_cny": round(cm["tokens_out"] * PRICE_OUT, 4),
                "extra_params": dict(EXTRA_PARAMS),
                "elapsed_s": round((res or {}).get("elapsed_s", 0), 1)})
    if not draft:
        return rec

    doc, issues = D2S.build(qid, draft, gold, cm)
    out = HERE / "out" / ("%s%s.json" % (qid, SUFFIX))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = D2S.score_audit(draft, gold)
    rec.update({"n_steps": len(doc["steps"]), "n_gold": len(gold["steps"]),
                "step_ratio": round(len(doc["steps"]) / len(gold["steps"]), 3),
                "issues": issues, "score_audit": audit})
    print("  [转换] %d 步（金标 %d，比 %.2f）  issue %d 条"
          % (len(doc["steps"]), len(gold["steps"]), rec["step_ratio"], len(issues)))

    v = validate(qid, out, stamp)
    rec.update({"schema_rc": v["schema_rc"], "n_e": v["n_e"], "n_w": v["n_w"],
                "e_lines": v["e_lines"]})
    lay = re.findall(r"整题层状态：(\{.*?\})", v["runner_out"])
    rec["layers"] = lay[-1] if lay else ""
    print("  [Schema] E=%d W=%d  rc=%d" % (v["n_e"], v["n_w"], v["schema_rc"]))
    if rec["layers"]:
        print("  [验证器] %s" % rec["layers"])
    for l in v["e_lines"]:
        print("    " + l.strip()[:160])
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--effort", default=None, help="透传 effort（low/medium/high）")
    ap.add_argument("--tag", default="", help="输出文件后缀，避免覆盖基线")
    ap.add_argument("--no-think", action="store_true",
                    help="关闭思维链（thinking=disabled）。已封存，仅供对照，见 成本判定 §7")
    args = ap.parse_args()
    global SUFFIX
    SUFFIX = args.tag or ""
    if args.effort:
        EXTRA_PARAMS["effort"] = args.effort
    if args.no_think:
        # 2026-11-25 裁定封存：A-08 上 23 步（步骤 11–22 为 2,-2,1 周期死循环）、
        # 三问错两问，而 Schema 仍 E=0。判据与证据见 评测/T20/成本判定_20261125.md §7。
        print("[警示] 无思维档已封存，仅作对照；用它跑出的数不得算作能力测量")
        EXTRA_PARAMS["thinking"] = {"type": "disabled"}
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY 不存在")
    qids = ALL_QIDS if args.all else ([args.qid] if args.qid else ["B-20"])

    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M")
    (HERE / "logs").mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        bal = balance()
        print("[余额] %.2f CNY" % bal)
        if bal < MIN_BALANCE:
            raise SystemExit("[停止] 余额 %.2f < %.1f，不空跑" % (bal, MIN_BALANCE))

    recs = []
    for q in qids:
        try:
            recs.append(solve(q, stamp, args.dry_run))
        except SystemExit:
            raise
        except Exception as exc:                  # noqa: BLE001
            print("  [异常] %s: %s" % (type(exc).__name__, exc))
            recs.append({"qid": q, "ok": False, "error": str(exc)[:200]})

    if not args.dry_run:
        (HERE / "logs" / ("run_%s.json" % stamp)).write_text(
            json.dumps(recs, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8")
        tin = sum(r.get("tokens_in") or 0 for r in recs)
        tout = sum(r.get("tokens_out") or 0 for r in recs)
        rtok = sum(r.get("reasoning_tokens") or 0 for r in recs)
        cost = sum(r.get("cost_cny") or 0 for r in recs)
        print("[汇总] %d 题  解析成功 %d  token %d+%d（思维 %d，%.1f%%）≈%.2f 元  日志 logs/run_%s.json"
              % (len(recs), sum(1 for r in recs if r.get("ok")), tin, tout,
                 rtok, rtok / max(tout, 1) * 100, cost, stamp))
        if not args.dry_run:
            try:
                print("[余额] 收尾 %.2f CNY" % balance())
            except Exception:                     # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

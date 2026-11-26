#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T07 基线实验 · 采集脚本

职责单一：读 prompts/ + 题干原文 → 调 DeepSeek API → 写 raw/{variant}/{qid}.json
不做判分（判分在 score.py）。

用法：
    python 评测/基线/run.py --variant v1                    # 全量 22 题
    python 评测/基线/run.py --variant v1 --qid A-06          # 单题（闸 1）
    python 评测/基线/run.py --variant v1 --limit 3           # 只跑前 3 题
    python 评测/基线/run.py --variant v1 --force             # 覆盖已有 raw

硬规则对应：
    R2  raw 落盘含完整 content / usage / model / 耗时
    R3  prompt 从 prompts/*.md 读取，脚本内不内联、不改写
    R4  temperature=0 固定，变体间一致
    R5  重试上限 2 次；finish_reason=length 记 truncated
    R6  token 与耗时逐条记
    R11 跑前算 sha256，写 stems/stem_fingerprints.csv
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))          # 评测/基线
PROJ = os.path.abspath(os.path.join(ROOT, "..", ".."))     # 项目根
STEM_DIR = os.path.join(PROJ, "采分点", "题干原文")

API_BASE = "https://api.deepseek.com"
MODEL_CANDIDATES = ["deepseek-chat"]
TEMPERATURE = 0.0
MAX_TOKENS = 32768   # 8192→6 题截断；16384→B-15 仍截断；再上调
MAX_RETRIES = 2          # R5：首次之外最多再试 2 次
TZ = timezone(timedelta(hours=8))

VARIANTS = {
    "v1": "v1_zero.md",
    "v2": "v2_role.md",
    "v3": "v3_fewshot.md",
}


# ---------------------------------------------------------------- 题干解析
def split_sections(text):
    """按 '## n.' 切小节，返回 {n: content}"""
    out = {}
    parts = re.split(r"^## (\d+)\..*?$", text, flags=re.M)
    # parts = [前言, '1', 内容, '2', 内容, ...]
    for i in range(1, len(parts) - 1, 2):
        out[int(parts[i])] = parts[i + 1].strip()
    return out


def list_stems():
    files = sorted(f for f in os.listdir(STEM_DIR)
                   if f.endswith(".md") and not f.startswith("_"))
    return files


def parse_meta(meta):
    """从 §1 元信息表抽 小问数 / 卷面分（值里可能带 ** 与注释）"""
    def grab(key):
        m = re.search(r"^\|\s*%s\s*\|\s*(.+?)\s*\|$" % key, meta, re.M)
        if not m:
            return None
        return m.group(1)
    raw_sub = grab("小问数") or ""
    raw_score = grab("卷面分") or ""
    sub = re.search(r"\d+", raw_sub)
    score = re.search(r"\d+", raw_score)
    return (int(sub.group()) if sub else None,
            int(score.group()) if score else None)


def load_stem(path):
    """
    {题干} 填充规则（卡 §3）：
        原文第 2 节「题干原文」+ 第 5 节「小问原文」拼接。
        [图n｜…｜图题…] 标记原样保留。
        第 3 节 caption 绝对不许拼进去。
    """
    text = open(path, encoding="utf-8").read()
    sec = split_sections(text)
    stem_body = sec[2]
    subs = sec[5]
    return stem_body.rstrip() + "\n\n" + subs.strip()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 指纹
def write_fingerprints():
    rows = []
    for fn in list_stems():
        p = os.path.join(STEM_DIR, fn)
        raw = open(p, "rb").read()
        text = raw.decode("utf-8")
        sec = split_sections(text)
        sub, score = parse_meta(sec[1])
        qid = fn.split("_")[0]
        rows.append({
            "qid": qid,
            "file": fn,
            "sha256": sha256_bytes(raw),
            "n_sub": sub if sub is not None else "",
            "paper_score": score if score is not None else "",
            "stem_chars": len(load_stem(p)),
            "bom": "yes" if raw.startswith(b"\xef\xbb\xbf") else "no",
        })
    out = os.path.join(ROOT, "stems", "stem_fingerprints.csv")
    import csv
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "file", "sha256", "n_sub",
                                         "paper_score", "stem_chars", "bom"])
        w.writeheader()
        w.writerows(rows)
    print("[指纹] 写入 %s（%d 行）" % (out, len(rows)))
    return rows


def dump_stems():
    """把实际送进 prompt 的题干落盘，供人工核对 caption 未混入"""
    d = os.path.join(ROOT, "stems")
    os.makedirs(d, exist_ok=True)
    for fn in list_stems():
        qid = fn.split("_")[0]
        stem = load_stem(os.path.join(STEM_DIR, fn))
        with open(os.path.join(d, qid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(stem)
    print("[题干] 落盘 22 份 → %s" % d)


# ---------------------------------------------------------------- prompt
def load_template(variant):
    p = os.path.join(ROOT, "prompts", VARIANTS[variant])
    return open(p, encoding="utf-8").read()


def render_prompt(variant, stem):
    tpl = load_template(variant)
    if tpl.count("{题干}") != 1:
        raise SystemExit("模板 %s 的 {题干} 占位符数量异常：%d"
                         % (VARIANTS[variant], tpl.count("{题干}")))
    return tpl.replace("{题干}", stem)


def prompt_file_sha(variant):
    p = os.path.join(ROOT, "prompts", VARIANTS[variant])
    return sha256_bytes(open(p, "rb").read())


# ---------------------------------------------------------------- API
def resolve_model():
    """先试 deepseek-chat；404 再列 /models 取可用名。实际用名必须写进报告。"""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY 不存在")
    for name in MODEL_CANDIDATES:
        try:
            r = requests.get(API_BASE + "/models",
                             headers={"Authorization": "Bearer " + key}, timeout=30)
        except requests.RequestException as e:
            raise SystemExit("[致命] 连不上 %s：%s" % (API_BASE, e))
        if r.status_code == 200:
            ids = [m.get("id") for m in r.json().get("data", [])]
            if name in ids:
                return name, ids
        print("[模型] %s 不在可用列表，继续探测" % name)
    # 兜底：取列表里第一个 chat 模型
    ids = r.json().get("data", [])
    if ids:
        return ids[0]["id"], [m.get("id") for m in ids]
    raise SystemExit("无法解析可用模型：%s" % r.text[:300])


def call_once(model, prompt):
    key = os.environ["DEEPSEEK_API_KEY"]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    t0 = time.time()
    try:
        r = requests.post(API_BASE + "/chat/completions",
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"},
                          json=payload, timeout=600)
    except requests.RequestException as e:
        # SSL 断链 / 连接重置 / 超时：都当可重试，不能让整批崩溃
        elapsed = time.time() - t0
        return {"ok": False, "status": "exc", "elapsed_s": round(elapsed, 3),
                "error": "%s: %s" % (type(e).__name__, str(e)[:300])}
    elapsed = time.time() - t0
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "elapsed_s": round(elapsed, 3),
                "error": r.text[:2000]}
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return {
        "ok": True,
        "elapsed_s": round(elapsed, 3),
        "content": msg.get("content") or "",
        "reasoning_content": msg.get("reasoning_content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": data.get("usage") or {},
        "model_returned": data.get("model"),
        "response_id": data.get("id"),
        "raw_response": data,
    }


def run_one(qid, variant, stem, model, force=False):
    out_dir = os.path.join(ROOT, "raw", variant)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, qid + ".json")
    if os.path.exists(out_path) and not force:
        print("[跳过] %s/%s 已存在" % (variant, qid))
        return "skip"

    prompt = render_prompt(variant, stem)
    attempts = []
    result = None
    for i in range(1 + MAX_RETRIES):
        res = call_once(model, prompt)
        attempts.append({k: res.get(k) for k in
                         ("ok", "status", "elapsed_s", "error")})
        if res["ok"]:
            result = res
            break
        print("  [重试 %d/%d] %s %s" % (i + 1, MAX_RETRIES,
                                        res.get("status"), res.get("error", "")[:120]))
        time.sleep(min(2 * (3 ** i), 20))   # 网络类故障退避重试

    rec = {
        "qid": qid,
        "variant": variant,
        "prompt_file": VARIANTS[variant],
        "prompt_sha256": prompt_file_sha(variant),
        "prompt_chars": len(prompt),
        "stem_sha256": sha256_bytes(stem.encode("utf-8")),
        "model_requested": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "created_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "attempts": attempts,
    }

    if result is None:
        rec.update({"ok": False, "failure": "api_error",
                    "content": "", "usage": {}, "elapsed_s": None})
    else:
        rec.update({
            "ok": True,
            "content": result["content"],
            "reasoning_content": result["reasoning_content"],
            "finish_reason": result["finish_reason"],
            "usage": result["usage"],
            "model_returned": result["model_returned"],
            "response_id": result["response_id"],
            "elapsed_s": result["elapsed_s"],
        })

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    status = "OK" if rec["ok"] else "FAIL"
    print("[%s] %s/%s  %.1fs  finish=%s  tok=%s+%s"
          % (status, variant, qid, rec.get("elapsed_s") or 0,
             rec.get("finish_reason"),
             rec.get("usage", {}).get("prompt_tokens", "?"),
             rec.get("usage", {}).get("completion_tokens", "?")))

    # 402 余额不足是账户级故障：不能逐题重试把 66 次调用全烧掉
    if not rec["ok"] and any(a.get("status") == 402 for a in attempts):
        raise SystemExit("[致命] 402 Insufficient Balance —— 已停止整批。"
                         "本次记录见 %s" % out_path)
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=list(VARIANTS))
    ap.add_argument("--qid", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--init-only", action="store_true", help="只写指纹与题干，不调 API")
    ap.add_argument("--no-init", action="store_true", help="跳过指纹/题干落盘（并行跑时避免同写）")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="覆盖 MAX_TOKENS（仅用于单题补跑长推理题，默认 32768）")
    args = ap.parse_args()

    if args.max_tokens:
        global MAX_TOKENS
        MAX_TOKENS = args.max_tokens
        print("[覆盖] max_tokens = %d" % MAX_TOKENS)

    if not args.no_init:
        write_fingerprints()
        dump_stems()
    if args.init_only:
        return

    files = list_stems()
    if args.qid:
        files = [f for f in files if f.startswith(args.qid + "_")]
        if not files:
            raise SystemExit("找不到 qid %s" % args.qid)
    if args.limit:
        files = files[:args.limit]

    model, ids = resolve_model()
    print("[模型] 请求名=%s ｜ 可用=%s" % (model, ids))

    stats = {"OK": 0, "FAIL": 0, "skip": 0}
    for fn in files:
        qid = fn.split("_")[0]
        stem = load_stem(os.path.join(STEM_DIR, fn))
        st = run_one(qid, args.variant, stem, model, force=args.force)
        stats[st if st in stats else "OK"] += 1
    print("[汇总] %s → %s" % (args.variant, stats))


if __name__ == "__main__":
    main()

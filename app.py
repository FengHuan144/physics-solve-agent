#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""app.py — 物理解题服务：选一道题 → 解题 → 校验 → 判分 → 打开解析页。

    python app.py                  # 演示模式：不调 API，复用既有 20 题产物
    python app.py --live           # 额外打开实时开关（还需 DEEPSEEK_API_KEY，会花钱）
    python app.py --port 8765      # 换端口

设计边界（写清，防止误读）：
- **两类题，两条链路。**
  ① 题库内 20 题（demo / live）：`run_solve.solve()` 依赖 `schema/examples/{qid}.json`
     金标做字段转换，跑完有判分（采分点是人工写的）。
  ② 题库外新题（mode=zero，2026-11-26 T40）：题干由用户粘贴，走
     `评测/T20/run_zero.py` → `from_zero.build_from_zero()`，不需要金标；
     **只出解析与自洽检查，不判分**——新题没有人工采分点，模型自出的 point
     用于判自己等于自证。页面顶栏会写「未判分」。
- **演示模式与实时模式只差第 1 步。** 第 2/3 步（验证器、判分器）在所有模式下都是真跑，
  不读缓存——页面上「校验器与判分器为本次重跑」这句是字面意思。zero 模式没有第 3 步。
- **判分器的结论只到「这一步自洽不自洽 + 有没有命中采分点」**，不判「建模有没有用对
  题给条件」。所以页面顶部有强制横幅，`#banner` 里那三句不许删（zero 模式另有横幅）。
- **新题的校验覆盖率低是已知的**：符号白名单（`知识表/…`）与别名表只覆盖题库 20 题，
  新题符号大多不在表内，L1/L2 会大面积 na。页面会写「新题符号未登记，这一层没检」，
  不许把它显示成「检过且通过」。

产物目录：`临时/app/<job_id>/`（ans / validated / grade / result.html）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
PROTO = ROOT / "原型"
TEMPLATE = PROTO / "模型解析_20题.html"
ANS_DIR = ROOT / "评测" / "T20" / "out"
GRADE_DIR = ROOT / "判分器" / "out"
WORK = ROOT / "临时" / "app"
FIG_DIR = ROOT / "原始资料" / "题图"
TZ = timezone(timedelta(hours=8))

# 与判分器正式口径同序（20 题）
QIDS = ("A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-08", "A-09", "A-10",
        "B-01", "B-02", "B-04", "B-05", "B-07", "B-09", "B-10", "B-12", "B-16",
        "B-19", "B-20")

DATA_RE = re.compile(r'(<script id="DATA" type="application/json">)[\s\S]*?(</script>)')
EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".svg": "image/svg+xml"}
FIG_ALIAS = {"甲": "1", "乙": "2", "丙": "3", "丁": "4"}

STAGES = ("解题", "校验", "判分", "渲染")

sys.path.insert(0, str(PROTO))
T20 = ROOT / "评测" / "T20"
if str(T20) not in sys.path:
    sys.path.append(str(T20))                        # zero 模式复用 run_solve / from_zero
from _build import load_errors, load_laws            # noqa: E402
from _build_model import build_grading, build_display   # noqa: E402

_CACHE: dict = {}


def _errors():
    if "errors" not in _CACHE:
        _CACHE["errors"] = load_errors()
    return _CACHE["errors"]


def _laws():
    if "laws" not in _CACHE:
        _CACHE["laws"] = load_laws()
    return _CACHE["laws"]


def now(fmt="%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now(TZ).strftime(fmt)


# --------------------------------------------------------------------------- 题库

def library() -> list[dict]:
    """20 题的现状摘要。缺文件的题跳过（不编数）。"""
    rows = []
    for qid in QIDS:
        ap = ANS_DIR / f"{qid}_validated.json"
        gp = GRADE_DIR / f"{qid}.json"
        if not ap.exists() or not gp.exists():
            continue
        try:
            a = json.loads(ap.read_text(encoding="utf-8"))
            g = json.loads(gp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        m = a.get("meta") or {}
        s = g.get("summary") or {}
        rows.append({
            "qid": qid,
            "source": str(m.get("source") or ""),
            "no": m.get("question_no"),
            "steps": len(a.get("steps") or []),
            "hit": s.get("hit"), "miss": s.get("miss"), "na": s.get("na"),
            "total": s.get("total"),
            "score": s.get("score"), "score_total": s.get("score_total"),
            "mtime": datetime.fromtimestamp(ap.stat().st_mtime, TZ).strftime("%m-%d %H:%M"),
        })
    return rows


def inline_images(qid: str) -> dict:
    """题图转 data URI。图直接内联进结果页，页面因此可单文件带走。"""
    out: dict[str, str] = {}
    if not FIG_DIR.is_dir():
        return out
    for p in sorted(FIG_DIR.iterdir()):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        m = re.match(r"^([A-Z]-\d{2})_(?:图)?(\d+|[甲乙丙丁])$", p.stem)
        if not m or m.group(1) != qid:
            continue
        no = FIG_ALIAS.get(m.group(2), m.group(2))
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        out[no] = f"data:{EXTS[p.suffix.lower()]};base64,{b64}"
    return out


# --------------------------------------------------------------------------- 任务

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
Q: "queue.Queue[str]" = queue.Queue()
LIVE_ENABLED = False
VERBOSE = False


def log(job: dict, msg: str) -> None:
    line = {"t": now("%H:%M:%S"), "m": str(msg)[:2000]}
    with LOCK:
        job["logs"].append(line)
        if len(job["logs"]) > 400:
            del job["logs"][:-400]


def save_job(job: dict) -> None:
    """把任务元数据落到 ``临时/app/<id>/job.json``。

    只存状态，不存日志——重启后首页/结果页仍能打开，日志区留空。
    """
    jd = WORK / job["id"]
    try:
        jd.mkdir(parents=True, exist_ok=True)
        meta = {k: job.get(k) for k in
                ("id", "qid", "mode", "status", "stage", "stage_name", "created_at",
                 "started_at", "finished_at", "elapsed_s", "cost_cny", "summary",
                 "error", "result", "stem")}
        (jd / "job.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def jset(job: dict, **kw) -> None:
    with LOCK:
        job.update(kw)
    save_job(job)


def load_jobs() -> int:
    """启动时把历史任务的状态读回内存。返回恢复条数。"""
    n = 0
    for f in sorted(WORK.glob("*/job.json")):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            continue
        meta.setdefault("logs", [])
        meta.setdefault("stage", 0)
        meta.setdefault("stage_name", "")
        JOBS[meta["id"]] = meta
        n += 1
    return n


def sh(cmd: list, job: dict, timeout: int = 1200) -> str:
    """跑子进程，把输出尾部抄进 job 日志。非 0 退出即抛。"""
    cmd = [str(c) for c in cmd]
    log(job, "$ " + " ".join(cmd))
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("超时 %d s：%s" % (timeout, " ".join(cmd[1:3])))
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    for line in out.splitlines()[-30:]:
        log(job, "  " + line)
    for line in err.splitlines()[-12:]:
        log(job, "  [err] " + line)
    log(job, "  用时 %.1fs · 退出码 %d" % (time.time() - t0, p.returncode))
    if p.returncode != 0:
        raise RuntimeError("退出码 %d（%s）" % (p.returncode, " ".join(cmd[1:3])))
    return out


def render_result(job: dict) -> Path:
    """把 ans/validated/grade 三份产物拼成单题解析页。

    zero 模式（题库外新题）没有 grade、没有别名表：
    grading 置空、symbols 置空，图片从任务目录内联。
    """
    qid = job["qid"]
    jd = WORK / job["id"]
    doc = json.loads((jd / f"{qid}_validated.json").read_text(encoding="utf-8"))

    if job["mode"] == "zero":
        doc["grading"] = {}
        doc.setdefault("_display", {})
        zmeta_p = jd / "zero_meta.json"
        if zmeta_p.exists():
            try:
                zd = json.loads(zmeta_p.read_text(encoding="utf-8"))
                doc["_display"] = dict(zd.get("display") or {})
                doc["_display"]["issues"] = zd.get("issues") or []
            except (ValueError, OSError):
                pass
        # 每步给分点：模型在草稿里写了 score / point，但产物 schema 里没这两格。
        # 优先用 zero_meta.display.points（新跑的任务自带），老任务回落到草稿文件。
        if not doc["_display"].get("points"):
            draft_p = jd / f"{qid}_draft.json"
            if draft_p.exists():
                try:
                    dr = json.loads(draft_p.read_text(encoding="utf-8"))
                    raw_steps = sorted(dr.get("steps") or [],
                                       key=lambda s: int(s.get("no") or 0))
                    doc["_display"]["points"] = [
                        {"step_no": i, "score": s.get("score"),
                         "text": str(s.get("point") or "").strip()}
                        for i, s in enumerate(raw_steps, 1)]
                except (ValueError, OSError, TypeError):
                    pass
        sref = jd / f"{qid}_symbols.json"
        doc["symbols"] = (json.loads(sref.read_text(encoding="utf-8"))
                          if sref.exists() else {"steps": {}, "givens": []})
        doc["symbols"].setdefault("givens", [])
        imgs: dict[str, str] = {}
        for i, p in enumerate(sorted(jd.glob("fig*.*")), 1):
            ext = p.suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                continue
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/" + ext[1:])
            imgs[str(i)] = "data:%s;base64,%s" % (
                mime, base64.b64encode(p.read_bytes()).decode("ascii"))
        images = {qid: imgs}
    else:
        grade = json.loads((jd / f"{qid}_grade.json").read_text(encoding="utf-8"))
        doc["grading"] = build_grading(qid, grade, doc.get("steps") or [])
        doc["symbols"] = build_display(qid, doc, jd / f"{qid}.json")
        images = {qid: inline_images(qid)}

    payload = {
        "generated_at": now("%Y-%m-%dT%H:%M:%S"),
        "kind": "zero" if job["mode"] == "zero" else "model",
        "run": {
            "mode": job["mode"],
            "job_id": job["id"],
            "finished_at": job.get("finished_at") or now(),
            "elapsed_s": job.get("elapsed_s"),
            "cost_cny": job.get("cost_cny"),
        },
        "answers": {qid: doc},
        "error_codes": _errors(),
        "laws": _laws(),
        "images": images,
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    new, n = DATA_RE.subn(lambda m: m.group(1) + blob + m.group(2), html, count=1)
    if n != 1:
        raise RuntimeError("模板里没找到 DATA 占位块：%s" % TEMPLATE)
    out = jd / "result.html"
    out.write_text(new, encoding="utf-8")
    return out


def run_zero_job(job: dict, jd: Path, t0: float) -> None:
    """题库外新题：解题 → 转换 → 校验 → 渲染。不判分。"""
    import run_zero as RZ

    qid = job["qid"]
    figs = sorted(p for p in jd.glob("fig*.*")
                  if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))

    jset(job, stage=1, stage_name="解题")
    log(job, "[1/4] 题库外新题：调用 deepseek-flash 现场解题（实测 45–150 秒，约 0.1 元）")
    log(job, "      无金标、无采分点；题干 %d 字，图 %d 张" % (len(job["stem"]), len(figs)))

    meta = RZ.solve_zero(job["stem"], jd, figs, qid=qid,
                         log=lambda m: log(job, "      " + m))
    jset(job, cost_cny=meta.get("cost_cny"))

    jset(job, stage=2, stage_name="校验")
    sch = meta["schema"]
    log(job, "[2/4] Schema 校验：%s" % ("通过" if sch["rc"] == 0 else "有 E（见产物 zero_meta.json）"))
    for e in (sch.get("errors") or [])[:5]:
        log(job, "      " + e)
    layers = meta["validation"].get("layers") or {}
    log(job, "      验证器整题层：%s" % (layers or "未返回"))
    if layers and all(v == "na" for v in layers.values()):
        log(job, "      全部 na 属预期：符号白名单只覆盖题库 20 题，新题符号对不上表")

    jset(job, stage=3, stage_name="不判分")
    log(job, "[3/4] 跳过判分：新题没有人工采分点。模型自出的 point 用来判自己 = 自证，不做")

    jset(job, stage=4, stage_name="渲染",
         elapsed_s=round(time.time() - t0, 1), finished_at=now())
    log(job, "[4/4] 拼解析页")
    page = render_result(job)
    log(job, "      %s  %.0f KB" % (page.name, page.stat().st_size / 1024))

    jset(job, status="done", result=str(page.relative_to(ROOT).as_posix()),
         summary={"steps": meta.get("n_steps"), "hit": None, "miss": None, "na": None,
                  "total": None, "score": None, "score_total": None})
    log(job, "完成，总用时 %.1fs" % job["elapsed_s"])


def run_job(job: dict) -> None:
    t0 = time.time()
    qid = job["qid"]
    jd = WORK / job["id"]
    jd.mkdir(parents=True, exist_ok=True)
    jset(job, status="running", started_at=now())

    try:
        if job["mode"] == "zero":
            return run_zero_job(job, jd, t0)

        # ---- 1/4 解题 -------------------------------------------------------
        jset(job, stage=1, stage_name=STAGES[0])
        if job["mode"] == "live":
            tag = "_app" + job["id"].replace("-", "")[-8:]
            src = ANS_DIR / f"{qid}{tag}.json"
            if src.exists():
                src.unlink()
            log(job, "[1/4] 调用 deepseek-flash 现场解题（实测 1–2.5 分钟，约 0.1 元）")
            sh([sys.executable, "评测/T20/run_solve.py", "--qid", qid, "--tag", tag], job)
            if not src.exists():
                raise RuntimeError("解题未产出 %s" % src.name)
            shutil.copyfile(src, jd / f"{qid}.json")
            log(job, "  产物已拷入临时目录：%s.json" % qid)
            # run_solve 的汇总行带 token 与成本，摘出来
            for line in reversed(job["logs"]):
                m = re.search(r"≈([\d.]+) 元", line["m"])
                if m:
                    jset(job, cost_cny=float(m.group(1)))
                    break
        else:
            src = ANS_DIR / f"{qid}.json"
            if not src.exists():
                raise RuntimeError("缺既有产物 %s" % src)
            mt = datetime.fromtimestamp(src.stat().st_mtime, TZ).strftime("%Y-%m-%d %H:%M")
            shutil.copyfile(src, jd / f"{qid}.json")
            log(job, "[1/4] 复用既有模型产物（生成于 %s），本次未调用 API" % mt)
            log(job, "      %s  %.0f KB" % (src.name, src.stat().st_size / 1024))

        # ---- 2/4 校验 -------------------------------------------------------
        jset(job, stage=2, stage_name=STAGES[1])
        # 必须加 --alias，与判分器内部口径一致。
        # T37 曾记「加不加对 B-20 无差异」，那只对 B-20 成立：它没有 T(张力) 这类歧义符号。
        # 2026-11-26 在 A-09 上实测 5/16 步不同（T 被当周期 → L2 假红叉），
        # 20 题合计 160 个 L1/L2 状态变化。不加就会出现「页面打叉、判分器给分」。
        log(job, "[2/4] 跑验证器（L1 量纲/代回 + L2 结构，符号先归一）")
        out = sh([sys.executable, "-m", "验证器.cli", str(jd / f"{qid}.json"),
                  "--out", str(jd / f"{qid}_validated.json"), "--alias"], job)
        m = re.findall(r"整题层状态：(\{.*?\})", out)
        if m:
            log(job, "  整题层：" + m[-1])

        # ---- 3/4 判分 -------------------------------------------------------
        jset(job, stage=3, stage_name=STAGES[2])
        log(job, "[3/4] 跑判分器（采分点三态：hit / miss / na）")
        out = sh([sys.executable, "判分器/grader.py",
                  "--answer", str(jd / f"{qid}_validated.json"),
                  "--out", str(jd / f"{qid}_grade.json")], job)
        grade = json.loads((jd / f"{qid}_grade.json").read_text(encoding="utf-8"))
        s = grade.get("summary") or {}
        jset(job, summary={"hit": s.get("hit"), "miss": s.get("miss"), "na": s.get("na"),
                           "total": s.get("total"), "score": s.get("score"),
                           "score_total": s.get("score_total")})

        # ---- 4/4 渲染 -------------------------------------------------------
        # 先定格「完成时刻」再渲染：解析页里的耗时/时间戳才是最终值，不会差几秒。
        jset(job, stage=4, stage_name=STAGES[3],
             elapsed_s=round(time.time() - t0, 1), finished_at=now())
        log(job, "[4/4] 拼解析页")
        page = render_result(job)
        log(job, "  %s  %.0f KB" % (page.name, page.stat().st_size / 1024))

        jset(job, status="done", result=str(page.relative_to(ROOT).as_posix()))
        log(job, "完成，总用时 %.1fs" % job["elapsed_s"])

    except Exception as exc:                              # noqa: BLE001
        el = round(time.time() - t0, 1)
        jset(job, status="error", elapsed_s=el, finished_at=now(),
             error="%s: %s" % (type(exc).__name__, exc))
        log(job, "[失败] %s: %s" % (type(exc).__name__, exc))


def worker() -> None:
    while True:
        jid = Q.get()
        job = JOBS.get(jid)
        try:
            if job:
                run_job(job)
        except Exception as exc:                          # noqa: BLE001
            if job:
                jset(job, status="error", error=str(exc))
        finally:
            Q.task_done()


JID_RE = re.compile(r"^\d{4}-\d{6}-[0-9a-f]{4}$")


def get_job(jid: str) -> dict | None:
    """先查内存，再查磁盘。服务重启后历史任务仍可访问。"""
    if not JID_RE.match(jid or ""):
        return None
    job = JOBS.get(jid)
    if job:
        return job
    f = WORK / jid / "job.json"
    if not f.exists():
        return None
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    meta.setdefault("id", jid)
    meta.setdefault("logs", [])
    meta.setdefault("stage", 0)
    meta.setdefault("stage_name", "")
    with LOCK:
        JOBS[jid] = meta
    return meta


def new_job(qid: str, mode: str, defer: bool = False, **extra) -> dict:
    jid = datetime.now(TZ).strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    job = {"id": jid, "qid": qid, "mode": mode, "status": "queued",
           "stage": 0, "stage_name": "排队", "logs": [], "summary": None,
           "created_at": now(), "started_at": None, "finished_at": None,
           "elapsed_s": None, "cost_cny": None, "error": None, "result": None}
    job.update(extra)                                    # zero 模式带 stem
    with LOCK:
        JOBS[jid] = job
    log(job, "任务已入队：%s · %s · %s" % (qid, mode, jid))
    if not defer:                                        # zero 要先把题图落盘再入队
        Q.put(jid)
    return job


# --------------------------------------------------------------------------- 页面

BASE_CSS = """
:root{
  --paper:#fbfaf7; --side:#f4f1ea; --ink:#1c1c1a; --ink2:#4a4844; --ink3:#8b8680;
  --line:#e2ded5; --line2:#d0cbc0; --red:#a5322b; --accent:#2f5d8a;
  --hl:#fdf7ea; --hlb:#f0e6cf;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--paper); color:var(--ink);
  font-family:-apple-system,"PingFang SC","Microsoft YaHei","Hiragino Sans GB",sans-serif;
  font-size:14px; line-height:1.7; -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
a:hover{text-decoration:underline}
button{font-family:inherit;cursor:pointer}
.wrap{max-width:1080px; margin:0 auto; padding:0 22px 80px}
header{
  position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:12px;
  padding:11px 22px; background:rgba(251,250,247,.95);
  border-bottom:1px solid var(--line); backdrop-filter:blur(6px);
}
header h1{font-size:14.5px; margin:0; font-weight:600; letter-spacing:.02em}
header .sub{font-size:11.5px; color:var(--ink3)}
.spacer{flex:1}
.tag{font-size:11px; color:var(--ink3); border:1px solid var(--line2); padding:1px 7px; border-radius:3px}
.tag.on{color:#2c6b46; border-color:#bcd8c6; background:#eff7f1}
.tag.off{color:#8a5a10; border-color:var(--hlb); background:var(--hl)}
.note{
  margin:18px 0 8px; padding:10px 14px; font-size:12.5px; line-height:1.75;
  background:var(--hl); border:1px solid var(--hlb); border-radius:6px; color:#5d4a12;
}
.note b{font-weight:600; color:#3f3309}
.card{background:#fff; border:1px solid var(--line); border-radius:9px; overflow:hidden}
table{width:100%; border-collapse:collapse; table-layout:fixed}
th,td{padding:9px 12px; text-align:left; border-bottom:1px solid var(--line); font-size:13px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
th{font-size:11.5px; color:var(--ink3); font-weight:500; background:#faf9f6; letter-spacing:.04em}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:#fcfbf8}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px}
.num{font-variant-numeric:tabular-nums}
.dim{color:var(--ink3)}
.btn{
  border:1px solid var(--line2); background:#fff; border-radius:5px;
  padding:4px 12px; font-size:12.5px; color:var(--ink2);
}
.btn:hover{border-color:var(--ink3); color:var(--ink)}
.btn.primary{background:var(--red); border-color:var(--red); color:#fff}
.btn.primary:hover{background:#8f2a24}
.btn[disabled]{opacity:.45; cursor:not-allowed}
footer{margin-top:26px; font-size:11.5px; color:var(--ink3); line-height:1.95}
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>物理解题 · 本地服务</title>
<link rel="icon" href="data:,">
<style>__CSS__
.modes{display:flex; gap:8px; margin:14px 0 4px}
.mode{border:1px solid var(--line2); background:#fff; border-radius:7px; padding:9px 14px;
  font-size:12.5px; color:var(--ink2); cursor:pointer; min-width:210px; text-align:left}
.mode b{display:block; font-size:13px; color:var(--ink); font-weight:600; margin-bottom:1px}
.mode small{color:var(--ink3); font-size:11px}
.mode.sel{border-color:var(--red); box-shadow:inset 0 0 0 1px var(--red)}
.mode.sel b{color:var(--red)}
.jobs{margin-top:10px}
.jrow{display:flex; align-items:center; gap:10px; padding:8px 13px;
  border-bottom:1px solid var(--line); font-size:12.5px}
.jrow:last-child{border-bottom:0}
.st{font-size:11px; padding:1px 6px; border-radius:3px; border:1px solid var(--line2); color:var(--ink3)}
.st.done{color:#2c6b46; border-color:#bcd8c6; background:#eff7f1}
.st.error{color:var(--red); border-color:#e2bdb9; background:#fbf1f0}
.st.running{color:var(--accent); border-color:#c3d3e2; background:#f2f7fb}
</style></head><body>
<header>
  <h1>物理解题 · 本地服务</h1>
  <span class="sub">解题 → 校验 → 判分 → 解析页</span>
  <span class="spacer"></span>
  <span class="tag __LIVETAG__">__LIVETEXT__</span>
</header>
<div class="wrap">
  <div class="note">
    <b>这是讲题工具，不是自动批改。</b>L1/L2 只验「这一步自身是否自洽」（量纲、代回），
    <b>不判建模有没有用对题给条件</b>——所以页面里的「校验 pass」不等于「这一步对」。
    判分器给的是采分点三态（hit / miss / na），判不了的点记 <b>na</b>，不扣分也不给分。
  </div>

  <div class="modes">
    <button class="mode sel" data-mode="demo">
      <b>演示模式</b>
      <small>复用已有 20 题产物 · 不调 API · 几秒完成</small>
    </button>
    <button class="mode" data-mode="live" __LIVEDIS__>
      <b>实时模式</b>
      <small>现场调 deepseek-flash · 1–3 分钟 · 约 0.1 元/题</small>
    </button>
  </div>

  <div class="note" style="margin-top:14px; background:#f5f5f2; border-color:var(--line); color:var(--ink2)">
    <b style="color:var(--ink)">能力边界：</b>下方 20 道题走完整链路（解题 → 校验 → 判分 → 解析页）。
    题库外新题走下面的「贴一道新题」：能出解析与自洽检查，<b style="color:var(--ink)">不判分</b>——
    新题没有人工采分点，让模型拿自己写的采分点判自己，等于自证。
  </div>

  <details id="newq" style="margin:14px 0 6px; background:#fff; border:1px solid var(--line); border-radius:9px">
    <summary style="padding:12px 16px; cursor:pointer; font-size:13px">
      <b>贴一道新题</b>
      <span class="dim" style="font-weight:400">题库外 · 无金标 · 出解析不判分</span>
    </summary>
    <div style="padding:0 16px 16px">
      <textarea id="stem" placeholder="把题干和小问整段贴进来。小问后面请带分值，例如「（4 分）」——分值决定每步的分数怎么分。"
        style="width:100%; min-height:150px; padding:11px 13px; font-size:13px; line-height:1.75;
               border:1px solid var(--line2); border-radius:6px; font-family:inherit; resize:vertical;
               background:var(--paper); color:var(--ink)"></textarea>
      <div id="figbox" style="margin-top:10px; border:1px dashed var(--line2); border-radius:7px;
           padding:9px 12px; background:#f7f5ef">
        <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
          <button class="btn" id="pickfig" type="button" style="padding:5px 12px">选图</button>
          <input type="file" id="figs" accept="image/*" multiple style="display:none">
          <span class="dim" style="font-size:12px">
            截图直接 <b style="color:var(--ink)">Ctrl+V</b> 粘在这儿，或把图拖进来。最多 4 张，单张 ≤ 8 MB。
          </span>
          <span class="spacer"></span>
          <span class="dim" id="fignote" style="font-size:12px">未加图</span>
        </div>
        <div id="figsPrev" style="display:flex; gap:8px; margin-top:0; flex-wrap:wrap"></div>
      </div>
      <div style="display:flex; align-items:center; gap:12px; margin-top:10px; flex-wrap:wrap">
        <span class="spacer"></span>
        <button class="btn" id="go" type="button" style="padding:8px 20px; font-size:13px">开始解题</button>
      </div>
      <div class="dim" id="nqmsg" style="font-size:12px; margin-top:8px">
        约 1–3 分钟，约 0.1 元。产物和题库题目一样落在 临时/app/&lt;job_id&gt;/。
      </div>
    </div>
  </details>

  <h3 style="font-size:13px; margin:24px 0 8px; color:var(--ink2); font-weight:600">
    题库 <span class="dim" style="font-weight:400">共 __NQ__ 道</span></h3>
  <div class="card"><table>
    <thead><tr>
      <th style="width:80px">题号</th><th>来源</th>
      <th style="width:58px">步数</th><th style="width:212px">已有结果</th>
      <th style="width:118px">产物时间</th><th style="width:88px"></th>
    </tr></thead>
    <tbody>__ROWS__</tbody>
  </table></div>

  <h3 style="font-size:13px; margin:26px 0 8px; color:var(--ink2); font-weight:600">最近任务</h3>
  <div class="card jobs" id="jobs"><div class="jrow dim">还没有任务。点上面任意一行的「跑一遍」。</div></div>

  <footer>
    产物写在 <span class="mono">临时/app/&lt;job_id&gt;/</span>：ans / validated / grade / result.html 四件套。<br>
    演示模式只是跳过第 1 步的 API 调用；第 2、3 步（验证器、判分器）每次都是真跑。
  </footer>
</div>
<script>
var MODE = 'demo';
var LIVE = __LIVEJSON__;
document.querySelectorAll('.mode').forEach(function (b) {
  if (b.disabled) return;
  b.addEventListener('click', function () {
    document.querySelectorAll('.mode').forEach(function (x) { x.classList.remove('sel'); });
    b.classList.add('sel');
    MODE = b.getAttribute('data-mode');
  });
});
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
async function submit(qid, btn) {
  if (MODE === 'live' && !LIVE) { alert('实时模式未开启：服务启动时未加 --live'); return; }
  if (MODE === 'live' && !confirm('实时模式会真调用 deepseek-flash，约 1–3 分钟、约 0.1 元。继续？')) return;
  btn.disabled = true; btn.textContent = '提交中';
  try {
    var r = await fetch('/api/job', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({qid: qid, mode: MODE})});
    var d = await r.json();
    if (!r.ok) { alert(d.error || '提交失败'); btn.disabled = false; btn.textContent = '跑一遍'; return; }
    location.href = '/job/' + d.job_id;
  } catch (e) {
    alert('提交失败：' + e); btn.disabled = false; btn.textContent = '跑一遍';
  }
}
function readAsDataURL(f) {
  return new Promise(function (res, rej) {
    var r = new FileReader();
    r.onload = function () { res(r.result); };
    r.onerror = rej;
    r.readAsDataURL(f);
  });
}
/* ---- 题图：选图 / 拖入 / Ctrl+V 粘贴，统一进 FIGFILES ---- */
var FIGFILES = [];
function figNote() {
  var el = document.getElementById('fignote');
  if (!el) return;
  el.textContent = FIGFILES.length ? ('已加 ' + FIGFILES.length + ' 张') : '未加图';
  el.style.color = FIGFILES.length ? 'var(--ink)' : '';
}
function figRender() {
  var box = document.getElementById('figsPrev');
  if (!box) return;
  box.innerHTML = FIGFILES.map(function (f, i) {
    return '<span style="position:relative; display:inline-block; margin-top:8px; border:1px solid var(--line2);' +
      ' border-radius:5px; overflow:hidden; background:#fff; line-height:0">' +
      '<img src="' + f.data + '" alt="" style="height:62px; max-width:126px; object-fit:cover; display:block">' +
      '<button type="button" data-i="' + i + '" class="figx" title="移除" style="position:absolute; top:0; right:0;' +
      ' width:17px; height:17px; line-height:14px; font-size:12px; border:0; border-bottom-left-radius:5px;' +
      ' background:rgba(28,28,26,.6); color:#fff; cursor:pointer; padding:0">×</button></span>';
  }).join('');
  Array.prototype.forEach.call(box.querySelectorAll('.figx'), function (b) {
    b.addEventListener('click', function () {
      FIGFILES.splice(+b.getAttribute('data-i'), 1); figRender();
    });
  });
  figNote();
}
async function figAdd(list) {
  var msg = document.getElementById('nqmsg');
  for (var i = 0; i < list.length; i++) {
    if (FIGFILES.length >= 4) { if (msg) msg.textContent = '题图最多 4 张，多的已忽略。'; break; }
    var f = list[i];
    if (!f || !/^image[/]/.test(f.type || '')) continue;
    if (f.size > 8 * 1024 * 1024) { if (msg) msg.textContent = '有一张超过 8 MB，已跳过。'; continue; }
    FIGFILES.push({name: f.name || ('粘贴图-' + (FIGFILES.length + 1) + '.png'),
                   data: await readAsDataURL(f)});
  }
  figRender();
}
(function () {
  var input = document.getElementById('figs');
  var pick = document.getElementById('pickfig');
  var boxd = document.getElementById('figbox');
  if (pick && input) pick.addEventListener('click', function () { input.click(); });
  if (input) input.addEventListener('change', function () {
    figAdd(Array.prototype.slice.call(input.files || [])); input.value = '';
  });
  if (boxd) {
    var hot = function (on) {
      boxd.style.borderColor = on ? 'var(--ink3)' : 'var(--line2)';
      boxd.style.background = on ? '#f1eee6' : '#f7f5ef';
    };
    boxd.addEventListener('dragover', function (e) { e.preventDefault(); hot(true); });
    boxd.addEventListener('dragleave', function () { hot(false); });
    boxd.addEventListener('drop', function (e) {
      e.preventDefault(); hot(false);
      figAdd(Array.prototype.slice.call((e.dataTransfer && e.dataTransfer.files) || []));
    });
  }
  document.addEventListener('paste', function (e) {
    var nq = document.getElementById('newq');
    if (!nq) return;
    var items = (e.clipboardData && e.clipboardData.items) || [];
    var imgs = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file' && /^image[/]/.test(items[i].type)) {
        var f = items[i].getAsFile(); if (f) imgs.push(f);
      }
    }
    if (!imgs.length) return;
    // 只有图（截图）时吞掉默认行为；图+文字（Word 复制）时让文字照常进 textarea
    var txt = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
    if (!txt.trim()) e.preventDefault();
    if (!nq.open) nq.open = true;        // 面板收起时粘贴也能收进图，不静默失败
    figAdd(imgs).then(function () {
      var m = document.getElementById('nqmsg');
      if (m && !document.getElementById('stem').value.trim()) {
        m.textContent = '已从剪贴板加入 ' + FIGFILES.length + ' 张图。题干若也在截图里，请再补贴一遍文字。';
      }
    });
  });
})();
async function submitZero() {
  var stem = document.getElementById('stem').value.trim();
  var msg = document.getElementById('nqmsg');
  var btn = document.getElementById('go');
  if (stem.length < 20) { msg.textContent = '题干太短，至少 20 字。'; return; }
  if (!LIVE) { msg.textContent = '服务未开启实时模式：启动时加 --live（新题必须调模型）。'; return; }
  if (!confirm('会真调用 deepseek-flash，约 1–3 分钟、约 0.1 元。继续？')) return;

  var files = FIGFILES.slice(0, 4);
  btn.disabled = true; btn.textContent = '提交中…';
  msg.textContent = files.length ? ('正在上传题干和 ' + files.length + ' 张题图…') : '正在提交…';
  try {
    var figs = [];
    for (var i = 0; i < files.length; i++) {
      figs.push({name: files[i].name, data: files[i].data});
    }
    msg.textContent = '已提交，正在解题…';
    var r = await fetch('/api/zero', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({stem: stem, figures: figs})});
    var d = await r.json();
    if (!r.ok) throw new Error(d.error || '提交失败');
    location.href = '/job/' + d.job_id;
  } catch (e) {
    msg.textContent = '提交失败：' + (e.message || e);
    btn.disabled = false; btn.textContent = '开始解题';
  }
}
var goBtn = document.getElementById('go');
if (goBtn) goBtn.addEventListener('click', submitZero);
var NAMES = {queued:'排队', running:'运行中', done:'完成', error:'失败'};
var CST = {queued:'', running:'running', done:'done', error:'error'};
async function loadJobs() {
  try {
    var r = await fetch('/api/jobs');
    var d = await r.json();
    var box = document.getElementById('jobs');
    if (!d.jobs.length) return;
    box.innerHTML = d.jobs.map(function (j) {
      var sm = j.summary;
      var tail = (sm && sm.hit != null) ? (' · ' + sm.hit + ' hit / ' + sm.na + ' na') : '';
      if (sm && sm.hit == null && sm.steps) tail = ' · ' + sm.steps + ' 步';
      var el = j.elapsed_s != null ? (' · ' + j.elapsed_s + 's') : '';
      var modeTxt = j.mode === 'zero' ? '新题' : (j.mode === 'live' ? '实时' : '演示');
      return '<div class="jrow">' +
        '<span class="st ' + (CST[j.status] || '') + '">' + (NAMES[j.status] || j.status) + '</span>' +
        '<span class="mono">' + esc(j.qid) + '</span>' +
        '<span class="dim">' + esc(modeTxt) + '</span>' +
        '<span class="dim">' + esc(j.stage_name || '') + tail + el + '</span>' +
        '<span class="spacer" style="flex:1"></span>' +
        '<a href="/job/' + esc(j.id) + '">日志</a>' +
        (j.status === 'done' ? ' · <a href="/result/' + esc(j.id) + '">解析页</a>' : '') +
        '</div>';
    }).join('');
  } catch (e) {}
}
loadJobs();
setInterval(function () { if (!document.hidden) loadJobs(); }, 4000);
</script>
</body></html>"""

JOB_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__JID__ · 运行</title>
<link rel="icon" href="data:,">
<style>__CSS__
.stages{display:flex; gap:0; margin:22px 0 6px}
.stg{flex:1; border-top:3px solid var(--line2); padding:9px 0 0; font-size:12px; color:var(--ink3); position:relative}
.stg b{display:block; font-weight:500; color:var(--ink3); margin-bottom:1px}
.stg.active{border-top-color:var(--red)}
.stg.active b{color:var(--red)}
.stg.done{border-top-color:#2c6b46}
.stg.done b{color:#2c6b46}
.logs{margin-top:18px; background:#1e1e1c; color:#d8d4cc; border-radius:8px;
  padding:14px 16px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:11.5px; line-height:1.75; max-height:52vh; overflow:auto; white-space:pre-wrap}
.logs .t{color:#7d7870; margin-right:8px}
.logs .e{color:#e8a09a}
.hd{display:flex; align-items:baseline; gap:12px; margin-top:26px}
.hd h2{font-size:17px; margin:0; font-weight:600}
.big{display:inline-block; margin-top:22px; padding:9px 22px; border-radius:6px;
  background:var(--red); color:#fff; font-size:13.5px}
.big:hover{background:#8f2a24; text-decoration:none}
.errbox{margin-top:16px; padding:10px 14px; border-radius:6px; background:#fbf1f0;
  border:1px solid #e2bdb9; color:var(--red); font-size:12.5px}
</style></head><body>
<header>
  <h1>__QID__ · 运行</h1>
  <span class="sub mono">__JID__</span>
  <span class="spacer"></span>
  <a href="/" style="font-size:12.5px">← 回题库</a>
</header>
<div class="wrap">
  <div class="hd">
    <h2 id="stname">排队中</h2>
    <span class="tag" id="sttag">queued</span>
  </div>
  <div class="stages" id="stages">
    <div class="stg"><b>1 解题</b><span id="s1">—</span></div>
    <div class="stg"><b>2 校验</b><span id="s2">—</span></div>
    <div class="stg"><b>3 判分</b><span id="s3">—</span></div>
    <div class="stg"><b>4 渲染</b><span id="s4">—</span></div>
  </div>
  <div id="body"></div>
  <div class="logs" id="logs">等待中…</div>
</div>
<script>
var JID = '__JID__';
var MODE = '__MODE__';
var NAMES = {queued:'排队中', running:'运行中', done:'完成', error:'失败'};
var STAGE_NOTE = ['复用既有产物', 'L1 量纲/代回 + L2 结构', '采分点三态', '拼单题解析页'];
if (MODE === 'live') STAGE_NOTE[0] = 'deepseek-flash 现场调用';
if (MODE === 'zero') STAGE_NOTE = ['deepseek-flash 现场解题', 'Schema + 验证器', '新题无采分点，跳过', '拼单题解析页'];
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function render(j) {
  document.getElementById('stname').textContent = NAMES[j.status] || j.status;
  document.getElementById('sttag').textContent = j.status + (j.elapsed_s != null ? ' · ' + j.elapsed_s + 's' : '');
  var finishedAll = j.status === 'done';
  for (var i = 1; i <= 4; i++) {
    var el = document.getElementById('s' + i);
    var box = el.parentNode;
    var done = finishedAll ? (i <= j.stage) : (i < j.stage);
    var live = !finishedAll && j.status === 'running' && i === j.stage;
    box.className = 'stg' + (done ? ' done' : (live ? ' active' : ''));
    el.textContent = done ? '完成' : (live ? '进行中…' : STAGE_NOTE[i-1]);
  }
  var logs = document.getElementById('logs');
  var atBottom = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 40;
  logs.innerHTML = j.logs.map(function (l) {
    var e = /失败|err|Traceback|退出码 [1-9]/.test(l.m) ? ' class="e"' : '';
    return '<div><span class="t">' + esc(l.t) + '</span><span' + e + '>' + esc(l.m) + '</span></div>';
  }).join('') || '等待中…';
  if (atBottom) logs.scrollTop = logs.scrollHeight;

  var body = document.getElementById('body');
  if (j.status === 'done') {
    var sm = j.summary || {};
    body.innerHTML = '<div style="margin-top:14px; font-size:13px; color:var(--ink2)">' +
      '能判 <b>' + (sm.total - sm.na) + '</b>/' + sm.total + ' 个采分点' +
      '（命中 ' + sm.hit + '、判错 ' + sm.miss + '、判不了 ' + sm.na + '）' +
      '<br><span style="color:var(--ink3)">得分 ' + sm.score + '/' + sm.score_total +
      '，只按能判的点计；判不了的不算错</span></div>' +
      '<a class="big" href="/result/' + esc(j.id) + '">打开解析页 →</a>';
  } else if (j.status === 'error') {
    body.innerHTML = '<div class="errbox">' + esc(j.error || '未知错误') + '</div>' +
      '<div style="margin-top:14px"><a class="btn" href="/">回题库重试</a></div>';
  }
}
async function tick() {
  try {
    var r = await fetch('/api/job/' + JID);
    var j = await r.json();
    if (!r.ok) { document.getElementById('logs').textContent = j.error || '任务不存在'; return; }
    render(j);
    if (j.status === 'done' || j.status === 'error') return;
  } catch (e) {}
  setTimeout(tick, 700);
}
tick();
</script>
</body></html>"""


def index_html() -> str:
    rows = library()
    trs = []
    for r in rows:
        if r["hit"] is None or not r["total"]:
            sm, sc = "—", ""
        else:
            sm = "判 %s/%s 点" % (r["total"] - (r["na"] or 0), r["total"])
            sc = "%s/%s 分" % (r["score"], r["score_total"])
        trs.append(
            '<tr>'
            '<td class="mono"><b>%s</b></td>'
            '<td>%s%s</td>'
            '<td class="num dim">%s</td>'
            '<td class="num">%s<span class="dim"> · %s</span></td>'
            '<td class="num dim">%s</td>'
            '<td><button class="btn" onclick="submit(\'%s\', this)">跑一遍</button></td>'
            '</tr>' % (
                r["qid"],
                r["source"] or "—",
                (" 第 %s 题" % r["no"]) if r["no"] is not None else "",
                r["steps"], sm, sc, r["mtime"], r["qid"]))
    live_tag = "on" if LIVE_ENABLED else "off"
    live_text = "实时可用" if LIVE_ENABLED else "实时未开"
    live_dis = "" if LIVE_ENABLED else "disabled"
    return (INDEX_HTML
            .replace("__CSS__", BASE_CSS)
            .replace("__LIVETAG__", live_tag)
            .replace("__LIVETEXT__", live_text)
            .replace("__LIVEDIS__", live_dis)
            .replace("__LIVEJSON__", "true" if LIVE_ENABLED else "false")
            .replace("__NQ__", str(len(rows)))
            .replace("__ROWS__", "\n".join(trs)))


def job_html(job: dict) -> str:
    return (JOB_HTML
            .replace("__CSS__", BASE_CSS)
            .replace("__JID__", job["id"])
            .replace("__QID__", job["qid"])
            .replace("__MODE__", job["mode"]))


def job_public(job: dict) -> dict:
    with LOCK:
        return {
            "id": job["id"], "qid": job["qid"], "mode": job["mode"],
            "status": job.get("status"), "stage": job.get("stage"),
            "stage_name": job.get("stage_name", ""),
            "logs": list(job.get("logs") or []), "summary": job.get("summary"),
            "created_at": job.get("created_at"), "finished_at": job.get("finished_at"),
            "elapsed_s": job.get("elapsed_s"), "cost_cny": job.get("cost_cny"),
            "error": job.get("error"), "result": job.get("result"),
        }


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "wuli-app/0.1"

    def log_message(self, fmt, *args):                    # noqa: A003
        if VERBOSE:
            super().log_message(fmt, *args)

    # ---- 工具
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _html(self, text: str, code: int = 200):
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400):
        self._json({"error": msg}, code)

    # ---- GET
    def do_GET(self):                                     # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._html(index_html())

        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")

        if path == "/health":
            return self._json({"ok": True, "live": LIVE_ENABLED, "jobs": len(JOBS)})

        if path == "/api/library":
            return self._json({"rows": library(), "live": LIVE_ENABLED,
                               "has_key": bool(os.environ.get("DEEPSEEK_API_KEY"))})

        if path == "/api/jobs":
            with LOCK:
                items = sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)[:12]
            return self._json({"jobs": [job_public(j) for j in items]})

        if path.startswith("/api/job/"):
            jid = path[len("/api/job/"):]
            job = get_job(jid)
            if not job:
                return self._err("任务不存在：%s" % jid, 404)
            return self._json(job_public(job))

        if path.startswith("/job/"):
            jid = path[len("/job/"):]
            job = get_job(jid)
            if not job:
                return self._html("<h1 style='font-family:sans-serif'>任务不存在：%s</h1>"
                                  "<p><a href='/'>回题库</a></p>" % jid, 404)
            return self._html(job_html(job))

        if path.startswith("/result/"):
            jid = path[len("/result/"):]
            page = WORK / jid / "result.html" if JID_RE.match(jid) else None
            if page and page.exists():
                return self._html(page.read_text(encoding="utf-8"))
            job = get_job(jid)
            if not job:
                return self._html("<h1 style='font-family:sans-serif'>任务不存在：%s</h1>"
                                  "<p><a href='/'>回题库</a></p>" % jid, 404)
            if job.get("status") != "done":
                self.send_response(302)
                self.send_header("Location", "/job/" + jid)
                self.end_headers()
                return
            return self._err("结果页丢失：%s" % jid, 500)

        return self._html("<h1 style='font-family:sans-serif'>404</h1><p><a href='/'>回首页</a></p>", 404)

    # ---- POST
    def _post_zero(self):                                 # noqa: N802
        if not LIVE_ENABLED:
            return self._err("服务未开启实时模式：启动时加 --live（新题必须调模型）")
        if not os.environ.get("DEEPSEEK_API_KEY"):
            return self._err("缺少 DEEPSEEK_API_KEY")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._err("请求体不是合法 JSON")

        stem = str(body.get("stem") or "").strip()
        if len(stem) < 20:
            return self._err("题干太短（%d 字），至少 20 字" % len(stem))
        if len(stem) > 6000:
            return self._err("题干太长（%d 字），上限 6000 字" % len(stem))

        figs = body.get("figures") or []
        if not isinstance(figs, list):
            return self._err("figures 必须是数组")
        if len(figs) > 4:
            return self._err("题图最多 4 张")

        used = sum(1 for j in JOBS.values() if j.get("mode") == "zero")
        qid = "Z-%02d" % (used % 99 + 1)
        # defer：先把图写进任务目录再入队，否则 worker 可能在图落盘前就开始跑
        job = new_job(qid, "zero", defer=True, stem=stem)
        jd = WORK / job["id"]
        jd.mkdir(parents=True, exist_ok=True)

        saved = 0
        for i, f in enumerate(figs, 1):
            m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$",
                         str(f.get("data") or ""), re.S)
            if not m:
                continue
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except (ValueError, TypeError):
                continue
            if len(raw) > 8 * 1024 * 1024:
                return self._err("第 %d 张图超过 8 MB" % i)
            ext = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp"}[m.group(1)]
            (jd / ("fig%d.%s" % (i, ext))).write_bytes(raw)
            saved += 1

        log(job, "新题已入队：题干 %d 字%s" % (len(stem), "，题图 %d 张" % saved if saved else "，无图"))
        Q.put(job["id"])
        return self._json({"job_id": job["id"], "qid": qid, "figures": saved}, 202)

    def do_POST(self):                                    # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/zero":
            return self._post_zero()
        if path != "/api/job":
            return self._err("不支持的接口：%s" % path, 404)

        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._err("请求体不是合法 JSON")

        qid = str(body.get("qid") or "")
        mode = str(body.get("mode") or "demo")
        if qid not in QIDS:
            return self._err("题号不在题库内：%s" % qid)
        if mode not in ("demo", "live"):
            return self._err("mode 只能是 demo / live")
        if mode == "live":
            if not LIVE_ENABLED:
                return self._err("服务未开启实时模式：启动时加 --live")
            if not os.environ.get("DEEPSEEK_API_KEY"):
                return self._err("缺少 DEEPSEEK_API_KEY")

        job = new_job(qid, mode)
        return self._json({"job_id": job["id"]}, 202)


def main() -> int:
    global LIVE_ENABLED, VERBOSE
    ap = argparse.ArgumentParser(description="物理解题本地服务")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--live", action="store_true", help="打开实时调用开关（会花钱）")
    ap.add_argument("--verbose", action="store_true", help="打印每条 HTTP 请求")
    args = ap.parse_args()

    LIVE_ENABLED = args.live
    VERBOSE = args.verbose

    if not TEMPLATE.exists():
        raise SystemExit("缺模板：%s" % TEMPLATE)
    WORK.mkdir(parents=True, exist_ok=True)

    rows = library()
    print("题库 %d 道 · 产物目录 %s" % (len(rows), WORK.relative_to(ROOT)))
    print("模式：%s" % ("演示 + 实时（--live 已开，会花钱）" if LIVE_ENABLED else "仅演示（不调 API）"))
    if LIVE_ENABLED and not os.environ.get("DEEPSEEK_API_KEY"):
        print("[警告] --live 已开但 DEEPSEEK_API_KEY 不存在，实时任务会被拒绝")

    n_old = load_jobs()
    if n_old:
        print("恢复历史任务 %d 条（状态在，日志不存）" % n_old)

    threading.Thread(target=worker, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("打开 http://%s:%d" % (args.host, args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

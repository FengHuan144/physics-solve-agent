# -*- coding: utf-8 -*-
"""题库外新题的验收脚本（对着实跑，不靠目测）。

    python 原型/_selftest_新题.py                       # 用最后一个 zero 任务的结果页
    python 原型/_selftest_新题.py --job 1126-175102-0b15
    python 原型/_selftest_新题.py --base http://127.0.0.1:8791   # 顺带验接口参数校验

验什么：
1. 首页有「贴一道新题」面板，textarea / 文件框 / 按钮都在
2. POST /api/zero 的入参校验（空题干、太短、图太多）——不触发真实解题，不花钱
3. 结果页：顶栏写「未判分」而不是 0 分；无 null/undefined/NaN/data_error/raw
4. 结果页：页脚说明「本题不判分」；校验记录说人话；无 JS 报错
5. 小问分值与题干标注一致（4/4/4 之类，从 doc 里读，不写死）

不会调用模型：只验收已经落盘的任务页与接口的拒绝分支。
"""
import argparse
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = ROOT / "临时" / "app"
SHOTS = HERE / "_shots"
SHOTS.mkdir(exist_ok=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺 playwright：pip install playwright && playwright install chromium")

results = []


def chk(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  ← " + str(extra)) if extra and not ok else ""))


def pick_job(explicit=None) -> tuple[str, pathlib.Path]:
    if explicit:
        d = WORK / explicit
        if not (d / "result.html").exists():
            sys.exit("指定任务没有 result.html：%s" % d)
        return explicit, d
    cands = []
    for d in WORK.iterdir():
        if not d.is_dir() or not (d / "result.html").exists():
            continue
        jp = d / "job.json"
        if not jp.exists():
            continue
        try:
            j = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if j.get("mode") == "zero" and j.get("status") == "done":
            cands.append(((d / "result.html").stat().st_mtime, d.name))
    if not cands:
        sys.exit("没有已完成的 zero 任务。先在首页贴一道新题跑一遍。")
    return max(cands)[1], WORK / max(cands)[1]


def api(base: str, path: str, body=None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"content-type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except (ValueError, json.JSONDecodeError):
            return e.code, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default=None)
    ap.add_argument("--base", default=None, help="服务地址；给了才验接口")
    args = ap.parse_args()

    jid, jd = pick_job(args.job)
    vp = next(iter(sorted(jd.glob("*_validated.json"))), None)   # 任务目录里 qid 不固定
    if vp is None:
        sys.exit("任务目录里没有 *_validated.json：%s" % jd)
    doc = json.loads(vp.read_text(encoding="utf-8"))
    subs = doc["question"]["subquestions"]
    print("任务 %s · %d 步 · 小问 %s" % (jid, len(doc["steps"]),
                                    "/".join(str(q.get("score")) for q in subs)))

    # ---------- 接口拒绝分支（不触发解题） ----------
    if args.base:
        code, d = api(args.base, "/api/zero", {"stem": "", "figures": []})
        chk("接口拒绝空题干", code == 400, "%s %s" % (code, d.get("error")))
        code, d = api(args.base, "/api/zero", {"stem": "太短", "figures": []})
        chk("接口拒绝过短题干", code == 400, "%s %s" % (code, d.get("error")))
        code, d = api(args.base, "/api/zero",
                      {"stem": "x" * 40, "figures": [{}] * 5})
        chk("接口拒绝 5 张图", code == 400, "%s %s" % (code, d.get("error")))

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1.5)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))

        # ---------- 首页面板 ----------
        if args.base:
            pg.goto(args.base + "/", wait_until="load")
            pg.wait_for_timeout(300)
            chk("首页有「贴一道新题」", "贴一道新题" in pg.inner_text("body"))
            chk("有题干输入框", pg.query_selector("#stem") is not None)
            chk("有题图上传框", pg.query_selector("#figs") is not None)
            chk("有开始按钮", pg.query_selector("#go") is not None)
            n_before = len(errs)

        # ---------- 结果页 ----------
        pg.goto((jd / "result.html").resolve().as_uri(), wait_until="load")
        pg.wait_for_timeout(400)
        body = pg.inner_text("body")

        score = pg.inner_text("#score")
        chk("顶栏写「未判分」", "未判分" in score, score[:60])
        chk("顶栏不出现 0/N 分", not re.search(r"\b0/\d+\s*分", score), score[:60])
        chk("模式标为题库外新题", "题库外新题" in pg.inner_text("#mode"))

        bad = {k: body.count(k) for k in ("null", "undefined", "NaN", "data_error", "raw:")}
        chk("无内部占位串", sum(bad.values()) == 0, bad)

        n_steps = len(pg.query_selector_all("#steps .step"))
        chk("步骤非空", n_steps == len(doc["steps"]) and n_steps > 0,
            "%d / doc %d" % (n_steps, len(doc["steps"])))

        chk("页脚写明不判分", "本题不判分" in pg.inner_text("#foot"))
        chk("页脚卷面分来自小问", "题干小问标注合计" in pg.inner_text("#foot"))

        # 校验记录必须是「没检」，不能是「检过且通过」
        chkrec = pg.inner_text("#steps")
        chk("校验记录说人话", "登记表" in chkrec or "没检" in chkrec,
            [x[:40] for x in chkrec.split("\n") if "校验" in x][:2])
        chk("无「校验 L1✓ L2✓」误报全过",
            not (doc["validation"]["layers"].get("L1") == "na" and "L1✓" in chkrec
                 and all(c.get("status") == "na"
                         for s in doc["steps"] for c in (s.get("checks") or []))))

        # 小问分值
        sub_txt = pg.inner_text("#subqs")
        for q in subs:
            chk("小问 %s 分值 %s 分显示" % (q["no"], q.get("score")),
                ("%g 分" % (q["score"] or 0)) in sub_txt, sub_txt[:80])

        chk("无新增 JS 报错", not errs, errs[:2])
        pg.screenshot(path=str(SHOTS / "zero_result.png"))
        b.close()

    ok = sum(1 for _, o, _ in results if o)
    print("-" * 60)
    print("结论：%d/%d 通过" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

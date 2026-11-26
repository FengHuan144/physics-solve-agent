# -*- coding: utf-8 -*-
"""题库外新题的验收脚本（对着实跑，不靠目测）。

    python 原型/_selftest_新题.py                       # 用最后一个 zero 任务的结果页
    python 原型/_selftest_新题.py --job 1126-175102-0b15
    python 原型/_selftest_新题.py --base http://127.0.0.1:8791   # 顺带验接口参数校验

验什么：
1. 首页有「贴一道新题」面板，textarea / 文件框 / 按钮都在
2. POST /api/zero 的入参校验（空题干、太短、图太多）——不触发真实解题，不花钱
3. 客户视图（默认）：只有「题目 + 思路 + 分步 + 每步给分点」；内部账（校验标记、
   采分点明细、任务号、耗时成本）一律不出现；顶栏写步数与卷面分，不写 0/N
4. 每步给分点数量与步数一致，分值合计等于卷面分
5. 技术视图（?tech=1）：内部账复原，校验记录必须是「没检」不能是「通过」
6. 小问分值与题干标注一致（从产物读，不写死）

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

        # ---------- 结果页：客户视图（默认） ----------
        pg.goto((jd / "result.html").resolve().as_uri(), wait_until="load")
        pg.wait_for_timeout(400)
        body = pg.inner_text("body")

        score = pg.inner_text("#score")
        chk("顶栏写步数", re.search(r"\d+\s*步", score) is not None, score[:60])
        chk("顶栏不出现 0/N 分", not re.search(r"\b0/\d+\s*分", score), score[:60])
        chk("客户视图不露内部题号与模式",
            pg.inner_text("#qtitle").strip() == "题目解析"
            and not pg.inner_text("#mode").strip(),
            pg.inner_text("#qtitle") + " | " + pg.inner_text("#mode"))

        bad = {k: body.count(k) for k in ("null", "undefined", "NaN", "data_error", "raw:")}
        chk("无内部占位串", sum(bad.values()) == 0, bad)
        noise = [k for k in ("本次运行", "总耗时", "采分点明细", "校验 L1", "任务 1", "未判分")
                 if k in body]
        chk("客户视图不出现内部账", not noise, noise)

        n_steps = len(pg.query_selector_all("#steps .step"))
        chk("步骤非空", n_steps == len(doc["steps"]) and n_steps > 0,
            "%d / doc %d" % (n_steps, len(doc["steps"])))

        # 每步给分点：数量与步数一致，分值合计等于卷面分（两者都从产物读，不写死）
        n_pt = len(pg.query_selector_all("#steps .ptline"))
        chk("每步都有给分点", n_pt == n_steps, "%d / %d 步" % (n_pt, n_steps))
        zm_p = jd / "zero_meta.json"
        zm = json.loads(zm_p.read_text(encoding="utf-8")) if zm_p.exists() else {}
        pts = (zm.get("display") or {}).get("points") or []
        if not pts:
            dp = next(iter(jd.glob("*_draft.json")), None)
            if dp:
                dr = json.loads(dp.read_text(encoding="utf-8"))
                pts = [{"score": s.get("score")} for s in dr.get("steps") or []]
        pt_sum = sum(float(s.get("score") or 0) for s in pts)
        full = doc["meta"].get("full_score")
        chk("给分点分值合计等于卷面分",
            full is None or abs(pt_sum - float(full)) < 1e-6, "%s / %s" % (pt_sum, full))

        foot = pg.inner_text("#foot")
        chk("页脚写明参考性质", "不是官方评分标准" in foot and "仅供参考" in foot, foot[:80])
        chk("页脚卷面分说明来源",
            full is None or ("卷面总分" in foot and "分值合计" in foot), foot[:80])

        # 客户视图不摊校验记录；技术视图才看得到，而且必须是「没检」不是「通过」
        chk("客户视图不摊校验记录",
            len([e for e in pg.query_selector_all("#steps .chkrec")
                 if e.evaluate("e => e.offsetParent !== null")]) == 0)

        pg.goto((jd / "result.html").resolve().as_uri() + "?tech=1", wait_until="load")
        pg.wait_for_timeout(400)
        tech_body = pg.inner_text("body")
        chk("技术视图露内部账", "本次运行" in tech_body and "校验 L1" in tech_body)
        chk("校验记录说人话", "登记表" in pg.inner_text("#steps") or "没检" in tech_body,
            pg.inner_text("#steps")[:60])
        chk("无「校验 L1✓ L2✓」误报全过",
            not (doc["validation"]["layers"].get("L1") == "na" and "L1✓" in tech_body
                 and all(c.get("status") == "na"
                         for s in doc["steps"] for c in (s.get("checks") or []))))

        pg.goto((jd / "result.html").resolve().as_uri(), wait_until="load")
        pg.wait_for_timeout(300)

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

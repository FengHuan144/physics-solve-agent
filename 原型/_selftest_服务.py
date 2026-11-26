# -*- coding: utf-8 -*-
"""app.py 的端到端验收：对着真跑的服务点一遍，不靠目测。

    python app.py --port 8791          # 另一个窗口先起服务
    python 原型/_selftest_服务.py --base http://127.0.0.1:8791

走完整路径：首页 → 点「跑一遍」→ 进度页 → 解析页，检查 12 项。
截图存 原型/_shots/svc_*.png。
"""
import argparse
import json
import pathlib
import re
import sys
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺 playwright：pip install playwright && playwright install chromium")

HERE = pathlib.Path(__file__).resolve().parent
SHOTS = HERE / "_shots"
SHOTS.mkdir(exist_ok=True)
results = []
QID = "B-20"          # 有图题，能顺带验图片内联


def chk(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  ← " + str(extra)) if extra and not ok else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8791")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        pg.on("console", lambda m: errors.append("console: %s" % m.text) if m.type == "error" else None)

        # ---------- 首页 ----------
        pg.goto(base + "/", wait_until="load")
        pg.wait_for_timeout(400)
        n_rows = pg.eval_on_selector_all("tbody tr", "els => els.length")
        chk("首页题库 20 行", n_rows == 20, n_rows)
        chk("首页横幅在", pg.locator(".note").first.is_visible())
        pg.screenshot(path=str(SHOTS / "svc_index.png"), full_page=True)

        # ---------- 点跑一遍 ----------
        t0 = time.time()
        pg.locator("tbody tr", has_text=QID).locator("button").click()
        pg.wait_for_url("**/job/**", timeout=15000)
        jid = re.search(r"/job/([^/?#]+)", pg.url).group(1)
        chk("提交后跳到进度页", bool(jid), pg.url)

        pg.wait_for_selector("a.big", timeout=180000)
        elapsed = round(time.time() - t0, 1)
        chk("任务完成并出现入口（%.0fs）" % elapsed, pg.locator("a.big").is_visible())
        body = pg.inner_text("#body")
        chk("进度页写明能判几个点",
            ("个采分点" in body and "判不了" in body), body[:150])
        pg.screenshot(path=str(SHOTS / "svc_job.png"), full_page=True)

        # ---------- 解析页 ----------
        pg.locator("a.big").click()
        pg.wait_for_url("**/result/**", timeout=30000)
        pg.wait_for_timeout(500)
        chk("解析页 URL 正确", jid in pg.url, pg.url)
        chk("解析页无 JS 报错", not errors, errors[:2])

        runbar = pg.inner_text("#runbar")
        chk("runbar 标明演示模式", "演示模式" in runbar, runbar[:120])
        chk("runbar 标明未调 API", "未调用 API" in runbar, runbar[:120])
        chk("runbar 含耗时", re.search(r"耗时 [\d.]+ s", runbar) is not None, runbar[:120])
        chk("runbar 含任务号", jid in runbar, runbar[:120])

        score = pg.inner_text("#score").replace("\n", " ")
        # 改版后顶栏是「判了 6/9 点 | 9/14 分」；判不了全判不了时是「N 个采分点全部判不了」
        ok_cov = re.search(r"判了 \d+/\d+ 点", score) or re.search(r"\d+ 个采分点全部判不了", score)
        chk("顶栏写明判分覆盖", ok_cov is not None and "分" in score, score)
        # 采分点明细：每条都要有状态与原因
        nrow = pg.eval_on_selector_all("#pt-body .pt-row", "e => e.length")
        nwhy = pg.eval_on_selector_all("#pt-body .pt-why", "e => e.filter(x => x.textContent.trim().length > 6).length")
        chk("采分点明细逐条有原因", nrow > 0 and nwhy == nrow, (nrow, nwhy))

        n_img = pg.eval_on_selector_all("#figures img", "els => els.length")
        loaded = pg.eval_on_selector_all("#figures img", "els => els.filter(e => e.naturalWidth > 0).length")
        chk("题图 2 张全部加载", n_img == 2 and loaded == 2, "%d 张 / 加载 %d" % (n_img, loaded))

        n_steps = pg.eval_on_selector_all("#steps .step", "els => els.length")
        chk("步骤非空", n_steps > 0, n_steps)
        t02 = pg.inner_text("#s-B-20-S02")
        chk("解析页公式用题面符号（N 而不是 Nf）",
            ("Nf" not in t02) and ("N + mg" in t02), t02[:60])
        chk("无「图缺」灰框", pg.eval_on_selector_all("#figures .fig-missing", "els => els.length") == 0)
        pg.screenshot(path=str(SHOTS / "svc_result.png"), full_page=True)
        pg.evaluate("window.scrollTo(0, 0)")
        pg.wait_for_timeout(150)
        pg.screenshot(path=str(SHOTS / "svc_result_top.png"),
                      clip={"x": 0, "y": 0, "width": 1440, "height": 820})

        # ---------- 与服务端产物对账 ----------
        time.sleep(0.2)
        b.close()

    # 用 urllib 对账，不依赖浏览器
    import urllib.request
    with urllib.request.urlopen(base + "/api/job/" + jid, timeout=10) as r:
        api = json.loads(r.read().decode("utf-8"))
    sm = api.get("summary") or {}
    judged = (sm.get("total") or 0) - (sm.get("na") or 0)
    got = float(sm.get("score") or 0)
    full = float(sm.get("score_total") or 0)
    # 页面把 1.0 显示成 1，所以按数值比，不按字符串比
    mm = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*分", score)
    ok_num = bool(mm) and abs(float(mm.group(1)) - got) < 1e-6 and abs(float(mm.group(2)) - full) < 1e-6
    ok_cov = ("%d/%d" % (judged, sm.get("total") or 0)) in score or judged == 0
    chk("顶栏数字与判分产物一致", ok_num and ok_cov,
        "期望 得分%s/%s 覆盖%d/%s，实得 %s" % (sm.get("score"), sm.get("score_total"),
                                              judged, sm.get("total"), score))

    print("\n%d/%d 通过" % (sum(1 for _, ok, _ in results if ok), len(results)))
    fails = [r for r in results if not r[1]]
    for name, _, extra in fails:
        print("  FAIL  %s  ← %s" % (name, extra))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

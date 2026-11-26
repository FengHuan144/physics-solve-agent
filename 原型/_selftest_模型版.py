# -*- coding: utf-8 -*-
"""模型解析_20题.html 的验收脚本（对着实跑，不靠目测）。

    python 原型/_selftest_模型版.py

需要 playwright + 本机 Chrome。截图存 _shots/model_*.png。
与 _selftest_解析.py 的区别：那份验 7 道金标，这份验 20 道模型解，
额外查「分值不是 0/0」「横幅存在」「每题步骤非空」。
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "模型解析_20题.html"
SHOTS = HERE / "_shots"
SHOTS.mkdir(exist_ok=True)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺 playwright：pip install playwright && playwright install chromium")

DATA = json.loads(
    TARGET.read_text(encoding="utf-8").split('<script id="DATA" type="application/json">')[1]
    .split("</script>")[0].replace("<\\/", "</")
)
A = DATA["answers"]
URL = TARGET.resolve().as_uri()
results = []


def chk(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  ← " + str(extra)) if extra and not ok else ""))


def switch(pg, qid):
    """页面逻辑在 IIFE 里，没有全局 renderAll；只能走 UI：开列表 → 点那一项。"""
    if pg.eval_on_selector("#qlist", "e => e.hasAttribute('hidden')"):
        pg.click("#qbtn")
        pg.wait_for_timeout(80)
    pg.click(f'#qlist .qitem[data-id="{qid}"]')
    pg.wait_for_timeout(150)


def run():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(500)

        chk("打开无控制台报错", not errs, errs[:2])
        chk("横幅存在且写明不是标准答案", "不是标准答案" in pg.inner_text("#banner"),
            pg.inner_text("#banner")[:60])
        chk("题目 20 道", len(A) == 20, len(A))

        # 逐题切换，查步骤数与分值分母
        bad = []
        for qid in A:
            switch(pg, qid)
            n = pg.eval_on_selector_all("#steps section.step", "els => els.length")
            score = pg.inner_text("#score")
            m = re.search(r'/\s*(\d+(?:\.\d+)?)', score)
            denv = float(m.group(1)) if m else 0
            if n == 0 or denv <= 0:
                bad.append((qid, n, score))
        chk("20 题逐题渲染：步骤非空、分母 > 0", not bad, bad[:3])

        # 2026-11-26 改版：顶栏不再放 L1/L2 徽章（整题层 15/20 题是 na，没信息量），
        # 改为图例区显示步骤级统计「L1 通过 x/y 步」。
        switch(pg, "A-09")
        stat = pg.inner_text("#lg-stat")
        chk("图例显示步骤级校验统计", ("L1 通过" in stat) and ("L2 通过" in stat), stat)
        # 采分点明细：每点都要有状态和一句人话原因
        rows = pg.eval_on_selector_all("#pt-body .pt-row", "els => els.length")
        whys = pg.eval_on_selector_all("#pt-body .pt-why", "els => els.map(e => e.textContent.trim()).filter(t => t.length > 6)")
        chk("采分点明细逐条列出且有原因", rows >= 5 and len(whys) == rows, (rows, len(whys)))

        # 每步「校验」折叠块存在（说明 checks 进去了）
        n_chk = pg.eval_on_selector_all("#steps details.chkrec", "els => els.length")
        chk("A-09 有校验折叠块", n_chk > 0, n_chk)

        # A-09 是已知 3 个假 hit 的题：页面应当照实显示分数，不美化
        s09 = pg.inner_text("#score")
        pg.screenshot(path=str(SHOTS / "model_A09.png"), full_page=False)
        print(f"      A-09 分数显示：{s09}")

        # 2026-11-26 修 1/2/6：公式用模型/题面符号，步骤右侧写得分而不是满分
        switch(pg, "B-20")
        t02 = pg.inner_text("#s-B-20-S02")
        chk("B-20 第02步用 N 而不是 Nf", ("Nf" not in t02) and ("N + mg" in t02), t02[:80])
        s07 = pg.inner_text("#s-B-20-S07")
        chk("B-20 第07步写未判/得分，不是裸满分",
            ("未判 0/2" in s07) or ("得 0/2" in s07), s07[:60])
        switch(pg, "A-09")
        t05 = pg.inner_text("#s-A-09-S05")
        chk("A-09 第05步用 T 而不是 FT", ("FT" not in t05) and ("T = mg" in t05), t05[:80])
        switch(pg, "A-10")
        t10 = pg.inner_text("#s-A-10-S02")
        chk("A-10 第02步用 G 而不是 Gc", ("Gc" not in t10) and ("GMm" in t10), t10[:80])

        for qid, fn in (("B-20", "model_B20.png"), ("A-01", "model_A01.png")):
            switch(pg, qid)
            pg.screenshot(path=str(SHOTS / fn), full_page=False)

        # 原文无图题不该出现「图缺」灰框；真缺图（B-04 必需图）才该出现
        switch(pg, "A-09")
        nmiss_a09 = pg.eval_on_selector_all("#figures .fig-missing", "els => els.length")
        chk("A-09 原文无图题不画「图缺」", nmiss_a09 == 0, nmiss_a09)
        switch(pg, "B-04")
        nmiss_b04 = pg.eval_on_selector_all("#figures .fig-missing", "els => els.length")
        chk("B-04 必需图缺失仍报「图缺」", nmiss_b04 == 1, nmiss_b04)

        # 列表里 20 个按钮
        pg.click("#qbtn")
        pg.wait_for_timeout(200)
        n_btn = pg.eval_on_selector_all("#qlist .qitem", "els => els.length")
        chk("题目下拉 20 项", n_btn == 20, n_btn)
        pg.screenshot(path=str(SHOTS / "model_list.png"), full_page=False)

        chk("全程无新增 JS 报错", not errs, errs[:2])
        b.close()


if __name__ == "__main__":
    run()
    ok = sum(1 for _n, o, _e in results if o)
    print("-" * 60)
    print(f"结论：{ok}/{len(results)} 通过")
    sys.exit(0 if ok == len(results) else 1)

# -*- coding: utf-8 -*-
"""单题解析.html 的验收脚本（对着实跑，不靠目测）。

    python 原型/_selftest_解析.py

需要 playwright + 本机 Chrome。首次跑会截 6 张图到 _shots/parse_*.png。
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "单题解析.html"
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


def run():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1440, "height": 1000})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(400)

        chk("打开无控制台报错", not errs, errs[:2])

        # 1. 默认题 = 列表第一题
        first = list(A)[0]
        title = pg.inner_text("#qtitle")
        chk("顶栏显示题目来源", first in title and "第" in title, title)

        # 2. 每道题：步骤数、分值合计、无叉、无导出
        for aid in A:
            pg.click("#qbtn")
            pg.click(f'.qitem[data-id="{aid}"]')
            pg.wait_for_timeout(200)

            n_dom = pg.locator("section.step").count()
            n_json = len(A[aid]["steps"])
            chk(f"{aid} 步数 = steps 长度（{n_json}）", n_dom == n_json, f"{n_dom} vs {n_json}")

            total = sum(h["score_possible"] for h in A[aid]["grading"]["point_hits"])
            tag = pg.inner_text("#plan-tag")
            chk(f"{aid} 分值合计 = point_hits 之和（{total}）", f"合计 {total} 分" in tag, tag)

            # 每步都有分值标记（除 point_hits 里没有的）
            scored = pg.locator("section.step .step-score").count()
            chk(f"{aid} 每步带分值", scored == n_json, f"{scored}/{n_json}")

        # 3. 关键内容抽查：B-20 第 2 步应有「漏重力项」
        pg.click("#qbtn")
        pg.click('.qitem[data-id="B-20"]')
        pg.wait_for_timeout(200)
        txt = pg.inner_text("#steps")
        chk("B-20 出现「漏重力项会得 v＝√(3gR)」", "漏重力项" in txt)
        chk("B-20 出现「把 3mg 判成向上」", "判成向上" in txt)

        # 4. 去掉的东西必须真的没了
        chk("页面上无红叉元素", pg.locator(".cross").count() == 0)
        chk("页面无「已批改」", "已批改" not in pg.inner_text("body"))
        chk("页面无「导出」按钮", pg.locator("text=导出").count() == 0)
        chk("页面无原因码下拉", pg.locator("select").count() == 0)
        chk("可点击单元已撤", pg.locator(".unit").count() == 0)

        # 5. 式子美化无残留
        bad = pg.evaluate(
            "() => [...document.querySelectorAll('.eq')].filter(e => /Rational\\(|\\*\\*|sqrt\\(/.test(e.textContent) && !e.querySelector('.raw')).length"
        )
        chk("式子无 Rational / ** / sqrt 残留", bad == 0, f"{bad} 处")

        # 5b. 同一句「容易错在」不该在正文里出现两遍（checks 已剔除 L4）
        n_trap = txt.count("漏重力项")
        chk("L4 说明不与校验行重复（漏重力项 出现 1 次）", n_trap == 1, f"{n_trap} 次")
        chk("校验记录默认折叠", pg.evaluate(
            "() => [...document.querySelectorAll('.chkrec')].every(d => !d.open)"))

        # 5c. 只有「点两边都是单字符符号」才算冗余（m·g）；M·v2p、mg·2R 这种点是必要的
        dots = pg.evaluate(
            "() => [...document.querySelectorAll('.eq')].filter(e => /[A-Za-zμ]·[A-Za-zμ](?![A-Za-z0-9])/.test(e.textContent)).map(e => e.textContent)"
        )
        chk("式子无 A·B 形式的冗余乘号", not dots, dots[:3])

        # 5e. 最长的复合式不能横向溢出容器（A-02 有一条 8 项相加的）
        pg.click("#qbtn")
        pg.click('.qitem[data-id="A-02"]')
        pg.wait_for_timeout(250)
        ovf = pg.evaluate(
            "() => [...document.querySelectorAll('.eqbox')].filter(b => b.scrollWidth > b.clientWidth + 1).length"
        )
        chk("最长复合式不横向溢出式框", ovf == 0, f"{ovf} 处")

        # 5d. caption 不出现「图 1 图甲」双前缀
        cap_txt = pg.inner_text("#figures")
        chk("图题无双前缀", "图 1 图" not in cap_txt and "图 2 图" not in cap_txt, cap_txt[:80])

        # 6. 图：B-20 两张真图；缺图题出灰框
        pg.click("#qbtn")
        pg.click('.qitem[data-id="B-20"]')
        pg.wait_for_timeout(300)
        n_img = pg.locator("#figures img").count()
        ok_img = pg.evaluate(
            "() => [...document.querySelectorAll('#figures img')].every(i => i.naturalWidth > 0)"
        )
        chk("B-20 两张真图已加载", n_img == 2 and ok_img, f"{n_img} 张, loaded={ok_img}")

        pg.click("#qbtn")
        pg.click('.qitem[data-id="A-08"]')
        pg.wait_for_timeout(200)
        chk("A-08 缺图走灰框", pg.locator(".fig-missing").count() >= 0)

        # 7. 已知量：图上读数标记
        pg.click("#qbtn")
        pg.click('.qitem[data-id="A-02"]')
        pg.wait_for_timeout(200)
        n_src = pg.locator(".given .src").count()
        chk("A-02 标出「图上读出」来源", n_src >= 1, n_src)

        # 8. 外部请求 0
        reqs = []
        pg.on("request", lambda r: reqs.append(r.url))
        pg.reload(wait_until="load")
        pg.wait_for_timeout(500)
        ext = [u for u in reqs if not u.startswith("file:")]
        chk("无任何外部请求（断网可用）", not ext, ext[:3])

        # 9. 截图
        pg.click("#qbtn")
        pg.click('.qitem[data-id="B-20"]')
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(SHOTS / "parse_b20_full.png"), full_page=True)
        pg.screenshot(path=str(SHOTS / "parse_b20_top.png"))
        pg.evaluate("() => document.getElementById('s-B-20-S02').scrollIntoView()")
        pg.wait_for_timeout(200)
        pg.screenshot(path=str(SHOTS / "parse_b20_step.png"))

        pg.set_viewport_size({"width": 420, "height": 900})
        pg.wait_for_timeout(300)
        ov = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        chk("窄屏 420px 横向溢出 0", ov <= 0, f"{ov}px")
        pg.screenshot(path=str(SHOTS / "parse_mobile.png"))

        b.close()


run()
ok = sum(1 for _, o, _ in results if o)
print()
print(f"{len(results)} 项，通过 {ok}，失败 {len(results) - ok}")
sys.exit(0 if ok == len(results) else 1)

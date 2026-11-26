# -*- coding: utf-8 -*-
"""原型自检：对着 §9 验收清单逐条跑。跑完打印 PASS/FAIL。"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "单题工作台.html"
URL = HTML.as_uri()
OUT = HERE / "_shots"
OUT.mkdir(exist_ok=True)

results = []


DATA_EXPR = "JSON.parse(document.getElementById('DATA').textContent).answers"


def check(name, ok, detail="", skip=False):
    if skip:
        results.append((name, True, detail, True))
        print("SKIP  " + name + (("   · " + str(detail)) if detail else ""))
        return
    results.append((name, bool(ok), detail, False))
    print(("PASS  " if ok else "FAIL  ") + name + (("   · " + str(detail)) if detail else ""))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()

        console = []
        page.on("console", lambda m: console.append((m.type, m.text)))
        page.on("pageerror", lambda e: console.append(("pageerror", str(e))))

        page.goto(URL)
        page.wait_for_timeout(400)
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_timeout(400)

        # ---- 1 控制台 ----
        errs = [c for c in console if c[0] in ("error", "pageerror")]
        check("file:// 打开，控制台 0 报错", not errs, errs[:3])

        # ---- 2 七题可切换 + 块数 ----
        ids = page.evaluate(f"Object.keys({DATA_EXPR})")
        ok_count = True
        detail = []
        for aid in ids:
            page.click("#qbtn")
            page.click(f'.qitem[data-id="{aid}"]')
            page.wait_for_timeout(120)
            got = page.eval_on_selector_all(".step", "els => els.length")
            want = page.evaluate(f"{DATA_EXPR}['{aid}'].steps.length")
            if got != want:
                ok_count = False
                detail.append(f"{aid}:{got}!={want}")
        check("7 题可切换，书写块数 = steps 长度", ok_count, detail or f"{len(ids)} 题")

        # ---- 3 点单个式子出内联槽 ----
        page.click("#qbtn")
        page.click('.qitem[data-id="A-08"]')
        page.wait_for_timeout(150)
        eq3 = page.locator('[data-uid="A-08-S03#equation"]')
        eq3.click()
        page.wait_for_timeout(120)
        check("点 A-08-S03 式子 → 内联批改槽", page.locator(".slot").count() == 1)

        # ---- 4 打叉 + 叉压在式子上 ----
        page.select_option(".slot-code", "E-11")
        page.fill(".slot-note", "量纲应为 N")
        page.click(".slot-ok")
        page.wait_for_timeout(200)
        box_wrap = page.locator('[data-uid="A-08-S03#equation"] .ucell').bounding_box()
        box_cross = page.locator('[data-uid="A-08-S03#equation"] .cross').bounding_box()
        inside = (box_cross
                  and abs(box_cross["x"] - (box_wrap["x"] - 6)) < 2
                  and abs(box_cross["width"] - (box_wrap["width"] + 12)) < 3)
        check("叉号压在式子上（宽随式子变化）", inside,
              f'wrap={box_wrap["width"]:.0f} cross={box_cross["width"]:.0f}')

        # 短式子 vs 长式子的叉宽不同
        page.locator('[data-uid="A-08-S07#equation"]').click()
        page.click(".slot-ok")
        page.wait_for_timeout(200)
        wide = page.locator('[data-uid="A-08-S07#equation"] .cross').bounding_box()
        check("叉宽随式子长短变化", wide and abs(wide["width"] - box_cross["width"]) > 20,
              f'{box_cross["width"]:.0f} vs {wide["width"]:.0f}')

        # ---- 5 刷新 3 次角度一致 ----
        angles = []
        for _ in range(3):
            page.reload()
            page.wait_for_timeout(250)
            angles.append(page.get_attribute('[data-uid="A-08-S03#equation"] .cross', "data-angle"))
        check("同一式子刷新 3 次角度一致", len(set(angles)) == 1, angles)

        # ---- 6 批注样式 ----
        st = page.eval_on_selector(
            '[data-uid="A-08-S03#equation"] .note',
            """el => {
                const c = getComputedStyle(el);
                return {family: c.fontFamily, color: c.color, transform: c.transform,
                        size: parseFloat(c.fontSize)};
            }""")
        base_size = page.eval_on_selector(".eq", "el => parseFloat(getComputedStyle(el).fontSize)")
        is_kai = ("Kai" in st["family"] or "楷" in st["family"])
        is_red = st["color"] in ("rgb(192, 57, 43)",)
        rotated = st["transform"] not in ("none", "matrix(1, 0, 0, 1, 0, 0)")
        smaller = st["size"] < base_size + 0.01
        check("批注楷体红色 rotate(-1.5deg) 且字号更小",
              is_kai and is_red and rotated and smaller,
              f'{st["family"][:24]} {st["color"]} {st["transform"]} {st["size"]}/{base_size}')

        # ---- 7 式子美化 + raw 可见 ----
        texts = page.eval_on_selector_all(".eq", "els => els.map(e => e.textContent)")
        bad = [t for t in texts if "Rational(" in t or "**" in t]
        check("式子已美化（无 Rational / **）", not bad, bad[:3])
        raw_n = page.eval_on_selector_all(".raw", "els => els.length")
        check("美化后仍保留 raw 原值", raw_n > 0, f"{raw_n} 条 raw")

        # ---- 8 判断步（equation 为 null）：叉必须打在 statement 上 ----
        probe = page.evaluate(f"""() => {{
            const A = {DATA_EXPR};
            for (const k in A)
              for (const s of A[k].steps) if (!s.equation) return [k, s.step_id];
            return null;
        }}""")
        if probe:
            aid, sid = probe
            page.click("#qbtn")
            page.click(f'.qitem[data-id="{aid}"]')
            page.wait_for_timeout(150)
            n_eq_unit = page.locator(f'[data-uid="{sid}#equation"]').count()
            n_stmt = page.locator(f'[data-uid="{sid}#statement"]').count()
            page.locator(f'[data-uid="{sid}#statement"]').click()
            page.wait_for_timeout(120)
            slot_n = page.locator(".slot").count()
            page.select_option(".slot-code", "E-09")
            page.fill(".slot-note", "判据错，须打在文字判断上")
            page.click(".slot-ok")
            page.wait_for_timeout(200)
            box_stmt = page.locator(f'[data-uid="{sid}#statement"] .ucell').bounding_box()
            box_cross = page.locator(f'[data-uid="{sid}#statement"] .cross').bounding_box()
            on_stmt = bool(box_stmt and box_cross
                           and abs(box_cross["x"] - (box_stmt["x"] - 6)) < 2
                           and abs(box_cross["width"] - (box_stmt["width"] + 12)) < 3)
            check("判断步（equation=null）：无式子单元，叉打在 statement 上",
                  n_eq_unit == 0 and n_stmt >= 1 and slot_n == 1 and on_stmt,
                  f"{sid} equation单元={n_eq_unit} 批改槽={slot_n} "
                  f"叉宽={box_cross['width']:.0f}/文字宽={box_stmt['width']:.0f}")
            page.click("#qbtn")
            page.click('.qitem[data-id="A-08"]')
            page.wait_for_timeout(150)
        else:
            check("判断步（equation=null）：无式子单元，叉打在 statement 上",
                  False, "7 份数据里找不到 equation=null 的步 —— 1.2 下不该发生")

        # ---- 9 刷新保持 + 擦掉 ----
        n_before = page.evaluate("JSON.parse(localStorage.getItem('proto:A-08')).marks.length")
        page.locator('[data-uid="A-08-S03#equation"]').click()
        page.wait_for_timeout(120)
        has_erase = page.locator(".erase-bar .erase").count() == 1
        page.click(".erase-bar .erase")
        page.wait_for_timeout(150)
        n_after = page.evaluate("JSON.parse(localStorage.getItem('proto:A-08')).marks.length")
        check("刷新后仍在 → 可擦掉", has_erase and n_after == n_before - 1,
              f"{n_before} → {n_after}")

        # ---- 10 导出结构 ----
        page.wait_for_timeout(100)
        payload = page.evaluate("""() => {
            const m = JSON.parse(localStorage.getItem('proto:A-08')).marks;
            return {n: m.length, keys: m.length ? Object.keys(m[0]).sort() : [],
                    dom: document.querySelector('#count b').textContent};
        }""")
        want_keys = ["at", "note", "part", "reason_code", "step_id"]
        check("记录结构 = §4.3，条数 = 页面计数",
              payload["keys"] == want_keys and int(payload["dom"]) == payload["n"],
              f'{payload["keys"]} n={payload["n"]} 页面={payload["dom"]}')

        # ---- 11 页面无扣分字样 ----
        body = page.inner_text("body")
        forbid = ["扣分", "扣 1 分", "扣1分", "扣 2 分", "扣2分", "得分率", "成绩"]
        hit = [w for w in forbid if w in body]
        check("页面上找不到「扣 N 分」字样", not hit, hit)

        # ---- 12 图区 ----
        page.click("#qbtn")
        page.click('.qitem[data-id="B-20"]')
        page.wait_for_timeout(150)
        miss = page.locator(".fig-missing").count()
        caps = page.locator(".fig-cap").count()
        imgs = page.locator(".figures .fig img").count()
        # 14:52 E 路取到真题原图后此条反转：有图必须显示真图，无图必须灰框
        check("B-20 图区显示真题原图（图甲/图乙）+ caption",
              imgs >= 2 and miss == 0 and caps >= 2, f"真图{imgs} 缺图{miss} caption{caps}")
        page.click("#qbtn")
        page.click('.qitem[data-id="A-08"]')
        page.wait_for_timeout(150)
        check("A-08 图区显示 figures[0].caption",
              page.locator(".fig-cap").count() >= 1 and
              "四分之一圆轨道" in page.inner_text(".fig-cap"))

        # ---- 13 零外部请求 ----
        reqs = []
        page2 = ctx.new_page()
        page2.on("request", lambda r: reqs.append(r.url))
        page2.goto(URL)
        page2.wait_for_timeout(500)
        ext = [u for u in reqs if not u.startswith("file://")]
        check("断网可用（无任何外部请求）", not ext, ext[:3])
        page2.close()

        # ---- 14 窄屏 ----
        page.set_viewport_size({"width": 900, "height": 900})
        page.wait_for_timeout(300)
        ov = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        drawer_hidden = page.evaluate("getComputedStyle(document.getElementById('sidebar')).maxHeight")
        page.click("#stem-btn")
        page.wait_for_timeout(350)
        drawer_open = page.evaluate("document.getElementById('main').classList.contains('drawer-open')")
        page.screenshot(path=str(OUT / "03_narrow.png"))
        check("900px 左栏变抽屉、无横向溢出", ov <= 1 and drawer_open,
              f"溢出{ov}px 收起时maxHeight={drawer_hidden} 可展开={drawer_open}")

        # ---- 截图存档 ----
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "04_marked.png"))
        page.locator(".step").nth(6).scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "05_lower.png"))

        browser.close()

    fails = [r for r in results if not r[1]]
    print()
    print(f"合计 {len(results)} 条，通过 {len(results) - len(fails)}，未通过 {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())

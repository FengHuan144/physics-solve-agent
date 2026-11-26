# -*- coding: utf-8 -*-
"""用真实 Chrome 打开公众号文章，导出所有图片地址（含 data-src）。
用法: python fetch_wx.py <url> [url2 ...]
"""
import sys, json, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).parent

def dump(pg, tag):
    info = pg.evaluate("""() => {
        const imgs = [...document.images].map(i => ({
            src: i.currentSrc || i.src || '',
            data_src: i.getAttribute('data-src') || '',
            w: i.naturalWidth, h: i.naturalHeight
        }));
        return {title: document.title, n: imgs.length, imgs};
    }""")
    print(f"### {tag} title={info['title']!r} imgs={info['n']}")
    for i in info["imgs"]:
        u = i["data_src"] or i["src"]
        print(f"  {i['w']}x{i['h']}  {u}")
    (OUT / f"wx_{tag}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True,
                          args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(
        viewport={"width": 1400, "height": 1000},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="zh-CN",
    )
    for n, url in enumerate(sys.argv[1:], 1):
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(4000)
            pg.mouse.wheel(0, 3000); pg.wait_for_timeout(1500)
            pg.mouse.wheel(0, 3000); pg.wait_for_timeout(1500)
            dump(pg, f"a{n}")
        except Exception as e:
            print(f"### a{n} ERROR {e}")
        finally:
            pg.close()
    b.close()

# -*- coding: utf-8 -*-
"""
把 7 份 schema/examples/*.json、xlsx 的「错误码枚举」sheet、定律表
注入 原型/*.html 的 <script id="DATA"> 块。

目标文件（存在哪个注入哪个）：
    原型/单题解析.html      ← 主交付物（解析页）
    原型/单题工作台.html    ← 旧原型（批改式），已废弃，仅留档

幂等：只替换 DATA 块，其余 HTML（样式、渲染逻辑）原样保留。

    python 原型/_build.py
"""
import datetime
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
EXAMPLE = ROOT / "schema" / "examples"
XLSX = ROOT / "原始资料" / "五卷力学大题_采分点总表_v2.xlsx"
LAWCSV = ROOT / "知识表" / "定律适用条件_v1.csv"
FIGDIR = ROOT / "原始资料" / "题图"
TARGET_MAIN = HERE / "单题解析.html"
TARGET_OLD = HERE / "单题工作台.html"
TARGETS = [p for p in (TARGET_MAIN, TARGET_OLD) if p.exists()]

DATA_RE = re.compile(
    r'(<script id="DATA" type="application/json">)[\s\S]*?(</script>)'
)

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg")
FIG_ALIAS = {"甲": "1", "乙": "2", "丙": "3", "丁": "4"}   # 文件名用「图乙」→ figures[].fig_no=2


def load_answers():
    """读 7 份 answer JSON。浮点按原文保留（6.0 不会变成 6）。"""
    out = {}
    for f in sorted(EXAMPLE.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"), parse_float=str)
        aid = d["meta"]["answer_id"]
        out[aid] = d
    return out


def load_errors():
    """读「错误码枚举」sheet，21 条。"""
    import openpyxl
    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws = wb["错误码枚举"]
    rows = ws.iter_rows(min_row=2, values_only=True)
    out = []
    for r in rows:
        if not r or not r[0]:
            continue
        out.append({
            "code": str(r[0]).strip(),
            "name": str(r[1] or "").strip(),
            "symptom": str(r[2] or "").strip(),
            "layer": str(r[3] or "").strip(),
            "severity": str(r[4] or "").strip(),
            "auto": str(r[8] or "").strip(),
        })
    wb.close()
    return out


def load_laws():
    """读定律表：law_id -> {name, one_liner, misuse}。解析页用来标「这步用了什么定律」。"""
    import csv
    out = {}
    if not LAWCSV.exists():
        return out
    with LAWCSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lid = (row.get("law_id") or "").strip()
            if not lid:
                continue
            out[lid] = {
                "name": (row.get("名称") or "").strip(),
                "one_liner": (row.get("一句话表述") or "").strip(),
                "misuse": (row.get("典型误用") or "").strip(),
            }
    return out


def load_images(answer_ids):
    """扫 原始资料/题图/{answer_id}_{fig_no}.{ext}；没有图就不写条目。"""
    found = {}
    if not FIGDIR.is_dir():
        return found
    for p in sorted(FIGDIR.iterdir()):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        # 图号允许：1 / 甲 / 图甲（T00 14:52 裁定：改代码，不复制文件）
        m = re.match(r"^([A-Z]-\d{2})_(?:图)?(\d+|[甲乙丙丁])$", p.stem)
        if not m:
            continue
        aid = m.group(1)
        fig_no = FIG_ALIAS.get(m.group(2), m.group(2))
        if aid not in answer_ids:
            continue
        rel = pathlib.Path(os.path.relpath(p, HERE)).as_posix()
        found.setdefault(aid, {})[fig_no] = rel
    return found


def main():
    answers = load_answers()
    if not answers:
        sys.exit("schema/examples 下没有 json，先确认数据源。")

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "answers": answers,
        "error_codes": load_errors(),
        "laws": load_laws(),
        "images": load_images(set(answers)),
    }

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")   # 防提前闭合 script

    if not TARGETS:
        sys.exit("原型/ 下没有可注入的 html。")

    for target in TARGETS:
        html = target.read_text(encoding="utf-8")
        new, n = DATA_RE.subn(lambda m: m.group(1) + blob + m.group(2), html, count=1)
        if n != 1:
            sys.exit(f'{target.name} 里没找到 <script id="DATA" type="application/json"> 占位块。')
        target.write_text(new, encoding="utf-8")

    total_steps = sum(len(a.get("steps", [])) for a in answers.values())
    print(f"[ok] 注入 {len(TARGETS)} 个文件：{', '.join(t.name for t in TARGETS)}")
    print(f"     题目 {len(answers)} 道：{', '.join(answers)}")
    print(f"     步骤 {total_steps} 步 · 错误码 {len(payload['error_codes'])} 条 · 定律 {len(payload['laws'])} 条")
    missing = [a["meta"]["answer_id"] for a in answers.values()
               if a["question"].get("figures") and
               a["meta"]["answer_id"] not in payload["images"]]
    if missing:
        print(f"     缺图（灰框态）：{', '.join(missing)}")
    for target in TARGETS:
        print(f"     {target.name} {target.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()

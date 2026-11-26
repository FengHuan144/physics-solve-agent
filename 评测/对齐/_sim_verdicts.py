# -*- coding: utf-8 -*-
"""T20 对齐：待裁定条目的数字后果模拟。
读 T20步点对齐_v1.json，在内存里逐条施加「若改判」，重算 §2 统计。
不改任何文件。

【状态：已结案】8 条裁定已全部作出并落到 v2（评测/对齐/T20对齐_裁定_20261125.md）。
本脚本保留原样，只对 v1 的「若改判」做复算，用于核对裁定书里引用的数字；
**不要再把它当当前口径**——现行判定看 T20步点对齐_v2.json。
"""
import json
import os
import copy
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "评测", "对齐", "T20步点对齐_v1.json")


def load():
    with open(SRC, encoding="utf-8") as f:
        return json.load(f)


def stats(doc):
    c = Counter()
    h = Counter()
    for it in doc["items"]:
        for s in it["steps"]:
            c[s["class"]] += 1
        for p in it["points"]:
            h[p["home"]] += 1
    n_step = sum(len(it["steps"]) for it in doc["items"])
    n_pt = sum(len(it["points"]) for it in doc["items"])
    red = (c["dup"] + c["meta"]) / n_step
    return dict(
        steps=n_step, pts=n_pt,
        primary=c["primary"], split=c["split"], merged=c["merged"],
        dup=c["dup"], new=c["new"], meta=c["meta"], off=c["off"],
        h11=h["1:1"], h1n=h["1:n"], hmg=h["merged"], hnone=h["none"],
        redundancy=red,
    )


def fmt(tag, s):
    return (f"{tag}: 步 {s['steps']}（p{s['primary']}+s{s['split']}+m{s['merged']}"
            f"+d{s['dup']}+n{s['new']}+x{s['meta']}" + (f"+off{s['off']}" if s['off'] else "") + "）"
            f"｜点 {s['pts']}（1:1 {s['h11']} / 1:n {s['h1n']} / mg {s['hmg']} / none {s['hnone']}）"
            f"｜冗余 {s['dup']+s['meta']}/{s['steps']}={s['redundancy']*100:.2f}%")


def find_step(doc, sid):
    for it in doc["items"]:
        for s in it["steps"]:
            if s["step_id"] == sid:
                return it, s
    raise KeyError(sid)


def find_point(doc, pid):
    for it in doc["items"]:
        for p in it["points"]:
            if p["point_id"] == pid:
                return it, p
    raise KeyError(pid)


def merged_case(doc):
    """A-02-S08 按 §5.1 字面改判 merged（撑 S06 + S07），点 S06 home→merged。"""
    it, s = find_step(doc, "A-02-S08")
    s["class"] = "merged"
    s["point_id"] = None
    s["point_ids"] = ["A-02-S06", "A-02-S07"]
    _, p = find_point(doc, "A-02-S06")
    p["home"] = "merged"
    # §10.2 的 merged 断言：merged 步数 *2 <= home=merged 点数
    m_steps = sum(1 for it2 in doc["items"] for x in it2["steps"] if x["class"] == "merged")
    m_home = sum(1 for it2 in doc["items"] for y in it2["points"] if y["home"] == "merged")
    return m_steps, m_home


def equiv_reject(doc, only_physical=True):
    """等价形式判「不命中」：步记 off（临时代号，只为算数），点失去该证据。

    only_physical=True 时只处理「物理等价但非代数等价」的 3 条；
    B-12-S09 按卡片 §6.2（两边同除 m+M）属代数等价，不算在内。
    """
    PHYS = {"A-02-S02", "A-02-S14", "A-02-S18"}
    hit = []
    for it in doc["items"]:
        for s in it["steps"]:
            if not s["equiv_form"]:
                continue
            if only_physical and s["step_id"] not in PHYS:
                continue
            hit.append((it, s))
    for it, s in hit:
        pid = s["point_id"]
        s["class"] = "off"
        s["point_id"] = None
        if pid:
            _, p = find_point(doc, pid)
            p["by"] = [b for b in p["by"] if b != s["step_id"]]
            if not p["by"]:
                p["home"] = "none"
    return [s["step_id"] for _, s in hit]


def a08_s07_split(doc):
    _, s = find_step(doc, "A-08-S07")
    s["class"] = "split"


def b02_s03_dup(doc):
    _, s = find_step(doc, "B-02-S03")
    s["class"] = "dup"
    s["dup_of"] = "B-02-S02"
    s["point_id"] = None


def b09_s05_none(doc):
    """缺口 2：结构隐含型不算命中 → 点 B-09-S05（金标「甲分两段」）落 none。"""
    _, p = find_point(doc, "B-09-S05")
    p["home"] = "none"
    p["by"] = []


def main():
    base = load()
    print(fmt("S0 基线", stats(base)))

    d = copy.deepcopy(base)
    m_steps, m_home = merged_case(d)
    print(fmt("S1 A-02-S08→merged", stats(d)))
    print(f"     §10.2 断言: merged 步 {m_steps} × 2 = {2*m_steps} vs home=merged 点 {m_home}"
          f" → {'通过' if m_home >= 2*m_steps else '失败（卡在此）'}")

    d = copy.deepcopy(base)
    ids = equiv_reject(d, only_physical=True)
    print(fmt("S2a 物理等价 3 条不认", stats(d)))
    print(f"     涉及步: {'、'.join(ids)}")

    d = copy.deepcopy(base)
    ids = equiv_reject(d, only_physical=False)
    print(fmt("S2b 连代数等价一起不认（过度严格）", stats(d)))
    print(f"     涉及步: {'、'.join(ids)}")

    d = copy.deepcopy(base)
    a08_s07_split(d)
    print(fmt("S3 A-08-S07→split", stats(d)))
    _, p6 = find_point(d, "A-08-S06")
    own = [x["step_id"] for x in d["items"][1]["steps"]
           if x["class"] == "primary" and x["point_id"] == "A-08-S06"]
    shared = [x["step_id"] for x in d["items"][1]["steps"]
              if x["class"] == "primary" and x["step_id"] in p6["by"] and x["point_id"] != "A-08-S06"]
    print(f"     点 A-08-S06：by={p6['by']}｜专属 primary={own or '无'}｜"
          f"借用的他点 primary={shared}")

    d = copy.deepcopy(base)
    b02_s03_dup(d)
    print(fmt("S4 B-02-S03→dup", stats(d)))

    d = copy.deepcopy(base)
    b09_s05_none(d)
    print(fmt("S5 B-09-S05 点→none", stats(d)))
    _, p = find_point(d, "B-09-S05")
    print(f"     该点 score={p['score']}，by 清空后需补 closest/gap 才过断言 5")

    d = copy.deepcopy(base)
    for it in d["items"]:
        if it["qid"] == "B-20":
            it["points"].append(dict(point_id="B-20-S99", score=1, home="1:1",
                                     by=["B-20-S05"], note="假想补点：折点 a=2 m/s² 读数"))
            it["gold_steps"] += 1
    print(fmt("S6 补 1 点（假想）", stats(d)))
    print("     代价：采分点表加行 + 金标 JSON 加步 + 断言 1 的 66 改 67")


if __name__ == "__main__":
    main()

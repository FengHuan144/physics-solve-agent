# -*- coding: utf-8 -*-
"""cli.py — 命令行入口。

两种调用方式都支持（卡 §5 / §6）：

    python -m 验证器.cli 验证器/tests/A-06.json --out _out.json
    python 验证器/cli.py 验证器/tests/A-06.json --out _out.json

附加两个审计开关（不属于判定流程，只出报告）：

    --audit-xlsx        采分点总表能给验证器提供多少可判的步
    --audit-formulas    公式库 74 条整体过 L2（真数据规模化验证）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # 以包方式运行（python -m 验证器.cli）
    from . import l2_dimension as L2
    from . import runner as R
    from . import units as U
except ImportError:  # 以脚本方式运行（python 验证器/cli.py）
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from 验证器 import l2_dimension as L2
    from 验证器 import runner as R
    from 验证器 import units as U


def _p(line: str = ""):
    print(line)


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(U.PROJECT_ROOT))
    except ValueError:
        return str(p)


def print_report(rep: dict, verbose: bool = False):
    _p(f"对象：{rep.get('answer_id') or '?'}（题 {rep.get('question_id') or '?'}，{rep['steps']} 步）")
    for layer in ("L1", "L2"):
        d = rep["checks"].get(layer) or {"pass": 0, "fail": 0, "na": 0, "skipped": 0}
        _p(f"{layer}  pass {d['pass']} / fail {d['fail']} / na {d['na']} / skipped {d['skipped']}"
           f"    判定通过率 {rep['judged_rate'].get(layer, '—')}    na 比例 {rep['na_ratio'].get(layer, '—')}")
    _p(f"整题层状态：{json.dumps(rep['layers'], ensure_ascii=False)}")

    if rep.get("alias"):
        a = rep["alias"]
        _p(f"别名层：题 {a['qid']}｜改写 {len(a['rewrites'])} 处"
           f"（{json.dumps(a['by_type'], ensure_ascii=False)}）"
           f"｜未识别 {len(a['unresolved'])} 处｜撞车 {len(a['collisions'])} 处")
        for c in a["collisions"]:
            _p(f"  ! 撞车 {c['step_id']} → {c['target']}（{c['sources']}）：{c['why']}")

    if rep["degraded_steps"]:
        _p(f"降级步（不参与统计）：{'、'.join(rep['degraded_steps'])}")
    if rep["known_conflicts"]:
        _p("已知冲突：")
        for c in rep["known_conflicts"]:
            _p(f"  ! {c}")
    if rep.get("known_data_errors"):
        _p("已知量的数据错误（不参与回代）：")
        for d in rep["known_data_errors"]:
            _p(f"  - {d}")
    if rep["data_errors"]:
        _p("数据错误（不静默修，已跳过）：")
        for d in rep["data_errors"]:
            _p(f"  - {d['step_id']} [{d['layer']}] {d['detail']}")
    if rep["chain_attributed"]:
        _p("chain 归因（单值错）：")
        for a in rep["chain_attributed"]:
            _p(f"  - {a['step_id']} {a['symbol']}: {a['stated']} → {a['solved']}")
    if rep["chain_ambiguous"]:
        _p(f"归因不唯一：{'、'.join(rep['chain_ambiguous'])}")
    if rep["chain_unclassified"]:
        _p("抓到但未分类的残差（结构性问题）：")
        for u in rep["chain_unclassified"]:
            _p(f"  - {u['step_id']} 残差 {u['residual']:.6g}｜{u['judgement']}")

    if rep["failures"]:
        _p("失败：")
        for f in rep["failures"]:
            _p(f"  x {f['step_id']} [{f['layer']}/{f['error_code']}] {f['detail']}")
    else:
        _p("失败：无")

    if verbose:
        _p("逐步：")
        for f in rep.get("per_step"):
            _p(f"  {f['step_id']}  L1 {f['L1']:<7} L2 {f['L2']:<7} {f['note']}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台防乱码
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="物理解析验证器 · L1 计算 + L2 量纲")
    ap.add_argument("answer", nargs="?", help="answer JSON 路径")
    ap.add_argument("--out", help="把带 checks 的 answer JSON 写到这个路径")
    ap.add_argument("--report", help="把汇总报告写成 JSON")
    ap.add_argument("--verbose", action="store_true", help="逐步打印")
    ap.add_argument("--audit-xlsx", action="store_true", help="审计采分点总表的可判性")
    ap.add_argument("--audit-formulas", action="store_true", help="公式库整体过 L2")
    ap.add_argument("--alias", action="store_true",
                    help="开符号别名层（T23）：先把模型符号翻译成白名单 id 再判；默认关闭")
    ap.add_argument("--alias-qid", help="别名的题号（默认取 meta.question_id）")
    args = ap.parse_args(argv)

    if args.audit_xlsx:
        a = R.audit_xlsx()
        _p(f"采分点总表：{_rel(Path(a['path']))}")
        _p(f"  台账行 {a['rows']} 行 / {a['questions']} 题 / {a['score']:g} 分"
           f"（A-01~A-06 部分 {a['first_six_rows']} 行 / {a['first_six_score']:g} 分）")
        _p(f"  含等号的式子型文本：全表 {a['rows_with_equal_sign']} 行"
           f"（A-01~A-06 段 {a['first_six_with_equal_sign']} / {a['first_six_rows']} 行）"
           f"——是散文里的符号，不是可解析表达式")
        _p(f"  有 equation.sympy 列：{a['has_sympy_column']}｜有 value 数值列：{a['has_value_column']}")
        _p(f"  结论：{a['verdict']}")
        _p(f"  类别分布：{json.dumps(a['by_category'], ensure_ascii=False)}")
        return 0

    if args.audit_formulas:
        s = L2.sweep_formula_lib()
        _p(f"公式库 L2 扫描：{s['pass']}/{s['total']} pass，{s['fail']} fail，{s['data_error']} data_error")
        for r in s["rows"]:
            if r["status"] != "pass":
                _p(f"  x {r['formula_id']}  {r['sympy']}  → {r['detail']}")
        return 0

    if not args.answer:
        ap.print_help()
        return 2

    path = Path(args.answer)
    if not path.exists():
        _p(f"[E] 文件不存在：{path}")
        return 2

    answer = json.loads(path.read_text(encoding="utf-8"))
    out, rep = R.run_answer(answer, alias=args.alias, alias_qid=args.alias_qid)

    # 逐步摘要（放进报告，--verbose 时打印）
    rep["per_step"] = [
        {"step_id": s.get("step_id"),
         "L1": next((c["status"] for c in s["checks"] if c["layer"] == "L1"), "—"),
         "L2": next((c["status"] for c in s["checks"] if c["layer"] == "L2"), "—"),
         "note": next((c["detail"] for c in s["checks"] if c["status"] != "pass"), "")[:60]}
        for s in out.get("steps") or []
    ]
    print_report(rep, args.verbose)

    viol = R.validate_checks(out)
    _p(f"check 契约校验：{len(viol)} 处违约" + ("" if not viol else "  ← 必须为 0"))
    for v in viol:
        _p(f"  x {v}")

    if args.out:
        outp = Path(args.out)
        outp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _p(f"已写：{_rel(outp)}")
    if args.report:
        rp = Path(args.report)
        rp.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _p(f"报告：{_rel(rp)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

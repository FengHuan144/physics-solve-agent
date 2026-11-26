#!/bin/bash
# 读题图（本地，不调任何外部接口）
#
# 用法：
#   ./read_figure.sh <图片路径>                    # 交互：跑内置两段式四问
#   ./read_figure.sh <图片路径> "你的问题"          # 自定义单问（默认 -n 600）
#   ./read_figure.sh <图片路径> "你的问题" 900      # 自定义单问并指定 token 上限
#
# ⚠️ -n 不能给太小：实测 300 会被截断导致答错，600 才够。默认已设为 600。
#    （T00 15:06 修：原版自定义单问硬编码 300，命令行传第三个参数会被静默忽略）
#
# 依赖：D:/峤的个人档案/做点东西/_vlm_local/ 下的 llama.cpp 与 Qwen2.5-VL-3B
# 台账：评测/本地方案实测_20261125.md

set -u
ROOT="D:/峤的个人档案/做点东西/_vlm_local"
BIN="$ROOT/llama/llama-mtmd-cli.exe"
MODEL="$ROOT/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
MMPROJ="$ROOT/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"

[ -x "$BIN" ] || { echo "找不到 llama-mtmd-cli：$BIN"; exit 2; }
[ -f "$MODEL" ] || { echo "找不到主模型：$MODEL"; exit 2; }
[ -f "$MMPROJ" ] || { echo "找不到 mmproj：$MMPROJ"; exit 2; }

IMG="${1:-}"
[ -n "$IMG" ] && [ -f "$IMG" ] || { echo "用法：$0 <图片路径> [问题] [token上限]"; exit 2; }

# --image-min-tokens 1024 不能省：llama.cpp 明确警告低于此值 grounding 任务不准
run () {
  "$BIN" -m "$MODEL" --mmproj "$MMPROJ" --image "$IMG" \
    -p "$1" -n "${2:-220}" --temp 0 -t 8 --no-warmup --image-min-tokens 1024 2>/dev/null \
    | grep -vE '^[0-9]+\.[0-9]+\.|^(load|print_info|main|mtmd|init):' | sed '/^$/d'
}

if [ $# -ge 2 ]; then
  echo "=== 问题 ==="; echo "$2"; echo "=== 回答 ==="
  run "$2" "${3:-600}"
  exit 0
fi

# 两段式：先读点，再算。直接问最终量会失败（见报告 §2.4）
echo "### 第一段：读图上的关键量"
run "这是一张物理题的图。请只回答：横轴表示什么物理量、单位是什么？纵轴表示什么物理量、单位是什么？曲线或折线有几段？各段的端点（或关键拐点）的横纵坐标数值分别是多少？只给数值，不要解释。" 600
echo ""
echo "### 第二段：把上一步读到的点交给它做计算"
echo "(把第一段读到的点代入下面这句，或人工核对后再算)"
echo "参考句式：已知直线过 (x1,y1) 和 (x2,y2)，求斜率与纵轴截距。"

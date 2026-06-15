#!/usr/bin/env bash
#
# 啟動 Douyin Live Monitor，並用 cgroup v2 (systemd-run) 設定「真實記憶體」上限。
#
# 為什麼要這樣做：
#   main.py 會同時開多個 Chrome 監看直播，極端情況下整棵行程樹可能吃光 RAM，
#   讓整台機器卡死甚至重啟。這裡用 systemd-run --scope 把 Python + Chrome + ffmpeg
#   全部放進同一個 cgroup，設定 MemoryMax 為真實記憶體硬上限、並關閉 swap，
#   一旦超過上限，kernel 只會 OOM-kill 這棵行程樹，而不會拖垮整台機器。
#
#   注意：不要用 RLIMIT_AS（ulimit -v）來限制，那是限制「虛擬位址空間」，
#   現代 Chrome 啟動時就要保留數十 GB 虛擬位址空間，會直接以 SIGTRAP 崩潰。
#
# 用法：
#   ./run.sh                 # 用預設上限啟動
#   MEM_MAX=16G ./run.sh     # 自訂上限
#
set -euo pipefail

cd "$(dirname "$0")"

# 真實記憶體硬上限（可用環境變數覆寫）。本機 30G RAM，預設留充足餘裕。
MEM_MAX="${MEM_MAX:-12G}"

# 沒有 systemd 時退回直接執行（不加上限，至少能跑）。
if ! command -v systemd-run >/dev/null 2>&1; then
    echo "⚠️  找不到 systemd-run，將不加記憶體上限直接執行。"
    exec uv run main.py
fi

echo "啟動 Douyin Live Monitor（記憶體上限 MemoryMax=${MEM_MAX}，swap 關閉）..."
exec systemd-run --user --scope \
    --unit="douyin-monitor-$$" \
    -p MemoryMax="${MEM_MAX}" \
    -p MemorySwapMax=0 \
    uv run main.py

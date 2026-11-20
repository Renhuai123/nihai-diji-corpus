#!/bin/zsh
# 堪舆三集（P31 P33 P35）逐帧层·Grok 版（2026-11-15 站长：用本机 Cursor 命令行的 Grok 4.7 跑，不用 DeepSeek；
#   先 20 路，没有限流报错再加到 40 路，明天到公司视情况再加）。取代 run_kanyu_frames.sh（DeepSeek 版，没跑过）。
# - 模型 grok-4.7-high-fast：11-15 在 P17 的 24 窗小考里对标准答案 触板 67/67、在写 60/60、动作 60/60、手可见 70/72，
#   字幕与苹果参照轨一致 81.2%（DeepSeek 同窗 79.2%），见 日志/grok小考-高快.log。
# - 结果写 逐帧层/全量/<集>.jsonl（与 DeepSeek 版同格式，每条另记 模型 / 用时 / 用量），join_sentences.py 不用改。
# - 同时在跑的窗数读 堪舆并发-grok.txt（随时可改，立刻生效）。
# - 一轮三集跑完还有失败窗就再来一轮；一整轮待跑数没减少，等 10 分钟再试，连续 3 轮没进展停。全部跑满写 逐帧层/全量/堪舆完成.flag。
# 日志：日志/堪舆-逐帧-grok.log；每集明细 日志/逐帧-grok-<集>.log
# 停：kill 本脚本，再 TERM 正在跑的 grok_frames.py（已落盘的窗保留，重跑自动续）。
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")"
PY=../.venv-vision/bin/python
LOG=日志/堪舆-逐帧-grok.log
EPS=(P31 P33 P35)
MODEL=grok-4.7-high-fast
mkdir -p 日志 逐帧层/全量
say() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $LOG; }
left_now() { $PY kanyu_status.py 2>/dev/null | sed -n 's/^合计待跑 \([0-9]*\) 窗$/\1/p'; }

say "堪舆逐帧层（Grok）启动（PID $$），模型 $MODEL"
stuck=0
while true; do
  if $PY kanyu_status.py >> $LOG 2>&1; then
    say "三集窗都已完成"; touch 逐帧层/全量/堪舆完成.flag; break
  fi
  before=$(left_now)
  for ep in $EPS; do
    say "开跑 $ep，同时在跑窗数读 堪舆并发-grok.txt（现在 $(cat 堪舆并发-grok.txt 2>/dev/null)）"
    $PY grok_frames.py $ep --模型 $MODEL --并发 60 --并发文件 堪舆并发-grok.txt --名 全量 2>&1 \
      | grep --line-buffered -v "^W0000\|^I0000\|absl" >> 日志/逐帧-grok-$ep.log
  done
  after=$(left_now)
  say "一轮结束：待跑 ${before:-?} → ${after:-?} 窗"
  if [ -n "$before" ] && [ -n "$after" ] && [ "$after" -ge "$before" ]; then
    stuck=$((stuck + 1))
    if [ $stuck -ge 3 ]; then say "连续 3 轮没进展（剩 $after 窗反复失败），停，等人看"; break; fi
    sleep 600
  else
    stuck=0
  fi
done
say "堪舆逐帧层（Grok）退出"

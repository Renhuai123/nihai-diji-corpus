#!/bin/zsh
# 【已停用，一窗没跑：站长 11-15 定逐帧层改用 Grok 4.7，见 run_kanyu_grok.sh】
# 堪舆三集（P31 P33 P35）逐帧层（2026-11-15）：照 run_full_allday.sh，只换集号与并发文件；三集清单都出来才开跑。
# - 日夜连续跑（站长 11-12：「成本增加一倍也没问题，我不想消耗太多时间」）；提示词、每窗 12 帧、出图与前 17 集完全相同。
# - 闸照旧：每集开跑前余额 <¥100 每 10 分钟查一次（充值后自动接着跑）；单次预算 ¥800；跑满 2000 窗后每窗扣费 >¥0.07 停。
# - 并发：每集开跑前读 堪舆并发.txt。在家上行约 13–24 Mbps，吞吐由上行决定，用 32 免得挤断别的连接；回公司改 160。
# - 一整轮待跑数没减少就等 30 分钟再试，连续 3 轮没进展停。全部跑满写 逐帧层/全量/堪舆完成.flag。
# 日志：日志/堪舆-逐帧.log；每集明细 日志/逐帧-全量-<集>.log
# 停：先 kill 本脚本，再 TERM 正在跑的 pilot_frames.py（别用 INT，会卡住）；重跑自动续。
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")"
PY=../.venv-vision/bin/python
LOG=日志/堪舆-逐帧.log
EPS=(P31 P33 P35)
mkdir -p 日志 逐帧层/全量
say() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $LOG; }
left_now() { $PY kanyu_status.py 2>/dev/null | sed -n 's/^合计待跑 \([0-9]*\) 窗$/\1/p'; }

say "堪舆逐帧层启动（PID $$），等三集清单"
for ep in $EPS; do
  while [ ! -f ../全帧-20261107/清单/$ep.tsv ]; do sleep 60; done
done
say "三集清单齐了，开跑"
stuck=0
while true; do
  if $PY kanyu_status.py >> $LOG 2>&1; then
    say "三集窗都已完成"; touch 逐帧层/全量/堪舆完成.flag; break
  fi
  before=$(left_now)
  for ep in $EPS; do
    while true; do
      b=$($PY full_status.py --余额 2>>$LOG)
      if [ -n "$b" ] && [ "$b" -ge 100 ]; then break; fi
      say "余额 ¥${b:-查询失败} 不足 ¥100，等充值（每 10 分钟查一次）"; sleep 600
    done
    CONC=$(cat 堪舆并发.txt 2>/dev/null | tr -cd '0-9'); CONC=${CONC:-32}
    say "开跑 $ep，并发 $CONC，余额 ¥$b"
    $PY pilot_frames.py $ep --并发 $CONC --名 全量 --预算 800 --单价上限 0.07 2>&1 | grep --line-buffered -v "^W0000\|^I0000\|absl" >> 日志/逐帧-全量-$ep.log
  done
  after=$(left_now)
  say "一轮结束：待跑 ${before:-?} → ${after:-?} 窗"
  if [ -n "$before" ] && [ -n "$after" ] && [ "$after" -ge "$before" ]; then
    stuck=$((stuck + 1))
    if [ $stuck -ge 3 ]; then say "连续 3 轮没进展（剩 $after 窗反复失败），停，等人看"; break; fi
    sleep 1800
  else
    stuck=0
  fi
done
say "堪舆逐帧层退出"

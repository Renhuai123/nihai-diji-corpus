#!/bin/zsh
# 堪舆三集（天纪合辑 P31 P33 P35 = 堪舆一、二、三）免费前序（2026-11-15）：下载 → 逐帧清单 → 本机预处理，零接口费。
# - 下载：复用 scripts/download_videos.py，只把集号换成 31 33 35（已下好的跳过，半截的续传），登记进 审计/视频核验.json。
# - 清单：make_manifest.py 本机解码（与 run.py 同一条命令），三集并行；不上传腾讯云。
# - 预处理：run_prep_full.sh P31 P33 P35，状态目录与日志和 15 集那轮分开（预处理状态-堪舆/、日志/预处理-堪舆.log）。
# 日志：日志/堪舆-前序.log
# 用法：cd 第0步 && 脱离当前会话后台跑本脚本（Cursor 里直接 nohup & 会在命令返回时被一起结束）
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$(dirname "$0")"
LOG=日志/堪舆-前序.log
EPS=(P31 P33 P35)
mkdir -p 日志
say() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $LOG; }

say "开始（PID $$）"
if ! (cd ../scripts && python3 -c "import download_videos as d; d.ORDER=[31,33,35]; d.main()") >> ../审计/下载-堪舆-P31P33P35.log 2>&1; then
  say "下载出错，见 审计/下载-堪舆-P31P33P35.log"; exit 1
fi
say "三集下载完成"

for ep in $EPS; do ../.venv-vision/bin/python make_manifest.py $ep > 日志/清单-$ep.log 2>&1 & done
wait
for ep in $EPS; do
  if [ ! -f ../全帧-20261107/清单/$ep.tsv ]; then say "清单出错 $ep，见 日志/清单-$ep.log"; exit 1; fi
done
say "三集清单完成：$(for ep in $EPS; do printf '%s %s 帧；' $ep $(wc -l < ../全帧-20261107/清单/$ep.tsv | tr -d ' '); done)"

PREP_LOG=$PWD/日志/预处理-堪舆.log PREP_STATE=$PWD/预处理状态-堪舆 ./run_prep_full.sh $EPS
say "预处理脚本退出，见 日志/预处理-堪舆.log"

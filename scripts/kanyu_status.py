"""堪舆三集（P31 P33 P35）逐帧层进度（不调接口）。用法（在 第0步/ 下）：../.venv-vision/bin/python kanyu_status.py
打印每集 已完成 / 总窗数和合计待跑；三集全满退出码 0，否则 1。结果在 逐帧层/全量/<集>.jsonl，与前 15 集同一目录。
"""
import sys

from full_status import done_windows, total_windows

EPS = ['P31', 'P33', 'P35']

left, ok = 0, True
for ep in EPS:
    t, d = total_windows(ep), done_windows(ep, '全量')
    left += t - d
    ok &= d >= t
    print(f'{ep} 全量 {d}/{t}')
print(f'合计待跑 {left} 窗')
sys.exit(0 if ok else 1)

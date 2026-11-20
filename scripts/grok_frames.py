"""逐帧层·Grok 版（2026-11-15，站长：堪舆四集的逐帧层改用本机 Cursor 命令行的 Grok 4.7，不用 DeepSeek）。
用法（在 第0步/ 下）：
  ../.venv-vision/bin/python grok_frames.py P17 --窗 2406,2407,... --模型 grok-4.7-high-fast --并发 4 --名 grok校准
  ../.venv-vision/bin/python grok_frames.py P31 [起窗 止窗] --模型 … --并发 60 --并发文件 堪舆并发-grok.txt --名 全量
  （--并发 是线程上限；--并发文件 里的数是同时在跑的窗数，每开一窗前读一次，改了立刻生效）
与 pilot_frames.py（DeepSeek）保持同一套输入，只换调用方式：
- 取帧、出图：同一条解码命令（segment.frames），每帧对清单 sha256；原分辨率，上方 44 像素黑条烧「#序号  frame 帧号」，JPG 质量 95。
- 提示词：逐帧提示词-v2.md 原文（run_frames.prompt_for 按张数改写），末尾加一句「图依次是 @01.jpg …，只在回复里输出 JSON」。
- 调用：cursor-agent -p --mode ask（只读）--output-format json，12 张图放在本窗临时目录、用 @ 附上；格式不对重发一次。
- 落盘：每窗一完成就追加写 逐帧层/<名>/<集>.jsonl，格式同 DeepSeek 版（窗 / 帧 / 行），另记 用时、用量（cursor-agent 回报的 token）、模型；
  重跑跳过已成功的窗。临时图每窗用完即删。
"""
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.argv, _argv = sys.argv[:1], sys.argv          # segment.py / run_frames.py 在导入时不读参数，这里先藏起来再取回
from segment import frames, manifest              # noqa: E402
import run_frames                                 # noqa: E402
from run_frames import prompt_for                 # noqa: E402
sys.argv = _argv

ROOT = Path(__file__).resolve().parent
run_frames.PROMPT = (ROOT / '逐帧提示词-v2.md').read_text()
WIN = 12
BAND = 44
AGENT = str(Path('~/.local/bin/cursor-agent').expanduser())


def opt(name, default):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def burn(img, label):
    h, w = img.shape[:2]
    out = np.zeros((h + BAND, w, 3), np.uint8)
    out[BAND:] = img
    cv2.putText(out, label, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def parse_lines(text, n):
    """同 run_frames.parse，但 Grok 常把一句开场白和第一行 JSON 连在同一行，从每行第一个「{」读起。"""
    rows = []
    for line in text.strip().splitlines():
        i = line.find('{')
        if i >= 0:
            rows.append(json.loads(line[i:].strip().rstrip(',')))
    if len(rows) != n:
        raise ValueError(f'行数 {len(rows)}')
    return rows


def drop_chat(wdir):
    """每窗调一次命令行，Cursor 会把这 12 张图存进 ~/.cursor/chats，一集就能堆上百 GB。
    结果已经落在 jsonl 里，这个会话记录没用，用完就删。只删工作目录正好是本窗的。"""
    root = Path.home() / '.cursor' / 'chats'
    if not root.is_dir():
        return
    needle = str(wdir)
    now = time.time()
    for name in os.listdir(root):
        p = root / name
        try:
            if now - p.stat().st_mtime > 3600:
                continue
        except OSError:
            continue
        for meta in p.glob('*/meta.json'):
            try:
                cwd = json.loads(meta.read_text()).get('cwd')
            except (OSError, ValueError):
                continue
            if cwd == needle:
                shutil.rmtree(p, ignore_errors=True)
                return


def ask(wdir, n, model):
    names = ' '.join(f'@{k:02d}.jpg' for k in range(1, n + 1))
    prompt = (prompt_for(n) + f'\n\n这 {n} 张图依次是：{names}。'
              f'只在回复里输出这 {n} 行 JSON，不要输出其他文字，不要运行任何命令，不要写任何文件。')
    p = subprocess.run([AGENT, '-p', prompt, '--model', model, '--mode', 'ask', '--output-format', 'json',
                        '--trust', '--workspace', str(wdir)], capture_output=True, text=True, timeout=900, cwd=wdir)
    if not p.stdout.strip():
        raise RuntimeError(f'命令行没有输出（退出码 {p.returncode}）：{p.stderr.strip()[-200:]}')
    d = json.loads(p.stdout.strip().splitlines()[-1])
    if d.get('is_error'):
        raise RuntimeError(str(d.get('result'))[:200])
    return d.get('result') or '', d.get('usage') or {}


def main():
    ep = sys.argv[1]
    pos = [a for a in sys.argv[2:] if not a.startswith('--') and sys.argv[sys.argv.index(a) - 1] not in ('--并发', '--名', '--模型', '--窗', '--并发文件')]
    model = opt('--模型', 'grok-4.7-high-fast')
    conc = int(opt('--并发', 4))          # 线程数上限；给了 --并发文件 时，同时在跑的窗数以文件里的数为准（随时可改）
    cfile = opt('--并发文件', None)
    name = opt('--名', 'grok')
    man = manifest(ep)
    total = max(man) + 1
    nwin = (total + WIN - 1) // WIN
    if '--窗' in sys.argv:
        wins = sorted(int(x) for x in opt('--窗', '').split(','))
    else:
        w0 = int(pos[0]) if pos else 0
        w1 = int(pos[1]) if len(pos) > 1 else nwin - 1
        wins = list(range(w0, w1 + 1))
    outdir = ROOT / '逐帧层' / name
    outdir.mkdir(parents=True, exist_ok=True)
    outp = outdir / f'{ep}.jsonl'
    tmp = ROOT / '逐帧层' / 'grok-临时' / name
    done = set()
    if outp.exists():
        for line in outp.open():
            r = json.loads(line)
            if r.get('行'):
                done.add(r['窗'])
    todo = [w for w in wins if w not in done]
    print(ep, model, f'待跑 {len(todo)} 窗（已完成 {len(done)}），并发 {conc}', flush=True)
    lock = threading.Lock()
    stats = {'成功': 0, '失败': 0, '输入': 0, '缓存读': 0, '输出': 0, 't0': time.time()}

    q = queue.Queue(maxsize=conc * 2)

    def producer():
        """顺序解码一遍，只给待跑的窗出图（每窗一个临时目录），送进队列。"""
        todo_set = set(todo)
        start, end = todo[0] * WIN, min((todo[-1] + 1) * WIN, total)
        cur, idxs = None, []
        for idx, jpg in frames(ep, start, end - start):
            if hashlib.sha256(jpg).hexdigest() != man[idx]:
                print(f'{ep} 帧 {idx} 与清单 sha256 不一致，停', flush=True)
                break
            w = idx // WIN
            if w not in todo_set:
                continue
            if w != cur:
                if cur is not None:
                    q.put((cur, idxs))
                cur, idxs = w, []
                shutil.rmtree(tmp / f'{ep}-{w}', ignore_errors=True)
                (tmp / f'{ep}-{w}').mkdir(parents=True)
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            k = len(idxs) + 1
            cv2.imwrite(str(tmp / f'{ep}-{w}' / f'{k:02d}.jpg'), burn(img, f'#{k:02d}  frame {idx}'),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            idxs.append(idx)
        if cur is not None:
            q.put((cur, idxs))
        for _ in range(conc):
            q.put(None)

    cond = threading.Condition()
    active = [0]

    def target():
        if cfile:
            try:
                return max(1, min(conc, int((ROOT / cfile).read_text().strip())))
            except (OSError, ValueError):
                pass
        return conc

    def worker():
        while True:
            item = q.get()
            if item is None:
                return
            with cond:
                while active[0] >= target():
                    cond.wait(timeout=30)
                active[0] += 1
            try:
                one(*item)
            finally:
                with cond:
                    active[0] -= 1
                    cond.notify_all()

    def one(w, idxs):
        wdir = tmp / f'{ep}-{w}'
        rec = {'窗': w, '帧': idxs, '模型': model}
        t = time.time()
        use = {}
        for attempt in range(2):
            text = ''
            try:
                text, u = ask(wdir, len(idxs), model)
                for k, v in u.items():
                    use[k] = use.get(k, 0) + v
                rec['行'] = parse_lines(text, len(idxs))
                rec.pop('错误', None)
                rec.pop('原文', None)
                break
            except Exception as e:  # 格式不对、超时、命令行报错：重发一次
                rec['错误'] = f'{type(e).__name__}: {e}'[:300]
                rec['原文'] = text[:6000]
                print(ep, f'窗 {w} 第 {attempt + 1} 次失败：{rec["错误"][:160]}', flush=True)
                if any(s in rec['错误'] for s in ('429', 'rate', 'Rate', 'limit', 'Limit', '限流', '频繁')):
                    time.sleep(60)
        rec['用时'] = round(time.time() - t, 1)
        rec['用量'] = use
        rec['时间'] = datetime.now().isoformat(timespec='seconds')
        drop_chat(wdir)
        shutil.rmtree(wdir, ignore_errors=True)
        with lock:
            with outp.open('a') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            stats['成功' if rec.get('行') else '失败'] += 1
            stats['输入'] += use.get('inputTokens', 0)
            stats['缓存读'] += use.get('cacheReadTokens', 0)
            stats['输出'] += use.get('outputTokens', 0)
            n = stats['成功'] + stats['失败']
            if n % 50 == 0 or n == len(todo):
                m = (time.time() - stats['t0']) / 60
                print(ep, f'{datetime.now():%H:%M} {n}/{len(todo)} 窗，失败 {stats["失败"]}，已用 {m:.1f} 分（{n / max(m, 0.1):.1f} 窗/分，同时 {active[0]} 路），'
                      f'token 输入 {stats["输入"]} 缓存读 {stats["缓存读"]} 输出 {stats["输出"]}', flush=True)

    if not todo:
        return
    threads = [threading.Thread(target=producer)] + [threading.Thread(target=worker) for _ in range(conc)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(ep, '结束', json.dumps({k: v for k, v in stats.items() if k != 't0'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

"""指代层：Grok 4.7 / Astra 6.2 各答一遍试点题，和 Kimi、Claude 盲标一起算三家投票（2026-11-18）。

站长 11-18：地纪第 6 步不想再用 Claude 的额度，改用 Kimi K3.1 Pro + Grok 4.7 high + Astra 6.2 max；
先拿紫微试点（P17、P05 共 297 题，Claude 盲标「确定」173 题）当标准答案打分，再定怎么投票。

用法：
  python deixis_trio.py answer grok  [--路数 6] [--只跑 N]     # cursor-agent，Cursor 账户
  python deixis_trio.py answer astra [--路数 4] [--只跑 N]     # ChatGPT 应用自带 codex 命令行，ChatGPT 订阅
  python deixis_trio.py score                                   # 单家成绩 + 三家投票成绩
  python deixis_trio.py answer grok --集 P31,P33,P35            # 地纪正式跑（--只跑 N 是每集各 N 题）
  python deixis_trio.py merge --集 P31,P33,P35                  # 两家一致才采用 → <集>/两家一致.json

提示词、题包（B 包：停顿帧 + 手部裁片）与 Kimi 那次完全相同（run_exp4b.prompt）。结果追加写
指代层/试点/<集>/<名>.jsonl（题号 / 答 / 原始回答 / 秒），断了重跑会跳过已答的题。
计分口径与 pilot_deixis_score.py 相同，门槛不变：确认率 ≥ 50%、指错 ≤ 5%、硬猜 ≤ 3%。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_argv, sys.argv = sys.argv, [sys.argv[0], 'kimi高']   # run_exp4b 一导入就按第一个参数取接口配置；这里只借它的提示词
import run_exp4b
sys.argv = _argv

ROOT = Path(__file__).resolve().parent / '指代层' / '试点'
EPS = ('P17', 'P05')   # 默认是紫微试点两集；地纪正式跑用 --集 P31,P33,P35
CURSOR = str(Path('~/.local/bin/cursor-agent').expanduser())
CODEX = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
NAME = {'grok': 'Grok47高', 'astra': 'Astra62max', 'kimi': 'Kimi-v2'}
TAIL = '只在回复里输出这一个 JSON 对象，不要输出其他文字，不要运行任何命令，不要写任何文件。'


def opt(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


EPS = tuple(opt('--集', ','.join(EPS)).split(','))


def ask_grok(wdir, prompt, names):
    full = prompt + '\n\n图片依次是：' + ' '.join('@' + n for n in names) + '。' + TAIL
    p = subprocess.run([CURSOR, '-p', full, '--model', 'grok-4.7-high', '--mode', 'ask', '--output-format', 'json',
                        '--trust', '--workspace', str(wdir)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900, cwd=wdir)
    if not p.stdout.strip():
        raise RuntimeError(f'命令行没有输出（退出码 {p.returncode}）：{p.stderr.strip()[-200:]}')
    d = json.loads(p.stdout.strip().splitlines()[-1])
    if d.get('is_error'):
        raise RuntimeError(str(d.get('result'))[:200])
    return d.get('result') or ''


def ask_astra(wdir, prompt, names):
    out = Path(wdir) / '_last.txt'
    cmd = [CODEX, 'exec', '-m', 'gpt-6.2-astra', '-c', 'model_reasoning_effort="max"', '-s', 'read-only',
           '--skip-git-repo-check', '--ephemeral', '--color', 'never', '-C', str(wdir), '--output-last-message', str(out)]
    for n in names:
        cmd += ['-i', str(Path(wdir) / n)]
    cmd += ['--', prompt + '\n\n' + TAIL]
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1200, cwd=wdir)
    if not out.exists() or not out.read_text().strip():
        raise RuntimeError(f'没有回答（退出码 {p.returncode}）：{(p.stderr or p.stdout).strip()[-300:]}')
    return out.read_text()


def answer(who):
    ask = {'grok': ask_grok, 'astra': ask_astra}[who]
    limit = opt('--只跑', 0)
    for ep in EPS:
        qs = [q for q in json.loads((ROOT / ep / '题目清单.json').read_text()) if q['停顿帧']]
        outp = ROOT / ep / f'{NAME[who]}.jsonl'
        done = {json.loads(l)['题号'] for l in outp.open()} if outp.exists() else set()
        todo = [q for q in qs if q['题号'] not in done]
        if limit:
            todo = todo[:limit]
        print(ep, who, '待答', len(todo), flush=True)

        def run(q):
            src = sorted((ROOT / ep / '题' / q['题号'] / 'B').glob('*.jpg'))
            wdir = Path(tempfile.mkdtemp(prefix=f'deixis-{who}-'))
            try:
                names = []
                for k, f in enumerate(src, 1):
                    n = f'{k:02d}.jpg'
                    shutil.copy(f, wdir / n)
                    names.append(n)
                t = time.time()
                text = ''
                for attempt in (1, 2):
                    try:
                        text = ask(wdir, run_exp4b.prompt(q), names)
                        break
                    except Exception as e:
                        print(q['题号'], f'第 {attempt} 次出错', str(e)[:160], flush=True)
                        if attempt == 2:
                            return
                m = re.search(r'\{.*\}', text, re.S)
                try:
                    parsed = json.loads(m.group(0)) if m else None
                except Exception:
                    parsed = None
                rec = {'题号': q['题号'], '答': parsed, '原始回答': text, '图数': len(names), '秒': round(time.time() - t, 1)}
                with outp.open('a') as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            finally:
                shutil.rmtree(wdir, ignore_errors=True)

        with ThreadPoolExecutor(opt('--路数', 6 if who == 'grok' else 4)) as ex:
            list(ex.map(run, todo))


def chars(s):
    return {c for c in (s or '') if c.strip() and c not in '□、，。,.()（）'}


def match(g, a):
    if chars(g['目标文字']) and chars(a.get('目标文字')) & chars(g['目标文字']):
        return True
    return g.get('格') is not None and a.get('格') == g.get('格')


def load(name):
    o = {}
    for ep in EPS:
        p = ROOT / ep / f'{name}.jsonl'
        if p.exists():
            for r in map(json.loads, p.open()):
                o[r['题号']] = r['答'] or {}
    return o


def vote(answers):
    """三家投票：至少两家答「是」且目标对得上（有共同字或同一格）才算「是」，目标取这两家共同的字；其余一律当「不采用」。"""
    yes = [a for a in answers if a.get('是指代') == '是' and (chars(a.get('目标文字')) or a.get('格') is not None)]
    for i in range(len(yes)):
        for j in range(i + 1, len(yes)):
            a, b = yes[i], yes[j]
            common = chars(a.get('目标文字')) & chars(b.get('目标文字'))
            same_cell = a.get('格') is not None and a.get('格') == b.get('格')
            if common or same_cell:
                # 目标文字只留两家都写了的字：一家多写的字（可能是硬猜）不进结果
                text = ''.join(c for c in (a.get('目标文字') or '') if c in common)
                return {'是指代': '是', '目标文字': text, '格': a.get('格') if same_cell else None}
    return {'是指代': '不采用'}


def report(label, o, gt):
    sure = {k: v for k, v in gt.items() if v['把握'] == '确定' and k in o}
    yes = {k: v for k, v in sure.items() if v['是指代'] == '是'}
    no = {k: v for k, v in sure.items() if v['是指代'] == '否'}
    conf = sum(1 for k, g in yes.items() if o[k].get('是指代') == '是' and match(g, o[k]))
    concl = [k for k in yes if o[k].get('是指代') == '是' and (chars(o[k].get('目标文字')) or o[k].get('格'))]
    wrong = sum(1 for k in concl if not match(yes[k], o[k]))
    pool = [k for k, g in sure.items() if not chars(g['目标文字']) or g['是指代'] != '是']
    guess = [k for k in pool if chars(o[k].get('目标文字'))]
    noacc = sum(1 for k in no if o[k].get('是指代') in ('否', '看不出', '不采用'))
    pct = lambda a, b: f'{a}/{b}（{a / b:.0%}）' if b else f'{a}/0'
    print(f'{label}：答了 {len(o)} 题，其中盲标确定 {len(sure)}｜确认率 {pct(conf, len(yes))}  指错 {pct(wrong, len(concl))}  '
          f'硬猜 {pct(len(guess), len(pool))}  口头用法识别 {pct(noacc, len(no))}')
    return guess


def score():
    gt = {}
    for f in sorted((ROOT / '盲标' / '结果').glob('*.json')):
        for a in json.loads(f.read_text()):
            gt[a['题号']] = a
    sets = {k: load(v) for k, v in NAME.items()}
    print('门槛：确认率 ≥ 50%、指错 ≤ 5%、硬猜 ≤ 3%')
    for k in ('kimi', 'grok', 'astra'):
        if sets[k]:
            report(NAME[k], sets[k], gt)
    both = set(sets['kimi']) & set(sets['grok']) & set(sets['astra'])
    if both:
        only = {k: {q: v[q] for q in both} for k, v in sets.items()}
        print(f'—— 三家都答了的 {len(both)} 题上 ——')
        for k in ('kimi', 'grok', 'astra'):
            report(NAME[k], only[k], gt)
        v3 = {q: vote([only['kimi'][q], only['grok'][q], only['astra'][q]]) for q in both}
        g = report('三家投票（两家一致才采用）', v3, gt)
        print('投票后答「是」', sum(1 for a in v3.values() if a['是指代'] == '是'), '题；硬猜例：', [(q, v3[q]['目标文字'], gt[q]['是指代']) for q in g[:6]])
        for a, b in (('kimi', 'grok'), ('kimi', 'astra'), ('grok', 'astra')):
            v2 = {q: vote([only[a][q], only[b][q]]) for q in both}
            report(f'两家一致 {NAME[a]} + {NAME[b]}', v2, gt)
    print('各家答案分布：', {NAME[k]: dict(Counter(a.get('是指代') for a in v.values())) for k, v in sets.items() if v})


def merge():
    """正式采用口径（站长 11-18 定）：Grok 和 Astra 两家答案一致才采用，其余一律「不采用」。
    试点成绩：确认率 51%、指错 3%、硬猜 0%，是唯一三项门槛全过的用法。结果写 指代层/试点/<集>/两家一致.json。"""
    g, a = load(NAME['grok']), load(NAME['astra'])
    for ep in EPS:
        qs = [q for q in json.loads((ROOT / ep / '题目清单.json').read_text()) if q['停顿帧']]
        out, miss = [], 0
        for q in qs:
            k = q['题号']
            if k not in g or k not in a:
                miss += 1
                continue
            out.append({'题号': k, '词': q['词'], '说出秒': q['说出秒'], **vote([g[k], a[k]])})
        (ROOT / ep / '两家一致.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
        yes = sum(1 for r in out if r['是指代'] == '是')
        print(f'{ep}：{len(qs)} 题，两家都答了 {len(out)}，缺 {miss}；采用 {yes}，不采用 {len(out) - yes}')


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == 'answer':
        answer(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == 'merge':
        merge()
    else:
        score()

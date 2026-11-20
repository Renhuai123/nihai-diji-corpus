#!/usr/bin/env python3
"""地纪第 7 步「选全集总结」：原来是 Claude 子代理（opus-high-reader）照 提示词/选总结读手提示词-堪舆.md 挑；
站长 11-18 定地纪第 6、7 步不用 Claude 写内容，所以改成外部模型挑（2026-11-19）。Claude 只做工程。

提示词正文（「---」以下）一字不改，占位符按文件头注释填：{集} {集数} {块数} {块文件列表} {本集主题}（本集主题 = 全量配置/PLAN-堪舆.json
该集各大段标签用「；」连起来）。原提示词让读手 Read 各块文件，接口做不到，所以照 cornell_write_trio.py 的做法在后面接【运行说明】：
各块文件的「小标题」「总结候选」两节附在后面（挑总结只用这两节），最终回复只要那个 JSON。

用法（在 第0步/ 下，各块稿子都齐了以后）：
  python cornell_pick_summary.py P31 --by astra --改            读 块N-astra-改.json，默认由 Astra 挑
  python cornell_pick_summary.py P31 --by astra --改 --选手 grok   改由 Grok 挑
  python cornell_pick_summary.py P31 --by astra --改 --只看提示词  不调接口，把要发的整段提示词存到 日志/ 下看
输出：按句拼接/试点/<集>-堪舆笔记块/全集总结选条-<by>[-改].json（cornell_render.py --by=<by> [--改] 出稿时读它；
      _运行 键是调用记录，出稿时跳过）。已有就不重挑（要重挑先把旧文件改名）。
"""
import json
import sys
import time
from pathlib import Path

import cornell_write_trio as T

TPL = T.HERE / '提示词' / '选总结读手提示词-堪舆.md'
RANGE = {'通用规则': (8, 10), '只在本例': (4, 7), '处世方法': (3, 5)}

ADAPT = T.ADAPT_HEAD + (
    '这次你是通过命令行调用的，没有 Read 工具。所以：\n'
    '1. 本次各块用的是 {版本说明}，文件名是 {文件样例}（与上面写的 块N.json 一一对应）。'
    '下面按块附上每个文件里的「小标题」和「总结候选」两节，内容与磁盘上的文件逐字相同（其余各节挑总结用不上，没附）。\n'
    '2. 最终回复只有那一个 JSON 对象，不要任何别的文字，不要运行命令，不要写文件。\n')


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--') and x not in (T.opt('--by', ''), T.opt('--选手', ''))]
    if not a:
        raise SystemExit(__doc__)
    ep, by, rev = a[0], T.opt('--by', ''), '--改' in sys.argv
    who = T.opt('--选手', 'astra')
    if who not in ('astra', 'grok'):
        raise SystemExit('--选手 只能是 astra / grok（地纪第 7 步不用 Claude）')
    suffix = (f'-{by}' if by else '') + ('-改' if rev else '')
    d = T.block_dir(ep)
    blocks = T.load_blocks(ep)
    files = [d / f'块{b["块"]}{suffix}.json' for b in blocks]
    miss = [f.name for f in files if not f.exists()]
    if miss:
        raise SystemExit(f'还缺这些块的稿子：{miss}')
    outp = d / f'全集总结选条{suffix}.json'
    if outp.exists() and '--只看提示词' not in sys.argv:
        raise SystemExit(f'{outp.name} 已有，没重挑（要重挑先把它改名）')
    notes = [json.loads(f.read_text()) for f in files]
    plan = json.loads((T.HERE / '全量配置' / 'PLAN-堪舆.json').read_text())
    n = len(blocks)
    vals = {'集': ep, '集数': int(ep[1:]), '块数': n, '块文件列表': '、'.join(f'块{k}.json' for k in range(1, n + 1)),
            '本集主题': '；'.join(x['标签'] for x in plan[ep])}
    body = T.body_of(TPL, '\n---\n')
    for k, v in vals.items():
        body = body.replace('{' + k + '}', str(v))
    ver = {'-astra-改': 'Astra 起草、Grok 逐条核过、Astra 按核稿意见改过的版本',
           '-astra': 'Astra 起草的版本', '': '原写手的版本'}.get(suffix, f'{suffix} 版')
    text = body + ADAPT.format(版本说明=ver, 文件样例=f'块1{suffix}.json … 块{n}{suffix}.json')
    for b, note in zip(blocks, notes):
        part = {'块': b['块'], '小标题': note.get('小标题'), '总结候选': note.get('总结候选')}
        text += f'\n===== 块{b["块"]}{suffix}.json（小标题、总结候选两节） =====\n' + json.dumps(part, ensure_ascii=False, indent=1)
    text += '\n'
    if '--只看提示词' in sys.argv:
        p = T.HERE / '日志' / f'选总结提示词-{ep}{suffix}.txt'
        p.write_text(text)
        print(f'没调接口；提示词 {len(text)} 字，存在 {p}')
        return
    t0 = time.time()
    reply, meta = T.ask(who, text, [])
    sel = T.parse_json(reply)
    if not sel:
        (d / f'全集总结选条{suffix}-原始回复.txt').write_text(reply)
        raise SystemExit('回复不是合法 JSON，原始回复已存')
    probs = []
    for cat, (lo, hi) in RANGE.items():
        lst = sel.get(cat) or []
        avail = sum(len((x.get('总结候选') or {}).get(cat) or []) for x in notes)
        if not lo <= len(lst) <= hi and len(lst) < avail:
            probs.append(f'{cat} 挑了 {len(lst)} 条（提示词要 {lo}–{hi}，候选共 {avail}）')
        for pair in lst:
            ok = isinstance(pair, list) and len(pair) == 2 and 1 <= pair[0] <= n \
                and 0 <= pair[1] < len((notes[pair[0] - 1].get('总结候选') or {}).get(cat) or [])
            if not ok:
                probs.append(f'{cat} 的 {pair} 不存在')
        if lst != sorted(lst) or len({tuple(p) for p in lst if isinstance(p, list)}) != len(lst):
            probs.append(f'{cat} 没按块号、序号升序或有重复')
    sel['_运行'] = {'模型': T.WHO[who], '用时秒': round(time.time() - t0), '时间': time.strftime('%Y-%m-%d %H:%M:%S'),
                   '读的稿': f'块N{suffix}.json', '程序核出的问题': probs, **meta}
    outp.write_text(json.dumps(sel, ensure_ascii=False, indent=1))
    print(f'已存 {outp.name}：' + '，'.join(f'{c} {len(sel.get(c) or [])} 条' for c in RANGE) + f'｜{sel["_运行"]["用时秒"]} 秒')
    for p in probs:
        print('  ⚠', p)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""地纪第 7 步：Grok 4.7 high 逐条核康奈尔笔记稿（2026-11-19）。

11-19 试写定「Astra 写主稿、Grok 核」。本程序把一块的笔记稿 + 该块材料（字幕、语音、手、☞ 两家一致的指代、✎ 板书清单）
+ 写手提示词里的规则 + 板书图，交给 Grok 逐条判：编造 / 改写失真 / 说话人 / 帧号 / 板书认字 / 要点栏 / 总结归类 / 引文。
每条判「通过 / 要改 / 删」；要改、删必须写理由、抄材料原文、给改法。程序再核一遍 Grok 抄的「材料原文」是不是真在材料里。
Claude 只做工程：本程序不写、不改笔记内容。调用方式照 cornell_write_trio.py（cursor-agent，ask 模式，stdin=/dev/null，图片 @文件）。

用法（在 第0步/ 下）：
  python cornell_grok_check.py P31 1 2 3 --by astra        核 块N-astra.json，块号可写 all（只核已有稿的块）
  python cornell_grok_check.py P37 all                      不加 --by：核 块N.json（P37 是 Claude 写手的稿）
  python cornell_grok_check.py P31 1 2 3 --by astra --稿 改  核改后的 块N-astra-改.json，输出 核对-grok-块N-改.json
  python cornell_grok_check.py P31 --by astra --汇总         不调接口，只汇总已有的核对结果
  选项：--路数 N（默认 3，最多 3）；--重跑（已有结果也重核）
输出：按句拼接/试点/<集>-堪舆笔记块/核对-grok-块N.json（逐条判 + 统计 + 引文核对 + 用时），原始回复存 核对原始/块N-grok.txt。
续跑：结果已在、JSON 合格、且所核稿子的 sha1 没变的块跳过；稿子改过（sha1 变了）会重核。
"""
import hashlib
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cornell_write_trio as T

TAGS = ('口述', '叠图', '板书', '指代', '推断')
KINDS = ('编造', '失真', '说话人', '帧号', '板书', '要点栏', '总结归类', '引文', '其他')
VERDICTS = ('通过', '要改', '删')
SUM_CATS = ('通用规则', '只在本例', '处世方法')
FPS = 30


def tc(f):
    s = int(f / FPS)
    return f'{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}'


def norm(s):
    return ''.join(ch for ch in (s or '') if ch.isalnum())


def sha1_file(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


# ───────────────────────── 稿子编号 ─────────────────────────

def note_items(note):
    """给稿子的每一条编号：正文条目「行.条」（从 1 数），总结候选「类-序」（从 1 数）。返回 [(编号, 种类, 内容)]。"""
    out = []
    for ri, row in enumerate(note.get('行', []), 1):
        for ii, it in enumerate(row.get('条目', []), 1):
            out.append((f'{ri}.{ii}', '条目', it))
    for cat in SUM_CATS:
        for si, s in enumerate((note.get('总结候选') or {}).get(cat) or [], 1):
            out.append((f'{cat}-{si}', '总结', s))
    return out


def item_line(it):
    a, e = it.get('起帧'), it.get('止帧')
    span = f'第 {a} 帧（{tc(a)}）' if a == e else f'第 {a}–{e} 帧（{tc(a)}–{tc(e)}）'
    return f'{it.get("标签")}｜{span}｜{it.get("文字", "")}'


def render_note(note):
    """稿子按编号逐条列出（给核稿人 / 改稿人看）。"""
    L = [f'小标题：{note.get("小标题", "")}', '']
    for ri, row in enumerate(note.get('行', []), 1):
        L.append(f'第 {ri} 行　提示：{row.get("提示", "")}')
        for ii, it in enumerate(row.get('条目', []), 1):
            L.append(f'  [{ri}.{ii}] {item_line(it)}')
    L += ['', '总结候选：']
    for cat in SUM_CATS:
        for si, s in enumerate((note.get('总结候选') or {}).get(cat) or [], 1):
            L.append(f'  [{cat}-{si}] {s}')
    L += ['', '写手自己记的待核（供参考，不用判）：']
    L += [f'  · {x}' for x in note.get('待核', [])] or ['  （无）']
    return '\n'.join(L)


# ───────────────────────── 规则（取自写手提示词） ─────────────────────────

def writer_rules(ep, blocks, b):
    """写手提示词里「画面怎么看」「写作规则」两节原文（块目录里有 写手提示词-块N.md 就用它，没有就按模板现算、不存盘）。"""
    text = T.writer_prompt(ep, blocks, b, save=False)
    secs = re.split(r'\n(?=## )', text)
    keep = [s.strip() for s in secs if s.startswith('## 画面怎么看') or s.startswith('## 写作规则')]
    head = secs[0].strip().splitlines()[0]
    m = re.search(r'(本集没有转写后期贴图[^。]*。)', head)
    if m:
        keep.insert(0, m.group(1))
    return '\n\n'.join(keep)


def format_issues(ep, blocks, b, note):
    """程序查规则 4、5 的格式：行数（按本块写手提示词的「本块大约写 a–b 行」）、每行 2–5 条、每条 30–150 字。"""
    lo, hi = map(int, T.writer_vals(ep, blocks, b)['行数'].split('–'))
    m = re.search(r'本块大约写 (\d+)–(\d+) 行', T.writer_prompt(ep, blocks, b, save=False))
    if m:
        lo, hi = map(int, m.groups())
    out = []
    if not lo <= len(note.get('行', [])) <= hi:
        out.append(f'全块 {len(note.get("行", []))} 行（规定大约 {lo}–{hi} 行）')
    for ri, row in enumerate(note.get('行', []), 1):
        k = len(row.get('条目', []))
        if not 2 <= k <= 5:
            out.append(f'第 {ri} 行 {k} 条（规定每行 2–5 条）')
        for ii, it in enumerate(row.get('条目', []), 1):
            L = len(it.get('文字', ''))
            if L < 30 or L > 150:
                out.append(f'[{ri}.{ii}] {L} 字（规定大约 30–150 字）')
    return out


# ───────────────────────── 提示词 ─────────────────────────

FMT_NOTE = '''
## 程序查出的格式问题（供参考，规则 4、5）
{列表}
这几处只是行数、条数、字数不合规定，不单独判。若某条短到意思说不清、或某行塞进了不相干的内容，就在相应编号的判里写出来（问题选「其他」，建议改法写清怎么并、怎么拆、怎么补）；只是短但意思完整、有依据的，照常判通过。
'''

CHECK_TASK = '''任务：你是核稿人。下面是倪海厦《天纪》堪舆学（天纪合辑第 {集数} 集，{集}）第 {n} 块的康奈尔笔记稿（另一位写手写的），以及写这份稿所依据的全部材料和板书图。请逐条核对这份稿，判断每一条站不站得住。只依据材料和附图判断，不许用你自己知道的风水、堪舆、罗盘、紫微斗数、八字等知识去判对错。

## 写手当时要遵守的规则（写手提示词原文摘出）
{规则}

## 每条要核的事
1. 编造：条目里有没有材料里找不到的内容——倪师没说过的话、数字、地名、人名、断语、因果关系。
2. 改写失真：转述的意思变了没有；轻重变了没有（把「可能」写成「一定」、把举例写成规则、把随口一提写成重点、把倪师否定的写成肯定，或反过来）。转述本身是允许的，意思和轻重没变就算通过，不要因为没用原话就判要改。
3. 说话人：是倪师自己的话，还是他转述别人（古书、某位先生、学生、故事里的人物）的话，有没有搞混。
4. 帧号：起帧、止帧框住的那几句，是不是这条所依据的话（材料每行方括号里是「第起–管到帧」）；板书条的帧号是不是写的那张图；指代条是不是用了 ☞ 行里「是（确定）」的那一题。
5. 板书认字：看附图，粉笔字认得对不对、图形描述对不对、认不出的有没有硬猜。
6. 要点栏：画面左边竖栏是上传者后期加的要点栏，有没有把那里的字当成倪师的话或粉笔字。
7. 总结归类：总结候选三类（通用规则＝倪师当普遍规律讲的；只在本例＝只针对某个地方、某座坟、某栋房子、某个人或某件事；处世方法＝不是风水规则，是待人处事、跟客户说话之类）归得牵不牵强，句子本身是否忠于材料、帧号对不对。
8. 引文：「」里的原话必须是材料「字幕」那一栏的原字（可用……省略、可按规则 2 改明显的同音错字并在待核里记一笔），不能是语音栏的字，不能把隔得很远的句子拼成一句。

## 判法
每条只能判三种之一：
- 通过：站得住。不影响意思的小毛病（措辞、字数）也算通过，不要为挑而挑。
- 要改：有上面 1–8 的问题，但能改好。
- 删：材料里找不到依据，或问题大到改不好。
判「要改」「删」的，必须写：
- 问题：从这几个里选一个或几个：编造、失真、说话人、帧号、板书、要点栏、总结归类、引文、其他；
- 理由：一两句说清错在哪；
- 材料原文：至少一条，逐字从下面附的材料里复制能证明问题的那几行（整行带行首方括号，如「[0123 00:05:01 第9030–9101帧] 字幕原文（0.9）｜语音：……」），板书问题可以写「图 f012345.jpg（第12345帧）：图上看到的是……」；
- 建议改法：给出改后的整条文字（帧号要改就写新的起帧、止帧），删的写删掉后要不要把哪句挪进待核。

## 输出（最终回复只有这一个 JSON 对象，不要任何别的文字，不要运行命令，不要写文件）
{{"块": {n}, "判": [
  {{"编号": "1.1", "结论": "通过"}},
  {{"编号": "1.2", "结论": "要改", "问题": ["失真"], "理由": "……", "材料原文": ["[0012 00:00:36 第1092–1199帧] ……"], "建议改法": "……"}},
  {{"编号": "通用规则-1", "结论": "删", "问题": ["总结归类"], "理由": "……", "材料原文": ["……"], "建议改法": "……"}}
], "总评": "一两句话"}}
「判」必须把下面列出的 {条数} 个编号每个判一次、按原顺序、不多不少（正文条目 {正文数} 个、总结候选 {总结数} 个）。JSON 字符串里不要出现英文双引号，引文一律用「」。

## 待核的笔记稿（共 {条数} 条；编号写在方括号里）
{稿}

## 板书图
{图}

## 材料
下面是本块材料的全文（与磁盘上的 块{n}-材料.md 逐字相同）。
'''


def check_message(ep, blocks, b, note):
    items = note_items(note)
    images = T.board_images(b)
    pics = '、'.join(f'@{Path(f).name}（第 {int(Path(f).stem[1:])} 帧）' for f in images)
    vals = {'集': ep, '集数': int(ep[1:]), 'n': b['块'], '规则': writer_rules(ep, blocks, b),
            '条数': len(items), '正文数': sum(k == '条目' for _, k, _ in items),
            '总结数': sum(k == '总结' for _, k, _ in items), '稿': render_note(note),
            '图': f'已作为图片随本消息附上，共 {len(images)} 张，顺序同材料末尾「板书图清单」：{pics}。核板书条时请逐张看。' if images else '本块没有板书图。'}
    text = CHECK_TASK.format(**vals)
    fmt = format_issues(ep, blocks, b, note)
    if fmt:   # 没有格式问题时不加这一节（P31 块 1–3 Astra 稿就没有）
        text = text.replace('\n## 板书图\n', FMT_NOTE.format(列表='\n'.join(f'- {x}' for x in fmt)) + '\n## 板书图\n', 1)
    mat = T.block_dir(ep) / f'块{b["块"]}-材料.md'
    return text + T.files_appendix([mat]), images, items, fmt


# ───────────────────────── 程序核 Grok 的回复 ─────────────────────────

def verify_quotes(j, mat_norm, board_frames):
    """Grok 抄的「材料原文」逐条核：去掉行首方括号后，各段（按……切）去标点要在材料全文里原样找到；
    或者是引图（写了某张板书图的帧号 / 文件名）。返回 (核上条数, 只引图条数, 没核上的原文列表)。"""
    ok = pic = 0
    bad = []
    for q in j.get('材料原文') or []:
        q = str(q)
        frames = {int(x) for x in re.findall(r'f(\d{6})', q)} | {int(x) for x in re.findall(r'第\s*(\d+)\s*帧', q)}
        body = re.sub(r'^\s*\[[^\]]*\]', '', q)
        body = re.sub(r'^(图\s*)?f\d{6}\.jpg[^：:]*[：:]', '', body.strip())
        segs = [norm(s) for s in re.split(r'…+|\.{3,}|｜', body)]
        segs = [s for s in segs if len(s) >= 2]
        if segs and all(s in mat_norm for s in segs):
            ok += 1
        elif frames & board_frames:
            pic += 1
        else:
            bad.append(q[:120])
    return ok, pic, bad


def grade(reply, items, mat_text, board_frames):
    d = T.parse_json(reply)
    if not d or not isinstance(d.get('判'), list):
        return None
    ids = [i for i, _, _ in items]
    by_id = {i: (k, c) for i, k, c in items}
    seen, extra, dup, judged = set(), [], [], []
    mat_norm = norm(mat_text)
    for j in d['判']:
        if not isinstance(j, dict):
            continue
        i = str(j.get('编号', '')).strip().strip('[]')
        if i not in by_id:
            extra.append(i)
            continue
        if i in seen:
            dup.append(i)
            continue
        seen.add(i)
        j['编号'] = i
        if j.get('结论') not in VERDICTS:
            j['_结论不认识'] = j.get('结论')
        if j.get('结论') in ('要改', '删'):
            ok, pic, bad = verify_quotes(j, mat_norm, board_frames)
            j['_材料原文核对'] = {'核上': ok, '只引图': pic, '没核上': bad}
            if not (j.get('理由') and (ok or pic)):
                j['_缺理由或原文'] = True
        k, c = by_id[i]
        j['_原'] = item_line(c) if k == '条目' else c
        judged.append(j)
    order = {i: n for n, i in enumerate(ids)}
    judged.sort(key=lambda j: order[j['编号']])
    return {'判': judged, '漏判': [i for i in ids if i not in seen], '多判': extra, '重复': dup, '总评': d.get('总评', '')}


def stats(g):
    st = Counter(j.get('结论') for j in g['判'])
    kinds = Counter(k for j in g['判'] if j.get('结论') in ('要改', '删') for k in (j.get('问题') or ['（没写）']))
    q = Counter()
    for j in g['判']:
        c = j.get('_材料原文核对')
        if c:
            q['核上'] += c['核上']
            q['只引图'] += c['只引图']
            q['没核上'] += len(c['没核上'])
            q['缺理由或原文的判'] += bool(j.get('_缺理由或原文'))
    return {'条': len(g['判']) + len(g['漏判']), '通过': st['通过'], '要改': st['要改'], '删': st['删'],
            '漏判': len(g['漏判']), '问题类': dict(kinds), '材料原文': dict(q)}


# ───────────────────────── 跑 ─────────────────────────

def draft_path(ep, n, by, ver):
    return T.block_dir(ep) / (f'块{n}' + (f'-{by}' if by else '') + (f'-{ver}' if ver else '') + '.json')


def out_path(ep, n, ver):
    return T.block_dir(ep) / (f'核对-grok-块{n}' + (f'-{ver}' if ver else '') + '.json')


def positional():
    out, skip = [], False
    for x in sys.argv[1:]:
        if skip:
            skip = False
        elif x in ('--by', '--路数', '--稿'):
            skip = True
        elif not x.startswith('--'):
            out.append(x)
    return out


def done(outp, sha):
    try:
        d = json.loads(outp.read_text())
        return d.get('稿sha1') == sha and isinstance(d.get('判'), list)
    except Exception:
        return False


def run_block(ep, blocks, b, by, ver, force):
    n = b['块']
    dp, op = draft_path(ep, n, by, ver), out_path(ep, n, ver)
    if not dp.exists():
        print(f'块{n}：没有稿子 {dp.name}，跳过', flush=True)
        return None
    sha = sha1_file(dp)
    if not force and done(op, sha):
        print(f'块{n}：已核过（{op.name}），跳过', flush=True)
        return json.loads(op.read_text())
    if op.exists() and not force:
        print(f'块{n}：{op.name} 已有但稿子变了或结果不合格，重核', flush=True)
    note = json.loads(dp.read_text())
    text, images, items, fmt = check_message(ep, blocks, b, note)
    mat_text = (T.block_dir(ep) / f'块{n}-材料.md').read_text()
    board_frames = {x['帧'] for x in b['板书图']}
    raw_dir = T.block_dir(ep) / '核对原始'
    raw_dir.mkdir(exist_ok=True)
    t0 = time.time()
    g, meta, tries = None, {}, []
    for attempt in (1, 2, 3):
        t = time.time()
        try:
            reply, m = T.ask('grok', text, images)
        except Exception as e:
            tries.append({'第几次': attempt, '出错': str(e)[:200], '秒': round(time.time() - t)})
            print(f'块{n} 第 {attempt} 次出错：{str(e)[:160]}', flush=True)
            continue
        (raw_dir / (f'块{n}' + (f'-{ver}' if ver else '') + f'-grok-第{attempt}次.txt')).write_text(reply)
        g2 = grade(reply, items, mat_text, board_frames)
        tries.append({'第几次': attempt, '秒': round(time.time() - t),
                      '结果': '不是合格 JSON' if g2 is None else f'漏判 {len(g2["漏判"])}'})
        if g2 is not None and (g is None or len(g2['漏判']) <= len(g['漏判'])):
            g, meta = g2, m                      # 几次里留漏判最少的那次
        if g is not None and not g['漏判']:
            break
        print(f'块{n} 第 {attempt} 次回复' + ('不是合格 JSON' if g2 is None else f'漏判 {len(g2["漏判"])} 条') + '，重问', flush=True)
        if attempt >= 2 and g is not None:
            break
    if g is None:
        print(f'块{n}：三次都没拿到合格回复，没写结果', flush=True)
        return None
    rec = {'集': ep, '块': n, '稿': dp.name, '稿sha1': sha, '模型': 'Grok 4.7 high（cursor-agent，ask 模式）',
           '附图': len(images), '用时秒': round(time.time() - t0), '各次': tries, '时间': time.strftime('%Y-%m-%d %H:%M:%S'),
           'usage': (meta or {}).get('usage'), '程序查出的格式问题': fmt, '统计': stats(g), **g}
    op.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    print_block(rec)
    return rec


def print_block(rec):
    s = rec['统计']
    kinds = '、'.join(f'{k} {v}' for k, v in sorted(s['问题类'].items(), key=lambda x: -x[1])) or '无'
    q = s['材料原文']
    print(f'块{rec["块"]}（{rec["稿"]}）：{s["条"]} 条｜通过 {s["通过"]} 要改 {s["要改"]} 删 {s["删"]} 漏判 {s["漏判"]}'
          f'｜问题类：{kinds}｜材料原文 核上 {q.get("核上", 0)}、只引图 {q.get("只引图", 0)}、没核上 {q.get("没核上", 0)}'
          f'｜{rec["用时秒"]} 秒', flush=True)


def summarize(ep, nums, ver):
    tot, kinds, secs = Counter(), Counter(), 0
    for n in nums:
        op = out_path(ep, n, ver)
        if not op.exists():
            continue
        rec = json.loads(op.read_text())
        print_block(rec)
        s = rec['统计']
        tot.update({k: s[k] for k in ('条', '通过', '要改', '删', '漏判')})
        tot.update({f'原文{k}': v for k, v in s['材料原文'].items()})
        kinds.update(s['问题类'])
        secs += rec['用时秒']
    if tot['条']:
        print(f'合计 {tot["条"]} 条：通过 {tot["通过"]}、要改 {tot["要改"]}、删 {tot["删"]}、漏判 {tot["漏判"]}；'
              f'问题类 {dict(kinds)}；Grok 抄的材料原文 核上 {tot["原文核上"]}、只引图 {tot["原文只引图"]}、'
              f'没核上 {tot["原文没核上"]}；用时合计 {secs} 秒')


def main():
    a = positional()
    if not a:
        raise SystemExit(__doc__)
    ep = a[0]
    by = T.opt('--by', None)
    ver = T.opt('--稿', None)
    blocks = T.load_blocks(ep)
    want = a[1:]
    todo = blocks if not want or want == ['all'] else [b for b in blocks if str(b['块']) in want]
    if '--汇总' in sys.argv:
        summarize(ep, [b['块'] for b in todo], ver)
        return
    k = min(T.opt('--路数', 3), 3)
    print(f'{ep} Grok 核稿：块 {[b["块"] for b in todo]}，稿 = 块N{"-" + by if by else ""}{"-" + ver if ver else ""}.json，{k} 路', flush=True)
    with ThreadPoolExecutor(k) as ex:
        list(ex.map(lambda b: run_block(ep, blocks, b, by, ver, '--重跑' in sys.argv), todo))
    summarize(ep, [b['块'] for b in todo], ver)


if __name__ == '__main__':
    main()

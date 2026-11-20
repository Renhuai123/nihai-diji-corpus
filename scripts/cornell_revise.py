#!/usr/bin/env python3
"""地纪第 7 步：把 Grok 判「要改 / 删」的条目交回 Astra 改（2026-11-19）。

流程：cornell_grok_check.py 出 核对-grok-块N.json → 本程序挑出其中「要改」「删」的条目，连同 Grok 的理由、材料原文、
建议改法、该块材料和相关板书图交给 Astra，让它只处理这些条目：同意就改 / 删；不同意可以保留原文，但必须写理由。
Astra 只回「处理清单」（每个被标编号一条），由程序把改动套到原稿上，别的条目一字不动；套完再用 difflib 把改前改后逐条比一遍，
核「只动了被标的条目」。Claude 只做工程，不写、不改笔记内容。调用方式照 cornell_write_trio.py（codex exec，只读，stdin=/dev/null）。

用法（在 第0步/ 下）：
  python cornell_revise.py P31 1 2 3 --by astra           块号可写 all（只改有核对结果的块）
  python cornell_revise.py P31 --by astra --汇总           不调接口，只汇总已有的改稿记录
  python cornell_revise.py P37 all                         不加 --by：改 块N.json（P37 Claude 写手的稿），输出 块N-改.json；改稿人仍是 Astra
  选项：--路数 N（默认 1：后台写手占着 Astra 2 路）；--重跑（已有改稿也重来）
输出：按句拼接/试点/<集>-堪舆笔记块/块N-<by>-改.json = 原稿套上改动 + 「改稿记录」（被标几条、改 / 删 / 不同意保留 / 没回 / 被拒、
      每条明细、比对结果）；Astra 原始回复存 改稿原始/块N-<by>.txt。被标 0 条的块不调 Astra，原样复制并写明。
续跑：块N-<by>-改.json 已在、且原稿和核对结果的 sha1 都没变的块跳过。
之后：python cornell_render.py <集> --堪舆 --check --by=<by> --改   核改后的版本（报告写 校验报告-<by>-改.json）。
"""
import copy
import difflib
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cornell_grok_check as C
import cornell_write_trio as T

TAGS = C.TAGS
SUM_CATS = C.SUM_CATS
ACTIONS = ('改', '删', '保留')


def sha1_file(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


# ───────────────────────── 提示词 ─────────────────────────

REVISE_TASK = '''任务：下面是倪海厦《天纪》堪舆学（天纪合辑第 {集数} 集，{集}）第 {n} 块的康奈尔笔记稿（下称「原稿」）。核稿人（Grok 4.7）对照材料逐条核过，对其中 {k} 条判了「要改」或「删」。请你只处理这 {k} 条：
- 同意核稿意见：按意见改，或删掉。改的时候仍守原来的写作规则（附在后面），帧号、引文都要能对回材料。
- 不同意：保留原文，但必须在「理由」里说清为什么，并引材料原文（逐字抄材料行）为证。
- 核稿意见也可能错，请自己对照材料和板书图判断，不要照单全收。
- 不许动其他条目、小标题、提示问句；不许新增条目。
- 改字或拿不准的地方，可以在「新增待核」里加一句（写清第几帧）；核稿意见说「删后挪进待核」的，也写在这里。
只依据材料和附图，不许用你自己知道的风水、堪舆、罗盘、紫微斗数、八字等知识去补充、纠正或解释。

## 原稿（逐条编号；正文条目编号「行.条」，总结候选编号「类-序」，都从 1 数）
{稿}

## 核稿意见（共 {k} 条，只处理这些编号）
{意见}

## 写作规则（写手提示词原文摘出，改的时候照守）
{规则}

## 板书图
{图}

## 输出（最终回复只有这一个 JSON 对象，不要任何别的文字，不要运行命令，不要写文件）
{{"块": {n}, "处理": [
  {{"编号": "3.2", "动作": "改", "新条目": {{"标签": "口述", "文字": "……", "起帧": 1234, "止帧": 1300}}, "理由": "同意：……"}},
  {{"编号": "5.1", "动作": "删", "理由": "同意：……"}},
  {{"编号": "处世方法-1", "动作": "改", "新文字": "……（第 a–b 帧）", "新类": "只在本例", "理由": "……"}},
  {{"编号": "2.4", "动作": "保留", "理由": "不同意：……材料原文「[0123 …] ……」……"}}
], "新增待核": ["……（第 a 帧）"]}}
- 「处理」把上面 {k} 个编号每个回一次，不多不少；「动作」只能是 改 / 删 / 保留。
- 正文条目改：给「新条目」整条（标签只能是 口述、叠图、板书、指代、推断；起帧、止帧是整数；板书的起帧 = 止帧 = 那张图的帧号）。
- 总结候选改：给「新文字」（一句话，句末括号注出处帧号范围）；觉得归错类就加「新类」（通用规则 / 只在本例 / 处世方法），不改类就不写「新类」。
- 没有要加的待核就写 "新增待核": []。JSON 字符串里不要出现英文双引号，引文一律用「」。

## 材料
下面是本块材料的全文（与磁盘上的 块{n}-材料.md 逐字相同）。
'''


def opinion_lines(flagged):
    L = []
    for j in flagged:
        L.append(f'[{j["编号"]}] 判：{j.get("结论")}｜问题：{"、".join(j.get("问题") or []) or "（没写）"}')
        L.append(f'  原条目：{j.get("_原", "")}')
        L.append(f'  理由：{j.get("理由", "")}')
        for q in j.get('材料原文') or []:
            L.append(f'  材料原文：{q}')
        L.append(f'  建议改法：{j.get("建议改法", "")}')
    return '\n'.join(L)


def pick_images(b, note, flagged):
    """只附和被标条目有关的板书图：被标的板书条的帧，以及意见里提到的板书图帧号。"""
    board = {x['帧']: x['图'] for x in b['板书图']}
    items = dict((i, c) for i, k, c in C.note_items(note) if k == '条目')
    want = set()
    for j in flagged:
        it = items.get(j['编号'])
        if it and it.get('标签') == '板书':
            want.add(it.get('起帧'))
        blob = ' '.join([str(j.get(k, '')) for k in ('理由', '建议改法')] + [str(x) for x in j.get('材料原文') or []])
        want |= {int(x) for x in re.findall(r'f(\d{6})', blob)} | {int(x) for x in re.findall(r'第\s*(\d+)\s*帧', blob)}
    return [board[f] for f in sorted(want) if f in board]


def revise_message(ep, blocks, b, note, flagged):
    images = pick_images(b, note, flagged)
    pics = '、'.join(f'{Path(f).name}（第 {int(Path(f).stem[1:])} 帧）' for f in images)
    vals = {'集': ep, '集数': int(ep[1:]), 'n': b['块'], 'k': len(flagged), '稿': C.render_note(note),
            '意见': opinion_lines(flagged), '规则': C.writer_rules(ep, blocks, b),
            '图': (f'和被标条目有关的板书图已作为图片随本消息附上，共 {len(images)} 张：{pics}。' if images else
                  '这次被标的条目不涉及板书图，没有附图。')}
    text = REVISE_TASK.format(**vals)
    mat = T.block_dir(ep) / f'块{b["块"]}-材料.md'
    return text + T.files_appendix([mat]), images


# ───────────────────────── 套改动 ─────────────────────────

FRAME_RE = re.compile(r'第\s*(\d+)\s*(?:[–—\-~～至到]\s*(\d+)\s*)?帧')


def check_new_item(it, board_frames):
    if not isinstance(it, dict):
        return '新条目不是对象'
    if it.get('标签') not in TAGS:
        return f'标签不认识：{it.get("标签")}'
    if not isinstance(it.get('文字'), str) or not it['文字'].strip():
        return '文字是空的'
    a, e = it.get('起帧'), it.get('止帧')
    if not isinstance(a, int) or not isinstance(e, int) or a > e:
        return f'帧号不对：{a}–{e}'
    if '"' in it['文字']:
        return '文字里有英文双引号'
    return None


def apply(note, flagged_ids, ans, board_frames):
    """把 Astra 的处理清单套到原稿上。返回 (新稿, 明细, 被拒, 没回, 新增待核)。"""
    new = copy.deepcopy(note)
    new.pop('改稿记录', None)
    acts, rejected = {}, []
    for x in (ans or {}).get('处理') or []:
        if not isinstance(x, dict):
            continue
        i = str(x.get('编号', '')).strip().strip('[]')
        if i not in flagged_ids:
            rejected.append({'编号': i, '原因': '不是被标的条目，越权改动，没采用', '处理': x})
            continue
        if i in acts:
            rejected.append({'编号': i, '原因': '同一编号回了两次，只用第一次', '处理': x})
            continue
        if x.get('动作') not in ACTIONS:
            rejected.append({'编号': i, '原因': f'动作不认识：{x.get("动作")}，按保留处理', '处理': x})
            continue
        if x.get('动作') == '保留' and not str(x.get('理由', '')).strip():
            rejected.append({'编号': i, '原因': '保留但没写理由，按「没回」记', '处理': x})
            continue
        acts[i] = x
    missing = [i for i in flagged_ids if i not in acts and i not in {r['编号'] for r in rejected}]

    # 正文条目
    rows_out, removed_rows = [], []
    for ri, row in enumerate(new.get('行', []), 1):
        kept = []
        for ii, it in enumerate(row.get('条目', []), 1):
            i = f'{ri}.{ii}'
            x = acts.get(i)
            if not x or x['动作'] == '保留':
                kept.append(it)
            elif x['动作'] == '删':
                pass
            else:
                bad = check_new_item(x.get('新条目'), board_frames)
                if bad:
                    rejected.append({'编号': i, '原因': f'新条目不合格（{bad}），保留原文', '处理': x})
                    acts.pop(i)
                    kept.append(it)
                else:
                    kept.append({k: x['新条目'][k] for k in ('标签', '文字', '起帧', '止帧')})
        if kept:
            row['条目'] = kept
            rows_out.append(row)
        else:
            removed_rows.append(row.get('提示'))
    new['行'] = rows_out

    # 总结候选
    sums = new.get('总结候选') or {}
    moved = []
    out = {c: [] for c in SUM_CATS}
    for cat in SUM_CATS:
        for si, s in enumerate(sums.get(cat) or [], 1):
            i = f'{cat}-{si}'
            x = acts.get(i)
            if not x or x['动作'] == '保留':
                out[cat].append(s)
            elif x['动作'] == '删':
                pass
            else:
                txt = str(x.get('新文字') or '').strip()
                to = x.get('新类') or cat
                if not txt or to not in SUM_CATS:
                    rejected.append({'编号': i, '原因': '新文字空或新类不认识，保留原文', '处理': x})
                    acts.pop(i)
                    out[cat].append(s)
                elif to == cat:
                    out[cat].append(txt)
                else:
                    moved.append((to, txt))
    for to, txt in moved:            # 换类的条目接在目标类末尾
        out[to].append(txt)
    new['总结候选'] = out

    adds = [str(x) for x in (ans or {}).get('新增待核') or [] if str(x).strip()]
    new['待核'] = list(note.get('待核', [])) + adds
    return new, acts, rejected, missing, adds, removed_rows, moved


def diff_check(before, after, flagged_ids, moved):
    """不看改动清单，直接比原稿和新稿：动到的条目必须全在被标编号里。"""
    def flat(note):
        out = []
        for ri, row in enumerate(note.get('行', []), 1):
            for ii, it in enumerate(row.get('条目', []), 1):
                out.append((f'{ri}.{ii}', json.dumps([row.get('提示'), it], ensure_ascii=False, sort_keys=True)))
        return out

    touched, problems = set(), []
    B, A = flat(before), flat(after)
    sm = difflib.SequenceMatcher(None, [c for _, c in B], [c for _, c in A], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        touched |= {B[i][0] for i in range(i1, i2)}
        if tag == 'insert':
            problems.append(f'正文多出条目：{[A[j][1][:60] for j in range(j1, j2)]}')
    moved_in = {}
    for to, txt in moved:
        moved_in.setdefault(to, []).append(txt)
    for cat in SUM_CATS:
        b = (before.get('总结候选') or {}).get(cat) or []
        a = (after.get('总结候选') or {}).get(cat) or []
        sm = difflib.SequenceMatcher(None, b, a, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            touched |= {f'{cat}-{i + 1}' for i in range(i1, i2)}
            extra = [a[j] for j in range(j1, j2) if a[j] not in moved_in.get(cat, [])]
            if tag == 'insert' and extra:
                problems.append(f'总结「{cat}」多出：{extra}')
    if before.get('小标题') != after.get('小标题'):
        problems.append('小标题变了')
    kept_rows = [r.get('提示') for r in after.get('行', [])]
    if [p for p in (r.get('提示') for r in before.get('行', [])) if p in kept_rows] != kept_rows:
        problems.append('提示问句变了或换了顺序')
    if after.get('待核', [])[:len(before.get('待核', []))] != before.get('待核', []):
        problems.append('原有待核被改动')
    outside = sorted(touched - set(flagged_ids))
    return {'只动了被标条目': not outside and not problems, '动到的编号': sorted(touched),
            '动了未标条目': outside, '其他问题': problems}


# ───────────────────────── 跑 ─────────────────────────

def tag(by):
    return f'-{by}' if by else ''      # 不加 --by：改 块N.json（如 P37 Claude 写手的稿），输出 块N-改.json


def paths(ep, n, by):
    d = T.block_dir(ep)
    return d / f'块{n}{tag(by)}.json', d / f'核对-grok-块{n}.json', d / f'块{n}{tag(by)}-改.json'


def done(outp, sha_d, sha_c):
    try:
        r = json.loads(outp.read_text())['改稿记录']
        return r['原稿sha1'] == sha_d and r['核对sha1'] == sha_c
    except Exception:
        return False


def run_block(ep, blocks, b, by, force):
    n = b['块']
    dp, cp, op = paths(ep, n, by)
    if not dp.exists() or not cp.exists():
        print(f'块{n}：缺 {dp.name if not dp.exists() else cp.name}，跳过', flush=True)
        return None
    sha_d, sha_c = sha1_file(dp), sha1_file(cp)
    if not force and done(op, sha_d, sha_c):
        print(f'块{n}：已改过（{op.name}），跳过', flush=True)
        return json.loads(op.read_text())
    note, chk = json.loads(dp.read_text()), json.loads(cp.read_text())
    if chk.get('稿sha1') != sha_d:
        print(f'块{n}：核对结果针对的不是现在这份 {dp.name}（sha1 不符），先重跑 cornell_grok_check.py', flush=True)
        return None
    flagged = [j for j in chk['判'] if j.get('结论') in ('要改', '删')]
    ids = [j['编号'] for j in flagged]
    rec = {'原稿': dp.name, '原稿sha1': sha_d, '核对': cp.name, '核对sha1': sha_c, '被标': len(ids),
           '被标编号': ids, '时间': time.strftime('%Y-%m-%d %H:%M:%S')}
    board_frames = {x['帧'] for x in b['板书图']}
    if not flagged:
        new = copy.deepcopy(note)
        rec.update({'模型': None, '用时秒': 0, '说明': 'Grok 全部判通过，没调 Astra，原样复制', '改': 0, '删': 0,
                    '不同意保留': 0, '没回': 0, '被拒': 0, '明细': [], '新增待核': []})
        rec['比对'] = diff_check(note, new, ids, [])
        new['改稿记录'] = rec
        op.write_text(json.dumps(new, ensure_ascii=False, indent=1))
        print(f'块{n}：Grok 全判通过，原样复制', flush=True)
        return new
    text, images = revise_message(ep, blocks, b, note, flagged)
    raw_dir = T.block_dir(ep) / '改稿原始'
    raw_dir.mkdir(exist_ok=True)
    t0, ans, tries = time.time(), None, []
    for attempt in (1, 2, 3):
        t = time.time()
        try:
            reply, meta = T.ask('astra', text, images)
        except Exception as e:
            tries.append({'第几次': attempt, '出错': str(e)[:200], '秒': round(time.time() - t)})
            print(f'块{n} 第 {attempt} 次出错：{str(e)[:160]}', flush=True)
            continue
        (raw_dir / f'块{n}{tag(by)}-第{attempt}次.txt').write_text(reply)
        a = T.parse_json(reply)
        got = {str(x.get('编号', '')).strip('[] ') for x in (a or {}).get('处理') or [] if isinstance(x, dict)}
        miss = [i for i in ids if i not in got]
        tries.append({'第几次': attempt, '秒': round(time.time() - t),
                      '结果': '不是合格 JSON' if a is None else f'没回 {len(miss)}'})
        if a is not None and (ans is None or len(miss) < ans[1]):
            ans = (a, len(miss))
        if a is not None and not miss:
            break
        print(f'块{n} 第 {attempt} 次回复' + ('不是合格 JSON' if a is None else f'没回 {len(miss)} 条') + '，重问', flush=True)
        if attempt >= 2 and ans is not None:
            break
    if ans is None:
        print(f'块{n}：三次都没拿到合格回复，没写改稿', flush=True)
        return None
    new, acts, rejected, missing, adds, removed_rows, moved = apply(note, ids, ans[0], board_frames)
    old_items = {i: c for i, _, c in C.note_items(note)}
    rej_ids = {r['编号'] for r in rejected}
    detail = []
    for j in flagged:
        x = acts.get(j['编号'])
        detail.append({'编号': j['编号'], 'Grok结论': j.get('结论'), 'Grok问题': j.get('问题'), 'Grok理由': j.get('理由'),
                       'Grok建议': j.get('建议改法'),
                       '动作': x['动作'] if x else ('回复不合格被拒（保留原文）' if j['编号'] in rej_ids else '没回（保留原文）'),
                       'Astra理由': (x or {}).get('理由', ''), '原': old_items.get(j['编号']),
                       '新': (x or {}).get('新条目') or (x or {}).get('新文字'),
                       **({'新类': x['新类']} if x and x.get('新类') else {})})
    cnt = lambda k: sum(1 for x in acts.values() if x['动作'] == k)
    rec.update({'模型': T.WHO['astra'], '附图': len(images), '用时秒': round(time.time() - t0), '各次': tries,
                '改': cnt('改'), '删': cnt('删'), '不同意保留': cnt('保留'), '没回': len(missing),
                '被拒': len(rejected), '被拒明细': rejected, '删掉的空行': removed_rows,
                '明细': detail, '新增待核': adds})
    rec['比对'] = diff_check(note, new, ids, moved)
    new['改稿记录'] = rec
    op.write_text(json.dumps(new, ensure_ascii=False, indent=1))
    print_block(n, rec)
    return new


def print_block(n, r):
    c = r['比对']
    print(f'块{n}：被标 {r["被标"]}｜改 {r["改"]} 删 {r["删"]} 不同意保留 {r["不同意保留"]} 没回 {r["没回"]} 被拒 {r["被拒"]}'
          f'｜新增待核 {len(r["新增待核"])}｜比对：{"只动了被标条目" if c["只动了被标条目"] else "有越界！" + str(c)}'
          f'｜{r["用时秒"]} 秒', flush=True)


def summarize(ep, nums, by):
    tot = {}
    for n in nums:
        op = T.block_dir(ep) / f'块{n}{tag(by)}-改.json'
        if not op.exists():
            continue
        r = json.loads(op.read_text())['改稿记录']
        print_block(n, r)
        for k in ('被标', '改', '删', '不同意保留', '没回', '被拒', '用时秒'):
            tot[k] = tot.get(k, 0) + r[k]
        tot['越界块'] = tot.get('越界块', 0) + (not r['比对']['只动了被标条目'])
    if tot:
        print('合计：', tot)


def main():
    a = C.positional()
    if not a:
        raise SystemExit(__doc__)
    ep, by = a[0], T.opt('--by', None)
    blocks = T.load_blocks(ep)
    want = a[1:]
    todo = blocks if not want or want == ['all'] else [b for b in blocks if str(b['块']) in want]
    if '--汇总' in sys.argv:
        summarize(ep, [b['块'] for b in todo], by)
        return
    k = T.opt('--路数', 1)
    print(f'{ep} Astra 按核稿意见改稿：块 {[b["块"] for b in todo]}，{k} 路', flush=True)
    with ThreadPoolExecutor(k) as ex:
        list(ex.map(lambda b: run_block(ep, blocks, b, by, '--重跑' in sys.argv), todo))
    summarize(ep, [b['块'] for b in todo], by)


if __name__ == '__main__':
    main()

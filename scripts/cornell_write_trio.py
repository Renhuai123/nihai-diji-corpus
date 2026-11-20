#!/usr/bin/env python3
"""地纪三集（P31 P33 P35）第 7 步：分段读手、康奈尔写手换成 Kimi / Grok / Astra（2026-11-19）。

站长 11-18 定：地纪第 6、7 步不用 Claude 写内容，写手、分段读手只用 Kimi K3.1 Pro、Grok 4.7 high、Astra 6.2 max。
Claude 只做工程（本程序、跑程序、核对）。调用方式照 deixis_trio.py（Grok / Astra）和 run_exp4b.py（Kimi）。

提示词与原 Claude 子代理完全相同：
  分段读手 = 提示词/分段读手提示词-堪舆.md 的正文（「---」以下），占位符按文件头注释从 join_sentences.py 的输出算；
  写手     = 康奈尔写手提示词-堪舆.md 的正文（注释以下），占位符同 P37 的做法（见 writer_prompt）；
            按句拼接/试点/<集>-堪舆笔记块/写手提示词-块N.md 已存在就原样用（可以手改），没有就生成并存下。
原提示词是给有 Read / Write 工具的子代理的，接口和只读命令行做不到「Read 文件」「Write 文件」，所以只在原文后面
接一段【运行说明】（ADAPT_*）：要读的文件全文附在后面、板书图随消息附上、JSON 直接放在最终回复里由程序存盘。
原提示词正文一字不改；三家拿到的文字材料和图完全相同（Kimi 不收图时只给文字，并在输出 _运行 里记下）。

用法（在 第0步/ 下；先跑过 join_sentences.py <集>）：
  python cornell_write_trio.py segment P31 P33 P35 --by kimi            分段读手，回复存 按句拼接/试点/<集>-分段读手-<模型>.json，并逐条核边界句
  python cornell_write_trio.py segment P31 --by kimi --写入              核过的大段写进 全量配置/PLAN-堪舆.json（P37 不动；已有的集不覆盖）
  （之后跑 cornell_blocks.py <集> --堪舆 出块材料）
  python cornell_write_trio.py prompts P31                              生成各块 写手提示词-块N.md（已有的不动）
  python cornell_write_trio.py cost P31 [块号…]                         用 Kimi 免费估算接口数输入 token，估钱
  python cornell_write_trio.py write P31 1 2 3 --by kimi|grok|astra     写手；块号可写 all；--路数 N 并发；--预算 元（只管 Kimi）
       输出 按句拼接/试点/<集>-堪舆笔记块/块N-<模型>.json（康奈尔 JSON + _运行 记录），原始回复存 写手原始/块N-<模型>.txt；
       已写好（JSON 合法、键齐）的块跳过，断了重跑即可。
  校验：python cornell_render.py P31 --堪舆 --check --by=kimi           （读 块N-kimi.json，报告写 校验报告-kimi.json）

Kimi 价格（元 / 百万 token，platform.kimi.com/docs/pricing/chat，2026-11-19 读）：kimi-k3.1-pro 输入 13、输出 68（含思考）、
缓存命中 1.3、缓存写入 5 分钟 13。账户余额由 /v1/users/me/balance 查（每次 Kimi 命令开头、结尾各查一次）。
"""
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / '按句拼接' / '试点'
WRITER_TPL = HERE / '康奈尔写手提示词-堪舆.md'
SEG_TPL = HERE / '提示词' / '分段读手提示词-堪舆.md'
PLAN_K = HERE / '全量配置' / 'PLAN-堪舆.json'
FPS = 30

CURSOR = str(Path('~/.local/bin/cursor-agent').expanduser())
CODEX = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
KIMI_URL = 'https://api.moonshot.cn/v1'
KIMI_MODEL = 'kimi-k3.1-pro'
KIMI_KEYF = Path('~/.config/nishi-study/kimi.key').expanduser()
PRICE = {'输入': 13.0, '输出': 68.0, '缓存命中': 1.3}   # 元 / 百万 token
WHO = {'kimi': 'Kimi K3.1 Pro（reasoning_effort=high）', 'grok': 'Grok 4.7 high（cursor-agent，ask 模式）',
       'astra': 'Astra 6.2 max（codex exec，只读）'}
NO_OVERLAY = {'P31', 'P33', 'P35'}   # 没做叠图转写的三集（康奈尔写手提示词-堪舆.md 注释 {本集说明}）

ADAPT_HEAD = '\n\n---\n【运行说明（程序接在原提示词后面的；以上原提示词一字未改）】\n'


def opt(name, default):
    if name in sys.argv:
        v = sys.argv[sys.argv.index(name) + 1]
        return type(default)(v) if default is not None else v
    return default


def body_of(tpl, sep):
    """模板文件去掉开头的说明注释，取正文。"""
    s = tpl.read_text()
    return s.split(sep, 1)[1].lstrip('\n')


def fill(text, vals):
    for k, v in vals.items():          # 逐个字符串替换（正文里有 JSON 花括号，不能用 str.format）
        text = text.replace('{' + k + '}', str(v))
    left = re.findall(r'\{(集|集数|n|本块说明|行数|本集说明|分钟|句数|万字节|块数范围)\}', text)
    if left:
        raise SystemExit(f'占位符没替换完：{left}')
    return text


def files_appendix(paths):
    out = []
    for k, p in enumerate(paths, 1):
        out += [f'\n===== 文件 {k}：{p} =====', Path(p).read_text().rstrip('\n'), f'===== 文件 {k} 结束 =====']
    return '\n'.join(out) + '\n'


# ───────────────────────── 三家调用 ─────────────────────────

def kimi_key():
    return KIMI_KEYF.read_text().strip()


def kimi_post(path, body, timeout=1800):
    req = urllib.request.Request(f'{KIMI_URL}{path}', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json', 'Authorization': f'Bearer {kimi_key()}'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def kimi_balance():
    req = urllib.request.Request(f'{KIMI_URL}/users/me/balance', headers={'Authorization': f'Bearer {kimi_key()}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['data']['available_balance']


def kimi_content(text, images):
    content = [{'type': 'text', 'text': text}]
    for k, f in enumerate(images, 1):
        content.append({'type': 'text', 'text': f'（第 {k} 张：{Path(f).name}）'})
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(Path(f).read_bytes()).decode()}})
    return content


def kimi_cost(u):
    u = u or {}
    cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens') or u.get('cached_tokens') or 0
    return ((u.get('prompt_tokens', 0) - cached) * PRICE['输入'] + cached * PRICE['缓存命中']
            + u.get('completion_tokens', 0) * PRICE['输出']) / 1e6


def ask_kimi(text, images, max_tokens):
    body = {'model': KIMI_MODEL, 'messages': [{'role': 'user', 'content': kimi_content(text, images)}],
            'reasoning_effort': 'high', 'max_tokens': max_tokens}
    last = None
    for attempt in range(3):
        try:
            d = kimi_post('/chat/completions', body)
            msg = d['choices'][0]['message']
            return msg.get('content') or '', {'usage': d.get('usage'), '元': round(kimi_cost(d.get('usage')), 4),
                                              '结束原因': d['choices'][0].get('finish_reason')}
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}：{e.read()[:300].decode("utf-8", "ignore")}'
            if e.code in (400, 401, 403):
                break
        except Exception as e:
            last = str(e)[:300]
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(last)


def ask_grok(text, images, wdir):
    names = []
    for f in images:
        shutil.copy(f, Path(wdir) / Path(f).name)
        names.append(Path(f).name)
    p = subprocess.run([CURSOR, '-p', text, '--model', 'grok-4.7-high', '--mode', 'ask', '--output-format', 'json',
                        '--trust', '--workspace', str(wdir)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=2400, cwd=wdir)
    if not p.stdout.strip():
        raise RuntimeError(f'命令行没有输出（退出码 {p.returncode}）：{p.stderr.strip()[-300:]}')
    d = json.loads(p.stdout.strip().splitlines()[-1])
    if d.get('is_error'):
        raise RuntimeError(str(d.get('result'))[:300])
    return d.get('result') or '', {'usage': d.get('usage'), '退出码': p.returncode}


def ask_astra(text, images, wdir):
    out = Path(wdir) / '_last.txt'
    cmd = [CODEX, 'exec', '-m', 'gpt-6.2-astra', '-c', 'model_reasoning_effort="max"', '-s', 'read-only',
           '--skip-git-repo-check', '--ephemeral', '--color', 'never', '-C', str(wdir), '--output-last-message', str(out)]
    for f in images:
        dst = Path(wdir) / Path(f).name
        shutil.copy(f, dst)
        cmd += ['-i', str(dst)]
    cmd += ['--', text]
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3600, cwd=wdir)
    if not out.exists() or not out.read_text().strip():
        raise RuntimeError(f'没有回答（退出码 {p.returncode}）：{(p.stderr or p.stdout).strip()[-300:]}')
    return out.read_text(), {'退出码': p.returncode}


def ask(who, text, images, max_tokens=64000):
    """返回 (回复文字, 记录)。Grok / Astra 在临时目录里跑（图片复制进去），跑完删掉。"""
    if who == 'kimi':
        return ask_kimi(text, images, max_tokens)
    wdir = tempfile.mkdtemp(prefix=f'cornell-{who}-')
    try:
        return (ask_grok if who == 'grok' else ask_astra)(text, images, wdir)
    finally:
        shutil.rmtree(wdir, ignore_errors=True)


def parse_json(text):
    t = re.sub(r'^```(?:json)?\s*|\s*```\s*$', '', (text or '').strip())
    a, b = t.find('{'), t.rfind('}')
    if a < 0 or b < a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except Exception:
        return None


# ───────────────────────── 分段读手 ─────────────────────────

ADAPT_SEG = ADAPT_HEAD + ('这次你是通过接口调用的，没有 Read 工具。上面「要读的文件」那一份可读稿的全文附在本说明后面，'
                          '内容与磁盘上的文件逐字相同，请从头到尾读完再定分段。最终回复只有那一个 JSON 对象，不要加任何别的文字。\n')


def seg_vals(ep):
    rows = [json.loads(l) for l in (BASE / f'{ep}.jsonl').open()]
    minutes = int(rows[-1]['管到帧'] / FPS / 60)
    size = (BASE / f'{ep}-可读.md').stat().st_size
    return rows, {'集': ep, '集数': int(ep[1:]), '分钟': minutes, '句数': f'{len(rows):,}',
                  '万字节': round(size / 10000), '块数范围': f'{minutes // 7}–{minutes // 5}'}


def seg_prompt(ep):
    rows, vals = seg_vals(ep)
    text = fill(body_of(SEG_TPL, '\n---\n'), vals)
    return rows, vals, text + ADAPT_SEG + files_appendix([BASE / f'{ep}-可读.md'])


def check_segments(ep, ans, rows, vals):
    """程序核边界（原来是主会话对着可读稿核一遍）：起秒对得上某一句的起秒、引的字幕原字就是那一句、顺序与块数。"""
    probs, segs = [], (ans or {}).get('大段') or []
    if not 3 <= len(segs) <= 6:
        probs.append(f'大段 {len(segs)} 个，提示词要 3–6 个')
    lo, hi = map(int, vals['块数范围'].split('–'))
    total = 0
    for k, s in enumerate(segs):
        name = s.get('标签', '')
        a, b, n = s.get('起秒'), s.get('止秒'), s.get('切几块')
        if not isinstance(n, int) or n < 1:
            probs.append(f'第 {k + 1} 段「{name}」切几块不是正整数：{n}')
        else:
            total += n
        if k == 0 and a != 0:
            probs.append(f'第 1 段起秒应为 0：{a}')
        if k and (not isinstance(a, (int, float)) or a <= segs[k - 1].get('起秒', 0)):
            probs.append(f'第 {k + 1} 段「{name}」起秒没比上一段大：{a}')
        if k + 1 < len(segs) and b != segs[k + 1].get('起秒'):
            probs.append(f'第 {k + 1} 段止秒 {b} ≠ 下一段起秒 {segs[k + 1].get("起秒")}')
        if k + 1 == len(segs) and b is not None:
            probs.append(f'最后一段止秒应为 null：{b}')
        if k and isinstance(a, (int, float)):
            # 可读稿里只有时间码和帧号，读手要自己用 起帧 ÷ 30 换成秒；cornell_blocks 按「起秒最近的那句」切，差一两秒不影响
            r = min(rows, key=lambda r: abs(r['起秒'] - a))
            off = abs(r['起秒'] - a)
            if off > 2:
                probs.append(f'第 {k + 1} 段起秒 {a} 离最近一句（{r["起秒"]}「{r["字幕"]}」）差 {off:.1f} 秒')
            else:
                if off > 0.1:
                    probs.append(f'第 {k + 1} 段起秒 {a} 与那句起秒 {r["起秒"]} 差 {off:.1f} 秒（只提醒，切块按最近一句）')
                quotes = re.findall(r'「([^「」]+)」', s.get('边界依据', ''))
                key = lambda t: re.sub(r'\W', '', t)
                if not any(key(q) and (key(q) in key(r['字幕']) or key(r['字幕']) in key(q)) for q in quotes):
                    probs.append(f'第 {k + 1} 段边界依据里没引到起秒那一句「{r["字幕"]}」（{r["时间码"]}，只提醒）')
                s['_边界句'] = f'{r["时间码"]}「{r["字幕"]}」'
                s['_核定起秒'] = r['起秒']
    if not lo <= total <= hi:
        probs.append(f'合计 {total} 块，提示词要 {vals["块数范围"]} 块（只提醒）')
    return probs, total


def plan_insert(ep, segs, src):
    """按文本插进 PLAN-堪舆.json 末尾：原有内容（P37 等）逐字不动。"""
    s = PLAN_K.read_text()
    cur = json.loads(s)
    if ep == 'P37':
        raise SystemExit('P37 的堪舆分段已定，不动')
    if ep in cur:
        raise SystemExit(f'PLAN-堪舆.json 里已经有 {ep}，没覆盖；要改请手改')
    keep = ('标签', '起秒', '止秒', '切几块', '边界依据')
    # 读手只看得到时间码，给的秒数常是取整的（769 而那句起于 769.6）；写进 PLAN 时对齐到核过的那句起秒，原数另记一键
    segs = [dict(x) for x in segs]
    for k, x in enumerate(segs):
        if k and '_核定起秒' in x and x['_核定起秒'] != x['起秒']:
            x['读手原给起秒'] = x['起秒']
            x['起秒'] = x['_核定起秒']
            segs[k - 1]['止秒'] = x['起秒']
    keep += ('读手原给起秒',)
    items = ',\n'.join('  ' + json.dumps({k: x[k] for k in keep if k in x}, ensure_ascii=False) for x in segs)
    add = f',\n "_来源-{ep}": {json.dumps(src, ensure_ascii=False)},\n "{ep}": [\n{items}\n ]\n}}'
    i = s.rstrip().rfind('}')
    new = s[:i].rstrip() + add + '\n'
    json.loads(new)   # 合法才写
    PLAN_K.write_text(new)


def cmd_segment(eps, who):
    bal0 = kimi_balance() if who == 'kimi' else None
    if bal0 is not None:
        print(f'Kimi 余额 ¥{bal0:.2f}', flush=True)
    for ep in eps:
        outp = BASE / f'{ep}-分段读手-{who}.json'
        rows, vals, text = seg_prompt(ep)
        if outp.exists():
            rec = json.loads(outp.read_text())
            print(ep, '已有分段读手回复，不重跑：', outp.name)
        else:
            t = time.time()
            print(ep, who, '分段读手开始', vals, flush=True)
            reply, meta = ask(who, text, [], max_tokens=32000)
            rec = {'集': ep, '模型': WHO[who], '用时秒': round(time.time() - t), **meta,
                   '提示词sha1': hashlib.sha1(text.encode()).hexdigest(), '回复': parse_json(reply), '原始回复': reply}
            outp.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        ans = rec.get('回复')
        if not ans:
            print(ep, '回复不是合法 JSON，原始回复在', outp)
            continue
        probs, total = check_segments(ep, ans, rows, vals)
        print(f'{ep}：{len(ans.get("大段", []))} 段、合计 {total} 块；{rec.get("元", "")}')
        for x in ans['大段']:
            print(f'  {x.get("起秒")}–{x.get("止秒")} 切{x.get("切几块")}｜{x.get("标签")}｜边界句 {x.get("_边界句", "（开头）")}')
        for p in probs:
            print('  ⚠', p)
        if '--写入' in sys.argv:
            hard = [p for p in probs if '只提醒' not in p]
            if hard:
                print(f'  {ep} 有问题没写进 PLAN-堪舆.json，先看上面 ⚠')
            else:
                plan_insert(ep, ans['大段'], f'{WHO[who]} 分段读手（提示词/分段读手提示词-堪舆.md）{time.strftime("%Y-%m-%d")} 回复，'
                                             f'边界句由 cornell_write_trio.py 程序核过；原始回复 按句拼接/试点/{outp.name}')
                print(f'  已写进 全量配置/PLAN-堪舆.json')
    if bal0 is not None:
        b = kimi_balance()
        print(f'Kimi 余额 ¥{bal0:.2f} → ¥{b:.2f}，余额差 ¥{bal0 - b:.2f}（扣费常晚到几分钟，以各集回执的「元」为准）')


# ───────────────────────── 写手 ─────────────────────────

TAIL_NOTE = '本块正文的头一两句可能是上一个话题的尾巴，结合「前文」判断，属于上一话题的不必单独成行。'
LAST_NOTE = '本块是这一集的最后一段，开头第一句可能落在一个话题的中间，结合「前文」把那个话题接上（前文的内容不单独成条，只在需要时用一句推断交代）。'


def block_dir(ep):
    return BASE / f'{ep}-堪舆笔记块'


def load_blocks(ep):
    p = block_dir(ep) / '分块.json'
    if not p.exists():
        raise SystemExit(f'{p} 不存在：先跑 cornell_blocks.py {ep} --堪舆')
    return json.loads(p.read_text())


def writer_vals(ep, blocks, b):
    """占位符取值，照 P37 堪舆版的做法（写手提示词-块N.md 逐字核过，块 6 那句手写的说明除外）：
    {行数} 块长 > 7 分钟 8–14、< 4 分钟 4–8、其余 6–12；
    {本块说明} 大段的第一块不写；大段中间切开的块写「可能是上一个话题的尾巴」；全集最后一块（且不是大段开头）写「最后一段」那句；
    {本集说明} 没做叠图转写的三集写「不要写叠图条目」那句，P37 空串。"""
    i = blocks.index(b)
    seg_start = i == 0 or blocks[i - 1]['命例'] != b['命例']
    minutes = (b['止秒'] - b['起秒']) / 60
    note = '' if seg_start else (LAST_NOTE if i == len(blocks) - 1 else TAIL_NOTE)
    rows = '8–14' if minutes > 7 else '4–8' if minutes < 4 else '6–12'
    ep_note = '本集没有转写后期贴图，材料里没有 ▣ 行，不要写「叠图」条目。' if ep in NO_OVERLAY else ''
    return {'本块说明': note, '本集说明': ep_note, '行数': rows, '集数': int(ep[1:]), '集': ep, 'n': b['块']}


def writer_prompt(ep, blocks, b, save=True):
    """原 Claude 写手的提示词：块目录里已有 写手提示词-块N.md 就原样用，没有就按模板生成并存下。"""
    p = block_dir(ep) / f'写手提示词-块{b["块"]}.md'
    if p.exists():
        return p.read_text()
    text = fill(body_of(WRITER_TPL, '-->'), writer_vals(ep, blocks, b))
    if save:
        p.write_text(text)
    return text


def board_images(b):
    return [x['图'] for x in b['板书图']]


def writer_adapt(who, b, out_name, images, with_images):
    names = [Path(f).name for f in images]
    if with_images:
        listing = '、'.join(f'第 {k} 张 {"@" if who == "grok" else ""}{n}（第 {int(n[1:7])} 帧）' for k, n in enumerate(names, 1))
        pic = f'已作为图片随本消息附上，共 {len(names)} 张，顺序与材料末尾「板书图清单」相同：{listing}。请逐张看。'
    else:
        pic = '这次没有附上（这个接口不收图片）：你看不到板书图，不要写「板书」条目；需要看图才能确认的地方写进「待核」。'
    return ADAPT_HEAD + (
        '这次你是通过接口 / 命令行调用的，没有 Read / Write 工具，也不能写文件。所以：\n'
        '1. 上面「要读的东西」第 1、2 项的两份文件，全文附在本说明后面，内容与磁盘上的文件逐字相同。\n'
        f'2. 第 3 项的板书图{pic}\n'
        f'3. 「输出」一节要写进文件的那个 JSON，改为直接作为你的最终回复：最终回复只有这一个 JSON 对象，不要加任何别的文字，'
        f'也不要回复「已写入」。程序会替你存成 {out_name}。\n')


def writer_message(ep, blocks, b, who, with_images=True):
    """完整消息 = 原提示词 + 运行说明 + 两份文件全文；图片另附。"""
    base = writer_prompt(ep, blocks, b)
    mat = block_dir(ep) / f'块{b["块"]}-材料.md'
    sample = re.search(r'格式样稿[^：]*：(\S+\.md)', base).group(1)
    images = board_images(b) if with_images else []
    text = base + writer_adapt(who, b, f'块{b["块"]}-{who}.json', images, with_images) + files_appendix([mat, sample])
    return base, text, images


KEYS = ('块', '小标题', '行', '总结候选', '待核')


def done_ok(p):
    try:
        d = json.loads(p.read_text())
        return all(k in d for k in KEYS)
    except Exception:
        return False


def pick_blocks(ep, args):
    blocks = load_blocks(ep)
    if not args or args == ['all']:
        return blocks, blocks
    want = {int(x) for x in args}
    return blocks, [b for b in blocks if b['块'] in want]


def cmd_prompts(ep):
    blocks = load_blocks(ep)
    for b in blocks:
        p = block_dir(ep) / f'写手提示词-块{b["块"]}.md'
        had = p.exists()
        writer_prompt(ep, blocks, b)
        v = writer_vals(ep, blocks, b)
        print(f'块{b["块"]}：{"已有，没动" if had else "已生成"}｜行数 {v["行数"]}｜本块说明：{v["本块说明"] or "（无）"}')


def cmd_write(ep, args, who):
    blocks, todo = pick_blocks(ep, args)
    d = block_dir(ep)
    (d / '写手原始').mkdir(exist_ok=True)
    todo = [b for b in todo if not done_ok(d / f'块{b["块"]}-{who}.json')]
    with_images = '--不附图' not in sys.argv
    budget = opt('--预算', 25.0)
    spent, lock = [0.0], threading.Lock()
    bal0 = kimi_balance() if who == 'kimi' else None
    if bal0 is not None:
        print(f'Kimi 余额 ¥{bal0:.2f}；本次预算 ¥{budget:.2f}（按回执 usage 累计，超了就不再派新块）', flush=True)
        if bal0 < 3:
            raise SystemExit('Kimi 余额不足 ¥3，没开跑')
    print(ep, who, '待写', [b['块'] for b in todo], flush=True)

    def run(b):
        n = b['块']
        if who == 'kimi':
            with lock:
                if spent[0] >= budget:
                    print(f'块{n} 没派：已花 ¥{spent[0]:.2f} ≥ 预算', flush=True)
                    return
        imgs_on, why_off = with_images, None if with_images else '加了 --不附图'
        base, text, images = writer_message(ep, blocks, b, who, imgs_on)
        t = time.time()
        reply, meta = '', {}
        for attempt in (1, 2, 3):
            try:
                reply, meta = ask(who, text, images)
                break
            except Exception as e:
                print(f'块{n} 第 {attempt} 次出错：{str(e)[:200]}', flush=True)
                if who == 'kimi' and imgs_on and re.search(r'image|图片|vision', str(e), re.I):
                    imgs_on, why_off = False, f'接口拒收图片：{str(e)[:120]}'   # Kimi 不收图 → 只给文字材料，记下来
                    base, text, images = writer_message(ep, blocks, b, who, False)
                elif attempt >= 2:
                    return
        if who == 'kimi':
            with lock:
                spent[0] += meta.get('元', 0)
        (d / '写手原始' / f'块{n}-{who}.txt').write_text(reply)
        note = parse_json(reply)
        run_rec = {'模型': WHO[who], '附图': len(images), '不附图原因': why_off,
                   '用时秒': round(time.time() - t), '提示词': f'写手提示词-块{n}.md',
                   '提示词sha1': hashlib.sha1(base.encode()).hexdigest(), '时间': time.strftime('%Y-%m-%d %H:%M:%S'), **meta}
        if not note or not all(k in note for k in KEYS):
            print(f'块{n} 回复不是合格的笔记 JSON（缺键或不合法），原始回复在 写手原始/块{n}-{who}.txt；{meta.get("元", "")}', flush=True)
            (d / '写手原始' / f'块{n}-{who}-运行.json').write_text(json.dumps(run_rec, ensure_ascii=False, indent=1))
            return
        if note.get('块') != n:
            run_rec['块号不符'] = note.get('块')
        note['_运行'] = run_rec
        (d / f'块{n}-{who}.json').write_text(json.dumps(note, ensure_ascii=False, indent=1))
        items = sum(len(r.get('条目', [])) for r in note.get('行', []))
        print(f'块{n} 已写：{len(note["行"])} 行 {items} 条，待核 {len(note["待核"])}｜{run_rec["用时秒"]} 秒'
              + (f'｜¥{meta["元"]:.2f}' if who == 'kimi' else ''), flush=True)

    with ThreadPoolExecutor(opt('--路数', {'kimi': 2, 'grok': 3, 'astra': 2}[who])) as ex:
        list(ex.map(run, todo))
    if bal0 is not None:
        b = kimi_balance()
        print(f'Kimi 余额 ¥{bal0:.2f} → ¥{b:.2f}，余额差 ¥{bal0 - b:.2f}；按 usage 算本次 ¥{spent[0]:.2f}'
              '（扣费常晚到几分钟，余额差可能含上一次的、缺这一次的；11-19 分段读手 ¥4.64 两种算法对上了）')


def cmd_cost(ep, args):
    """Kimi 免费估算接口数「原提示词 + 运行说明 + 文件 + 图」的输入 token；输出按 P37 已交稿的 JSON 大小 + 思考另算。"""
    blocks, todo = pick_blocks(ep, args)
    tot_in = 0
    for b in todo:
        _, text, images = writer_message(ep, blocks, b, 'kimi')
        n_in = kimi_post('/tokenizers/estimate-token-count',
                         {'model': KIMI_MODEL, 'messages': [{'role': 'user', 'content': kimi_content(text, images)}]},
                         timeout=120)['data']['total_tokens']
        tot_in += n_in
        print(f'块{b["块"]}：输入约 {n_in:,} token（图 {len(images)} 张，材料 {b["材料字节"] // 1024}KB）→ 输入 ¥{n_in * PRICE["输入"] / 1e6:.2f}')
    print(f'{ep} {len(todo)} 块输入合计约 {tot_in:,} token → ¥{tot_in * PRICE["输入"] / 1e6:.2f}（输出另算：每块输出 token × ¥68/百万）')


def positional():
    out, skip = [], False
    for x in sys.argv[1:]:
        if skip:
            skip = False
        elif x in ('--by', '--路数', '--预算'):
            skip = True
        elif not x.startswith('--'):
            out.append(x)
    return out


if __name__ == '__main__':
    a = positional()
    if not a:
        raise SystemExit(__doc__)
    who = opt('--by', None)
    if a[0] in ('segment', 'write') and who not in WHO:
        raise SystemExit('要写 --by kimi|grok|astra')
    if a[0] == 'segment':
        cmd_segment(a[1:], who)
    elif a[0] == 'prompts':
        cmd_prompts(a[1])
    elif a[0] == 'write':
        cmd_write(a[1], a[2:], who)
    elif a[0] == 'cost':
        cmd_cost(a[1], a[2:])
    else:
        raise SystemExit(__doc__)

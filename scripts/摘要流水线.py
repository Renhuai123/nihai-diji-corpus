"""地纪（堪舆）四集公开摘要：Astra 6.2 max 写 → Grok 4.7 high 对底稿复核 → Astra 按复核改一轮 → 程序核引文与时间码。
2026-11-19 站长「两个都开」。Claude 只做工程：本程序不写、不改摘要内容。调用方式照 补齐-写手/period_write_trio.py。

用法：python3 摘要流水线.py [--集 P31,P33] [--路数 2]
产物：本目录 P31.md …（终稿）、原始/（初稿、复核、改稿原文）、程序核对.md、运行记录.jsonl
"""
import json
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / '断法对照/运限断语设计/补齐-写手'))
from period_write_trio import ask  # noqa: E402  （ask('astra'|'grok', 文本) → (回答, 用量)）

SRC = {
    'P31': ROOT / '康奈尔样稿/P31-堪舆-整集第一稿-astra-改.md',
    'P33': ROOT / '康奈尔样稿/P33-堪舆-整集第一稿-astra-改.md',
    'P35': ROOT / '康奈尔样稿/P35-堪舆-整集第一稿-astra-改.md',
    'P37': ROOT / '康奈尔样稿/P37-堪舆-整集第一稿-改.md',
}
EXAMPLE = (ROOT / '公开摘要稿/P37.md').read_text()
RAW = HERE / '原始'
RAW.mkdir(exist_ok=True)
LOG = HERE / '运行记录.jsonl'
LOCK = threading.Lock()


def say(*a):
    with LOCK:
        print(time.strftime('%H:%M:%S'), *a, flush=True)


def log(row):
    with LOCK, LOG.open('a') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def base_of(p):
    t = SRC[p].read_text()
    head = t.splitlines()[0]
    m = re.search(r'## 全集总结\n(.*?)\n## 目录', t, re.S)
    if not m:
        raise RuntimeError(f'{p} 找不到「全集总结」')
    body = m.group(1).strip()
    n = len(re.findall(r'^- ', body, re.M))
    return head, body, n


RULES = '''规则（每条都要守）：
1. 只用底稿里有的内容：不加底稿没有的说法，不推断，不评价对错。每条保留底稿那一条的时间码，只取起点，写成 [HH:MM:SS](链接)，链接用底稿那一条里的 B 站链接原样照抄；不写帧号。
2. 用我们自己的话转述。倪师原话只引短句，每处不超过 20 个字，必须和底稿里「」中的字或底稿原句一字不差。「一句原话」一节只放一句最能代表本集的原话。
3. 版式照后面附的样例（同一系列紫微那边的公开摘要），依次是：
   - 标题行：照底稿标题，去掉括号里的时间范围和帧数；
   - 引言块：第一行「**公开摘要稿 · 草稿，未公开**（2026-11-19 出稿，过目后再发布）」；第二行写原视频（B 站 BV1KJsLekEfA 第 N P，全长 = 底稿标题里的结束时间，附「打开」链接）和「每条后面的时间码可以点，跳到 B 站那一秒」；第三行写法说明照样例改成堪舆用语；第四行免责声明照样例，把「医疗、婚姻、投资等建议」改成「风水、择址、医疗、婚姻、投资等建议」；
   - ## 本集讲什么：一段 3–5 句，按讲课先后概括；
   - ## 一句原话；
   - ## 通用规则（倪师所讲）；
   - ## 只在本例（例子里的断法）；
   - ## 处世方法（不是堪舆规则）——底稿没有这类条目就省掉这一节；
   - 分隔线后一行：底稿：私有笔记仓 `康奈尔笔记/{P}/{P}-堪舆-康奈尔笔记.md` 开头的「全集总结」（底稿 {N} 条，本稿 M 条，逐条改写）。
4. 公开红线：不出现任何人的出生年月日、八字、命盘宫位干支（凡能反推生辰的都删）；不出现在世普通人的姓名（历史人物、古籍、地名可以）；不出现收费、价格、任何软件或网站名；不写「化解、改运、催财、旺宅、保证」这类替人担保效果的话——倪师讲的效果照转述成「倪师说……」，不替他担保。
5. 底稿每一条都要有着落：改写进正文，或者因为红线删掉。删掉的在全文最后另起一节「## 本稿删掉的底稿条目（发布前去掉这一节）」逐条写「底稿第几条：原因」；一条都没删就写「无」。
6. 只交 markdown 正文，不要任何解释或前言。'''


def prompt_write(p, head, body, n):
    return (f'你是写手。下面是倪师堪舆课第 {p[1:]} P 逐帧精读稿的标题和开头「全集总结」（私有底稿，共 {n} 条）。'
            f'请把它改写成一篇可以放进公开 GitHub 仓库的「公开摘要」。\n\n'
            + RULES.replace('{P}', p).replace('{N}', str(n))
            + f'\n\n【底稿标题】\n{head}\n\n【底稿：全集总结】\n{body}\n\n【样例：同一系列紫微那边的公开摘要，只学版式和写法，内容不要照抄】\n{EXAMPLE}\n')


def prompt_review(p, head, body, n, draft):
    return (f'你是复核员。下面是倪师堪舆课第 {p[1:]} P 的私有底稿（全集总结，{n} 条）和写手据此写的公开摘要初稿。'
            '请逐条对照底稿核初稿，只挑真问题，别挑措辞偏好。要核的：\n'
            'A 走样：意思和底稿那条不一致、加了底稿没有的内容、把「只在本例」写成了通用规则或反过来；\n'
            'B 引文：「」里的字和底稿不是一字不差，或者一处超过 20 个字；\n'
            'C 时间码：和底稿那条的起点不一致，或链接不对；\n'
            'D 红线：出现出生年月日、八字、宫位干支、在世普通人姓名、价格、软件或网站名、替人担保效果的话；\n'
            'E 漏条：底稿某条既没写进正文、也没列进「本稿删掉的底稿条目」；删掉的理由不成立也算。\n'
            '只交一个 JSON 对象，不要别的字：{"结论": "通过" 或 "要改", "问题": [{"类型": "A|B|C|D|E", "位置": "初稿里那一条的开头几个字", '
            '"底稿": "对应底稿条目的开头几个字或第几条", "说明": "错在哪", "建议": "怎么改"}]}\n\n'
            f'【底稿标题】\n{head}\n\n【底稿：全集总结】\n{body}\n\n【公开摘要初稿】\n{draft}\n')


def prompt_revise(p, head, body, n, draft, review):
    return (f'你是写手。你写的倪师堪舆课第 {p[1:]} P 公开摘要初稿经复核员核过，下面给出底稿、初稿和复核意见。'
            '请按复核意见改出终稿：意见对的照改；你认为意见不对的可以不改，但要在全文最后另起一节「## 写手对复核意见的说明（发布前去掉这一节）」逐条写理由。'
            '原有的规则仍然全部要守：\n\n' + RULES.replace('{P}', p).replace('{N}', str(n))
            + f'\n\n【底稿标题】\n{head}\n\n【底稿：全集总结】\n{body}\n\n【初稿】\n{draft}\n\n【复核意见（JSON）】\n{review}\n\n只交改好的 markdown 全文。')


def strip_fence(t):
    t = t.strip()
    m = re.match(r'^```(?:markdown|md)?\n(.*)\n```$', t, re.S)
    return m.group(1).strip() if m else t


def parse_json(t):
    m = re.search(r'\{.*\}', t, re.S)
    return json.loads(m.group(0)) if m else None


def program_check(p, body, final):
    """程序核：「」引文是否在底稿里一字不差、长度、时间码是否都在底稿出现过、有没有帧号 / 四位年份。"""
    probs = []
    quotes = re.findall(r'「([^」]+)」', final)
    for q in quotes:
        if q in ('一句原话',):
            continue
        if q not in body:
            probs.append(f'引文不在底稿里：「{q}」')
        if len(q) > 20:
            probs.append(f'引文超过 20 字（{len(q)}）：「{q}」')
    base_tc = set(re.findall(r'\[(\d\d:\d\d:\d\d)[–\]]', body))
    for tc in re.findall(r'\[(\d\d:\d\d:\d\d)\]\(', final):
        if tc not in base_tc and not tc.startswith('00:00:00'):
            probs.append(f'时间码在底稿里找不到：{tc}')
    if '帧' in final:
        probs.append('出现了「帧」字')
    for y in re.findall(r'(?<!\d)(1[89]\d\d|20\d\d)(?=\s*年)', final):
        probs.append(f'有四位年份「{y}年」，人工确认不是某人生年')
    return probs


def one(p):
    head, body, n = base_of(p)
    t0 = time.time()
    row = {'集': p, '底稿条数': n, '开始': time.strftime('%H:%M:%S')}
    try:
        say(f'{p} Astra 写初稿（底稿 {n} 条）')
        d1, u1 = ask('astra', prompt_write(p, head, body, n))
        d1 = strip_fence(d1)
        (RAW / f'{p}-初稿.md').write_text(d1)
        row['初稿用量'] = u1
        say(f'{p} Grok 复核')
        rv, u2 = ask('grok', prompt_review(p, head, body, n, d1))
        (RAW / f'{p}-复核.txt').write_text(rv)
        rj = parse_json(rv)
        row['复核用量'] = u2
        row['复核结论'] = (rj or {}).get('结论')
        row['复核问题数'] = len((rj or {}).get('问题') or [])
        final = d1
        if not rj or rj.get('结论') != '通过' or rj.get('问题'):
            say(f'{p} Astra 按复核改（{row["复核问题数"]} 条意见）')
            d2, u3 = ask('astra', prompt_revise(p, head, body, n, d1, rv))
            final = strip_fence(d2)
            (RAW / f'{p}-改稿.md').write_text(final)
            row['改稿用量'] = u3
        (HERE / f'{p}.md').write_text(final + '\n')
        probs = program_check(p, body, final)
        row['程序核对问题'] = probs
        row['结果'] = '完成'
        say(f'{p} ✓ 完成，程序核对 {len(probs)} 处要看')
    except Exception as e:
        row['结果'] = f'失败：{str(e)[:300]}'
        say(f'{p} ✗ {row["结果"]}')
    row['用时秒'] = round(time.time() - t0)
    log(row)
    return row


def main():
    eps = sys.argv[sys.argv.index('--集') + 1].split(',') if '--集' in sys.argv else list(SRC)
    lanes = int(sys.argv[sys.argv.index('--路数') + 1]) if '--路数' in sys.argv else 2
    say(f'开跑：{",".join(eps)}，同时 {lanes} 集')
    with ThreadPoolExecutor(lanes) as ex:
        rows = list(ex.map(one, eps))
    lines = ['# 地纪公开摘要 · 程序核对', '', f'（{time.strftime("%Y-%m-%d %H:%M")}）', '']
    for r in rows:
        lines.append(f'## {r["集"]}：{r["结果"]}（底稿 {r["底稿条数"]} 条，复核 {r.get("复核结论")}、{r.get("复核问题数")} 条意见，用时 {r["用时秒"]} 秒）')
        for x in r.get('程序核对问题') or []:
            lines.append(f'- {x}')
        if not r.get('程序核对问题'):
            lines.append('- 无')
        lines.append('')
    (HERE / '程序核对.md').write_text('\n'.join(lines))
    say('全部结束，见 程序核对.md')


if __name__ == '__main__':
    main()

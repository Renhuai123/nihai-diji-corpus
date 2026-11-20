"""堪舆（地纪）四集精读进度页（2026-11-15 站长要的 HTML 进度）。不调接口，只读本机现成数据。
用法（在 第0步/ 下）：../.venv-vision/bin/python kanyu_progress.py      → 写 ../堪舆（地纪）进度.html
页面每 5 分钟自动刷新；数据由 run_kanyu_progress_loop.sh 每 5 分钟重算一次。
样式照 ../整体进度流程图.html（紫微那份）。实时部分：逐帧层（Grok）每集进度、速度、预计完成、token 用量、P37 补写块数；
其余步骤的状态写在下面 STEPS 里，做到哪一步就改那一步。
"""
import html
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from full_status import total_windows

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / '堪舆（地纪）进度.html'
EPS = [('P31', '堪舆一', '龙脉 / 明堂 / 官鬼 / 相上风水 / 罗经使用 / 朝山取穴法'),
       ('P33', '堪舆二', '官鬼 / 九星 / 天星四贵 / 内外砂 / 真假龙 / 城局 / 骑龙葬 / 杖法'),
       ('P35', '堪舆三', '三吉六秀 / 穿山 72 龙 / 天罡 28 宿 / 罗盘使用 / 分房宫位法 / 透地 60 龙 / 批风水顺序')]
WEEK = '一二三四五六日'

CSS = """
:root{--ground:#f7f8f7;--surface:#fff;--ink:#1d2320;--ink-2:#4f5a55;--ink-3:#85908b;--line:#dfe4e1;--board:#2f4a3e;
--done:#2f7a55;--done-bg:#e6f2eb;--run:#a8620e;--run-bg:#fbf0e0;--wait:#8a3b8f;--wait-bg:#f5e9f5;--todo:#6b7570;--todo-bg:#eef1ef;--bad:#b23a2e;--bad-bg:#fbe9e6}
@media (prefers-color-scheme:dark){:root{--ground:#151917;--surface:#1d2321;--ink:#e8ece9;--ink-2:#b3bcb7;--ink-3:#7f8a85;--line:#2f3833;--board:#8fc0a6;
--done:#7fcf9f;--done-bg:#1f3329;--run:#f0b065;--run-bg:#3a2c19;--wait:#dba3df;--wait-bg:#36243a;--todo:#a3ada8;--todo-bg:#262d2a;--bad:#f08a7e;--bad-bg:#3d2320}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font:15px/1.65 "Noto Sans SC","PingFang SC","Hiragino Sans GB",system-ui,sans-serif;padding:40px 20px 64px}
.wrap{max-width:920px;margin:0 auto}
h1{font-family:"Noto Serif SC","Songti SC",serif;font-size:30px;line-height:1.3;margin:0 0 6px;text-wrap:balance}
.sub{color:var(--ink-2);margin:0 0 22px}
.num{font-variant-numeric:tabular-nums}
.facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:18px}
.fact{background:var(--surface);padding:12px 14px}
.fact b{display:block;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.fact span{color:var(--ink-3);font-size:12.5px}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin:0 0 26px;font-size:13px;color:var(--ink-2)}
.chip{display:inline-flex;align-items:center;gap:5px;padding:1px 9px;border-radius:999px;font-size:12.5px;font-weight:600;white-space:nowrap}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.c-done{color:var(--done);background:var(--done-bg)}.c-run{color:var(--run);background:var(--run-bg)}
.c-wait{color:var(--wait);background:var(--wait-bg)}.c-todo{color:var(--todo);background:var(--todo-bg)}.c-bad{color:var(--bad);background:var(--bad-bg)}
.flow{position:relative;padding-left:34px}
.flow::before{content:"";position:absolute;left:11px;top:8px;bottom:8px;width:2px;background:var(--line)}
.step{position:relative;margin-bottom:18px}
.dot{position:absolute;left:-34px;top:16px;width:24px;height:24px;border-radius:50%;background:var(--surface);border:2px solid var(--todo);display:grid;place-items:center;font-size:12px;font-weight:700;color:var(--todo);font-variant-numeric:tabular-nums}
.step.done .dot{border-color:var(--done);background:var(--done);color:var(--surface)}
.step.run .dot{border-color:var(--run);color:var(--run);box-shadow:0 0 0 4px var(--run-bg)}
.step.wait .dot{border-color:var(--wait);color:var(--wait)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px 12px}
.step.run .card{border-color:var(--run)}.step.wait .card{border-color:var(--wait)}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 10px;margin-bottom:6px}
.head h2{font-family:"Noto Serif SC","Songti SC",serif;font-size:18px;margin:0}
.head .when{color:var(--ink-3);font-size:12.5px;margin-left:auto}
.card ul{margin:4px 0 2px;padding-left:1.15em}.card li{margin:3px 0;color:var(--ink-2)}.card li b{color:var(--ink);font-weight:600}
.note{font-size:13px;color:var(--ink-3);margin:8px 0 0}
.bar{height:8px;border-radius:4px;background:var(--todo-bg);overflow:hidden;margin:8px 0 4px}
.bar i{display:block;height:100%;background:var(--run);border-radius:4px}.bar.ok i{background:var(--done)}
.barlab{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.prog-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;font-size:13.5px;color:var(--ink-2)}
.prog-head b{white-space:nowrap;font-size:22px;font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}
.eps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 18px;margin-top:14px}
.ep .barlab span:first-child{color:var(--ink);font-weight:600}
.ep p{margin:0;font-size:12.5px;line-height:1.55;color:var(--ink-3)}
.kv{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:14px 0 4px}
.kv div{background:var(--ground);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kv b{display:block;font-size:16px;font-variant-numeric:tabular-nums}.kv span{font-size:12px;color:var(--ink-3)}
.chart{margin:14px 0 2px}.chart svg{display:block;width:100%;height:auto}
.chart .cap{font-size:12.5px;color:var(--ink-3);margin:0 0 4px}
.res{width:100%;border-collapse:collapse;margin:6px 0 2px;font-size:14px}
.res th{text-align:left;font-size:12.5px;color:var(--ink-3);font-weight:600;padding:4px 8px 4px 0}
.res td{padding:7px 8px 7px 0;border-top:1px solid var(--line);vertical-align:top;font-variant-numeric:tabular-nums}
.res td:first-child{font-weight:600;white-space:nowrap}
.log{list-style:none;padding-left:0!important;margin:10px 0 0!important;font-size:13px}
.log li{display:flex;gap:10px;color:var(--ink-2)}.log time{flex:none;color:var(--ink-3);font-variant-numeric:tabular-nums}
footer{margin-top:26px;color:var(--ink-3);font-size:12.5px}footer code{font-size:12px}
@media (max-width:640px){body{padding:24px 16px 48px}h1{font-size:24px}.facts,.kv{grid-template-columns:repeat(2,minmax(0,1fr))}.eps{grid-template-columns:1fr}.head .when{margin-left:0;width:100%}}
"""


def esc(s):
    return html.escape(str(s), quote=False)


def when(t):
    return f'{t:%m-%d} 周{WEEK[t.weekday()]} {t:%H:%M}'


def bar(a, b, ok=False):
    pct = 100 * a / b if b else 0
    return f'<div class="bar{" ok" if ok else ""}"><i style="width:{pct:.1f}%"></i></div>'


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ''


def load(ep):
    """返回 已成功窗集合、只有失败记录的窗集合、全部记录。"""
    p = ROOT / '逐帧层' / '全量' / f'{ep}.jsonl'
    ok, bad, recs = set(), set(), []
    if p.exists():
        for line in p.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            recs.append(r)
            (ok if r.get('行') else bad).add(r['窗'])
    return ok, bad - ok, recs


def main():
    now = datetime.now()
    rows, allrecs = [], []
    for ep, name, topic in EPS:
        ok, bad, recs = load(ep)
        rows.append((ep, name, topic, len(ok), len(bad), total_windows(ep)))
        allrecs += recs
    done = sum(r[3] for r in rows)
    fail = sum(r[4] for r in rows)
    total = sum(r[5] for r in rows)
    times = [(datetime.fromisoformat(r['时间']), bool(r.get('行'))) for r in allrecs if r.get('时间')]
    okt = sorted(t for t, good in times if good)
    recent = [t for t in okt if t >= now - timedelta(minutes=30)]
    rate = len(recent) / 30 if recent else 0.0
    left = total - done
    eta = now + timedelta(minutes=left / rate) if rate > 0 else None
    succ = [r for r in allrecs if r.get('行')]
    last_ok = max((t for t, good in times if good), default=None)
    ago = int((now - last_ok).total_seconds()) if last_ok else None
    last_hms = last_ok.strftime('%H:%M:%S') if last_ok else ''
    last_ms = int(last_ok.timestamp() * 1000) if last_ok else 0
    if last_ok is None:
        fresh = '还没有跑完的窗'
    else:
        fresh = f'最后一窗 {last_ok:%H:%M:%S}，{ago} 秒前' + ('' if ago < 180 else '（超过 3 分钟没出新窗，可能停了）')
    tok = Counter()
    for r in allrecs:
        for k, v in (r.get('用量') or {}).items():
            tok[k] += v
    per = (tok['inputTokens'] + tok['cacheReadTokens'] + tok['outputTokens']) / len(succ) if succ else 0
    med = sorted(r['用时'] for r in succ if r['时间'] >= (now - timedelta(minutes=30)).isoformat(timespec='seconds'))
    med = med[len(med) // 2] if med else None
    try:
        conc = int((ROOT / '堪舆并发-grok.txt').read_text().strip())
    except (OSError, ValueError):
        conc = None
    alive = bool(sh(['pgrep', '-f', 'run_kanyu_grok.sh']).strip())
    live = len(sh(['pgrep', '-f', 'grok-临时']).split())
    finished = (ROOT / '逐帧层' / '全量' / '堪舆完成.flag').exists()

    # 速度图：每 15 分钟成功窗数
    svg = ''
    if okt:
        start = okt[0].replace(minute=okt[0].minute // 15 * 15, second=0, microsecond=0)
        nb = int((now - start).total_seconds() // 900) + 1
        cnt = [0] * nb
        for t in okt:
            cnt[min(nb - 1, int((t - start).total_seconds() // 900))] += 1
        cnt = cnt[-96:]
        start = start + timedelta(minutes=15 * (nb - len(cnt)))
        W, H, top = 880, 120, max(cnt) or 1
        bw = W / len(cnt)
        bars = ''.join(f'<rect x="{i * bw + 1:.1f}" y="{H - 18 - (H - 30) * c / top:.1f}" width="{max(bw - 2, 1):.1f}" '
                       f'height="{(H - 30) * c / top:.1f}" rx="2" fill="var(--run)"><title>{(start + timedelta(minutes=15 * i)):%H:%M} 起 15 分钟：{c} 窗</title></rect>'
                       for i, c in enumerate(cnt))
        step = max(1, len(cnt) // 8)
        idxs = list(range(0, len(cnt), step))
        if idxs[-1] != len(cnt) - 1:
            idxs.append(len(cnt) - 1)
        labs = []
        for i in idxs:
            label = (start + timedelta(minutes=15 * i)).strftime('%H:%M')
            if i == len(cnt) - 1:
                labs.append(f'<text x="{W - 2}" y="{H - 4}" font-size="11" text-anchor="end" fill="var(--ink)">{label}</text>')
            else:
                labs.append(f'<text x="{i * bw + bw / 2:.1f}" y="{H - 4}" font-size="11" text-anchor="middle" fill="var(--ink-3)">{label}</text>')
        labs = ''.join(labs)
        svg = (f'<div class="chart"><p class="cap">每 15 分钟跑完的窗数（最高 {top} 窗，鼠标停在柱子上看数；最右一根是正在进行的 15 分钟，还没满）</p>'
               f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="每 15 分钟跑完的窗数">{bars}{labs}</svg></div>')

    # 调度日志里的关键事件
    events = []
    logp = ROOT / '日志' / '堪舆-逐帧-grok.log'
    if logp.exists():
        for line in logp.read_text().splitlines():
            if any(k in line for k in ('启动', '并发 ', '一轮结束', '都已完成', '停，等人看')) and '一轮结束：待跑 27558 → 27558' not in line:
                events.append((line[:14], line[15:]))
    starts = [i for i, (_, b) in enumerate(events) if '启动' in b]
    events = [e for i, e in enumerate(events) if i not in starts[:-1]][-8:]   # 只留最后一次启动

    p37 = sum((ROOT / '按句拼接' / '试点' / 'P37-堪舆笔记块' / f'块{n}.json').exists() for n in range(1, 9))

    if finished:
        st, chip, status = 'done', 'c-done', '已完成'
    elif alive:
        st, chip, status = 'run', 'c-run', '进行中'
    else:
        st, chip, status = 'wait', 'c-bad', '调度没在跑'
    # 调度是一集跑完再接下一集（P31 → P33 → P35），失败窗等三集都过一遍后统一补；按当前速度推算每集何时开始、何时跑完
    eps_html, clock, running = '', now, None
    for ep, name, topic, d, f, t in rows:
        todo_n = t - d - f
        if todo_n <= 0:
            state = '已跑满' if d >= t else f'本轮已跑完，失败 {f} 窗等三集过完后统一补跑'
        elif running is None:
            running = ep
            end = clock + timedelta(minutes=todo_n / rate) if rate > 0 else None
            state = f'正在跑{f"，预计 {when(end)} 跑完" if end else ""}' + (f'；失败 {f} 窗之后统一补跑' if f else '')
            clock = end or clock
        else:
            end = clock + timedelta(minutes=todo_n / rate) if rate > 0 else None
            state = (f'排队：上一集跑完自动接着跑，预计 {when(clock)} 开始、{when(end)} 跑完' if end
                     else '排队：上一集跑完自动接着跑')
            clock = end or clock
        eps_html += (f'<div class="ep"><div class="barlab"><span>{ep} {name}</span><span>{d:,} / {t:,}</span></div>{bar(d, t, d >= t)}'
                     f'<p>{esc(topic)}</p><p><b style="color:var(--ink-2);font-weight:600">{state}</b></p></div>')
    run_card = f'''
    <div class="prog-head"><span>三集合计（每窗 12 帧）</span><b>{done:,} / {total:,} 窗 · {100 * done / total:.1f}%</b></div>
    <div class="barlab"><span id="lastwin" data-last="{last_ms}" data-hms="{last_hms}">{fresh}</span><span>现在 <b id="nowclock"></b>，数字每 1 分钟重载</span></div>
    {bar(done, total, finished)}
    <div class="barlab"><span>{"全部跑满" if finished else (f"预计跑完：{when(eta)}（按最近 30 分钟速度推算）" if eta else "还没有速度数据")}</span><span>剩 {left:,} 窗</span></div>
    <div class="kv">
      <div><b>{rate:.1f} 窗/分</b><span>最近 30 分钟速度</span></div>
      <div><b>{conc if conc else "—"} 路</b><span>同时在跑（现在实际 {live} 个 Grok 进程）</span></div>
      <div><b>{f"{med:.0f} 秒" if med else "—"}</b><span>最近 30 分钟每窗用时中位</span></div>
      <div><b>{fail:,} 窗</b><span>失败待补（一轮跑完自动重跑）</span></div>
    </div>
    <div class="eps">{eps_html}</div>
    {svg}
    <table class="res" style="margin-top:14px">
      <tr><th>token 用量</th><th>已用</th><th>平均每窗</th><th>按此推算全量</th></tr>
      <tr><td>输入</td><td>{tok["inputTokens"] / 1e4:,.0f} 万</td><td>{tok["inputTokens"] / max(len(succ), 1) / 1e4:.1f} 万</td><td>{tok["inputTokens"] / max(len(succ), 1) * total / 1e8:.1f} 亿</td></tr>
      <tr><td>缓存读</td><td>{tok["cacheReadTokens"] / 1e4:,.0f} 万</td><td>{tok["cacheReadTokens"] / max(len(succ), 1) / 1e4:.1f} 万</td><td>{tok["cacheReadTokens"] / max(len(succ), 1) * total / 1e8:.1f} 亿</td></tr>
      <tr><td>输出</td><td>{tok["outputTokens"] / 1e4:,.0f} 万</td><td>{tok["outputTokens"] / max(len(succ), 1) / 1e4:.1f} 万</td><td>{tok["outputTokens"] / max(len(succ), 1) * total / 1e8:.1f} 亿</td></tr>
    </table>
    <p class="note">用量算在 Cursor 账户里（不花 DeepSeek 的钱）。失败窗的用量也计入，所以「平均每窗」略偏高。合计每窗约 {per / 1e4:.1f} 万 token。</p>
    {"<ul class='log'>" + "".join(f"<li><time>{esc(a)}</time><span>{esc(b)}</span></li>" for a, b in events) + "</ul>" if events else ""}
    '''

    steps = [
        ('done', '范围与方案', '11-15', [
            '<b>四集：</b>天纪合辑（程心学校正版 BV1KJsLekEfA）P31 / P33 / P35 / P37 = 堪舆一至四，与《天纪·堪舆学》合辑逐秒相同，约 3.9 小时',
            '<b>做法同紫微 17 集：</b>逐帧层 → 本机预处理 → 指代盲标 → 按句拼接 → 分段写康奈尔笔记 → 程序逐条核对',
            '<b>与紫微不同：</b>画面左侧是上传者加的要点栏和配图，不算倪师的话，不当依据；三集不做叠图转写，笔记只依据口述、板书、指代',
            '<b>仓库：</b>公开 <b>nihai-diji-corpus</b>（方法、脚本、摘要；11-19 站长定名，与天纪、人纪两库对齐），私有 <b>nihai-diji-notes</b>（笔记正文），要推送时再建；公开内容先给站长过目']),
        ('done', '下载与逐帧清单', '11-15 17:24 – 17:36', [
            '三集下载并核对时长：P31 685MB、P33 652MB、P35 672MB',
            '逐帧 sha256 清单 <b>330,673 帧</b>（P31 107,401 · P33 111,693 · P35 111,579），帧数与视频自带记录一致；只存本机，不上传腾讯云',
            'P37 的逐帧层 11-13 已用 DeepSeek 跑完，不重跑']),
        ('done', '逐帧层换 Grok 4.7：先小考', '11-15 17:50 – 18:00', [
            '站长定：逐帧层用本机 Cursor 命令行的 Grok 4.7，不用 DeepSeek；提示词、每窗 12 帧、出图与紫微完全相同',
            '<table class="res"><tr><th></th><th>Grok 高档快速版</th><th>Grok 超高档</th><th>DeepSeek（当时）</th></tr>'
            '<tr><td>标准答案：触板</td><td>67/67</td><td>67/67</td><td>67/67</td></tr>'
            '<tr><td>在写 / 动作</td><td>60/60 · 60/60</td><td>60/60 · 60/60</td><td>60/60 · 60/60</td></tr>'
            '<tr><td>手可见</td><td>70/72</td><td>71/72</td><td>64/72</td></tr>'
            '<tr><td>字幕对参照轨一致</td><td>81.2%</td><td>—</td><td>79.2%</td></tr>'
            '<tr><td>每窗用时中位</td><td>90 秒</td><td>120 秒</td><td>—</td></tr></table>',
            '<p class="note">结论：过线，不比 DeepSeek 差；超高档不更准还更慢，全量用<b>高档快速版</b>。</p>']),
        (st, '逐帧层全量（Grok 4.7 高档快速版）', '11-15 18:06 起', None),
        ('todo', '本机预处理', '等逐帧层跑完', ['苹果字幕参照轨、whisper 逐字语音、MediaPipe 手势、找「这里 / 这个」出题；免费，占 CPU 约 2–3 小时（站长定：逐帧层跑完再开）',
                                         '第 5 步起<b>不会自己开始</b>，逐帧层跑完后由我来启动']),
        ('todo', '指代盲标', '等预处理', ['Claude 子代理看原帧逐题标「这里 / 这个」指哪；用堪舆版标注说明（左侧栏不算、黑板上的图只写形状）']),
        ('todo', '分段 → 写笔记 → 程序核对 → 出稿（P31 / P33 / P35）', '等逐帧层与盲标', [
            '分段读手通读全集定分段 → 每块一个 Claude 写手照材料写 → 程序逐条核对引文、板书、指代 → 选全集总结 → 出网页和 md']),
        ('todo', 'P37（堪舆四）补写六神三段', f'笔记块 {p37} / 8', [
            '紫微版只写了紫微相关两段；堪舆版整集写，切成 8 块',
            '块 5 与紫微版块 3 逐帧相同、直接沿用；其余 7 块的写手 17:25 派出，18:46 前全部交稿（JSON 都合法，共 341 条笔记）',
            '下一步：程序逐条核对引文、板书、指代 → 选全集总结 → 出稿；按站长定的，和三集一起做',
            bar(p37, 8, p37 >= 8)], '块已写完 · 待核对出稿' if p37 >= 8 else None),
        ('todo', '建仓与公开', '最后', ['公开 <b>nihai-diji-corpus</b> 11-19 已建、已放主页第四个置顶位（先放说明页）；之后放方法、脚本、工作记录和公开摘要，<b>先给站长过目再推</b>',
                                     '私有 <b>nihai-diji-notes</b> 放四集笔记，推送时再建']),
    ]
    flow = []
    for i, (s, title, t, items, *label) in enumerate(steps, 1):
        c = {'done': ('c-done', '已完成'), 'run': ('c-run', '进行中'), 'wait': ('c-bad', status), 'todo': ('c-todo', '未开始')}[s]
        if label and label[0]:
            c = (c[0], label[0])
        if items is None:
            body = run_card
        else:
            li = ''.join(f'<li>{x}</li>' for x in items if not x.startswith('<'))
            body = (f'<ul>{li}</ul>' if li else '') + ''.join(x for x in items if x.startswith('<'))
        flow.append(f'<section class="step {s}"><div class="dot">{i}</div><div class="card"><div class="head"><h2>{title}</h2>'
                    f'<span class="chip {c[0]}">{c[1]}</span><span class="when">{t}</span></div>{body}</div></section>')

    sub = (f'现在在跑第 4 步：Grok 4.7 逐帧层，{conc or "—"} 路，每分钟约 {rate:.0f} 窗，'
           + (f'预计 <b>{when(eta)}</b> 跑完三集。' if eta else '速度数据还不够。')
           + '第 5 步起等逐帧层跑完再做。') if not finished else '逐帧层已全部跑满，接下来做本机预处理。'
    if not alive and not finished:
        sub = '<b>注意：逐帧层调度没在跑</b>（可能被停了或出错），请告诉我看一下。' + sub
    page = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60"><title>地纪 · 倪师堪舆四集精读进度</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;700&family=Noto+Sans+SC:wght@400;500;600&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
<h1>地纪 · 倪师《天纪》堪舆四集逐帧精读进度</h1>
<p class="sub">{sub}</p>
<div class="facts">
  <div class="fact"><b>4 集 · 3.9 小时</b><span>堪舆一至四（P31 P33 P35 P37）</span></div>
  <div class="fact"><b>330,673 帧</b><span>新跑三集逐帧（P37 已在紫微那轮跑完）</span></div>
  <div class="fact"><b>{100 * done / total:.1f}%</b><span>逐帧层 {done:,} / {total:,} 窗</span></div>
  <div class="fact"><b>{(tok["inputTokens"] + tok["cacheReadTokens"] + tok["outputTokens"]) / 1e8:.2f} 亿</b><span>已用 token（Cursor 账户）</span></div>
</div>
<div class="legend"><span class="chip c-done">已完成</span><span class="chip c-run">进行中</span><span class="chip c-todo">未开始</span><span class="chip c-bad">要处理</span></div>
<div class="flow">{"".join(flow)}</div>
<footer>本页 {now:%Y-%m-%d %H:%M:%S} 生成，每 1 分钟重载数字；「几秒前」和右上角时钟每秒走。数据来自 <code>第0步/逐帧层/全量/P31–P35.jsonl</code> 与调度日志 <code>第0步/日志/堪舆-逐帧-grok.log</code>；生成脚本 <code>第0步/kanyu_progress.py</code>。</footer>
</div>
<script>
const lastEl = document.getElementById('lastwin');
const clock = document.getElementById('nowclock');
const lastMs = lastEl ? Number(lastEl.dataset.last) : 0;
function tick() {{
  const now = new Date();
  if (clock) clock.textContent = now.toLocaleTimeString('zh-CN', {{hour12: false}});
  if (!lastEl || !lastMs) return;
  const ago = Math.max(0, Math.round((Date.now() - lastMs) / 1000));
  const warn = ago >= 180 ? '（超过 3 分钟没出新窗，可能停了）' : '';
  lastEl.textContent = '最后一窗 ' + lastEl.dataset.hms + '，' + ago + ' 秒前' + warn;
}}
tick();
setInterval(tick, 1000);
setTimeout(function () {{ location.reload(); }}, 60000);
</script>
</body></html>
'''
    tmp = OUT.with_suffix('.html.part')
    tmp.write_text(page)
    tmp.rename(OUT)
    print('已写', OUT, f'{done}/{total}', f'{rate:.1f} 窗/分')


if __name__ == '__main__':
    main()

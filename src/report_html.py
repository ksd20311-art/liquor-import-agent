"""스킬(report_style) 형식의 한국어 HTML 리포트. 숫자는 모두 계산 결과에서 가져오고 문장은 코드 템플릿이다.

규칙 출처: report_style/SKILL.md (제목 40자 이내 명사 종결, 숫자는 비교 대상과 함께, 그림·표마다 출처 줄,
가로줄 표, 한 색 계열, A4 세로 판면). 딜로이트 이름·로고·초록색은 쓰지 않는다.
"""
import csv
import html
import json
import re
import shutil
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "report_style" / "scripts" / "check_korean.py"
SETTINGS = ROOT / "config" / "report_settings.json"

COUNTRY_NAMES = {"JP": "일본", "FR": "프랑스", "US": "미국", "GB": "영국", "IE": "아일랜드", "IT": "이탈리아",
                 "ES": "스페인", "DE": "독일", "CL": "칠레", "AU": "호주", "CA": "캐나다", "NZ": "뉴질랜드",
                 "CN": "중국", "IN": "인도", "TR": "튀르키예", "VN": "베트남", "MX": "멕시코", "NL": "네덜란드",
                 "BE": "벨기에", "CZ": "체코", "TH": "태국", "PH": "필리핀", "SG": "싱가포르", "RU": "러시아",
                 "TW": "대만", "SE": "스웨덴", "CU": "쿠바", "PT": "포르투갈", "AT": "오스트리아", "AR": "아르헨티나",
                 "ZA": "남아프리카공화국", "ID": "인도네시아", "BR": "브라질", "PL": "폴란드", "DK": "덴마크",
                 "KR": "한국", "JM": "자메이카", "CO": "콜롬비아", "PE": "페루", "MY": "말레이시아", "KH": "캄보디아"}
KIND_NAMES = {"retail": "소매가", "quote": "도매·견적가"}
CSS = """
  @page { size: A4; margin: 29mm 17mm 35mm 15mm; }
  :root { --ink:#231f20; --gray:#5f636a; --rule:#c8c9cc; --accent:#1e5e9e; --accent-2:#6f9fd0; --accent-3:#c9dcf0;
          --accent-4:#0f3d6b; --accent-5:#a9c6e4; --tint:#f3f6fa; }
  * { box-sizing: border-box; }
  body { margin:0; color:var(--ink); background:#fff; font-family:'NanumBarunGothic','Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif; font-size:8.5pt; line-height:1.65; }
  .num, td.n, th.n { font-family:'Open Sans','NanumBarunGothic','Noto Sans KR','Malgun Gothic',sans-serif; font-variant-numeric:tabular-nums; }
  body, p, h1, h2, h3, td, th, li { word-break:keep-all; overflow-wrap:break-word; }
  .refs { word-break:break-all; }
  section.page { page-break-after:always; }
  section.page:last-child { page-break-after:auto; }
  section.page.fit { display:flex; flex-direction:column; min-height:230mm; }
  @media screen { body { background:#e9eaec; padding:16px; }
    section.page, section.page.fit { width:210mm; max-width:100%; min-height:297mm; margin:0 auto 16px; background:#fff; padding:29mm 17mm 35mm 15mm; } }
  .eyebrow { font-size:9pt; color:var(--accent); font-weight:700; letter-spacing:.02em; margin:0 0 3mm; }
  h1 { font-size:24pt; line-height:1.3; margin:0 0 5mm; letter-spacing:-.01em; }
  h2 { font-size:17pt; line-height:1.3; margin:0 0 4mm; letter-spacing:-.01em; }
  h3 { font-size:11pt; line-height:1.35; margin:5mm 0 2.2mm; padding-left:2.5mm; border-left:1mm solid var(--accent); }
  .split h3:first-child, .cols2 h3:first-child { margin-top:0; }
  .lead { font-size:10pt; line-height:1.55; color:var(--gray); margin:0 0 5mm; }
  p { margin:0 0 3mm; }
  .grow { flex:1; min-height:3mm; }
  .pagefoot { border-top:.5px solid var(--rule); padding-top:2mm; font-size:7pt; color:var(--gray); display:flex; justify-content:space-between; }
  /* 표지 */
  .cover .bar { height:4mm; width:40mm; background:var(--accent); margin-bottom:8mm; }
  .cover .meta { font-size:8pt; color:var(--gray); margin:0; }
  .facts { display:grid; grid-template-columns:1fr 1fr; column-gap:8mm; border-top:1.5px solid var(--ink); margin-top:14mm; }
  .facts div { display:flex; justify-content:space-between; gap:5mm; padding:2.4mm 0; border-bottom:.5px solid var(--rule); }
  .facts span { color:var(--gray); white-space:nowrap; } .facts b { text-align:right; }
  /* 요약 */
  .concl { background:var(--accent-4); color:#fff; padding:4mm 5.5mm; font-size:10pt; line-height:1.55; margin:0 0 5mm; }
  .concl b { display:block; font-size:8pt; color:var(--accent-3); letter-spacing:.06em; margin-bottom:1mm; }
  .keys { display:grid; grid-template-columns:repeat(3,1fr); gap:4mm; }
  .key { background:var(--tint); border-top:2px solid var(--accent); padding:3.5mm 4mm 3mm; }
  .key .big { font-size:20pt; font-weight:700; color:var(--accent); line-height:1.15; }
  .key .cmp { font-size:7.5pt; line-height:1.5; color:var(--gray); margin:.8mm 0 2mm; }
  .key p { margin:0; }
  .note { border:.5px solid var(--rule); border-left:1.2mm solid var(--accent); padding:2.5mm 3.5mm; margin-top:5mm; font-size:8pt; line-height:1.6; }
  .note p { margin:0 0 1.5mm; } .note p:last-child { margin:0; }
  /* 본문 */
  .split { display:grid; grid-template-columns:1.1fr 1fr; gap:7mm; align-items:start; margin-bottom:4mm; }
  .cols2 { display:grid; grid-template-columns:1fr 1fr; gap:7mm; align-items:start; margin-bottom:3mm; }
  .cols2 p:last-child { margin-bottom:0; }
  figure { margin:0; }
  figcaption { font-size:9pt; font-weight:700; margin-bottom:2mm; }
  .source { font-size:7pt; line-height:1.5; color:var(--gray); margin-top:2mm; }
  table { width:100%; border-collapse:collapse; font-size:8pt; line-height:1.5; }
  th { text-align:left; font-weight:700; border-bottom:1.5px solid var(--ink); padding:1.6mm 1.2mm; vertical-align:bottom; }
  td { border-bottom:.5px solid var(--rule); padding:1.6mm 1.2mm; vertical-align:top; }
  table.compact { line-height:1.4; } table.compact th, table.compact td { padding:.55mm 1.2mm; }
  td:first-child, th:first-child { white-space:nowrap; padding-right:3mm; }
  td.n, th.n { text-align:right; }
  tr.hl td { background:#e6eef8; font-weight:700; }
  .legend { font-size:7.5pt; margin-top:2mm; } .legend span.sw { display:inline-block; width:2.6mm; height:2.6mm; margin-right:1.2mm; vertical-align:-0.3mm; }
  .legend div { padding:.7mm 0; border-bottom:.5px solid var(--rule); display:flex; justify-content:space-between; }
  .flow { display:flex; align-items:stretch; gap:1.4mm; }
  .flow .cell { flex:1; background:var(--tint); padding:2.4mm 1.5mm; text-align:center; line-height:1.4; }
  .flow .cell small { display:block; font-size:7pt; color:var(--gray); } .flow .cell b { font-size:10pt; }
  .flow .op { align-self:center; font-size:10pt; font-weight:700; color:var(--gray); }
  .flow .cell.total { flex:1.3; background:var(--accent-4); color:#fff; } .flow .cell.total small { color:var(--accent-3); }
  .badge { background:var(--tint); border-left:1.5mm solid var(--accent); padding:4mm 5mm; }
  .badge small { display:block; font-size:7.5pt; color:var(--gray); }
  .badge b { display:block; font-size:18pt; line-height:1.2; color:var(--accent); margin:.5mm 0 1.5mm; }
  .badge p { margin:0; }
  .stats { display:grid; gap:2mm; }
  .stat { background:var(--tint); border-left:1mm solid var(--accent-2); padding:2mm 3.5mm; line-height:1.35; }
  .stat small { display:block; font-size:7.5pt; color:var(--gray); } .stat span { display:block; font-size:7pt; color:var(--gray); }
  .stat b { display:block; font-size:13pt; color:var(--accent); }
  ol.implication { list-style:none; padding:0; margin:0; counter-reset:todo; border-top:1.5px solid var(--ink); }
  ol.implication li { counter-increment:todo; position:relative; margin:0; padding:1.7mm 0 1.7mm 9mm; border-bottom:.5px solid var(--rule); }
  ol.implication li::before { content:counter(todo); position:absolute; left:0; top:1.6mm; width:5.4mm; height:5.4mm; border-radius:50%;
    background:var(--accent); color:#fff; font-size:8pt; font-weight:700; line-height:5.4mm; text-align:center; }
  .refs { font-size:7.5pt; line-height:1.5; color:var(--gray); margin-bottom:1.5mm; } ol.refs { padding-left:4mm; margin:0; } ol.refs li { margin-bottom:.8mm; }
  .running { font-size:7pt; color:var(--gray); border-top:.5px solid var(--rule); padding-top:2mm; margin-top:8mm; }
"""


def assumption_text(asm: dict) -> str:
    """운임·보험료·통관비 가정값을 한 줄로. 모두 0이면 「모두 0원, 미포함」."""
    f, i, c = float(asm["freight_local"]), float(asm["insurance_local"]), float(asm["clearance_domestic_krw"])
    if not (f or i or c):
        return "모두 0원, 미포함"
    return f"운임 {f:g}·보험료 {i:g}(현지 통화), 통관·국내운송비 {c:,.0f}원"


def margin_text(asm: dict) -> str:
    """마진율과 출처: 「30%(가정)」 또는 「25%(입력값)」."""
    return f"{float(asm['retail_margin']) * 100:g}%({'입력값' if asm.get('margin_input') else '가정'})"


def e(x) -> str:
    return html.escape(str(x))


def w(x) -> str:
    return f"{int(Decimal(str(x)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def pct(x, nd=1, sign=False) -> str:
    return f"{float(x):+.{nd}f}%" if sign else f"{float(x):.{nd}f}%"


def author() -> str:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get("author", "수입 주류 원가·시장 리포트 에이전트")
    except (OSError, ValueError):
        return "수입 주류 원가·시장 리포트 에이전트"


def short_name(name: str) -> str:
    s = re.sub(r"\(.*?\)|\d{2,4}\s*ml|\d+(\.\d+)?\s*%", "", name, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*(위스키|와인|사케)$", "", s).strip()
    if len(s) > 24:  # 표지 제목(이름 + 「, 국내 판매가 대비 원가 열위」 16자)이 40자를 넘지 않게. 단어 중간에서 자르지 않는다
        s = s[:24].rsplit(" ", 1)[0]
    return s.strip()


def has_batchim(word: str) -> bool:
    ch = word.strip()[-1:]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch in "0136780"  # 영·일·삼·육·칠·팔·공(영어·기호는 받침 없음으로 본다)


def eun(word: str) -> str:
    return word + ("은" if has_batchim(word) else "는")


def compare_cols(r):
    names = list(r["costs"])
    main = "협정세율" if "협정세율" in r["costs"] else names[0]
    return names, main, r["costs"][main]


# ---- 그림 ---------------------------------------------------------------
def svg_stack(c):
    parts = [("과세가격", c["taxable_value"], "var(--accent-3)", "#231f20"), ("관세", c["customs"], "var(--accent-5)", "#231f20"),
             ("주세", c["liquor_tax"], "var(--accent-4)", "#fff"), ("교육세", c["edu_tax"], "var(--accent)", "#fff"),
             ("부가세", c["vat"], "var(--accent-2)", "#fff")]
    total = sum(float(p[1]) for p in parts) or 1
    x, rects = 0.0, []
    for label, val, color, ink in parts:
        wd = float(val) / total * 300
        rects.append(f'<rect x="{x:.1f}" y="4" width="{wd:.1f}" height="38" fill="{color}"/>')
        if wd >= 30:  # 칸이 넉넉할 때만 비중을 막대 안에 적는다
            rects.append(f'<text x="{x + wd / 2:.1f}" y="27" font-size="9" font-weight="700" fill="{ink}" text-anchor="middle">'
                         f'{float(val) / total * 100:.0f}%</text>')
        x += wd
    svg = (f'<svg viewBox="0 0 300 46" width="100%" role="img" aria-label="도착 원가 구성 막대">{"".join(rects)}</svg>')
    legend = "".join(
        f'<div><span><span class="sw" style="background:{color}"></span>{label}</span>'
        f'<span class="num">{w(val)}원 ({float(val) / total * 100:.1f}%)</span></div>' for label, val, color, _ in parts)
    return svg + f'<div class="legend">{legend}</div>'


def svg_months(table):
    vals = [x["usd"] or 0 for x in table]
    mx = max(vals) or 1
    div, unit = (1e6, "백만 달러") if mx >= 1e6 else (1e3, "천 달러")
    dec = 1 if mx / div >= 10 else 2
    peak = vals.index(max(vals))
    grid, bars, labels, marks = [], [], [], []
    for frac in (0.5, 1.0):  # 가로 눈금선(절반, 최대)
        y = 96 - frac * 74
        grid.append(f'<line x1="30" y1="{y:.1f}" x2="326" y2="{y:.1f}" stroke="#e3e5e8"/>'
                    f'<text x="27" y="{y + 3:.1f}" text-anchor="end">{mx * frac / div:.{dec}f}</text>')
    for i, x in enumerate(table):
        h = (x["usd"] or 0) / mx * 74
        bx = 34 + i * 24.5
        last = i == len(table) - 1
        bars.append(f'<rect x="{bx:.1f}" y="{96 - h:.1f}" width="17" height="{h:.1f}" fill="{"var(--accent)" if last else "var(--accent-2)"}"/>')
        if i % 2 == 1 or last:
            labels.append(f'<text x="{bx + 8.5:.1f}" y="108">{x["ym"][2:4]}.{x["ym"][4:]}</text>')
        if (i == peak or last) and x["usd"]:  # 최대 월과 최근월에만 값을 적는다
            marks.append(f'<text x="{bx + 8.5:.1f}" y="{93 - h:.1f}" font-weight="700" fill="#231f20">{x["usd"] / div:.{dec}f}</text>')
    return (f'<svg viewBox="0 0 330 113" width="100%" role="img" aria-label="월별 수입액 막대 그래프">'
            f'<g font-size="7.5" fill="#5f636a">{"".join(grid)}<text x="30" y="9">{unit}</text></g>'
            f'<line x1="30" y1="96" x2="326" y2="96" stroke="#c8c9cc"/>{"".join(bars)}'
            f'<g font-size="7.5" fill="#5f636a" text-anchor="middle">{"".join(labels)}{"".join(marks)}</g></svg>')


def svg_hbars(rows):
    mx = max(v for _, v, _ in rows) or 1
    out = []
    for i, (label, v, shade) in enumerate(rows):
        y = 4 + i * 28
        wd = v / mx * 150
        out.append(f'<text x="0" y="{y + 13}" font-size="8" fill="#231f20">{e(label)}</text>'
                   f'<rect x="122" y="{y}" width="{wd:.1f}" height="19" fill="{shade}"/>'
                   f'<text x="{126 + wd:.1f}" y="{y + 13}" font-size="8" font-weight="700" fill="#231f20">{w(v)}원</text>')
    return (f'<svg viewBox="0 0 330 {4 + len(rows) * 28}" width="100%" role="img" aria-label="금액 비교 막대">'
            f'{"".join(out)}</svg>')


def tbl(head, rows, hl=None, num_from=1, cls=""):
    h = "".join(f'<th class="{"n" if i >= num_from else ""}">{e(c)}</th>' for i, c in enumerate(head))
    body = ""
    for ri, row in enumerate(rows):
        rc = ' class="hl"' if hl is not None and ri == hl else ""
        body += f"<tr{rc}>" + "".join(
            f'<td class="{"n" if i >= num_from else ""}">{e(c)}</td>' for i, c in enumerate(row)) + "</tr>"
    return f'<table{(" class=" + chr(34) + cls + chr(34)) if cls else ""}><tr>{h}</tr>{body}</table>'


def paragraphs(text: str, first: int = 2) -> str:
    """긴 해설을 문장 단위로 두 문단으로 나눈다(앞 문단 first문장). 문장은 「다.」로 끝난다고 본다."""
    sents = [s for s in re.split(r"(?<=다\.)\s+", text.strip()) if s]
    if len(sents) <= first + 1:
        return f"<p>{e(' '.join(sents))}</p>"
    return f"<p>{e(' '.join(sents[:first]))}</p><p>{e(' '.join(sents[first:]))}</p>"


# ---- 본문 ---------------------------------------------------------------
def build_html(r: dict) -> str:
    inp, fxi, v, asm, rule = r["input"], r["fx"], r["fta"], r["assumptions"], r["rule"]
    names, main, c = compare_cols(r)
    costs, rates = r["costs"], r["rates"]
    price, cur = float(inp["local_price"]), inp["currency"]
    price_s = f"{price:,.0f}" if price == int(price) else f"{price:,.2f}"  # 29.99달러를 30으로 보이지 않게
    pname = inp.get("product_name_ko") or inp["product_name"]
    short = short_name(pname) or pname[:20].strip() or "수입 후보"
    dom = float(inp["domestic_price"]) if inp.get("domestic_price") else None
    landed, retail = float(c["landed_cost"]), float(c["expected_retail"])
    tax_total = float(c["total_tax"])
    share = tax_total / landed * 100
    gap = (retail / dom - 1) * 100 if dom else None
    origin = COUNTRY_NAMES.get(inp.get("origin_country", ""), inp.get("origin_country", ""))
    margin = float(asm["retail_margin"]) * 100
    liq_rate = float(rule.liquor_tax_rate) * 100
    edu_ratio = (float(rule.edu_tax_ratio) * 100 if rule.edu_tax_ratio is not None else (30 if liq_rate > 70 else 10))
    kind = KIND_NAMES.get(inp.get("price_kind") or "retail", "소매가")
    per_l = float(rule.specific_tax_per_liter or 0)
    series = r["trend"]
    today = r["as_of"]
    gen_c = costs.get("일반세율")
    diff_fta = float(gen_c["landed_cost"]) - landed if gen_c is not None and main == "협정세율" else None
    cust_share = float(c["customs"]) / tax_total * 100
    liq_share = float(c["liquor_tax"]) / tax_total * 100
    # 쪽 구성: 표지, 요약, 1장, 2장, (3장 시장), (4장 국내가), 시사점·출처
    total_pages = 5 + (1 if series else 0) + (1 if dom else 0)

    def foot(n):
        return (f'<div class="grow"></div><div class="pagefoot"><span>수입 후보 원가·시장 리포트 · {e(short)} · {e(today)}</span>'
                f'<span class="num">{n} / {total_pages}</span></div>')

    # 표지 -----------------------------------------------------------------
    if dom:
        verdict_word = "열위" if retail > dom else "우위"
        title = f"{short}, 국내 판매가 대비 원가 {verdict_word}"
    else:
        title = f"{short}의 도착 원가와 FTA 판정"
    sub = (f"소규모 주류 수입사 상품 기획 담당자 대상 · 견적 전 후보 검토용 참고 원가 · {origin}산 {rule.name_ko} · 입력가 "
           f"{price_s}{cur} 기준")
    facts = [("제품", pname), ("주종 · 품목 코드", f"{rule.name_ko} · {inp.get('hs_code') or '-'}"),
             ("원산지 · 구매국", f"{origin or '-'} · {COUNTRY_NAMES.get(inp['purchase_country'], inp['purchase_country'])}"),
             ("입력가 · 가격 종류", f"{price_s} {cur} · {kind}"),
             ("과세환율", f"{cur} 1단위 {fxi['rate']}원"), ("환율 적용 주간", f"{fxi['week_start']}~{fxi['week_end']}"),
             ("적용 관세율", " / ".join(f"{n} {float(rates[n]) * 100:g}%" for n in names)), ("FTA 판정", v.verdict)]
    cover = f"""<section class="page fit cover"><div><div class="bar"></div>
<p class="eyebrow">수입 후보 원가·시장 리포트 · {e(today)}</p><h1>{e(title)}</h1><p class="lead">{e(sub)}</p>
<div class="facts">{''.join(f'<div><span>{e(k)}</span><b>{e(x)}</b></div>' for k, x in facts)}</div></div>
<div class="grow"></div>
<p class="meta">작성 {e(today)} · 작성자 {e(author())} · 자료 출처: 관세청 관세환율정보, 품목번호별 관세율표, 품목별 국가별 수출입실적</p></section>"""

    # 요약에 들어갈 문장과 숫자 -------------------------------------------------
    if dom:
        concl = (f"{eun(short)} 입력가 {price_s}{cur} 기준 도착 원가가 {w(landed)}원이고 예상 소비자가 {w(retail)}원이 국내 판매가 "
                 f"{w(dom)}원보다 {abs(gap):.1f}% {'높아' if gap > 0 else '낮아'}, "
                 + ("입력가로는 국내 판매가와 경쟁하기 어렵다." if gap > 0 else "마진을 더 확보할 여지가 있다."))
    else:
        concl = f"{short}의 도착 원가는 입력가 {price_s}{cur} 기준 {w(landed)}원이며 세금이 {share:.1f}%를 차지한다."
    k1_cmp = (f"일반세율 원가 {w(gen_c['landed_cost'])}원 대비 {w(diff_fta)}원 낮음" if diff_fta is not None and diff_fta > 0
              else f"과세가격 {w(c['taxable_value'])}원 대비 세금 {w(tax_total)}원 가산")
    k1_txt = f"{main} 적용 도착 원가는 과세가격에 세금 {w(tax_total)}원이 더해진 금액이다."
    if dom:
        k2_big, k2_cmp = pct(gap, 1, True), f"국내 판매가 {w(dom)}원 대비 예상 소비자가 {w(retail)}원"
        k2_txt = f"마진율 {margin_text(asm)}을 붙인 예상 소비자가가 국내 판매가를 {'웃돈다' if gap > 0 else '밑돈다'}."
    else:
        k2_big, k2_cmp = pct(share, 1), f"도착 원가 {w(landed)}원 대비 세금 비중"
        k2_txt = f"주세와 교육세가 세금 {w(tax_total)}원의 {(float(c['liquor_tax']) + float(c['edu_tax'])) / tax_total * 100:.0f}%를 차지한다."
    if series:
        s = series["summary"]
        yoy = s["yoy_12m_pct"]
        k3_big = f"{s['usd_12m'] / 1e6:.1f}백만 달러"
        k3_cmp = (f"직전 12개월 {s['usd_prev_12m'] / 1e6:.1f}백만 달러 대비 {yoy:+.1f}%" if yoy is not None
                  else (f"최근 12개월 평균 단가 {s['unit_12m']:.2f}달러/kg" if s["unit_12m"] else f"최근월 {s['last_month']} 기준"))
        k3_txt = f"{origin}산 동일 품목의 최근 12개월 수입액이다."
    else:
        k3_big, k3_cmp = f"{fxi['rate']}원", f"관세청 과세환율 {inp['currency']} 1단위, 적용 주간 {fxi['week_start']}~{fxi['week_end']}"
        k3_txt = "시장 추이는 자료를 받지 못해 환율만 제시한다."
    sens = r["sensitivity"][main]
    ten_local = float(sens["ten_pct_local"])
    ten_s = f"{ten_local:,.0f}" if ten_local == int(ten_local) else f"{ten_local:,.2f}"
    m_rate = float(asm["retail_margin"])
    note = (f'<div class="note"><p><b>참고 원가다.</b> 이 리포트는 관세사·포워더 견적을 받기 전에 여러 후보 가운데 견적을 받아 볼 후보를 거르는 용도다. '
            f"운임·보험료·통관·국내운송비는 거래마다 달라 가정값({e(assumption_text(asm))})으로 계산했으므로, 견적을 받으면 아래 표로 도착 원가를 보정한다. "
            f"예상 소비자가는 도착 원가에 마진율 {margin_text(asm)}을 붙인 값이다.</p></div>")
    sens_rows = [
        ["운임·보험료", ("과세가격에 들어가 관세·부가세가 함께 붙음(주세는 용량 기준)" if rule.is_specific else "과세가격에 들어가 관세·주세·교육세·부가세가 함께 붙음"), f"{float(sens['per_krw']):.2f}원",
         f"현지가의 10%({ten_s}{cur}, {w(sens['ten_pct_krw'])}원)", f"+{w(sens['ten_pct_delta'])}원",
         f"+{w(float(sens['ten_pct_delta']) * (1 + m_rate))}원"],
        ["통관·국내운송비", "세금 계산 뒤에 더해져 금액만큼 늘어남", f"{float(sens['clearance_per_krw']):.2f}원",
         f"{w(sens['clearance_example'])}원", f"+{w(sens['clearance_delta'])}원",
         f"+{w(float(sens['clearance_delta']) * (1 + m_rate))}원"]]
    sens_block = (f'<h3>견적을 받으면 이렇게 보정한다 ({e(main)} 기준)</h3>'
                  + tbl(["비용 항목", "도착 원가에 반영되는 방식", "1원당 도착 원가 증가", "예시 금액", "도착 원가 증가", "예상 소비자가 증가"],
                        sens_rows, num_from=2)
                  + f'<p class="source">출처: 본 에이전트 계산(같은 세율·과세환율로 비용만 늘려 다시 계산). 예상 소비자가 증가는 마진율 {margin_text(asm)} 적용. '
                    '숫자의 근거 목록은 같은 폴더의 facts.csv에 있다.</p>')

    # 1장 원가 ---------------------------------------------------------------
    if rule.is_specific:
        para1 = (f"{eun(rule.name_ko)} 가격이 아니라 용량에 주세가 붙는 종량세 주종이다. "
                 f"주세는 용량 {int(inp['volume_ml']):,}ml에 리터당 {per_l:g}원을 곱한 {w(c['liquor_tax'])}원으로 세금 {w(tax_total)}원의 {liq_share:.0f}%다. "
                 + (f"교육세는 주세의 {edu_ratio:g}%인 {w(c['edu_tax'])}원이 붙는다. " if edu_ratio else "교육세는 붙지 않는다. ")
                 + f"관세는 {w(c['customs'])}원으로 세금 전체의 {cust_share:.0f}%를 차지한다. 가격이 올라도 주세는 변하지 않고 관세와 부가세만 늘어난다.")
    else:
        para1 = (f"주세 {w(c['liquor_tax'])}원이 세금 {w(tax_total)}원의 {liq_share:.0f}%로 가장 큰 항목이다. "
                 f"이는 {rule.name_ko} 주세율 {liq_rate:.0f}%가 과세가격에 관세를 더한 금액에 적용되기 때문이다. "
                 f"또한 교육세는 {'주세율이 70%를 넘어 ' if liq_rate > 70 else ''}주세의 {edu_ratio:g}%인 {w(c['edu_tax'])}원이 붙는다. "
                 f"반면 관세는 {w(c['customs'])}원으로 세금 전체의 {cust_share:.0f}%에 그친다.")
    head = ["구분(원)"] + [f"{n} {float(rates[n]) * 100:.1f}%" for n in names]
    keys = [("과세가격", "taxable_value"), ("관세", "customs"), ("주세", "liquor_tax"), ("교육세", "edu_tax"),
            ("부가세", "vat"), ("통관·국내운송(가정)", "clearance_domestic"), ("도착 원가", "landed_cost")]
    rows1 = [[lab] + [w(costs[n][k]) for n in names] for lab, k in keys]
    steps = [("과세가격", c["taxable_value"]), ("관세", c["customs"]), ("주세", c["liquor_tax"]), ("교육세", c["edu_tax"]), ("부가세", c["vat"])]
    flow = '<span class="op">+</span>'.join(f'<div class="cell"><small>{lab}</small><b class="num">{w(val)}</b></div>' for lab, val in steps)
    flow = (f'<div class="flow">{flow}<span class="op">=</span>'
            f'<div class="cell total"><small>도착 원가</small><b class="num">{w(landed)}원</b></div></div>')
    t1 = f"도착 원가의 {share:.0f}%가 세금으로 구성"
    sec1 = f"""<section class="page fit"><p class="eyebrow">1장 · 원가</p><h2>{e(t1)}</h2>
<p class="lead">입력가 {price_s}{cur}에 과세환율 {fxi['rate']}원을 곱한 과세가격은 {w(c['taxable_value'])}원이며, 세금 {w(tax_total)}원이 더해져 도착 원가는 {w(landed)}원이다.</p>
<figure style="margin-bottom:6mm"><figcaption>과세가격에서 도착 원가까지 (단위: 원, {e(main)} 기준)</figcaption>{flow}</figure>
<div class="split"><figure><figcaption>도착 원가 구성 (단위: 원, {e(main)} 기준, {e(today)})</figcaption>{svg_stack(c)}
<p class="source">출처: 관세청 관세환율정보(적용 주간 {e(fxi['week_start'])}~{e(fxi['week_end'])}), 관세청 품목번호별 관세율표 2026, 주세법 제8조, 교육세법 제5조 (계산: 본 에이전트)</p></figure>
<div><h3>세금 구성</h3>{paragraphs(para1)}</div></div>
<figure><figcaption>세율 구분별 원가 분해표 (단위: 원)</figcaption>{tbl(head, rows1, hl=len(rows1) - 1)}
<p class="source">출처: 본 에이전트 계산. 통관·국내운송비는 가정값 {w(asm['clearance_domestic_krw'])}원이다.</p></figure>{foot(3)}</section>"""

    # 2장 FTA ---------------------------------------------------------------
    if v.verdict == "적용 가능":
        t2 = f"{v.agreement} 협정세율 적용 가능 판정"
    elif v.verdict == "적용 불가":
        t2 = "협정세율 적용 불가, 일반세율 기준 원가 산정"
    else:
        t2 = ("FTA 판정은 확인 필요, 협정세율 적용 시 " + w(diff_fta) + "원 절감") if diff_fta else "FTA 판정은 확인 필요 단계"
    pref = float(v.preferential_rate) * 100 if v.preferential_rate is not None else None
    gen = float(v.general_rate) * 100 if v.general_rate is not None else None
    if v.agreement and pref is not None and gen is not None:
        p2a = (f"{v.agreement} 협정세율은 {pref:.1f}%로 일반세율 {gen:.1f}%보다 {gen - pref:.1f}%p 낮다. "
               + (f"이 차이로 도착 원가는 {w(diff_fta)}원 달라진다. " if diff_fta else "")
               + f"다만 협정세율은 원산지증명서와 직접 운송 요건을 갖춘 경우에만 적용된다. ")
    else:
        p2a = "이 품목은 규칙표에서 협정세율을 찾지 못해 일반세율을 적용했다. "
    p2b = (f"원산지 국가 생산 여부 응답은 「{inp.get('made_in_origin', '모름')}」, 원산지증명서 발급 가능 여부 응답은 「{inp.get('has_certificate', '모름')}」이다. "
           + (f"구매국 {inp['purchase_country']}과 원산지 {inp.get('origin_country')}이 다르면 경유 구매로 보아 협정세율이 배제될 수 있다." if inp.get("origin_country") != inp["purchase_country"]
              else "구매국과 원산지가 같아 경유 구매 문제는 없다."))
    levels = [["적용 가능", "협정·품목 있음, 원산지 일치, 생산 「예」, 증명서 「예」", "협정세율, 필요 서류 안내"],
              ["확인 필요", "증명서 「모름」, 경유 구매, 규칙표에 없음", "협정·일반 두 원가 병기"],
              ["적용 불가", "협정 없음, 대상 품목 아님, 증명서 「아니오」", "일반세율"]]
    hl2 = {"적용 가능": 0, "확인 필요": 1, "적용 불가": 2}[v.verdict]
    badge_txt = (f"협정세율 {pref:g}% · 일반세율 {gen:g}%" if pref is not None and gen is not None
                 else f"적용 세율 {' / '.join(f'{n} {float(rates[n]) * 100:g}%' for n in names)}")
    rate_rows = [[n, f"{float(rates[n]) * 100:g}%", f"{w(costs[n]['customs'])}원", f"{w(costs[n]['landed_cost'])}원"] for n in names]
    shades = ["var(--accent-4)", "var(--accent)", "var(--accent-5)", "var(--accent-2)"]
    cost_bars = ""
    if len(names) > 1:  # 두 세율을 함께 보여 줄 때만 비교 막대를 넣는다
        cost_bars = f"""<figure style="margin-top:5mm"><figcaption>세율별 도착 원가 비교 (단위: 원)</figcaption>
<div style="width:64%">{svg_hbars([(f"{n} {float(rates[n]) * 100:g}%", float(costs[n]["landed_cost"]), shades[i]) for i, n in enumerate(names)])}</div>
<p class="source">출처: 본 에이전트 계산. 판정이 「확인 필요」여서 두 세율의 원가를 함께 제시한다.</p></figure>"""
    sec2 = f"""<section class="page fit"><p class="eyebrow">2장 · FTA</p><h2>{e(t2)}</h2>
<p class="lead">판정 결과는 「{e(v.verdict)}」이며 근거는 {e(v.reason)}</p>
<div class="split"><div class="badge"><small>FTA 판정{(' · ' + e(v.agreement)) if v.agreement and v.agreement != '없음' else ''}</small><b>{e(v.verdict)}</b><p>{e(badge_txt)}</p></div>
<figure><figcaption>세율별 관세와 도착 원가</figcaption>{tbl(["세율 구분", "관세율", "관세", "도착 원가"], rate_rows)}
<p class="source">출처: 본 에이전트 계산(관세청 품목번호별 관세율표 2026).</p></figure></div>
<figure><figcaption>FTA 3단계 판정 기준 (현재 판정 강조)</figcaption>{tbl(["판정", "조건", "원가 처리"], levels, hl=hl2, num_from=9)}
<p class="source">출처: 관세청 품목번호별 관세율표 2026(공공데이터포털 15051179), YES FTA 포털. {e(v.disclaimer)}</p></figure>
<div class="cols2" style="margin-top:5mm"><div><h3>적용 세율</h3><p>{e(p2a)}</p></div><div><h3>응답과 경유 구매</h3><p>{e(p2b)}</p></div></div>
{('<p><b>필요 서류</b> ' + e(v.documents) + '</p>') if v.documents else ''}{cost_bars}{foot(4)}</section>"""

    # 3장 시장 ---------------------------------------------------------------
    sec3, t3 = "", ""
    if series:
        s, t = series["summary"], series["table"]
        yoy = s["yoy_12m_pct"]
        word = "확대" if (yoy or 0) >= 0 else "축소"
        t3 = f"{origin}산 {rule.name_ko} 수입액, 직전 12개월 대비 {abs(yoy):.1f}% {word}" if yoy is not None else f"{origin}산 {rule.name_ko}의 최근 12개월 수입 추이"
        peaks = [x for x in t if x["usd"]]
        last = t[-1]
        p3 = (f"최근 12개월 {origin}산 수입액은 {s['usd_12m']:,} 달러로 직전 12개월 {s['usd_prev_12m']:,} 달러보다 {abs(yoy):.1f}% {'늘었다' if yoy >= 0 else '줄었다'}. "
              if yoy is not None else f"최근 12개월 {origin}산 수입액은 {s['usd_12m']:,} 달러다. ")
        if peaks:  # 수입액이 모두 0인 경우에도 멈추지 않게 한다
            peak = max(peaks, key=lambda x: x["usd"])
            p3 += (f"월별 최대는 {peak['ym'][:4]}.{peak['ym'][4:]}의 {peak['usd']:,} 달러이고 최근월 {last['ym'][:4]}.{last['ym'][4:]}의 "
                   f"수입액은 {(last['usd'] or 0):,} 달러였다. ")
        if s["unit_12m"]:
            p3 += (f"또한 평균 단가는 {s['unit_12m']:.2f}달러/kg"
                   + (f"이며 최근월은 {last['unit_usd_per_kg']:.2f}달러/kg이다. " if last["unit_usd_per_kg"] else "이다. ")
                   + "이 단가는 품목 전체 평균이어서 병당 가격과는 근사 비교만 가능하다.")
        pos = r.get("position")
        p3b = ""
        if not pos and not inp.get("volume_ml"):
            p3b = "용량 정보가 없어 후보의 가격 위치는 계산하지 않았다."
        if pos:
            rel = "높은" if pos["ratio"] >= 1 else "낮은"
            p3b = (f"후보의 입력가를 달러로 환산하면 약 {pos['unit']:,.0f}달러/kg로, 최근 12개월 평균 수입단가 {s['unit_12m']:.2f}달러/kg의 "
                   f"{pos['ratio']:.1f}배에 해당한다. 월별 단가 {pos['months_total']}개 가운데 {pos['months_below']}개보다 {rel} 수준이며 "
                   f"월별 최고 {pos['month_max']:.2f}달러/kg과 최저 {pos['month_min']:.2f}달러/kg의 범위 "
                   f"{'안에 있다' if pos['month_min'] <= pos['unit'] <= pos['month_max'] else '밖에 있다'}. "
                   "이 평균에는 저가 제품이 함께 들어 있어서 프리미엄 제품은 높게 나온다. "
                   f"순중량은 용량과 도수({pos['net_kg']:.2f}kg{', 도수는 기본값 가정' if pos['abv_assumed'] else ''})로 추정한 근사값이다.")
        stats = [("최근 12개월 수입액", f"{s['usd_12m'] / 1e6:.1f}백만 달러" if s["usd_12m"] >= 1e6 else f"{s['usd_12m']:,} 달러",
                  f"직전 12개월 대비 {yoy:+.1f}%" if yoy is not None else f"최근월 {last['ym'][:4]}.{last['ym'][4:]}")]
        if s["unit_12m"]:
            stats.append(("평균 수입단가", f"{s['unit_12m']:.2f}달러/kg", "최근 12개월, 수입액 ÷ 중량"))
        if pos:
            stats.append(("후보 환산 단가(근사)", f"평균의 {pos['ratio']:.1f}배", f"약 {pos['unit']:,.0f}달러/kg, 입력가 기준"))
        stat_html = "".join(f'<div class="stat"><small>{e(a)}</small><b class="num">{e(b)}</b><span>{e(cc)}</span></div>' for a, b, cc in stats)
        rows3 = [[f"{x['ym'][:4]}.{x['ym'][4:]}", f"{x['usd']:,}" if x["usd"] is not None else "자료 없음",
                  f"{x['kg']:,}" if x["kg"] is not None else "-", f"{x['unit_usd_per_kg']:.2f}" if x["unit_usd_per_kg"] else "-",
                  pct(x["yoy_pct"], 1, True) if x["yoy_pct"] is not None else "-"] for x in t]
        text3 = (f'<div class="cols2"><div><h3>수입 추이</h3><p>{e(p3.strip())}</p></div><div><h3>후보의 가격 위치</h3><p>{e(p3b)}</p></div></div>'
                 if p3b else f'<h3>수입 추이</h3><p>{e(p3.strip())}</p>')
        sec3 = f"""<section class="page fit"><p class="eyebrow">3장 · 시장</p><h2>{e(t3)}</h2>
<p class="lead">HS {e(inp.get('hs_code', ''))} 품목의 {origin}산 수입 실적이며 최근월은 {last['ym'][:4]}.{last['ym'][4:]}이다.</p>
<div class="split" style="grid-template-columns:1.55fr 1fr"><figure><figcaption>월별 수입액 (단위: 달러, 최근 12개월)</figcaption>{svg_months(t)}
<p class="source">출처: 관세청 품목별 국가별 수출입실적(공공데이터포털 15100475), 조회 {e(today)}</p></figure>
<div class="stats">{stat_html}</div></div>
{text3}
<figure><figcaption>월별 수입 실적 (단위: 달러, kg, 달러/kg)</figcaption>{tbl(["월", "수입액", "중량(kg)", "단가", "전년 동월 대비"], rows3, cls="compact")}
<p class="source">출처: 위와 같음. 단가는 수입액을 중량으로 나눈 값이다.</p></figure>{foot(5)}</section>"""

    # 4장 국내가 비교 ----------------------------------------------------------
    sec4, t4 = "", ""
    if dom:
        rc = r["ref_costs"]
        t4 = f"예상 소비자가, 국내 판매가 대비 {gap:+.1f}% 격차"
        bar_rows = [("도착 원가", landed, shades[0]), (f"예상 소비자가(마진율 {margin:g}%)", retail, shades[1]), ("국내 판매가", dom, shades[2])]
        if rc and main in rc:
            bar_rows.append(("희망소매가 기준 예상 소비자가", float(rc[main]["expected_retail"]), shades[3]))
        p4 = f"예상 소비자가 {w(retail)}원은 국내 판매가 {w(dom)}원을 {w(abs(retail - dom))}원 {'웃돈다' if retail > dom else '밑돈다'}. "
        if rc and main in rc:
            ref_in = float(inp.get("manufacturer_price_jpy_ex_tax") or 0)
            p4 += (f"입력가 {price_s}{cur}는 일본 {kind}이고, 제조사 희망소매가 {ref_in:,.0f}{cur}(세금 별도)로 같은 조건을 계산하면 도착 원가는 "
                   f"{w(rc[main]['landed_cost'])}원으로 {w(landed - float(rc[main]['landed_cost']))}원 낮아진다. "
                   "입력가가 낮을수록 격차도 줄어든다. ")
        p4 += (f"운임·보험료·통관비는 가정값({assumption_text(asm)})이어서 견적을 반영하면 격차는 달라지며, 마진율 {margin_text(asm)}에 따라서도 달라진다. "
               "국내 판매가도 한 판매처의 1건이라 대표 시세로 보기 어렵다.")
        rows4 = [[f"입력가({kind}) 기준"] + [w(costs[n]["landed_cost"]) for n in names]]
        if rc:
            rows4.append([f"희망소매가 {float(inp.get('manufacturer_price_jpy_ex_tax') or 0):,.0f}{cur} 기준"] + [w(rc[n]["landed_cost"]) for n in names])
        stat4 = [("예상 소비자가", f"{w(retail)}원", f"도착 원가 {w(landed)}원 + 마진율 {margin_text(asm)}"),
                 ("국내 판매가", f"{w(dom)}원", "사용자가 확인해 입력한 값"),
                 ("격차", pct(gap, 1, True), f"{w(abs(retail - dom))}원 {'높음' if retail > dom else '낮음'}")]
        stat4_html = "".join(f'<div class="stat"><small>{e(a)}</small><b class="num">{e(b)}</b><span>{e(cc)}</span></div>' for a, b, cc in stat4)
        sec4 = f"""<section class="page fit"><p class="eyebrow">4장 · 국내가</p><h2>{e(t4)}</h2>
<p class="lead">예상 소비자가 {w(retail)}원과 국내 판매가 {w(dom)}원을 같은 기준으로 견주었다.</p>
<div class="split" style="grid-template-columns:1.7fr 1fr"><figure><figcaption>도착 원가·예상 소비자가·국내 판매가 비교 (단위: 원, {e(main)} 기준)</figcaption>{svg_hbars(bar_rows)}
<p class="source">출처: 본 에이전트 계산, 국내 판매가는 {e(inp.get('domestic_price_note') or '입력값')} (확인 {e(today)})</p></figure>
<div class="stats">{stat4_html}</div></div>
<h3>격차의 원인</h3>{paragraphs(p4, first=2 if rc and main in rc else 1)}
<figure style="margin-top:4mm"><figcaption>입력가 종류별 도착 원가 (단위: 원)</figcaption>{tbl(["입력가 기준"] + [f"{n} 도착 원가" for n in names], rows4)}
<p class="source">출처: 본 에이전트 계산. 일본 판매처 가격과 제조사 희망소매가는 출처·방법 쪽에 있다.</p></figure>{foot(total_pages - 1)}</section>"""

    # 시사점 -----------------------------------------------------------------
    todo = []
    if dom and gap > 0:
        todo.append("더 낮은 구매 가격을 찾을 수 있는지 확인한 뒤 같은 계산에 넣어 채산을 다시 판단할 필요가 있다.")
    todo.append("견적을 받을 후보로 정하면 운임·보험료·통관비를 포워더·관세사 견적으로 확인하고, 요약 쪽의 민감도로 도착 원가를 보정할 필요가 있다.")
    if v.verdict != "적용 가능":
        todo.append("거래처가 원산지증명서를 발급할 수 있는지 확인해 FTA 판정을 「적용 가능」 또는 「적용 불가」로 확정해야 한다.")
    todo.append(f"과세환율은 매주 바뀌므로 후보를 등록할 때 적용 주간({fxi['week_start']}~{fxi['week_end']})을 함께 기록할 필요가 있다.")
    if not inp.get("info_confirmed", True):
        todo.append("주종과 HS 코드는 자동 제안값이므로 담당자가 확인한 뒤 다시 계산해야 한다.")
    todo = todo[:5]
    t5 = "후보 판단 전에 확인할 과제"
    sec5 = f"""<div style="margin-bottom:6mm"><p class="eyebrow">시사점</p><h2>{e(t5)}</h2>
<ol class="implication">{''.join('<li>' + e(x) + '</li>' for x in todo)}</ol></div>"""

    # 출처·방법 ---------------------------------------------------------------
    refs = [f"관세청, 관세환율정보(GW), 공공데이터포털 15101230, 적용 주간 {fxi['week_start']}~{fxi['week_end']}(수입·과세), 조회 {today}.",
            "관세청, 품목번호별 관세율표(2026), 공공데이터포털 15051179, 협정세율·일반세율(탄력·양허 F)." ]
    if series:
        refs.append("관세청, 품목별 국가별 수출입실적(GW), 공공데이터포털 15100475, 최근 24개월 조회.")
    refs.append("국가법령정보센터, 주세법 제8조(세율), 교육세법 제5조(과세표준과 세율).")
    if inp.get("price_source_url"):
        refs.append(f"현지 판매처 가격: {inp['price_source_url']} (확인 {inp.get('checked_at', today)}).")
    if inp.get("manufacturer_price_url"):
        refs.append(f"제조사 희망소매가: {inp['manufacturer_price_url']}.")
    if inp.get("domestic_price_url"):
        refs.append(f"국내 판매가: {inp['domestic_price_url']} (확인 {inp.get('checked_at', today)}).")
    in_rows = [["제품", pname], ["주종 / HS 코드", f"{rule.name_ko} / {inp.get('hs_code', '-')}"],
               ["용량 / 도수", f"{inp.get('volume_ml') or '-'}ml / " + (f"{float(inp['abv_percent']):g}" if inp.get('abv_percent') else "-") + "%"],
               ["입력가 / 가격 종류 / 구매국", f"{price_s} {cur} / {kind} / {inp['purchase_country']}"],
               ["제품 정보 확인", "담당자 확인" if inp.get("info_confirmed", True) else "자동 제안값 사용(미확인)"]]
    calc_liquor = (f"주세 = 용량(리터) × 리터당 {per_l:g}원(종량세)." if rule.is_specific
                   else f"주세 = (과세가격 + 관세) × 주세율({liq_rate:.0f}%).")
    assum = e(" / ".join(asm["labels"][k] for k in ("freight_local", "insurance_local", "clearance_domestic_krw", "retail_margin")))
    sec6 = f"""<section class="page fit">{sec5}<p class="eyebrow">출처와 방법</p><h2>자료 목록과 계산 방법</h2>
<div class="cols2"><figure><figcaption>입력 정보</figcaption>{tbl(["항목", "값"], in_rows, num_from=9, cls="compact")}
<p class="refs" style="margin-top:2.5mm"><b>가정값</b> {assum}</p></figure>
<div><h3>계산 방법</h3><p class="refs">과세가격 = (입력가 + 운임 + 보험료) × 과세환율. 관세 = 과세가격 × 관세율. {calc_liquor} 교육세 = 주세 × {edu_ratio:g}%. 부가세 = (과세가격 + 관세 + 주세 + 교육세) × 10%. 도착 원가 = 위 합계 + 통관·국내운송비. 예상 소비자가 = 도착 원가 × (1 + 마진율).</p>
<p class="refs">비워 둔 항목: 실제 운임·보험료·통관비, 현지가 자동 수집. 세액과 FTA 판정은 참고용이며 법률·세무 자문이 아니다.</p></div></div>
<h3>자료 목록</h3><ol class="refs">{''.join('<li>' + e(x) + '</li>' for x in refs)}</ol>{foot(total_pages)}</section>"""

    # 요약(2쪽): 뒤 장의 제목이 정해진 뒤에 만든다 ---------------------------------
    toc = [("1장 · 원가", t1, 3), ("2장 · FTA", t2, 4)]
    if series:
        toc.append(("3장 · 시장", t3, 5))
    if dom:
        toc.append(("4장 · 국내가", t4, total_pages - 1))
    toc.append(("시사점", t5, total_pages))
    summary = f"""<section class="page fit"><p class="eyebrow">요약</p><h2>입력가 기준 채산 판단의 세 가지 근거</h2>
<p class="concl"><b>결론</b>{e(concl)}</p><div class="keys">
<div class="key"><div class="big num">{w(landed)}원</div><div class="cmp">{e(k1_cmp)}</div><p>{e(k1_txt)}</p></div>
<div class="key"><div class="big num">{e(k2_big)}</div><div class="cmp">{e(k2_cmp)}</div><p>{e(k2_txt)}</p></div>
<div class="key"><div class="big num">{e(k3_big)}</div><div class="cmp">{e(k3_cmp)}</div><p>{e(k3_txt)}</p></div></div>
<h3>장별 결론</h3>{tbl(["장", "결론", "쪽"], [[a, b, str(n)] for a, b, n in toc], num_from=2, cls="compact")}
{note}
{sens_block}{foot(2)}</section>"""

    body = cover + summary + sec1 + sec2 + sec3 + sec4 + sec6
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(title)}</title><style>{CSS}</style></head><body>{body}</body></html>")


# ---- 검사·PDF -------------------------------------------------------------
def body_text(doc: str) -> str:
    t = re.sub(r"<(style|script).*?</\1>", " ", doc, flags=re.S)
    t = re.sub(r"</(p|li|h1|h2|h3|div|tr|figcaption)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return html.unescape(re.sub(r"[ \t]+", " ", t))


def run_korean_check(doc: str, work_dir: Path):
    """스킬의 검사기로 금지어를 찾는다. 반환: (통과 여부, 출력 요약)."""
    if not CHECKER.exists():
        return None, "검사기(report_style/scripts/check_korean.py)를 찾지 못했습니다."
    txt = work_dir / "report_body.txt"
    txt.write_text(body_text(doc), encoding="utf-8")
    p = subprocess.run([sys.executable, "-I", str(CHECKER), str(txt)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    ok = p.returncode == 0
    lines = [ln for ln in p.stdout.splitlines() if "금지어" in ln or "x " in ln or "판정" in ln]
    return ok, "\n".join(lines)


def find_browser():
    cands = [shutil.which(n) for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")]
    cands += [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return next((c for c in cands if c and Path(c).exists()), None)


def html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    exe = find_browser()
    if not exe:
        return False
    tmp_profile = html_path.resolve().parent / ".browser_profile"
    # 리눅스 서버(웹앱 배포 환경)는 브라우저 샌드박스를 쓸 수 없는 경우가 많아 끄고 실행한다(우리가 만든 HTML만 연다)
    extra = ["--no-sandbox"] if sys.platform.startswith("linux") else []
    try:
        subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer", *extra, f"--user-data-dir={tmp_profile}",
                        f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()],
                       capture_output=True, timeout=90)
    except (subprocess.SubprocessError, OSError):
        return False
    finally:
        shutil.rmtree(tmp_profile, ignore_errors=True)
    return pdf_path.exists() and pdf_path.stat().st_size > 2000


def facts_rows(r: dict):
    inp, fxi, v = r["input"], r["fx"], r["fta"]
    rows = [["입력가", f"{inp['local_price']} {inp['currency']} ({KIND_NAMES.get(inp.get('price_kind') or 'retail', '소매가')})",
             inp.get("price_source_url") or "사용자 입력", inp.get("checked_at", "")],
            ["과세환율(원/통화 1단위)", str(fxi["rate"]), f"관세청 관세환율정보 {fxi['source']}", f"{fxi['week_start']}~{fxi['week_end']}"],
            ["관세율(적용)", "; ".join(f"{n} {float(x) * 100:.1f}%" for n, x in r["rates"].items()), "관세청 품목번호별 관세율표 2026", r["as_of"]],
            (["주세(종량세)", f"리터당 {float(r['rule'].specific_tax_per_liter):g}원 × 용량 {inp.get('volume_ml')}ml", "주세법 제8조", r["as_of"]]
             if r["rule"].is_specific else
             ["주세율", f"{float(r['rule'].liquor_tax_rate) * 100:.0f}%", "주세법 제8조", r["as_of"]]),
            ["FTA 판정", f"{v.verdict}: {v.reason}", "fta_rules.csv(관세율표 2026에서 생성)", r["as_of"]]]
    for n, c in r["costs"].items():
        rows.append([f"도착 원가({n})", w(c["landed_cost"]), "본 에이전트 계산", r["as_of"]])
    if inp.get("domestic_price"):
        rows.append(["국내 판매가", str(inp["domestic_price"]), inp.get("domestic_price_url") or "사용자 입력", inp.get("checked_at", "")])
    if r["trend"]:
        s = r["trend"]["summary"]
        rows.append(["최근 12개월 수입액(USD)", f"{s['usd_12m']:,}", "관세청 품목별 국가별 수출입실적", s["last_month"]])
    pos = r.get("position")
    if pos:
        rows.append(["후보 환산 단가(USD/kg)", f"{pos['unit']:.1f} (시장 평균 대비 {pos['ratio']:.1f}배)",
                     "본 에이전트 근사 계산(과세가격÷USD 과세환율÷순중량)", r["as_of"]])
    rows.append(["마진율", margin_text(r["assumptions"]), "사용자 입력" if r["assumptions"].get("margin_input") else "가정값(config/assumptions.json)", r["as_of"]])
    for n, s in r["sensitivity"].items():
        rows.append([f"운임·보험료 현지가 10% 가정 시 도착 원가 증가({n})", w(s["ten_pct_delta"]),
                     f"본 에이전트 계산(원화 1원당 {float(s['per_krw']):.2f}원)", r["as_of"]])
        rows.append([f"통관·국내운송비 10만 원 가정 시 도착 원가 증가({n})", w(s["clearance_delta"]),
                     f"본 에이전트 계산(원화 1원당 {float(s['clearance_per_krw']):.2f}원)", r["as_of"]])
    return rows


def write_facts(r: dict, path: Path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["항목", "값", "출처", "기준일"])
        wr.writerows(facts_rows(r))

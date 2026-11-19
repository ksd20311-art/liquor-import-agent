"""2차(11월 범위) 결과 발표 자료 생성: 10월에 약속한 범위와 실제 결과를 나란히 보여 준다.
숫자는 결과 파일(outputs/, watchlist/, docs/verification/)에서 읽는다. 1차 발표 자료(build_slides.py)는 그대로 둔다.
사용: python docs/presentation/build_slides_final.py   → slides_final.html / slides_final.pdf
"""
import csv
import html
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import report_html  # noqa: E402  (브라우저 탐색·PDF 인쇄 재사용)
import tax  # noqa: E402

OUT = Path(__file__).resolve().parent
e = html.escape
CSS = re.search(r'CSS = """(.*?)"""', (OUT / "build_slides.py").read_text(encoding="utf-8"), re.S).group(1)  # 1차와 같은 모양


def n(x) -> str:
    return f"{round(float(x)):,}"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


W = load("outputs/result.json")
B = load("outputs/beer/result.json")
WATCH = load("watchlist/watchlist.json")
ALERT_FILE = sorted((ROOT / "watchlist" / "reports").glob("alert_*.json"))[-1]
ALERT = json.loads(ALERT_FILE.read_text(encoding="utf-8"))
ALERT_DAY = ALERT[0]["checked_at"]
RULES = tax.load_tax_rules()
AD = [r.name_ko for r in RULES.values() if not r.is_specific]
SP = [r.name_ko for r in RULES.values() if r.is_specific]
with open(ROOT / "config" / "fta_rules.csv", encoding="utf-8-sig", newline="") as f:
    FTA_ROWS = sum(1 for _ in csv.DictReader(f))
with open(ROOT / "data" / "fx_history.csv", encoding="utf-8-sig", newline="") as f:
    FXH = list(csv.DictReader(f))
FX_WEEKS = sorted({r["week_start"] for r in FXH})
TESTS = sum(len(re.findall(r"^def test_", p.read_text(encoding="utf-8"), re.M)) for p in (ROOT / "tests").glob("test_*.py"))
VERIFY = re.search(r"결과: \*\*(.+?)\*\*", (ROOT / "docs" / "verification" / "RESULT.md").read_text(encoding="utf-8")).group(1)
TIMING = [ln.split("|")[4].strip() for ln in (ROOT / "docs" / "verification" / "TIMING.md").read_text(encoding="utf-8").splitlines()
          if ln.startswith("| inputs/")]
N_ALERT = sum(1 for a in ALERT if a.get("alert"))
BASE = {x["id"]: x for x in WATCH["items"]}
TOTAL = 8


def table(head, rows, widths=None, hl=None, nums=()):
    cg = "".join(f'<col style="width:{w}">' for w in widths) if widths else ""
    h = "".join(f'<th class="{"n" if i in nums else ""}">{e(c)}</th>' for i, c in enumerate(head))
    b = ""
    for ri, row in enumerate(rows):
        b += f'<tr class="{"hl" if hl == ri else ""}">' + "".join(
            f'<td class="{"n" if i in nums else ""}">{c}</td>' for i, c in enumerate(row)) + "</tr>"
    return f"<table><colgroup>{cg}</colgroup><tr>{h}</tr>{b}</table>"


def slide(num, tag, title, body, foot="", cls=""):
    return (f'<section class="slide {cls}"><p class="tag">{e(tag)}</p><h2>{title}</h2>{body}'
            f'<div class="foot"><span>수입 주류 원가·시장 리포트 에이전트 · 김성도 · 2차 결과</span><span>{e(foot)}  {num} / {TOTAL}</span></div></section>')


DONE, PART, LEFT = '<span class="pill">달성</span>', '<span class="pill h">일부</span>', '<span class="pill g">사람 확인 남음</span>'

S1 = f"""<section class="slide" style="display:flex;flex-direction:column;justify-content:center">
<p class="tag">디지털마케팅전략 · 2026 Fall · 개인 에이전트 2차(11월 범위) 결과</p>
<h1>수입 주류 원가·시장 리포트 에이전트</h1>
<p style="font-size:26px;color:var(--gray);max-width:1040px">10월에 약속한 「11월 말까지 완성할 범위」 8개 항목을 구현하고, 항목마다 숫자로 결과를 확인했습니다.</p>
<div class="box accent" style="max-width:1040px;margin-top:18px;font-size:21px"><b>목적은 그대로입니다</b>: 관세사·포워더 견적을 받기 전에 여러 후보 가운데 견적을 받아 볼 만한 후보를 거르는 1차 검토 도구이며, 결과는 참고 원가입니다. 2차에서는 주종을 넓히고, 등록한 후보의 원가 변동을 알려 주는 월간 알림을 더했습니다.</div>
<p style="margin-top:34px;font-size:22px">김성도 · 기준일 {e(ALERT_DAY)}</p></section>"""

S2 = slide(2, "1. 약속 대비 결과", "8개 항목 가운데 5개 달성, 3개는 남은 일이 있습니다",
    table(["범위", "10월에 약속한 기준", "결과", "판정"], [
        ["지원 주종", "종가세 6종 이상 + 종량세 2종", f"종가세 {len(AD)}종 + 종량세 {len(SP)}종({'·'.join(SP)})", DONE],
        ["계산 정확도", "공개 계산 사례 3건 이상, 엑셀 독립 계산 20건 오차 1원 이내", f"엑셀 {e(VERIFY)}. 공개 사례는 기사 2건(세 번째를 찾지 못함)", PART],
        ["세율 정확도", "규칙표 샘플 10건 중 9건 이상 공식 조회와 일치", f"규칙표 {FTA_ROWS:,}행을 관세율표 2026 파일에서 생성. 공식 화면 대조표 12건은 만들어 두었고 확인은 아직", LEFT],
        ["환율", "주 1회 API 자동 수집, 리포트 100% 환율 출처 표기", f"수집 명령과 작업 스케줄러 등록 배치, 주간 기록 {len(FX_WEEKS)}주. 모든 리포트에 출처·적용 주간 표기", DONE],
        ["월간 알림", "후보 3개 이상에서 ±5% 변동 시 환율·세율·현지가 원인 분해 알림", f"시연 후보 {len(ALERT)}건 중 {N_ALERT}건 알림, 원인 분해 리포트 생성", DONE],
        ["도매가 대응", "견적가 입력 지원, 가격 종류 표기", "가격 종류(소매가 / 도매·견적가) 선택, 리포트·근거표에 표기", DONE],
        ["웹앱 배포", "URL 접속만으로 리포트 생성, RITA에 URL 등록", "웹앱 완성, 이 PC에서 동작 확인. 외부 배포와 URL 등록은 아직", PART],
        ["실행 시간", "후보 1건 1분 이내", f"실시간 조회와 PDF 생성 포함 {e(' / '.join(TIMING))}(위스키 / 맥주, 1회 측정)", DONE]],
        widths=["12%", "30%", "46%", "12%"]), "11월 채점 기준", cls="dense")

BC = B["costs"]["협정세율"]
S3 = slide(3, "2. 지원 주종", f"종가세 {len(AD)}종과 종량세 {len(SP)}종, 맥주는 용량에 세금이 붙습니다",
    f"""<div class="cols c2"><div>{table(["주종", "방식", "주세", "교육세"], [
        ["위스키·브랜디·럼·진·보드카·데킬라", "종가세", "72%", "주세의 30%"], ["와인·사케", "종가세", "30%", "주세의 10%"],
        ["맥주", "종량세", f"리터당 {float(RULES['beer'].specific_tax_per_liter):g}원", "주세의 30%"],
        ["탁주(막걸리)", "종량세", f"리터당 {float(RULES['takju'].specific_tax_per_liter):g}원", "없음"]], widths=["44%", "16%", "22%", "18%"])}
<p class="sub" style="margin-top:8px">관세율은 품목번호 × 원산지별 규칙표 {FTA_ROWS:,}행(1차 304행)에서 읽습니다. 협정이 없는 생산국(멕시코·러시아·대만 등)은 「적용 불가」로 일반세율만 계산합니다.</p>
<p class="sub">근거: 관세청 품목번호별 관세율표 2026, 주세법 제8조, 교육세법 제5조. 2차에서 추가한 품목번호의 이름과 탁주 교육세는 공식 화면 확인이 남아 있습니다.</p></div>
<div class="box accent"><h3>종량세 예: 아사히 수퍼드라이 350ml (220엔은 예시 가격)</h3>
<div class="big">{n(BC['landed_cost'])}원</div><div class="sub">일본 RCEP 협정세율 {float(B['rates']['협정세율']) * 100:g}% 도착 원가 (일반세율 {float(B['rates']['일반세율']) * 100:g}%: {n(B['costs']['일반세율']['landed_cost'])}원)</div>
<p style="margin-top:10px;font-size:18px">과세가격 {n(BC['taxable_value'])}원 + 관세 {n(BC['customs'])}원 + <b>주세 {n(BC['liquor_tax'])}원</b>(0.35L × {float(RULES['beer'].specific_tax_per_liter):g}원) + 교육세 {n(BC['edu_tax'])}원 + 부가세 {n(BC['vat'])}원</p>
<p class="sub">가격이 올라도 주세는 변하지 않고 관세와 부가세만 늘어납니다. 그래서 같은 환율 변동에도 맥주의 원가 변동률이 위스키보다 작습니다.</p></div></div>""")

rows4 = []
for a in ALERT:
    it = BASE[a["id"]]
    d = a["vs_baseline"]
    short = report_html.short_name(a["name"]) or a["name"]
    rows4.append([e(short), it["baseline"]["currency"], n(it["baseline"]["landed_main"]), n(a["snapshot"]["landed_main"]),
                  f"{d['pct']:+.1f}%", '<span class="pill">알림</span>' if a["alert"] else "기준 이내"])
S4 = slide(4, "3. 월간 변동 알림", f"시연 후보 {len(ALERT)}건 중 {N_ALERT}건이 등록 시점 대비 ±5%를 넘었습니다",
    table(["후보", "통화", "등록 시 원가(원)", "현재 원가(원)", "변동률", "판정"], rows4, widths=["34%", "8%", "17%", "17%", "12%", "12%"], nums=(2, 3, 4))
    + f"""<div class="cols c2" style="margin-top:14px"><div class="box"><h3>동작</h3><ul style="font-size:17px"><li>후보를 등록하면 그때의 환율·세율·현지가·원가를 기준으로 저장합니다.</li><li>확인할 때 지금 값으로 다시 계산해 기준 폭(기본 ±5%, 바꿀 수 있음)을 넘으면 알림으로 표시합니다.</li><li>직전 확인 대비 변동도 함께 보여 줍니다.</li></ul></div>
<div class="box todo"><h3>시연 조건 (그대로 밝힙니다)</h3><ul style="font-size:17px"><li>등록 기준일을 {e(WATCH['items'][0]['registered_at'])}로 <b>소급</b>했습니다. 그 주의 실제 과세환율을 썼고 리포트에 「소급」으로 표시됩니다.</li><li>10월 27일 기준으로 등록하면 변동이 1% 안쪽이라 알림이 나오지 않습니다.</li><li>야마자키를 뺀 4건의 현지가는 예시 가격입니다.</li></ul></div></div>""", f"기준일 {ALERT_DAY}")

A1 = ALERT[0]
D1, B1, C1 = A1["vs_baseline"], BASE[A1["id"]]["baseline"], A1["snapshot"]
S5 = slide(5, "4. 원인 분해", "변동을 환율·세율·현지가로 나누고 합계가 맞는지 확인합니다",
    f"""<div class="cols c21"><div><h3>야마자키 12년 (등록 {e(B1['as_of'])} → 확인 {e(C1['as_of'])})</h3>
{table(["요인", "등록 시점", "현재", "원가 영향(원)", "등록 원가 대비"], [
    ["과세환율(100엔당)", f"{float(B1['fx_rate']) * 100:,.2f}원", f"{float(C1['fx_rate']) * 100:,.2f}원", f"{Decimal(D1['fx_effect']):+,.0f}", f"{D1['fx_pct']:+.1f}%"],
    ["적용 관세율", f"{float(B1['customs_rate']) * 100:g}%", f"{float(C1['customs_rate']) * 100:g}%", f"{Decimal(D1['rate_effect']):+,.0f}", f"{D1['rate_pct']:+.1f}%"],
    ["현지가", f"{B1['local_price']:,.0f}엔", f"{C1['local_price']:,.0f}엔", f"{Decimal(D1['price_effect']):+,.0f}", f"{D1['price_pct']:+.1f}%"],
    ["도착 원가", f"{n(B1['landed_main'])}원", f"{n(C1['landed_main'])}원", f"{Decimal(D1['total']):+,.0f}", f"{D1['pct']:+.1f}%"]],
    widths=["24%", "19%", "19%", "20%", "18%"], hl=3, nums=(1, 2, 3, 4))}
<div class="box accent" style="margin-top:12px;font-size:18px">알림 문장: 「{e(A1['messages'][0])}」</div></div>
<div><h3>방법</h3><ul style="font-size:17px"><li>환율 → 세율 → 현지가 순서로 하나씩 지금 값으로 바꿔 다시 계산한 차이입니다.</li><li>세 효과의 합은 전체 변동과 같습니다(테스트로 확인).</li><li>세율이 바뀌면 FTA 판정 변화도 함께 알려 줍니다.</li></ul>
<h3>한계</h3><ul style="font-size:17px"><li>현지가는 자동 수집하지 않아 사용자가 갱신할 때만 반영됩니다.</li><li>세율은 새 관세율표로 규칙표를 다시 만들어야 바뀝니다.</li><li>이번 시연의 변동은 모두 환율에서 나왔습니다. 세율·현지가 효과는 테스트로만 확인했습니다.</li></ul></div></div>""")

JPY = [r for r in FXH if r["currency"] == "JPY"]
JMAX, JMIN = max(JPY, key=lambda r: Decimal(r["krw_per_unit"])), min(JPY, key=lambda r: Decimal(r["krw_per_unit"]))
S6 = slide(6, "5. 환율 수집·가격 종류·웹앱", "주간 환율 기록과 웹 화면을 더했고, 외부 배포는 남아 있습니다",
    f"""<div class="cols c3"><div class="box"><h3>과세환율 주 1회 수집</h3><ul style="font-size:17px"><li>관세청 API로 그 주의 전체 통화를 받아 기록합니다(같은 주는 한 번만).</li><li>기록 {len(FX_WEEKS)}주({e(FX_WEEKS[0])} ~ {e(FX_WEEKS[-1])} 주간), 통화 {len({r['currency'] for r in FXH})}개</li><li>같은 기간 엔화는 100엔당 {float(JMAX['krw_per_unit']) * 100:,.2f}원({e(JMAX['week_start'])}) ~ {float(JMIN['krw_per_unit']) * 100:,.2f}원({e(JMIN['week_start'])})</li></ul><p class="sub">지금 기록은 {e(ALERT_DAY)}에 한꺼번에 받은 것입니다. 매주 자동 실행은 작업 스케줄러 등록 배치로 하며, 등록은 사용할 PC에서 직접 해야 합니다.</p></div>
<div class="box"><h3>가격 종류 표기</h3><ul style="font-size:17px"><li>현지 가격이 소매가인지 도매·견적가인지 고릅니다.</li><li>리포트의 입력 정보와 근거표에 표기됩니다.</li><li>계산식은 같습니다. 운임·통관비 견적은 리포트의 보정표로 반영합니다.</li></ul><p class="sub">견적을 받아야만 쓸 수 있는 도구가 되지 않도록, 입력은 가격 종류 선택까지만 넣었습니다.</p></div>
<div class="box todo"><h3>웹앱</h3><ul style="font-size:17px"><li>입력 창과 같은 계산 코드를 쓰는 웹 화면(리포트 만들기, 월간 변동 알림, 사용 안내)</li><li>이 PC에서 리포트 생성과 알림 등록·확인까지 동작 확인</li><li><b>외부 배포와 RITA URL 등록은 아직 하지 않았습니다.</b> API 키를 서버에만 두는 절차를 문서로 남겼습니다.</li></ul></div></div>""")

S7 = slide(7, "6. 정확도 검증", f"엑셀 독립 계산 20건이 일치했고, 공식 화면 대조는 사람 확인이 남았습니다",
    f"""<div class="cols c2"><div><h3>확인한 것</h3>{table(["검증", "결과"], [
        ["엑셀 독립 계산", f"{e(VERIFY)}. 10개 주종 × 협정·일반세율, 법 조문의 식을 엑셀 수식으로 적어 비교"],
        ["자동 테스트", f"{TESTS}건 통과(1차 48건). 종량세 손계산, 월간 알림 후보 3건, 원인 분해 합계, 환율 수집 포함"],
        ["기사 계산 사례", "2건 일치(와인 6,824원, 위스키 163,553원). 실행할 때마다 자체 점검"],
        ["기존 규칙 보존", "규칙표를 넓힌 뒤에도 1차 304행의 값은 모두 같음"],
        ["처리 시간", f"{e(' / '.join(TIMING))}(위스키 / 맥주, 실시간 조회와 PDF 생성 포함)"]], widths=["26%", "74%"])}</div>
<div><h3>남은 확인 (에이전트가 대신할 수 없는 것)</h3><div class="box todo"><ul style="font-size:17px"><li><b>세율 공식 화면 대조</b>: 대조표 12건을 규칙표 값으로 채워 두었습니다. UNI-PASS 화면 값은 사람이 넣어야 합니다.</li><li><b>품목명</b>: 관세율표 파일에 품목명이 없어 2208907000(데킬라) 등의 이름을 확인하지 못했습니다.</li><li><b>탁주 교육세</b>: 0원으로 계산했으나 조문을 직접 확인하지 못했습니다.</li><li><b>2026년 맥주·탁주 세액</b>: 근거는 2025년 1월 시행본입니다.</li><li><b>공개 계산 사례</b>: 3건 약속에 2건입니다.</li></ul></div>
<p class="sub" style="margin-top:8px">한-EU·한-영 협정세율은 파일에 2026-06-30까지만 있어, 그 뒤 값은 「확인 필요」로 표시하고 두 원가를 함께 보여 줍니다.</p></div></div>""")

WC = W["costs"]
S8 = slide(8, "7. 결과물과 한계", "바로 열어 볼 수 있는 결과물과 아직 하지 못한 일",
    f"""<div class="cols c2"><div><h3>결과물</h3>{table(["파일", "내용"], [
        ["outputs/report_yamazaki12.pdf", f"위스키(종가세) 리포트. 협정세율 {n(WC['협정세율']['landed_cost'])}원 / 일반세율 {n(WC['일반세율']['landed_cost'])}원({e(W['as_of'])} 과세환율)"],
        ["outputs/beer/report_beer_asahi350.pdf", f"맥주(종량세) 리포트. 협정세율 {n(BC['landed_cost'])}원(예시 가격)"],
        [f"watchlist/reports/{e(ALERT_FILE.stem)}.pdf", f"월간 변동 알림 리포트({len(ALERT)}건 중 {N_ALERT}건 알림)"],
        ["docs/verification/", "엑셀 독립 계산 20건, 공식 화면 대조표, 처리 시간 측정"],
        ["run_gui.bat / run_watch.bat / run_webapp.bat", "입력 창 / 월간 알림 / 웹 화면"]], widths=["44%", "56%"])}
<p class="sub" style="margin-top:8px">1차 결과물의 457,530원은 10월 31일 주간 환율 기준이며, 저장된 자료로 재현됩니다(run_example.bat).</p></div>
<div><h3>아직 하지 못한 일</h3><ul style="font-size:18px"><li>웹앱 외부 배포와 URL 등록</li><li>세율 공식 화면 대조 10건, 품목명 확인</li><li>공개 계산 사례 세 번째</li><li>실무자 사용자 검증(1차와 같이 연결되지 않음)</li></ul>
<h3>바뀌지 않는 한계</h3><ul style="font-size:18px"><li>운임·보험료·통관비는 가정값(0원)이고 보정표로 반영합니다.</li><li>현지가와 국내 판매가는 사용자가 확인해 넣습니다.</li><li>세액과 FTA 판정은 참고용이며 확정은 관세사가 합니다.</li></ul></div></div>""")

DOC = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>수입 주류 원가·시장 리포트 에이전트 2차 결과</title><style>{CSS}</style></head><body>'
       + S1 + S2 + S3 + S4 + S5 + S6 + S7 + S8 + "</body></html>")
html_path = OUT / "slides_final.html"
html_path.write_text(DOC, encoding="utf-8")
pdf_path = OUT / "slides_final.pdf"
ok = report_html.html_to_pdf(html_path, pdf_path)
print("HTML:", html_path)
print("PDF:", pdf_path if ok else "브라우저(Edge·Chrome)를 찾지 못해 만들지 못했습니다")

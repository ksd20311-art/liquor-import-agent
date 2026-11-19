"""후보 리포트 PDF (가이드 6-2 구성). 숫자는 항상 계산 결과에서 가져온다."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
FONT_CANDIDATES = [
    ROOT / "fonts" / "NanumGothic.ttf",
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    Path("/Library/Fonts/NanumGothic.ttf"),
]


def _register_font() -> str:
    for p in FONT_CANDIDATES:
        if p.exists():
            pdfmetrics.registerFont(TTFont("KR", str(p)))
            return "KR"
    pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))  # 폰트 파일이 없을 때(뷰어 글꼴에 의존)
    return "HYGothic-Medium"


def w(x) -> str:
    return f"{int(Decimal(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def pct(x, nd=1) -> str:
    return f"{float(x):+.{nd}f}%"


def build_pdf(r: dict, path: Path):
    font = _register_font()
    H1 = ParagraphStyle("h1", fontName=font, fontSize=17, leading=22, spaceAfter=4)
    H2 = ParagraphStyle("h2", fontName=font, fontSize=12, leading=16, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#1f3a5f"))
    P = ParagraphStyle("p", fontName=font, fontSize=9, leading=13)
    S = ParagraphStyle("s", fontName=font, fontSize=8, leading=11, textColor=colors.HexColor("#555555"))

    def table(data, widths, header=True, align_right_from=1):
        rows = [[Paragraph(str(c), P) for c in row] for row in data]
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")))
        t.setStyle(TableStyle(st))
        return t

    inp, fxi, v, asm = r["input"], r["fx"], r["fta"], r["assumptions"]
    costs, rates = r["costs"], r["rates"]
    names = list(costs)
    first = costs[names[0]]
    dom = inp.get("domestic_price")
    pname = inp.get("product_name_ko") or inp["product_name"]  # 일본어 글자는 일부 글꼴에서 깨질 수 있어 한글명 우선
    story = []

    story += [Paragraph("수입 주류 후보 원가·시장 리포트", H1),
              Paragraph(f"{pname} · 기준일 {r['as_of']} · "
                        f"{'샘플 모드(저장된 실제 API 응답)' if r['sample_mode'] else '실시간 호출'}", S)]

    # 1. 요약
    story.append(Paragraph("1. 요약", H2))
    rows = [["항목"] + names]
    rows.append(["도착 원가(원)"] + [w(costs[n]["landed_cost"]) for n in names])
    rows.append([f"예상 소비자가(원, 마진율 {float(asm['retail_margin']) * 100:g}% {'입력값' if asm.get('margin_input') else '가정'})"] +
                [w(costs[n]["expected_retail"]) for n in names])
    if dom:
        rows.append(["국내 실제 판매가(원)"] + [w(dom)] * len(names))
        rows.append(["예상 소비자가 - 국내 판매가"] +
                    [f"{int(costs[n]['expected_retail'] - Decimal(dom)):+,} ({pct((costs[n]['expected_retail'] / Decimal(dom) - 1) * 100)})"
                     for n in names])
    story.append(table(rows, [70 * mm] + [45 * mm] * len(names)))
    story.append(Paragraph(f"FTA 판정: <b>{v.verdict}</b> — {v.reason}", P))
    sens = r["sensitivity"][names[0]]
    story.append(Paragraph(
        "<b>참고 원가입니다.</b> 관세사·포워더 견적을 받기 전에 견적 받아 볼 후보를 거르는 용도입니다. 운임·보험료·통관비는 가정값이라 "
        "견적을 받으면 아래 표로 보정합니다.", P))
    story.append(table([["비용 항목", "1원당 도착 원가 증가", "예시", f"{names[0]} 도착 원가 증가"],
                        ["운임·보험료(과세가격에 포함, 세금이 붙음)", f"{float(sens['per_krw']):.2f}원",
                         f"현지가의 10%({w(sens['ten_pct_krw'])}원)", f"+{w(sens['ten_pct_delta'])}원"],
                        ["통관·국내운송비(세금 계산 뒤 더함)", f"{float(sens['clearance_per_krw']):.2f}원",
                         f"{w(sens['clearance_example'])}원", f"+{w(sens['clearance_delta'])}원"]],
                       [62 * mm, 36 * mm, 42 * mm, 40 * mm]))

    # 2. 입력·확인 내용
    story.append(Paragraph("2. 입력·확인 내용", H2))
    cert = inp.get("has_certificate", "모름")
    rows = [["항목", "값"],
            ["제품", pname],
            ["주종 / HS 코드", f"{r['rule'].name_ko} / {inp.get('hs_code', '-')}"],
            ["용량 / 도수", f"{inp.get('volume_ml', '-')}ml / {inp.get('abv_percent', '-')}%"],
            ["현지 가격", f"{float(inp['local_price']):,.2f}".rstrip("0").rstrip(".") + f" {inp['currency']} (구매국 {inp['purchase_country']})"],
            ["가격 출처", inp.get("price_source_url") or "-"],
            ["원산지 국가 생산 여부 / 원산지증명서 발급", f"{inp.get('made_in_origin', '모름')} / {cert}"]]
    if "info_confirmed" in inp:
        confirmed = "사용자가 확인·수정함" if inp["info_confirmed"] else "자동 제안값을 확인 없이 사용함(미확인)"
        rows.append(["제품 정보(주종·HS 코드)", f"{confirmed}. " + " / ".join(inp.get("intake_notes", []))])
    if inp.get("local_price_note"):
        rows.append(["가격 비고", inp["local_price_note"]])
    story.append(table(rows, [55 * mm, 125 * mm]))

    # 3. 원가 분해표
    story.append(Paragraph("3. 원가 분해표 (원)", H2))
    keys = [("과세가격(CIF×과세환율)", "taxable_value"), ("관세", "customs"), ("주세", "liquor_tax"),
            ("교육세", "edu_tax"), ("부가세", "vat"), ("통관·국내운송(가정)", "clearance_domestic"),
            ("도착 원가", "landed_cost")]
    rows = [["구분"] + [f"{n}({float(rates[n]) * 100:.1f}%)" for n in names]]
    for label, k in keys:
        rows.append([label] + [w(costs[n][k]) for n in names])
    story.append(table(rows, [70 * mm] + [45 * mm] * len(names)))
    story.append(Paragraph(
        f"주세율 {float(r['rule'].liquor_tax_rate) * 100:.0f}%(종가세), 교육세는 주세율 70% 초과 시 주세의 30%, "
        "아니면 10%. 부가세 10%.", S))

    # 4. FTA 판정과 근거
    story.append(Paragraph("4. FTA 판정과 근거", H2))
    story.append(Paragraph(f"<b>{v.verdict}</b>: {v.reason}", P))
    if v.agreement:
        story.append(Paragraph(f"협정: {v.agreement} / 협정세율 {float(v.preferential_rate) * 100:.1f}% / "
                               f"일반세율 {float(v.general_rate) * 100:.1f}% (관세청 품목번호별 관세율표 2026, "
                               "YES FTA 포털 조회로 교차 확인)" if v.preferential_rate is not None else
                               f"협정: {v.agreement} / 협정세율 미입력", P))
    if v.documents:
        story.append(Paragraph(f"필요 서류: {v.documents}", P))
    story.append(Paragraph(v.disclaimer, S))

    # 5. 시장 추이
    story.append(Paragraph("5. 시장 추이 (같은 주종·원산지, 최근 12개월 수입)", H2))
    if r["trend"]:
        t, s = r["trend"]["table"], r["trend"]["summary"]
        rows = [["월", "수입액(USD)", "중량(kg)", "단가(USD/kg)", "전년 동월 대비"]]
        for x in t:
            rows.append([f"{x['ym'][:4]}.{x['ym'][4:]}",
                         f"{x['usd']:,}" if x["usd"] is not None else "자료 없음",
                         f"{x['kg']:,}" if x["kg"] is not None else "-",
                         f"{x['unit_usd_per_kg']:.2f}" if x["unit_usd_per_kg"] else "-",
                         pct(x["yoy_pct"]) if x["yoy_pct"] is not None else "-"])
        story.append(table(rows, [28 * mm, 40 * mm, 35 * mm, 38 * mm, 38 * mm]))
        yoy = f", 직전 12개월 대비 수입액 {pct(s['yoy_12m_pct'])}" if s["yoy_12m_pct"] is not None else ""
        unit = f", 평균 단가 {s['unit_12m']:.2f} USD/kg" if s["unit_12m"] else ""
        story.append(Paragraph(f"최근 12개월 수입액 합계 {s['usd_12m']:,} USD{unit}{yoy}.", P))
        story.append(Paragraph("출처: 관세청 품목별 국가별 수출입실적(공공데이터포털). 단가는 달러/kg 기준이라 "
                               "병당 가격과는 근사 비교입니다.", S))
        pos = r.get("position")
        if pos:
            story.append(Paragraph(
                f"가격 위치: 입력가를 달러로 환산한 후보 단가는 약 {pos['unit']:,.0f}달러/kg로 시장 평균 {pos['market_avg']:.2f}달러/kg의 "
                f"{pos['ratio']:.1f}배입니다(월별 단가 {pos['months_total']}개 중 {pos['months_below']}개보다 높음, 근사값).", P))
    else:
        story.append(Paragraph(f"자료 없음: {r['trend_msg']}", P))

    # 차이 원인
    if dom:
        story.append(Paragraph("6. 예상 소비자가와 국내 판매가 차이의 원인 가설", H2))
        diff = costs[names[0]]["expected_retail"] - Decimal(dom)
        lines = []
        if r["ref_costs"]:
            rc = r["ref_costs"][names[0]]
            lines.append(f"입력가는 일본 소매가({Decimal(str(inp['local_price'])):,.0f}엔)입니다. 제조사 희망소매가 "
                         f"{Decimal(str(inp['manufacturer_price_jpy_ex_tax'])):,.0f}엔(세금 별도)로 같은 조건을 계산하면 "
                         f"도착 원가 {w(rc['landed_cost'])}원, 예상 소비자가 {w(rc['expected_retail'])}원입니다. "
                         "입력가가 낮을수록 격차도 줄어듭니다.")
            lines.append("일본 판매가의 소비세(10%) 환급은 반영하지 않았습니다(보수적 가정).")
        lines.append(f"운임·보험료·통관비는 가정값이라 견적을 반영하면 격차가 달라지고, 마진율 {float(asm['retail_margin']) * 100:g}%에 따라서도 달라집니다.")
        lines.append("국내 판매가는 단일 판매처 1건이라 대표 시세가 아닐 수 있습니다.")
        story.append(Paragraph(f"예상 소비자가는 국내 판매가보다 {int(diff):+,}원 차이 납니다. 원인 가설:", P))
        for ln in lines:
            story.append(Paragraph("· " + ln, P))
        if r["ref_costs"]:
            rows = [["입력가 기준"] + [f"{n} 도착 원가" for n in names]]
            rows.append([f"일본 소매가 {Decimal(str(inp['local_price'])):,.0f}엔"] + [w(costs[n]["landed_cost"]) for n in names])
            rows.append([f"희망소매가 {Decimal(str(inp['manufacturer_price_jpy_ex_tax'])):,.0f}엔(세금 별도)"] +
                        [w(r["ref_costs"][n]["landed_cost"]) for n in names])
            story += [Spacer(1, 3), table(rows, [70 * mm] + [45 * mm] * len(names))]

    # 환율·가정
    story.append(Paragraph("7. 사용한 환율과 가정값", H2))
    rows = [["항목", "값"],
            ["적용 환율", f"관세청 고시 과세환율(수입) 1{inp['currency']} = {fxi['rate']}원 · 적용 주간 {fxi['week_start']}~{fxi['week_end']}"],
            ["환율 출처", fxi["source"]]]
    for k in ("freight_local", "insurance_local", "clearance_domestic_krw", "retail_margin"):
        rows.append(["가정", asm["labels"][k]])
    story.append(table(rows, [35 * mm, 145 * mm]))
    if fxi["warning"]:
        story.append(Paragraph(f"경고: {fxi['warning']}", P))

    # 다음 확인
    story.append(Paragraph("8. 다음 확인 예고 (11월 예정)", H2))
    story.append(Paragraph("등록한 후보를 매달 다시 계산해 등록 시점 대비 ±5% 이상 변하면 환율·세율·현지가 중 "
                           "원인별 금액과 함께 알립니다. 현재 버전에는 구현되어 있지 않습니다.", P))
    story.append(Spacer(1, 6))
    story.append(Paragraph("본 리포트는 참고용이며 법률·세무 자문이 아닙니다. 세액과 FTA 판정은 통관 시 관세사를 통해 확정됩니다.", S))

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=14 * mm, bottomMargin=14 * mm, title="후보 원가·시장 리포트").build(story)

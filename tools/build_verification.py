"""엑셀 독립 계산 검증 파일을 만든다(11월 성공 기준: 엑셀 독립 계산 20건 오차 1원 이내).

  python tools/build_verification.py          → docs/verification/independent_calc_20cases.xlsx

엑셀 쪽은 법 조문의 계산식을 셀 수식으로 직접 적은 것이고(에이전트 코드를 쓰지 않음),
에이전트 값은 src/tax.py가 계산한 값이다. 엑셀에서 열면 두 값의 차이와 판정이 계산된다.
세율은 config/fta_rules.csv·tax_rules.csv에서, 환율은 data/fx_history.csv(관세청 API 수집분)에서 읽는다.
필요: openpyxl (pip install openpyxl) - 이 도구에서만 쓴다.
"""
import csv
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import tax  # noqa: E402

WEEK = "2026-11-15"  # 환율 기준 주간(data/fx_history.csv)
# (주종, 원산지, HS 코드, 현지가, 통화, 용량 ml, 세율 구분: pref=협정세율 / general=일반세율)
CASES = [
    ("whisky", "JP", "2208309000", 22500, "JPY", 700, "pref"), ("whisky", "JP", "2208309000", 22500, "JPY", 700, "general"),
    ("whisky", "GB", "2208301000", 70, "GBP", 700, "pref"), ("whisky", "US", "2208302000", 30, "USD", 750, "pref"),
    ("wine", "FR", "2204211000", 600, "EUR", 750, "general"), ("wine", "CL", "2204211000", 18, "USD", 750, "pref"),
    ("wine", "FR", "2204100000", 45, "EUR", 750, "general"), ("sake", "JP", "2206002010", 6000, "JPY", 720, "pref"),
    ("sake", "JP", "2206002010", 6000, "JPY", 720, "general"), ("brandy", "FR", "2208201000", 55, "EUR", 700, "general"),
    ("brandy", "US", "2208209000", 40, "USD", 750, "pref"), ("rum", "CU", "2208400000", 25, "USD", 700, "general"),
    ("gin", "GB", "2208500000", 28, "GBP", 700, "general"), ("vodka", "SE", "2208600000", 22, "EUR", 700, "general"),
    ("tequila", "MX", "2208907000", 50, "USD", 750, "general"), ("beer", "JP", "2203000000", 220, "JPY", 350, "pref"),
    ("beer", "DE", "2203000000", 1.2, "EUR", 500, "general"), ("beer", "US", "2203000000", 2, "USD", 355, "pref"),
    ("takju", "JP", "2206002030", 500, "JPY", 720, "pref"), ("takju", "CN", "2206002030", 10, "CNY", 750, "pref"),
]
MARGIN = Decimal("0.30")


def main():
    rules = tax.load_tax_rules()
    with open(ROOT / "config" / "fta_rules.csv", encoding="utf-8-sig", newline="") as f:
        fta = {(r["origin"], r["hs_code"]): r for r in csv.DictReader(f)}
    with open(ROOT / "data" / "fx_history.csv", encoding="utf-8-sig", newline="") as f:
        fxr = {r["currency"]: Decimal(r["krw_per_unit"]) for r in csv.DictReader(f) if r["week_start"] == WEEK}

    wb = Workbook()
    ws = wb.active
    ws.title = "독립 계산 20건"
    head = ["#", "주종", "원산지", "HS 코드", "방식", "현지가", "통화", "과세환율(원)", "관세율", "세율 구분", "주세율",
            "리터당 주세(원)", "용량(ml)", "종량세 교육세 비율", "과세가격", "관세", "주세", "교육세", "부가세",
            "도착 원가(엑셀)", "도착 원가(에이전트)", "차이(원)", "판정"]
    ws.append(["엑셀 독립 계산 검증: 법 조문의 계산식을 셀 수식으로 적어 에이전트(src/tax.py) 값과 견준다. "
               f"환율은 관세청 과세환율 {WEEK} 주간, 세율은 관세율표 2026·주세법 제8조·교육세법 제5조."])
    ws.append(head)
    for c in ws[2]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDE7F3")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, (ltype, origin, hs, price, cur, vol, kind) in enumerate(CASES, start=1):
        rule, row = rules[ltype], fta[(origin, hs)]
        rate = Decimal(row["preferential_rate"]) if kind == "pref" else Decimal(row["general_rate"])
        agent = tax.calc_landed_cost(price, fxr[cur], rule, customs_rate=rate, retail_margin=MARGIN, volume_ml=vol)
        r = i + 2
        ws.append([
            i, rule.name_ko, origin, hs, "종량세" if rule.is_specific else "종가세", float(price), cur, float(fxr[cur]), float(rate),
            ("협정세율 " + row["agreement"]) if kind == "pref" else "일반세율", float(rule.liquor_tax_rate),
            float(rule.specific_tax_per_liter or 0), vol, float(rule.edu_tax_ratio) if rule.edu_tax_ratio is not None else "",
            f"=F{r}*H{r}",                                             # 과세가격 = 현지가 x 과세환율(운임·보험료 0 가정)
            f"=O{r}*I{r}",                                             # 관세 = 과세가격 x 관세율
            f'=IF(E{r}="종량세",M{r}/1000*L{r},(O{r}+P{r})*K{r})',      # 주세: 종량세는 리터 x 리터당 세액, 종가세는 (과세가격+관세) x 주세율
            f'=Q{r}*IF(E{r}="종량세",N{r},IF(K{r}>0.7,0.3,0.1))',       # 교육세: 주세율 70% 초과 30%, 아니면 10%(종량세는 표의 비율)
            f"=(O{r}+P{r}+Q{r}+R{r})*0.1",                             # 부가세 10%
            f"=O{r}+P{r}+Q{r}+R{r}+S{r}",                              # 도착 원가
            float(round(agent["landed_cost"], 6)),
            f"=ABS(T{r}-U{r})", f'=IF(V{r}<=1,"일치","불일치")',
        ])
    last = len(CASES) + 2
    ws.append([])
    ws.append(["합계", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "최대 차이(원)", f"=MAX(V3:V{last})",
               f'=COUNTIF(W3:W{last},"일치")&"건 일치 / {len(CASES)}건"'])
    for col, wdt in zip("ABCDEFGHIJKLMNOPQRSTUVW", (4, 12, 7, 12, 8, 9, 6, 11, 8, 16, 7, 10, 8, 10, 13, 12, 12, 12, 12, 15, 15, 9, 9)):
        ws.column_dimensions[col].width = wdt
    for row in ws.iter_rows(min_row=3, max_row=last, min_col=15, max_col=22):
        for c in row:
            c.number_format = "#,##0.00"
    out = ROOT / "docs" / "verification"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "independent_calc_20cases.xlsx"
    wb.save(path)
    print(f"{len(CASES)}건 작성: {path}")


if __name__ == "__main__":
    main()

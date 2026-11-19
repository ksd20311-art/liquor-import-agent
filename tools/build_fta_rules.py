"""관세청 「품목번호별 관세율표」 XLSX(공공데이터포털 15051179)에서 config/fta_rules.csv를 만든다.

사용: python tools/build_fta_rules.py 관세율표.xlsx [기준일 YYYYMMDD]
- 대상 HS: 위스키·청주·포도주·브랜디·럼·진·보드카·데킬라·맥주·탁주(TARGETS)
- 주류 생산국 가운데 협정세율 구분이 없는 나라(NO_AGREEMENT)는 「협정 없음」 행으로 넣는다.
- 원산지 국가별로 적용 기간 안에 있는 협정세율 중 가장 낮은 값을 고른다.
- 일반세율은 탄력·양허세율 구분 F가 있으면 그 값, 없으면 기본세율(A)을 쓴다(2208309000 화면 확인과 일치).
표준 라이브러리만 사용한다.
"""
import csv
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
ASEAN = "BN KH ID LA MY MM PH SG TH VN".split()
# 관세율 구분 코드 -> (협정 이름, 원산지 국가 코드들). 국가 범위가 불확실한 구분(EFTA 등)은 넣지 않는다.
AGREEMENTS = {
    "FUS1": ("한-미", ["US"]), "FGB1": ("한-영", ["GB"]), "FEU1": ("한-EU", EU),
    "FCL1": ("한-칠레", ["CL"]), "FAU1": ("한-호주", ["AU"]), "FCA1": ("한-캐나다", ["CA"]),
    "FCN1": ("한-중", ["CN"]), "FNZ1": ("한-뉴질랜드", ["NZ"]), "FIN1": ("한-인도", ["IN"]),
    "FTR1": ("한-튀르키예", ["TR"]), "FVN1": ("한-베트남", ["VN"]),
    "FRCJP1": ("RCEP", ["JP"]), "FRCAU1": ("RCEP", ["AU"]), "FRCCN1": ("RCEP", ["CN"]), "FRCNZ1": ("RCEP", ["NZ"]),
    "FAS1": ("한-아세안", ASEAN), "FRCAS1": ("RCEP", ASEAN), "FSG1": ("한-싱가포르", ["SG"]),
    "FID1": ("한-인도네시아", ["ID"]), "FKH1": ("한-캄보디아", ["KH"]), "FPH1": ("한-필리핀", ["PH"]),
    "FCO1": ("한-콜롬비아", ["CO"]), "FPE1": ("한-페루", ["PE"]), "FIL1": ("한-이스라엘", ["IL"]),
    "FCECR1": ("한-중미", ["CR"]), "FCEHN1": ("한-중미", ["HN"]), "FCENI1": ("한-중미", ["NI"]),
    "FCEPA1": ("한-중미", ["PA"]), "FCESV1": ("한-중미", ["SV"]),
}
# 주류 생산국 가운데 2026 관세율표에 협정세율 구분이 없는 나라: 「협정 없음, 일반세율」로 판정한다
NO_AGREEMENT = ["MX", "RU", "TW", "ZA", "AR", "BR", "CU", "JM"]
TARGETS = {
    "2208301000": "whisky", "2208302000": "whisky", "2208303000": "whisky", "2208309000": "whisky",
    "2206002010": "sake",
    "2204100000": "wine", "2204211000": "wine", "2204212000": "wine", "2204219000": "wine",
    "2208201000": "brandy", "2208209000": "brandy",
    "2208400000": "rum", "2208500000": "gin", "2208600000": "vodka", "2208907000": "tequila",
    "2203000000": "beer", "2206002030": "takju",
}


# (HS, 구분 코드, 세율%, 시작일, 종료일): 2026-10-27 UNI-PASS 화면 확인, 유럽 FEU1 0% (2026-07-01~2027-06-30)
VERIFIED_EXTENSIONS = [("2208309000", "FEU1", 0.0, "20260701", "20270630")]


def read_rows(xlsx: str):
    z = zipfile.ZipFile(xlsx)
    ss = []
    for _, el in ET.iterparse(z.open("xl/sharedStrings.xml")):
        if el.tag == M + "si":
            ss.append("".join(t.text or "" for t in el.iter(M + "t")))
            el.clear()
    sheet = "xl/worksheets/sheet2.xml" if "xl/worksheets/sheet2.xml" in z.namelist() else "xl/worksheets/sheet1.xml"
    for _, el in ET.iterparse(z.open(sheet)):
        if el.tag == M + "row":
            r = []
            for c in el.findall(M + "c"):
                v = c.find(M + "v")
                r.append("" if v is None else (ss[int(v.text)] if c.get("t") == "s" else v.text))
            yield r
            el.clear()


def main():
    xlsx = sys.argv[1]
    on = sys.argv[2] if len(sys.argv) > 2 else date.today().strftime("%Y%m%d")
    year = on[:4]
    rates = {}  # (hs, 구분) -> [(rate, start, end)] 전체 기간
    for r in read_rows(xlsx):
        if len(r) >= 6 and r[0] in TARGETS and (r[1] in AGREEMENTS or r[1] in ("A", "C", "F")):
            rates.setdefault((r[0], r[1]), []).append((float(r[2]), r[4], r[5]))

    # 파일에는 없지만 UNI-PASS 화면(inputs/evidence/unipass_kr_2208309000_main_rates.png)으로 확인한 후속 기간 값
    for hs, code, rate, s, e in VERIFIED_EXTENSIONS:
        rates.setdefault((hs, code), []).append((rate, s, e))

    def pick(hs, code):
        """기준일에 유효한 행을 우선하고, 없으면 가장 늦게 끝난 행을 「기간 경과」로 표시해 쓴다."""
        rows = rates.get((hs, code), [])
        valid = [x for x in rows if x[1] <= on <= x[2]]
        if valid:
            return valid[0] + ("valid",)
        past = [x for x in rows if x[2] < on]
        if past:
            return max(past, key=lambda x: x[2]) + ("period_ended",)
        return None

    out = []
    for hs, ltype in TARGETS.items():
        g = pick(hs, "F") or pick(hs, "A")
        if g is None:
            continue
        general = g[0]
        best = {}  # origin -> (rate, agreement, code, start, end, status)
        for code, (name, origins) in AGREEMENTS.items():
            p = pick(hs, code)
            if not p:
                continue
            rate, s, e, status = p
            for o in origins:
                cur = best.get(o)
                # 유효한 행이 기간 경과 행보다 우선, 같은 상태끼리는 낮은 세율
                if cur is None or (status == "valid" and cur[5] != "valid") or (status == cur[5] and rate < cur[0]):
                    best[o] = (rate, name, code, s, e, status)
        for o, (rate, name, code, s, e, status) in sorted(best.items()):
            out.append([o, ltype, hs, name, year, f"{round(rate, 4) / 100:g}", f"{general / 100:g}", on, code, f"{s}~{e}",
                        "" if status == "valid" else status])
        for o in NO_AGREEMENT:
            if o not in best:
                out.append([o, ltype, hs, "없음", year, "", f"{general / 100:g}", on, "", "", ""])

    path = Path(__file__).resolve().parent.parent / "config" / "fta_rules.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["origin", "liquor_type", "hs_code", "agreement", "year", "preferential_rate", "general_rate",
                    "checked_on", "source_code", "period", "status"])
        w.writerows(out)
    print(f"{len(out)}행 작성: {path} (기준일 {on})")


if __name__ == "__main__":
    main()

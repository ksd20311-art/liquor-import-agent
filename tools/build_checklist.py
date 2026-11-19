"""세율 공식 화면 대조 목록(사람이 채우는 표)을 규칙표 값으로 만든다.

  python tools/build_checklist.py   → docs/verification/CHECKLIST_공식조회_대조.md
규칙표 값은 config/fta_rules.csv에서 그대로 옮기고, 공식 화면 값·일치 여부·확인일 칸은 비워 둔다.
이미 채운 표를 덮어쓰지 않도록, 파일이 있으면 --force를 줘야 다시 만든다.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "verification" / "CHECKLIST_공식조회_대조.md"
PICKS = [("JP", "2203000000", "맥주"), ("US", "2203000000", "맥주"), ("DE", "2203000000", "맥주"), ("CN", "2203000000", "맥주"),
         ("MX", "2208907000", "데킬라"), ("FR", "2208201000", "브랜디"), ("GB", "2208500000", "진"), ("JP", "2206002030", "탁주"),
         ("FR", "2204100000", "스파클링 와인"), ("JP", "2208400000", "럼"), ("SE", "2208600000", "보드카"), ("CL", "2204211000", "붉은 포도주")]


def main():
    if OUT.exists() and "--force" not in sys.argv:
        print(f"이미 있습니다(채운 내용을 지키려고 그대로 둠): {OUT}\n다시 만들려면 --force")
        return
    with open(ROOT / "config" / "fta_rules.csv", encoding="utf-8-sig", newline="") as f:
        rows = {(r["origin"], r["hs_code"]): r for r in csv.DictReader(f)}
    out = [
        "# 세율 공식 화면 대조 목록 (사람이 확인해 채우는 표)", "",
        "11월 성공 기준 「규칙표 샘플 10건 중 9건 이상 공식 조회와 일치」를 확인하기 위한 표입니다. "
        "에이전트가 대신 확인할 수 없는 단계라 「공식 화면 값」 칸을 비워 두었습니다.", "",
        "확인 방법: 관세법령정보포털(unipass.customs.go.kr/clip)의 국내 주요 세율에서 품목번호 10자리를 조회하거나, "
        "YES FTA 포털의 「FTA 수입세율 조회」에서 국가와 품목번호를 넣습니다. 화면을 캡처해 `inputs/evidence/`에 두면 근거가 남습니다.", "",
        "규칙표 값은 `config/fta_rules.csv`(관세청 품목번호별 관세율표 2026 파일, 2026-11-16 내려받음)에서 그대로 옮긴 것입니다.", "",
        "| # | 품목(에이전트가 붙인 이름) | 품목번호 | 원산지 | 규칙표: 협정 | 규칙표: 협정세율 | 규칙표: 일반세율 | 규칙표 적용 기간 | 공식 화면 값 | 일치 | 확인일 |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, (origin, hs, name) in enumerate(PICKS, 1):
        r = rows[(origin, hs)]
        pref = f"{float(r['preferential_rate']) * 100:g}%" if r["preferential_rate"] else "-"
        note = " (기간 지남 → 에이전트는 「확인 필요」로 표시)" if r["status"] else ""
        out.append(f"| {i} | {name} | {hs} | {origin} | {r['agreement']} | {pref} | {float(r['general_rate']) * 100:g}% | "
                   f"{r['period'] or '-'}{note} |  |  |  |")
    out += [
        "", "## 함께 확인할 것", "",
        "| 항목 | 에이전트가 쓰는 값 | 근거 | 공식 확인 값 | 확인일 |", "|---|---|---|---|---|",
        "| 품목번호 2208907000의 품목명 | 데킬라로 처리 | 관세율표 파일에는 품목명이 없어 확인하지 못함 |  |  |",
        "| 품목번호 2208201000 / 2208209000의 품목명 | 브랜디(포도주 증류주)로 처리 | HS 6단위 2208.20 기준 |  |  |",
        "| 품목번호 2206002030의 품목명 | 탁주로 처리 | 2206.00.20 계열(청주 2010은 1차에서 확인) |  |  |",
        "| 맥주 주세 | 1kL당 885,700원 | 주세법 제8조(2025-01-01 시행본 캡처) |  |  |",
        "| 탁주 주세 | 1kL당 44,400원 | 주세법 제8조(2025-01-01 시행본 캡처) |  |  |",
        "| 맥주 교육세 | 주세의 30% | 교육세법 제5조 제1항 제4호(캡처) |  |  |",
        "| 탁주 교육세 | 없음(0%) | 교육세법상 주정·탁주·약주의 주세액은 제외로 알고 있으나 조문을 직접 확인하지 못함 |  |  |",
        "| 한-EU·한-영 협정세율(2026-07-01 이후) | 「확인 필요」로 표시하고 두 원가 병기 | 관세율표 파일에 2026-06-30까지만 있음 |  |  |",
        "", "공식 값이 규칙표와 다르면 `config/tax_rules.csv` 또는 `tools/build_fta_rules.py`의 `VERIFIED_EXTENSIONS`를 고치고 "
        "규칙표를 다시 만든 뒤(`python tools/build_fta_rules.py data/raw/tariff_2026.xlsx 기준일`) 테스트를 돌립니다.", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"작성: {OUT}")
    print("\n".join(out[8:22]))


if __name__ == "__main__":
    main()

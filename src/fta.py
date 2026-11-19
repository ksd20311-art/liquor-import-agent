"""FTA 3단계 판정: 적용 가능 / 확인 필요 / 적용 불가 (가이드 5-1)."""
import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DISCLAIMER = "참고용 판정이며 실제 적용 여부는 통관 시 관세사를 통해 확정된다."

APPLICABLE, CHECK, NOT_APPLICABLE = "적용 가능", "확인 필요", "적용 불가"
YES, NO, UNKNOWN = "예", "아니오", "모름"


@dataclass(frozen=True)
class FtaResult:
    verdict: str
    reason: str
    agreement: str = ""
    preferential_rate: Decimal = None  # 협정세율 (확인 필요일 때 병기용, 값이 있을 때만)
    general_rate: Decimal = None
    documents: str = ""
    disclaimer: str = DISCLAIMER


def load_fta_rules(path: Path = CONFIG_DIR / "fta_rules.csv") -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _rate(text):
    text = (text or "").strip()
    return Decimal(text) if text else None


def judge(origin, purchase_country, liquor_type, year, made_in_origin, has_certificate, rules,
          hs_code=None) -> FtaResult:
    """origin: 원산지 국가코드, purchase_country: 구매국 코드,
    made_in_origin/has_certificate: 예/아니오/모름 (None은 모름으로 취급).
    hs_code가 있고 규칙표에 같은 HS 코드 행이 있으면 그 행을 우선 쓴다(품목별로 세율이 다르므로)."""
    made_in_origin = made_in_origin or UNKNOWN
    has_certificate = has_certificate or UNKNOWN

    candidates = [r for r in rules
                  if r["origin"] == origin and r["liquor_type"] == liquor_type and str(r["year"]) == str(year)]
    row = next((r for r in candidates if hs_code and (r.get("hs_code") or "") == hs_code), None)
    if row is None:
        row = next((r for r in candidates if not (r.get("hs_code") or "")), None)
    if row is None and candidates and not hs_code:
        row = candidates[0]
    if row is None:
        return FtaResult(CHECK, "규칙표에 해당 원산지·주종·연도가 없어 판정할 수 없다. 협정·일반 두 원가를 비교해야 한다.")

    agreement = (row["agreement"] or "").strip()
    general = _rate(row["general_rate"])
    pref = _rate(row["preferential_rate"])
    common = dict(agreement=agreement, preferential_rate=pref, general_rate=general)

    if not agreement or agreement == "없음":
        return FtaResult(NOT_APPLICABLE, "해당 원산지·품목에 적용되는 협정이 없어 일반세율을 적용한다.", **common)
    if made_in_origin == NO:
        return FtaResult(NOT_APPLICABLE, "원산지 국가에서 생산된 제품이 아니므로 협정세율 대상이 아니다.", **common)
    if has_certificate == NO:
        return FtaResult(NOT_APPLICABLE, "거래처가 원산지증명서를 발급할 수 없어 협정세율을 적용할 수 없다.", **common)
    if (row.get("status") or "") == "period_ended":
        return FtaResult(
            CHECK,
            f"규칙표의 협정세율은 적용 기간({row.get('period', '')})이 지난 값이다. 현재 적용 세율을 UNI-PASS에서 확인해야 한다.",
            **common,
        )
    if origin != purchase_country:
        return FtaResult(
            CHECK,
            f"원산지({origin})와 구매국({purchase_country})이 달라 경유 구매에 해당할 수 있다. "
            "직접 운송·원산지 증명 요건을 확인해야 한다.",
            **common,
        )
    if has_certificate == UNKNOWN or made_in_origin == UNKNOWN:
        return FtaResult(CHECK, "원산지증명서 발급 가능 여부 또는 생산지가 확인되지 않았다.", **common)
    if pref is None:
        return FtaResult(CHECK, "규칙표에 협정세율이 아직 입력되지 않았다(UNI-PASS 조회 필요).", **common)
    return FtaResult(
        APPLICABLE,
        f"{agreement} 협정세율 대상이며 원산지 요건이 충족되는 것으로 응답했다.",
        documents="원산지증명서(거래처 발급), 직접 운송 증빙",
        **common,
    )

"""주류 수입 세금·원가 계산 (규칙표 기반, LLM 미사용).

종가세(위스키·와인·사케·브랜디·보드카·진·럼·데킬라):
  과세가격 = (현지가격 + 운임 + 보험료) x 과세환율          (CIF)
  관세     = 과세가격 x 관세율
  주세     = (과세가격 + 관세) x 주세율
  교육세   = 주세 x (주세율 70% 초과 30%, 아니면 10%)
  부가세   = (과세가격 + 관세 + 주세 + 교육세) x 10%
종량세(맥주·탁주): 주세만 다르다.
  주세     = 용량(리터) x 리터당 세액        (가격과 무관)
  교육세   = 주세 x 규칙표의 비율(맥주 30%, 탁주 0%)
"""
import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
VAT_RATE = Decimal("0.10")


def _d(value) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class TaxRule:
    liquor_type: str
    name_ko: str
    method: str  # ad_valorem(종가세) / specific(종량세)
    general_customs_rate: Decimal
    liquor_tax_rate: Decimal  # 종가세 주세율(종량세는 0)
    note: str = ""
    specific_tax_per_liter: Decimal = None  # 종량세 리터당 주세(원)
    edu_tax_ratio: Decimal = None  # 교육세 비율을 규칙표에서 정한 경우(종량세). None이면 주세율로 정한다

    @property
    def is_specific(self) -> bool:
        return self.method == "specific"


def load_tax_rules(path: Path = CONFIG_DIR / "tax_rules.csv") -> dict:
    rules = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            per_l = (row.get("specific_tax_per_liter") or "").strip()
            edu = (row.get("edu_tax_ratio") or "").strip()
            rules[row["liquor_type"]] = TaxRule(
                liquor_type=row["liquor_type"],
                name_ko=row["name_ko"],
                method=row["method"],
                general_customs_rate=_d(row["general_customs_rate"]),
                liquor_tax_rate=_d(row["liquor_tax_rate"] or 0),
                note=row.get("note", ""),
                specific_tax_per_liter=_d(per_l) if per_l else None,
                edu_tax_ratio=_d(edu) if edu else None,
            )
    return rules


def education_tax_ratio(liquor_tax_rate: Decimal) -> Decimal:
    """주세율 70% 초과면 주세의 30%, 아니면 10%."""
    return Decimal("0.30") if liquor_tax_rate > Decimal("0.70") else Decimal("0.10")


def calc_taxes(taxable_value, customs_rate, liquor_tax_rate, specific_liquor_tax=None, edu_ratio=None) -> dict:
    """과세가격(원)에서 각 세금을 계산한다. 반올림 없이 Decimal 그대로 반환.
    specific_liquor_tax(원)를 주면 종량세로 보고 그 금액을 주세로 쓴다."""
    taxable_value = _d(taxable_value)
    customs_rate = _d(customs_rate)
    liquor_tax_rate = _d(liquor_tax_rate)
    if taxable_value <= 0:
        raise ValueError("과세가격이 0 이하입니다. 입력(가격·환율)을 확인하세요.")

    customs = taxable_value * customs_rate
    if specific_liquor_tax is not None:
        liquor_tax = _d(specific_liquor_tax)
    else:
        liquor_tax = (taxable_value + customs) * liquor_tax_rate
    ratio = _d(edu_ratio) if edu_ratio is not None else education_tax_ratio(liquor_tax_rate)
    edu_tax = liquor_tax * ratio
    vat = (taxable_value + customs + liquor_tax + edu_tax) * VAT_RATE
    return {
        "taxable_value": taxable_value,
        "customs": customs,
        "liquor_tax": liquor_tax,
        "edu_tax": edu_tax,
        "vat": vat,
        "total_tax": customs + liquor_tax + edu_tax + vat,
    }


def calc_landed_cost(
    local_price,
    fx_rate,
    rule: TaxRule,
    customs_rate=None,
    freight=0,
    insurance=0,
    clearance_domestic=0,
    retail_margin=0,
    volume_ml=None,
) -> dict:
    """도착 원가와 예상 소비자가.

    local_price/freight/insurance: 현지 통화. fx_rate: 현지 통화 1단위당 원(관세청 과세환율).
    customs_rate: FTA 판정 결과 적용할 관세율(None이면 일반세율).
    clearance_domestic: 통관·국내운송 가정치(원). retail_margin: 마진율(0.3 = 30%, 입력이 없으면 가정치).
    volume_ml: 용량. 종량세 주종(맥주·탁주)은 꼭 필요하다.
    """
    fx_rate = _d(fx_rate)
    if fx_rate <= 0:
        raise ValueError("환율이 0 이하입니다.")
    rate = rule.general_customs_rate if customs_rate is None else _d(customs_rate)

    taxable = (_d(local_price) + _d(freight) + _d(insurance)) * fx_rate
    if rule.is_specific:
        if not volume_ml or _d(volume_ml) <= 0:
            raise ValueError(f"{rule.name_ko}: 종량세 주종이라 용량(ml)이 있어야 주세를 계산할 수 있습니다.")
        if rule.specific_tax_per_liter is None:
            raise ValueError(f"{rule.name_ko}의 리터당 세액이 규칙표(tax_rules.csv)에 없습니다.")
        specific = _d(volume_ml) / 1000 * rule.specific_tax_per_liter
        taxes = calc_taxes(taxable, rate, 0, specific_liquor_tax=specific,
                           edu_ratio=rule.edu_tax_ratio if rule.edu_tax_ratio is not None else 0)
    else:
        taxes = calc_taxes(taxable, rate, rule.liquor_tax_rate, edu_ratio=rule.edu_tax_ratio)
    landed = taxable + taxes["total_tax"] + _d(clearance_domestic)
    if landed <= 0:
        raise ValueError("도착 원가가 0 이하입니다.")
    taxes.update(
        {
            "customs_rate": rate,
            "clearance_domestic": _d(clearance_domestic),
            "landed_cost": landed,
            "expected_retail": landed * (1 + _d(retail_margin)),
        }
    )
    return taxes

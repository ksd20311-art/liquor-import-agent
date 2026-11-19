"""기사 계산 사례 검증 (가이드 4-4). 출처: 한경 머니(와인), 비즈워치 2024.1.27(위스키)."""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import fta  # noqa: E402
import tax  # noqa: E402


def test_wine_article_case():
    """CIF 10,000원, 관세 15%, 주세 30% -> 세금 합 6,824.5원 (기사: 6,824원)."""
    r = tax.calc_taxes(10000, "0.15", "0.30")
    assert r["customs"] == Decimal("1500")
    assert r["liquor_tax"] == Decimal("3450")
    assert r["edu_tax"] == Decimal("345")
    assert r["vat"] == Decimal("1529.5")
    assert int(r["total_tax"]) == 6824  # 기사 정답(원 단위 절사)


def test_whisky_article_case():
    """수입원가 64,000원, 관세 20%, 주세 72% -> 세금 포함 163,553원."""
    r = tax.calc_taxes(64000, "0.20", "0.72")
    assert r["customs"] == Decimal("12800")
    assert r["liquor_tax"] == Decimal("55296")
    assert r["edu_tax"] == Decimal("16588.80")  # 70% 초과 -> 30%
    assert round(64000 + r["total_tax"]) == 163553


def test_rejects_non_positive_value():
    with pytest.raises(ValueError):
        tax.calc_taxes(0, "0.15", "0.30")


def test_specific_tax_beer_and_takju():
    """종량세: 주세 = 용량(L) x 리터당 세액. 맥주는 교육세 30%, 탁주는 교육세 없음."""
    rules = tax.load_tax_rules()
    beer = tax.calc_landed_cost(200, 9, rules["beer"], customs_rate="0.30", volume_ml=500)
    # 과세가격 1,800 / 관세 540 / 주세 0.5L x 885.7 = 442.85 / 교육세 132.855 / 부가세 (1800+540+442.85+132.855) x 10%
    assert beer["taxable_value"] == Decimal("1800") and beer["customs"] == Decimal("540")
    assert beer["liquor_tax"] == Decimal("442.85") and beer["edu_tax"] == Decimal("132.855")
    assert beer["vat"] == Decimal("291.5705") and beer["landed_cost"] == Decimal("3207.2755")
    takju = tax.calc_landed_cost(1000, 1, rules["takju"], customs_rate="0.15", volume_ml=750)
    assert takju["liquor_tax"] == Decimal("33.3") and takju["edu_tax"] == 0  # 0.75L x 44.4원, 교육세 없음
    assert takju["vat"] == (Decimal("1000") + 150 + Decimal("33.3")) * Decimal("0.1")
    # 가격이 두 배가 되어도 종량세 주세는 그대로다
    assert tax.calc_landed_cost(400, 9, rules["beer"], customs_rate="0.30", volume_ml=500)["liquor_tax"] == Decimal("442.85")
    with pytest.raises(ValueError, match="용량"):
        tax.calc_landed_cost(200, 9, rules["beer"])


# --- FTA 3단계 판정 ---
RULES = [
    {"origin": "FR", "liquor_type": "wine", "agreement": "한-EU", "year": "2026",
     "preferential_rate": "0", "general_rate": "0.15", "checked_on": "t"},
    {"origin": "JP", "liquor_type": "sake", "agreement": "RCEP", "year": "2026",
     "preferential_rate": "", "general_rate": "0.15", "checked_on": ""},
    {"origin": "CN", "liquor_type": "wine", "agreement": "없음", "year": "2026",
     "preferential_rate": "", "general_rate": "0.15", "checked_on": "t"},
]


def test_fta_applicable():
    r = fta.judge("FR", "FR", "wine", 2026, "예", "예", RULES)
    assert r.verdict == fta.APPLICABLE


def test_fta_transit_purchase_needs_check():
    """프랑스 와인을 미국 사이트에서 구매 -> 경유 구매, 확인 필요 (와인21 보도)."""
    r = fta.judge("FR", "US", "wine", 2026, "예", "예", RULES)
    assert r.verdict == fta.CHECK


def test_fta_unknown_certificate_needs_check():
    assert fta.judge("FR", "FR", "wine", 2026, "예", "모름", RULES).verdict == fta.CHECK


def test_fta_no_certificate_not_applicable():
    assert fta.judge("FR", "FR", "wine", 2026, "예", "아니오", RULES).verdict == fta.NOT_APPLICABLE


def test_fta_missing_rate_needs_check():
    assert fta.judge("JP", "JP", "sake", 2026, "예", "예", RULES).verdict == fta.CHECK


def test_fta_no_agreement_not_applicable():
    assert fta.judge("CN", "CN", "wine", 2026, "예", "예", RULES).verdict == fta.NOT_APPLICABLE


def test_fta_rule_missing_needs_check():
    assert fta.judge("AU", "AU", "wine", 2026, "예", "예", RULES).verdict == fta.CHECK


def test_fta_rules_are_hs_specific():
    """일본 RCEP는 버번(2208302000)만 10%, 나머지 위스키는 13.3% - 품목별 규칙표."""
    rules = fta.load_fta_rules()
    bourbon = fta.judge("JP", "JP", "whisky", 2026, "예", "예", rules, hs_code="2208302000")
    other = fta.judge("JP", "JP", "whisky", 2026, "예", "예", rules, hs_code="2208309000")
    assert (bourbon.verdict, bourbon.preferential_rate) == (fta.APPLICABLE, Decimal("0.1"))
    assert (other.verdict, other.preferential_rate) == (fta.APPLICABLE, Decimal("0.133"))


def test_fta_us_whisky_applicable_zero():
    r = fta.judge("US", "US", "whisky", 2026, "예", "예", fta.load_fta_rules(), hs_code="2208302000")
    assert r.verdict == fta.APPLICABLE and r.preferential_rate == Decimal("0")


def test_fta_period_ended_rule_needs_check():
    """영국 스카치: 규칙표 값의 적용 기간이 지났으면 확인 필요로 두 원가를 병기."""
    rules = [{"origin": "GB", "liquor_type": "whisky", "hs_code": "2208301000", "agreement": "한-영", "year": "2026",
              "preferential_rate": "0", "general_rate": "0.2", "period": "20260101~20260630", "status": "period_ended"}]
    r = fta.judge("GB", "GB", "whisky", 2026, "예", "예", rules, hs_code="2208301000")
    assert r.verdict == fta.CHECK and r.preferential_rate == Decimal("0") and "기간" in r.reason


def test_tax_rules_csv_loads():
    rules = tax.load_tax_rules()
    ad_valorem = {k for k, r in rules.items() if r.method == "ad_valorem"}
    specific = {k for k, r in rules.items() if r.method == "specific"}
    assert ad_valorem == {"sake", "wine", "whisky", "brandy", "rum", "gin", "vodka", "tequila"}  # 종가세 8종
    assert specific == {"beer", "takju"}  # 종량세 2종
    assert rules["beer"].specific_tax_per_liter == Decimal("885.7") and rules["takju"].edu_tax_ratio == 0

"""수입 주류 원가·시장 리포트 에이전트.

  python src/main.py --input inputs/candidate_whisky.json --sample   (API 키 불필요)
  python src/main.py --input inputs/candidate_whisky.json            (.env 키로 실시간 호출)
"""
import argparse
import json
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fta  # noqa: E402
import fx  # noqa: E402
import tax  # noqa: E402
import trade  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("product_name", "liquor_type", "local_price", "currency", "purchase_country")
YEAR_RULE_BASE = 2026  # 규칙표 기준 연도


class AgentError(Exception):
    """5장 실패 기준에 따라 실행을 중단해야 하는 오류."""


def won(x) -> int:
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def self_check():
    """기사 계산 사례 2건이 어긋나면 실행 금지(워크플로 6단계)."""
    w = tax.calc_taxes(10000, "0.15", "0.30")
    k = tax.calc_taxes(64000, "0.20", "0.72")
    if int(w["total_tax"]) != 6824 or round(64000 + k["total_tax"]) != 163553:
        raise AgentError("세금 계산 자체 점검(기사 사례 2건) 불일치: 실행을 중단합니다.")


def validate_input(inp: dict):
    """입력(JSON·입력 창·명령행 공통)을 검증하고 숫자·코드를 정규화한다. 문제가 있으면 한글 안내로 중단."""
    import intake
    missing = [k for k in REQUIRED if inp.get(k) in (None, "")]
    if missing:
        raise AgentError(f"입력 누락: {', '.join(missing)} 칸을 채워 주세요.")
    try:
        inp["local_price"] = intake.parse_price(inp["local_price"], "현지 가격")
        if inp.get("domestic_price") not in (None, ""):
            inp["domestic_price"] = intake.parse_price(inp["domestic_price"], "국내 판매가")
        if inp.get("volume_ml") not in (None, ""):
            inp["volume_ml"] = intake.parse_volume(inp["volume_ml"])
        if inp.get("abv_percent") not in (None, ""):
            inp["abv_percent"] = intake.parse_abv(inp["abv_percent"])
        if inp.get("fx_override") not in (None, ""):
            inp["fx_override"] = intake.parse_number(inp["fx_override"], "과세환율")
        if inp.get("margin_percent") not in (None, ""):
            inp["margin_percent"] = intake.parse_margin(inp["margin_percent"])
        inp["price_kind"] = intake.parse_price_kind(inp.get("price_kind"))
        hs_type = intake.type_from_hs(inp.get("hs_code") or "")
        if hs_type and hs_type != inp["liquor_type"]:
            raise ValueError(f"주종({inp['liquor_type']})과 품목 코드({inp['hs_code']}, {intake.TYPE_NAMES[hs_type]})가 맞지 않습니다. 하나를 고쳐 주세요.")
        inp["currency"] = intake.normalize_currency(inp["currency"])
        inp["purchase_country"] = intake.check_country(intake.normalize_country(inp["purchase_country"]), inp["purchase_country"])
        if inp.get("origin_country"):
            inp["origin_country"] = intake.check_country(intake.normalize_country(inp["origin_country"]), inp["origin_country"])
        if inp.get("hs_code"):
            inp["hs_code"] = intake.parse_hs(str(inp["hs_code"]))
    except ValueError as e:
        raise AgentError(str(e))
    if inp.get("checked_at"):
        try:
            date.fromisoformat(str(inp["checked_at"]))
        except ValueError:
            raise AgentError(f"checked_at(확인일)은 YYYY-MM-DD 형식이어야 합니다: {inp['checked_at']}")


def cost_scenario(price_local, fx_rate, rule, customs_rate, asm, volume_ml=None):
    return tax.calc_landed_cost(
        price_local, fx_rate, rule, customs_rate=customs_rate,
        freight=asm["freight_local"], insurance=asm["insurance_local"],
        clearance_domestic=asm["clearance_domestic_krw"], retail_margin=asm["retail_margin"],
        volume_ml=volume_ml,
    )


def load_assumptions(inp: dict) -> dict:
    """가정값(config/assumptions.json)에 사용자가 입력한 마진율을 반영한다."""
    asm = json.loads((ROOT / "config" / "assumptions.json").read_text(encoding="utf-8"))
    asm["margin_input"] = inp.get("margin_percent") not in (None, "")
    if asm["margin_input"]:  # 마진율은 수입사가 정하는 값이라 입력하면 가정값 대신 쓴다
        asm["retail_margin"] = Decimal(str(inp["margin_percent"])) / 100
        asm["labels"] = dict(asm["labels"], retail_margin=f"마진율: {float(inp['margin_percent']):g}% - 사용자 입력")
    return asm


def serialize(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, dict):
        return {k: serialize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [serialize(v) for v in o]
    return o


DEFAULT_ABV = {"whisky": 40.0, "wine": 13.0, "sake": 15.0, "brandy": 40.0, "rum": 40.0, "gin": 40.0, "vodka": 40.0,
               "tequila": 40.0, "beer": 5.0, "takju": 6.0}


def price_position(inp, costs, series, as_of, sample, env, save_samples):
    """후보 가격이 시장(무역통계 평균 수입단가) 어디쯤인지: 입력가(과세가격)를 달러/kg로 환산해 견준다.
    근사값이다: 순중량 = 용량 × (1 - 0.0013 × 도수)kg/L, 무역통계 수입중량과 같은 기준이라고 가정한다."""
    if not series or not inp.get("volume_ml"):
        return None
    try:
        usd = fx.get_fx("USD", as_of, sample=sample, env=env, save=save_samples and not sample)
    except RuntimeError:
        return None
    abv = inp.get("abv_percent")
    assumed = not abv
    abv = float(abv or DEFAULT_ABV.get(inp["liquor_type"], 40.0))
    taxable = float(next(iter(costs.values()))["taxable_value"])
    cand_usd = taxable / float(usd["rate"])
    net_kg = float(inp["volume_ml"]) / 1000 * (1 - 0.0013 * abv)
    unit = cand_usd / net_kg
    months = [x["unit_usd_per_kg"] for x in series["table"] if x["unit_usd_per_kg"]]
    avg = series["summary"]["unit_12m"]
    if not months or not avg:
        return None
    return {
        "cand_usd": cand_usd, "net_kg": net_kg, "unit": unit, "market_avg": avg, "ratio": unit / avg,
        "months_total": len(months), "months_below": sum(1 for m in months if unit > m),
        "month_min": min(months), "month_max": max(months), "abv_assumed": assumed, "usd_rate": float(usd["rate"]),
    }


def build_result(inp: dict, sample: bool, save_samples: bool = False, as_of: date = None, with_trend: bool = True) -> dict:
    """as_of: 기준일을 직접 정할 때(월간 알림의 등록·확인 시점). with_trend=False면 시장 추이 조회를 건너뛴다."""
    validate_input(inp)
    self_check()
    env = fx.load_env()
    asm = load_assumptions(inp)
    rules = tax.load_tax_rules()
    ltype = inp["liquor_type"]
    if ltype not in rules:
        raise AgentError(f"지원 주종이 아닙니다: {ltype}. 지원 주종: " + ", ".join(rules))
    rule = rules[ltype]
    volume = inp.get("volume_ml")
    if rule.is_specific and not volume:
        import intake
        raise AgentError(f"{intake._eun(rule.name_ko)} 용량에 세금이 붙는 종량세 주종입니다. 용량(ml)을 입력해 주세요(예: 330, 500ml).")

    if as_of is None:
        as_of = date.fromisoformat(inp["checked_at"]) if sample and inp.get("checked_at") else date.today()
    if inp.get("fx_override"):  # 사용자가 환율을 직접 입력한 경우(원/통화 1단위)
        fx_info = {"rate": Decimal(str(inp["fx_override"])), "week_start": as_of.isoformat(), "week_end": as_of.isoformat(),
                   "source": "사용자 직접 입력", "warning": "과세환율을 사용자가 직접 입력한 값으로 계산했습니다(관세청 고시값과 다를 수 있음)."}
    else:
        fx_info = fx.get_fx(inp["currency"], as_of, sample=sample, env=env, save=save_samples and not sample)
    fx_rate = fx_info["rate"]

    origin = inp.get("origin_country") or inp["purchase_country"]
    verdict = fta.judge(
        origin, inp["purchase_country"], ltype, YEAR_RULE_BASE,
        inp.get("made_in_origin"), inp.get("has_certificate"), fta.load_fta_rules(),
        hs_code=inp.get("hs_code"),
    )
    general = verdict.general_rate if verdict.general_rate is not None else rule.general_customs_rate
    pref = verdict.preferential_rate

    # 판정별 원가: 적용 가능=협정세율 / 적용 불가=일반세율 / 확인 필요=두 원가 병기
    if verdict.verdict == fta.APPLICABLE:
        rates = {"협정세율": pref}
    elif verdict.verdict == fta.NOT_APPLICABLE:
        rates = {"일반세율": general}
    else:
        rates = {"일반세율": general}
        if pref is not None:
            rates = {"협정세율": pref, "일반세율": general}

    price = inp["local_price"]
    main_costs = {name: cost_scenario(price, fx_rate, rule, r, asm, volume) for name, r in rates.items()}
    # 견적 전에 쓰는 도구라 운임·보험료·통관비는 가정값이다. 실제 값이 원가를 얼마나 바꾸는지 함께 보여 준다
    # 운임·보험료는 과세가격에 들어가 세금이 붙고, 통관·국내운송비는 세금 계산 뒤에 더해진다(현지가의 10%, 10만 원을 예로 듦)
    ten_pct = Decimal(str(price)) * Decimal("0.1")
    clr = Decimal("100000")
    by_freight = dict(asm, freight_local=Decimal(str(asm["freight_local"])) + ten_pct)
    by_clearance = dict(asm, clearance_domestic_krw=Decimal(str(asm["clearance_domestic_krw"])) + clr)
    sensitivity = {}
    for name, r in rates.items():
        base = main_costs[name]["landed_cost"]
        delta = cost_scenario(price, fx_rate, rule, r, by_freight, volume)["landed_cost"] - base
        delta_c = cost_scenario(price, fx_rate, rule, r, by_clearance, volume)["landed_cost"] - base
        sensitivity[name] = {"per_krw": delta / (ten_pct * fx_rate), "ten_pct_local": ten_pct, "ten_pct_krw": ten_pct * fx_rate,
                             "ten_pct_delta": delta, "clearance_per_krw": delta_c / clr, "clearance_example": clr,
                             "clearance_delta": delta_c}
    ref_costs = None
    if inp.get("manufacturer_price_jpy_ex_tax") and inp["currency"] == "JPY":
        ref_costs = {name: cost_scenario(inp["manufacturer_price_jpy_ex_tax"], fx_rate, rule, r, asm, volume)
                     for name, r in rates.items()}

    hs = inp.get("hs_code") or ""
    series, trend_msg = (None, "HS 코드가 없어 시장 추이를 조회하지 못했습니다.")
    if not with_trend:
        trend_msg = "시장 추이는 이번 계산에서 조회하지 않았습니다."
    elif hs:
        end_ym = trade.add_months(f"{as_of:%Y%m}", -1)
        key = env.get("DATA_GO_KR_KEY_TRADE") or env.get("DATA_GO_KR_KEY")
        series, trend_msg = trade.get_trend(hs, origin, end_ym, sample, key, save=save_samples and not sample)

    position = price_position(inp, main_costs, series, as_of, sample, env, save_samples) if with_trend else None

    return {
        "position": position,
        "input": inp, "rule": rule, "assumptions": asm, "fx": fx_info, "fta": verdict,
        "rates": rates, "costs": main_costs, "ref_costs": ref_costs, "sensitivity": sensitivity,
        "trend": series, "trend_msg": trend_msg, "sample_mode": sample, "as_of": as_of.isoformat(),
    }


def write_outputs(inp: dict, result: dict, out: Path) -> Path:
    """리포트 PDF, 계산 결과(result.json), 사용한 입력(last_input.json)을 저장하고 PDF 경로를 돌려준다."""
    import report_html
    from datetime import datetime
    out.mkdir(parents=True, exist_ok=True)
    name = inp.get("report_name", "report")
    pdf = out / f"{name}.pdf"
    if pdf.exists():  # 이전 PDF를 지워야 새로 인쇄된 파일인지 확인할 수 있다. 뷰어가 열고 있으면 다른 이름으로 저장
        try:
            pdf.unlink()
        except PermissionError:
            name = f"{name}_{datetime.now():%H%M%S}"
            pdf = out / f"{name}.pdf"
    doc = report_html.build_html(result)
    html_path = out / f"{name}.html"
    html_path.write_text(doc, encoding="utf-8")
    ok, check_text = report_html.run_korean_check(doc, out)
    result["korean_check"] = (ok, check_text)
    (out / "report_body.txt").unlink(missing_ok=True)
    report_html.write_facts(result, out / "facts.csv")
    if report_html.html_to_pdf(html_path, pdf):
        result["pdf_engine"] = "html"
    else:  # 브라우저(Edge·Chrome)가 없으면 reportlab으로 만든 기본 PDF로 대신한다
        import report
        report.build_pdf(result, pdf)
        result["pdf_engine"] = "reportlab"
    (out / "result.json").write_text(
        json.dumps(serialize({k: v for k, v in result.items() if k not in ("rule", "fta", "korean_check")} |
                             {"fta": result["fta"].__dict__}), ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "last_input.json").write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return pdf


def summary_lines(result: dict) -> list:
    lines = []
    for name, c in result["costs"].items():
        lines.append(f"{name} 도착 원가 {won(c['landed_cost']):,}원 / 예상 소비자가 {won(c['expected_retail']):,}원")
    lines.append(f"FTA 판정: {result['fta'].verdict} - {result['fta'].reason}")
    import report_html
    name, s = next(iter(result["sensitivity"].items()))
    lines.append(f"참고 원가: 운임·보험료·통관비는 가정값({report_html.assumption_text(result['assumptions'])})입니다. "
                 f"견적을 받으면 운임·보험료는 원화 1원당 도착 원가 {float(s['per_krw']):.2f}원, 통관·국내운송비는 1원당 "
                 f"{float(s['clearance_per_krw']):.2f}원씩 더하면 됩니다({name} 기준, 리포트 요약 쪽 표 참고). "
                 f"마진율 {report_html.margin_text(result['assumptions'])}.")
    if result["fx"]["warning"]:
        lines.append(f"경고: {result['fx']['warning']}")
    if not result["trend"]:
        lines.append(f"시장 추이: {result['trend_msg']}")
    p = result.get("position")
    if not p and result["trend"] and not result["input"].get("volume_ml"):
        lines.append("가격 위치: 용량(ml)을 알 수 없어 계산하지 않았습니다. 용량을 입력하면 시장 평균 단가와 견줍니다.")
    if p:
        lines.append(f"가격 위치: 입력가는 약 {p['unit']:,.0f}달러/kg로 시장 평균 수입단가 {p['market_avg']:.2f}달러/kg의 {p['ratio']:.1f}배"
                     f"(월별 단가 {p['months_total']}개 중 {p['months_below']}개보다 높음, 근사값)")
    if "korean_check" in result:
        ok, text = result["korean_check"]
        lines.append("한글 검사(금지어): " + ("통과" if ok else ("건너뜀 - " + text if ok is None else "금지어 발견 - " + text)))
    if result.get("pdf_engine") == "reportlab":
        lines.append("안내: Edge·Chrome을 찾지 못해 기본 PDF로 만들었습니다(스킬 형식은 HTML 파일 참고).")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="수입 주류 원가·시장 리포트 에이전트. 인자 없이 실행하면 제품명·가격·구매 국가를 물어봅니다.")
    ap.add_argument("--input", help="후보 입력 JSON(없으면 아래 인자 또는 대화로 입력)")
    ap.add_argument("--name", help="제품명")
    ap.add_argument("--price", help="현지 가격(숫자)")
    ap.add_argument("--country", help="구매 국가(JP, FR, US 또는 일본 등)")
    ap.add_argument("--currency", help="통화(생략하면 구매 국가로 추정)")
    ap.add_argument("--type", choices=list(tax.load_tax_rules()), help="주종(생략하면 제품명으로 제안)")
    ap.add_argument("--price-kind", dest="price_kind", choices=["retail", "quote"],
                    help="현지 가격의 종류: retail(소매가, 기본) / quote(도매·견적가). 리포트에 표기됩니다")
    ap.add_argument("--hs", help="HS 코드 10자리(생략하면 제안)")
    ap.add_argument("--origin", help="원산지 국가 코드(생략하면 브랜드 사전의 원산지, 없으면 구매 국가)")
    ap.add_argument("--fx-rate", dest="fx_rate", help="과세환율 직접 입력(원/통화 1단위, 관세청 고시값을 모를 때)")
    ap.add_argument("--volume", help="용량(ml, 생략하면 제품명에서 읽음. 없으면 가격 위치를 계산하지 않음)")
    ap.add_argument("--domestic-price", dest="domestic_price", help="국내 실제 판매가(원, 선택)")
    ap.add_argument("--margin", help="마진율(%%, 도착 원가에 붙일 마진. 생략하면 30%% 가정)")
    ap.add_argument("--price-url", dest="price_url", help="가격 출처 URL(선택)")
    ap.add_argument("--made-in-origin", dest="made_in_origin", choices=["예", "아니오", "모름"])
    ap.add_argument("--certificate", choices=["예", "아니오", "모름"], help="거래처의 원산지증명서 발급 가능 여부")
    ap.add_argument("--yes", action="store_true", help="제안값 확인을 건너뜀(리포트에 미확인으로 표시)")
    ap.add_argument("--sample", action="store_true", help="저장된 실제 API 응답으로 실행(API 키 불필요)")
    ap.add_argument("--save-samples", dest="save_samples", action="store_true",
                    help="실시간 모드에서 받은 API 응답을 data/samples에 저장(키 없는 PC에서 같은 제품을 재현하려면 사용)")
    ap.add_argument("--out", default=str(ROOT / "outputs"), help="출력 폴더")
    a = ap.parse_args(argv)
    sample = a.sample
    if not sample and not fx.has_api_key():  # 입력 창과 같게: 키가 없으면 저장된 실제 응답으로 같은 품질의 리포트를 만든다
        print("[안내] API 키(.env)가 없어 저장된 실제 API 응답으로 실행합니다(샘플 모드).")
        sample = True

    try:
        if a.input:
            try:
                inp = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))  # 메모장 저장(BOM)도 허용
            except (OSError, json.JSONDecodeError) as e:
                raise AgentError(f"입력 파일을 읽을 수 없습니다({a.input}): {e}")
            if a.fx_rate:  # 입력 파일로 실행해도 명령행의 환율 직접 입력을 반영한다
                inp["fx_override"] = a.fx_rate
            if a.margin:
                inp["margin_percent"] = a.margin
            if a.price_kind:
                inp["price_kind"] = a.price_kind
        else:
            import intake
            try:
                inp = intake.build_candidate(a)
            except (ValueError, EOFError) as e:
                raise AgentError(str(e))
        result = build_result(inp, sample, a.save_samples)
    except AgentError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 3
    except (ValueError, ArithmeticError, KeyError, TypeError) as e:  # 검증을 빠져나간 입력 오류도 한글로 안내
        print(f"[중단] 입력값을 처리하지 못했습니다({type(e).__name__}: {e}). 입력을 확인해 주세요.", file=sys.stderr)
        return 2

    out = Path(a.out)
    if not a.input and out == ROOT / "outputs":  # 직접 입력한 실행은 제출용 결과물을 덮어쓰지 않게 따로 저장
        out = ROOT / "outputs" / "runs" / inp["report_name"]
    try:
        pdf = write_outputs(inp, result, out)
    except OSError as e:
        print(f"[중단] 결과 파일을 저장하지 못했습니다({e}). 열려 있는 파일을 닫거나 --out으로 다른 폴더를 지정해 주세요.",
              file=sys.stderr)
        return 4
    print(f"리포트 생성: {pdf}")
    for name, c in result["costs"].items():
        print(f"  {name} 도착 원가 {won(c['landed_cost']):,}원 / 예상 소비자가 {won(c['expected_retail']):,}원")
    print(f"  FTA 판정: {result['fta'].verdict}")
    print("  " + next(ln for ln in summary_lines(result) if ln.startswith("참고 원가")))
    for w in (result["fx"]["warning"],):
        if w:
            print(f"  경고: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

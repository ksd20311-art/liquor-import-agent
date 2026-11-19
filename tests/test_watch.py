"""2차(11월 범위): 월간 변동 알림, 환율 주간 수집, 가격 종류, 새 주종."""
import csv
import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import fx  # noqa: E402
import intake  # noqa: E402
import main as agent  # noqa: E402
import watch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "inputs" / "candidate_whisky.json"
BEER = {"product_name": "Asahi Super Dry 350ml", "liquor_type": "beer", "hs_code": "2203000000", "origin_country": "JP",
        "purchase_country": "JP", "currency": "JPY", "local_price": 220, "volume_ml": 350,
        "made_in_origin": "예", "has_certificate": "예"}
WINE = {"product_name": "Montes Alpha Cabernet Sauvignon Red Wine 750ml", "liquor_type": "wine", "hs_code": "2204211000",
        "origin_country": "CL", "purchase_country": "CL", "currency": "USD", "local_price": 18, "volume_ml": 750,
        "made_in_origin": "예", "has_certificate": "예"}


def whisky():
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


@pytest.fixture
def fake_fx(monkeypatch):
    """과세환율을 시험 값으로 바꾼다: rates[통화] = 원/1단위."""
    rates = {"JPY": Decimal("8.4277"), "USD": Decimal("1400"), "GBP": Decimal("1800")}

    def get_fx(currency, on, sample=False, env=None, save=False):
        return {"rate": rates[currency], "week_start": "2026-10-25", "week_end": "2026-10-31", "source": "시험 환율", "warning": ""}
    monkeypatch.setattr(fx, "get_fx", get_fx)
    return rates


def test_three_candidates_alert_when_fx_moves_over_threshold(tmp_path, fake_fx):
    """성공 기준: 후보 3개 이상에서 등록 시점 대비 ±5% 변동 시 원인 분해 알림을 만든다."""
    path = tmp_path / "watchlist.json"
    for inp in (whisky(), BEER, WINE):
        watch.add(inp, sample=True, path=path)
    assert [x["id"] for x in watch.load(path)["items"]] == ["w1", "w2", "w3"]
    assert agent.won(watch.load(path)["items"][0]["baseline"]["landed_main"]) == 457530  # 1차 결과물과 같은 기준 원가

    quiet = watch.check(sample=True, as_of=date(2026, 11, 2), path=path)  # 아무것도 안 바뀌면 알림 없음
    assert all(not r["record"]["alert"] and r["record"]["vs_baseline"]["pct"] == 0 for r in quiet)

    fake_fx["JPY"] *= Decimal("1.08")  # 엔화 +8%
    fake_fx["USD"] *= Decimal("0.93")  # 달러 -7%
    results = watch.check(sample=True, as_of=date(2026, 11, 16), path=path)
    assert len(results) == 3 and all(r["record"]["alert"] for r in results)
    for r in results:
        d = r["record"]["vs_baseline"]
        parts = sum(Decimal(d[k]) for k in ("fx_effect", "rate_effect", "price_effect", "other_effect"))
        assert abs(parts - Decimal(d["total"])) < Decimal("0.000001")  # 원인별 효과의 합 = 전체 변동
        assert Decimal(d["rate_effect"]) == 0 and Decimal(d["price_effect"]) == 0  # 환율만 움직였다
    w1, w2, w3 = (r["record"]["vs_baseline"]["pct"] for r in results)
    assert w1 == pytest.approx(8.0) and w3 == pytest.approx(-7.0)  # 종가세는 환율 변동률 그대로
    assert 5 < w2 < 8  # 맥주는 주세가 용량 기준이라 환율 영향이 조금 작다
    assert "엔화 과세환율이 100엔당 842.77원에서 910.19원으로 올라" in results[0]["record"]["messages"][0]
    assert "늘었다" in results[0]["record"]["messages"][0] and "줄었다" in results[2]["record"]["messages"][0]
    saved = watch.load(path)["items"][0]["checks"]
    assert len(saved) == 2 and saved[-1]["alert"] and saved[-1]["vs_previous"]["pct"] == pytest.approx(8.0)


def test_decomposition_fx_rate_price_effects_sum_to_total(tmp_path, fake_fx):
    """환율·세율·현지가가 함께 바뀌어도 세 효과의 합은 전체 변동과 같다."""
    path = tmp_path / "watchlist.json"
    item = watch.add(whisky(), sample=True, path=path)
    data = watch.load(path)
    base = data["items"][0]["baseline"]
    assert base["scenario"] == "협정세율" and Decimal(base["customs_rate"]) == Decimal("0.133")
    # 등록 때는 일반세율 20%가 적용됐다고 가정해 기준을 바꿔 둔다(세율 변동을 흉내)
    import tax
    rule = tax.load_tax_rules()["whisky"]
    asm = agent.load_assumptions(item["input"])
    base["customs_rate"], base["scenario"] = "0.2", "일반세율"
    base["landed_main"] = str(agent.cost_scenario(22500, Decimal("8.4277"), rule, "0.2", asm, 700)["landed_cost"])
    watch.save(data, path)

    fake_fx["JPY"] = Decimal("8.9")
    watch.update_price("w1", "23,500엔", path=path)
    rec = watch.check(sample=True, path=path)[0]["record"]
    d = rec["vs_baseline"]
    fx_e, rate_e, price_e = (Decimal(d[k]) for k in ("fx_effect", "rate_effect", "price_effect"))
    assert fx_e > 0 and rate_e < 0 and price_e > 0  # 환율 상승, 세율 인하(20% → 13.3%), 현지가 상승
    assert abs(fx_e + rate_e + price_e - Decimal(d["total"])) < Decimal("0.000001") and Decimal(d["other_effect"]) == 0
    # 손으로 다시 계산: 환율 효과 = 같은 가격·세율에서 환율만 바꾼 차이
    hand = (agent.cost_scenario(22500, Decimal("8.9"), rule, "0.2", asm, 700)["landed_cost"]
            - agent.cost_scenario(22500, Decimal("8.4277"), rule, "0.2", asm, 700)["landed_cost"])
    assert fx_e == hand
    text = " ".join(rec["messages"])
    assert "적용 관세율이 20%에서 13.3%로 내려" in text and "현지가가 22,500JPY에서 23,500JPY로 올라" in text


def test_threshold_and_price_update(tmp_path, fake_fx):
    path = tmp_path / "watchlist.json"
    watch.add(BEER, sample=True, threshold=1.0, path=path)
    fake_fx["JPY"] *= Decimal("1.02")  # +2%: 기본 기준(5%)이면 조용하지만 이 후보 기준(1%)에서는 알림
    r = watch.check(sample=True, path=path)[0]
    assert r["threshold"] == 1.0 and r["record"]["alert"]
    assert not watch.check(sample=True, threshold=5, path=path)[0]["record"]["alert"]
    with pytest.raises(agent.AgentError, match="등록 목록"):
        watch.update_price("w9", "100", path=path)
    with pytest.raises(agent.AgentError):
        watch.update_price("w1", "-5", path=path)
    assert watch.remove("w1", path=path)["id"] == "w1" and watch.load(path)["items"] == []


def test_alert_report_follows_skill_rules(tmp_path, fake_fx):
    """알림 리포트도 스킬 규칙(제목 40자 이내·명사 종결, 금지어 0건, 출처 줄)을 따른다."""
    import report_html
    path = tmp_path / "watchlist.json"
    for inp in (whisky(), BEER, WINE):
        watch.add(inp, sample=True, path=path)
    fake_fx["JPY"] *= Decimal("0.9")
    results = watch.check(sample=True, as_of=date(2026, 11, 16), path=path)
    rep = watch.write_report(results, "2026-11-16", tmp_path / "reports")
    doc = rep["html"].read_text(encoding="utf-8")
    titles = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h2>(.*?)</h2>", doc)]
    assert titles[0] == "등록 후보 3건 중 2건, 기준 ±5% 초과 변동"
    for t in titles:
        assert len(t) <= 40 and not t.endswith("다"), t
    assert rep["korean_check"][0], rep["korean_check"][1]
    assert doc.count("출처:") >= 4 and "원가 영향(원)" in doc
    if report_html.find_browser():
        assert rep["pdf"] and rep["pdf"].stat().st_size > 5000
    lines = watch.console_lines(results)
    assert any("→ 알림" in ln for ln in lines) and any("기준 이내" in ln for ln in lines)


def test_one_failing_candidate_does_not_stop_others(tmp_path, fake_fx):
    path = tmp_path / "watchlist.json"
    watch.add(whisky(), sample=True, path=path)
    watch.add(WINE, sample=True, path=path)
    del fake_fx["USD"]  # 달러 환율을 못 받는 상황

    def get_fx(currency, on, sample=False, env=None, save=False):
        if currency not in fake_fx:
            raise RuntimeError("USD 과세환율을 실시간으로 받지 못했습니다(호출 한도 소진이나 인터넷 연결 문제).")
        return {"rate": fake_fx[currency], "week_start": "2026-10-25", "week_end": "2026-10-31", "source": "시험 환율", "warning": ""}
    fx.get_fx = get_fx  # fake_fx 픽스처가 끝나면 원래 함수로 돌아간다
    results = watch.check(sample=True, path=path)
    assert "record" in results[0] and "과세환율" in results[1]["error"]
    assert "확인 실패" in "\n".join(watch.console_lines(results))


def test_collect_fx_appends_weekly_history_once(tmp_path, monkeypatch):
    """환율 주 1회 자동 수집: 같은 주는 한 번만 쌓는다."""
    monkeypatch.setattr(watch, "FX_HISTORY", tmp_path / "fx_history.csv")
    monkeypatch.setattr(fx, "fetch_week", lambda on, env=None: (fx.week_start(on), {"JPY": Decimal("8.465"), "USD": Decimal("1345.2")}))
    r1 = watch.collect_fx(date(2026, 11, 16))
    r2 = watch.collect_fx(date(2026, 11, 18))  # 같은 주
    r3 = watch.collect_fx(date(2026, 11, 23))  # 다음 주
    assert (r1["added"], r2["added"], r3["added"]) == (2, 0, 2) and r1["week_start"] == "2026-11-15"
    with open(tmp_path / "fx_history.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4 and rows[0]["currency"] == "JPY" and rows[0]["krw_per_unit"] == "8.465"


def test_price_kind_is_shown_in_report_and_facts():
    import report_html
    inp = whisky()
    r = agent.build_result(inp, sample=True)
    assert r["input"]["price_kind"] == "retail" and "22,500 JPY / 소매가 / JP" in report_html.build_html(r)
    inp2 = whisky()
    inp2["price_kind"] = "도매·견적가"
    r2 = agent.build_result(inp2, sample=True)
    assert r2["input"]["price_kind"] == "quote" and "도매·견적가" in report_html.build_html(r2)
    assert "도매·견적가" in report_html.facts_rows(r2)[0][1]
    assert agent.won(r2["costs"]["협정세율"]["landed_cost"]) == 457530  # 가격 종류는 표기만 바꾸고 계산은 같다
    bad = whisky()
    bad["price_kind"] = "모름"
    with pytest.raises(agent.AgentError, match="가격 종류"):
        agent.build_result(bad, sample=True)


def test_long_product_name_keeps_title_within_40_chars(fake_fx):
    """제품명이 길어도 표지 제목은 40자 이내(스킬 규칙). 2차 점검에서 찾은 문제."""
    import report_html
    fake_fx["EUR"] = Decimal("1500")
    inp = intake.build_from_form({"name": "Chateau Margaux 2015 Red Wine 750ml", "price": "600", "country": "France",
                                  "domestic": "1500000"})
    doc = report_html.build_html(agent.build_result(inp, sample=True, with_trend=False))
    titles = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h[12]>(.*?)</h[12]>", doc)]
    assert titles[0].endswith("국내 판매가 대비 원가 열위") and all(len(t) <= 40 for t in titles), titles


def test_report_layout_page_numbers_and_contents_match():
    """리포트 디자인: 표지를 뺀 모든 쪽 아래에 쪽 번호가 있고, 요약의 장별 결론은 각 장 제목과 같다."""
    import report_html
    for inp, pages in ((whisky(), 7), (dict(BEER, checked_at="2026-10-27"), 5)):  # 맥주는 저장된 추이가 없어 3장이 빠진다
        doc = report_html.build_html(agent.build_result(inp, sample=True))
        sections = re.findall(r'<section class="page[^"]*">', doc)
        assert len(sections) == pages
        assert re.findall(r'<span class="num">(\d+) / (\d+)</span>', doc) == [(str(n), str(pages)) for n in range(2, pages + 1)]
        h2 = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h2>(.*?)</h2>", doc)]
        toc = re.search(r"<h3>장별 결론</h3><table.*?</table>", doc, re.S).group(0)
        for title in h2[1:-1]:  # 요약 제목과 출처 제목을 뺀 장 제목이 모두 목록에 있어야 한다
            assert f">{title}</td>" in toc, title
        assert '<p class="concl"><b>결론</b>' in doc and doc.count("출처:") >= 5


def test_broken_watchlist_file_is_reported_not_overwritten(tmp_path):
    """손으로 고치다 깨진 목록 파일은 한글로 알리고 덮어쓰지 않는다. 2차 점검에서 찾은 문제."""
    path = tmp_path / "watchlist.json"
    path.write_text("{깨진 파일", encoding="utf-8")
    with pytest.raises(agent.AgentError, match="읽을 수 없습니다"):
        watch.check(sample=True, path=path)
    assert path.read_text(encoding="utf-8") == "{깨진 파일"
    assert watch.main(["list"]) == 0  # 정상 목록은 그대로 읽힌다


def test_form_builder_shared_by_gui_and_web():
    v = {"name": "Asahi Super Dry 350ml", "price": "220", "country": "일본", "kind": "quote", "margin": "20"}
    inp = intake.build_from_form(v)
    assert (inp["liquor_type"], inp["hs_code"], inp["volume_ml"], inp["currency"], inp["price_kind"]) == ("beer", "2203000000", 350, "JPY", "quote")
    with pytest.raises(ValueError, match="용량"):
        intake.build_from_form({"name": "Asahi Super Dry", "price": "220", "country": "JP"})
    assert intake.build_from_form({"name": "Asahi Super Dry", "price": "220", "country": "JP", "volume": "500ml"})["volume_ml"] == 500
    with pytest.raises(ValueError, match="맞지 않습니다"):
        intake.build_from_form({"name": "아무개", "price": "1", "country": "JP", "type": "wine", "hs": "2203000000"})


def test_no_agreement_country_uses_general_rate(tmp_path):
    """협정이 없는 생산국(멕시코 데킬라)은 「적용 불가」로 일반세율만 계산한다."""
    code = agent.main(["--name", "Patron Silver Tequila 750ml", "--price", "50", "--country", "MX", "--currency", "USD",
                       "--made-in-origin", "예", "--certificate", "예", "--yes", "--sample", "--out", str(tmp_path)])
    assert code == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["fta"]["verdict"] == "적용 불가" and list(r["costs"]) == ["일반세율"] and Decimal(r["rates"]["일반세율"]) == Decimal("0.2")

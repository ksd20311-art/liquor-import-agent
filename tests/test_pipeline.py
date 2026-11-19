"""샘플 모드 end-to-end와 실패 기준(5장) 검증. API 키 없이 실행된다."""
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import fx  # noqa: E402
import main as agent  # noqa: E402
import trade  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "inputs" / "candidate_whisky.json"


def load_candidate():
    return json.loads(CANDIDATE.read_text(encoding="utf-8"))


def test_sample_run_creates_report(tmp_path):
    code = agent.main(["--input", str(CANDIDATE), "--sample", "--out", str(tmp_path)])
    assert code == 0
    pdf = tmp_path / "report_yamazaki12.pdf"
    assert pdf.exists() and pdf.stat().st_size > 5000
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["fta"]["verdict"] == "확인 필요"
    assert set(result["costs"]) == {"협정세율", "일반세율"}  # 확인 필요 -> 두 원가 병기


def test_sample_costs_match_hand_calculation():
    r = agent.build_result(load_candidate(), sample=True)
    c = r["costs"]["협정세율"]
    # 22,500엔 x 8.4277 = 189,623.25원 -> 관세 13.3% -> 주세 72% -> 교육세 30% -> 부가세 10%
    assert int(c["taxable_value"]) == 189623
    assert agent.won(c["landed_cost"]) == 457530
    assert r["fx"]["rate"] == Decimal("8.4277")


def test_freight_sensitivity_matches_tax_multiplier(tmp_path):
    r = agent.build_result(load_candidate(), sample=True)
    # 운임 1원당: (1 + 관세율) x (1 + 주세 72% + 교육세 21.6%) x 1.1(부가세)
    assert abs(float(r["sensitivity"]["협정세율"]["per_krw"]) - 1.133 * 1.936 * 1.1) < 0.01
    assert abs(float(r["sensitivity"]["일반세율"]["per_krw"]) - 1.20 * 1.936 * 1.1) < 0.01
    assert r["sensitivity"]["협정세율"]["ten_pct_local"] == Decimal("2250.0")
    assert agent.won(r["costs"]["협정세율"]["landed_cost"]) == 457530  # 민감도 계산이 본 원가를 바꾸지 않음
    assert float(r["sensitivity"]["협정세율"]["clearance_per_krw"]) == 1.0  # 통관·국내운송비는 세금 뒤에 더해짐
    import report_html
    doc = report_html.build_html(r)
    assert "참고 원가다" in doc and "견적을 받기 전에" in doc and "이렇게 보정한다" in doc and "통관·국내운송비" in doc
    assert "도매" not in doc  # 도매가 이야기는 발표 자료에서만 다룬다


def test_margin_input_replaces_assumption():
    inp = load_candidate()
    inp["margin_percent"] = "25%"
    r = agent.build_result(inp, sample=True)
    c = r["costs"]["협정세율"]
    assert agent.won(c["landed_cost"]) == 457530  # 마진율은 도착 원가에 영향 없음
    assert agent.won(c["expected_retail"]) == agent.won(c["landed_cost"] * Decimal("1.25"))
    import report_html
    assert report_html.margin_text(r["assumptions"]) == "25%(입력값)"
    assert report_html.margin_text(agent.build_result(load_candidate(), sample=True)["assumptions"]) == "30%(가정)"
    bad = load_candidate()
    bad["margin_percent"] = "-5"
    try:
        agent.build_result(bad, sample=True)
        assert False, "음수 마진율은 막아야 함"
    except agent.AgentError as e:
        assert "마진율" in str(e)


def test_missing_price_stops_with_message(tmp_path, capsys):
    bad = load_candidate()
    bad["local_price"] = None
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    assert agent.main(["--input", str(p), "--sample", "--out", str(tmp_path)]) == 2
    assert "local_price" in capsys.readouterr().err


def test_unsupported_liquor_type_stops(tmp_path, capsys):
    bad = load_candidate()
    bad["liquor_type"] = "soju"  # 규칙표에 없는 주종
    del bad["hs_code"]
    p = tmp_path / "soju.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    assert agent.main(["--input", str(p), "--sample", "--out", str(tmp_path)]) == 2
    assert "지원 주종" in capsys.readouterr().err
    mismatch = load_candidate()
    mismatch["liquor_type"] = "beer"  # 품목 코드는 위스키인데 주종만 맥주로 바꾼 입력
    p.write_text(json.dumps(mismatch), encoding="utf-8")
    assert agent.main(["--input", str(p), "--sample", "--out", str(tmp_path)]) == 2
    assert "맞지 않습니다" in capsys.readouterr().err


def test_fx_week_starts_on_sunday():
    from datetime import date
    assert fx.week_start(date(2026, 10, 27)) == date(2026, 10, 25)
    assert fx.week_start(date(2026, 10, 25)) == date(2026, 10, 25)
    assert fx.week_start(date(2026, 10, 31)) == date(2026, 10, 25)


def test_fx_missing_week_falls_back_with_warning():
    from datetime import date
    res = fx.get_fx("JPY", date(2026, 12, 1), sample=True, env={})
    assert res["warning"]  # 해당 주간 값이 없으면 가장 최근 고시값 + 경고


def test_fx_sample_uses_latest_saved_week_for_any_currency():
    """저장 주간이 지난 뒤에도 키 없이 EUR 같은 통화가 동작한다(경고 표시)."""
    from datetime import date
    res = fx.get_fx("EUR", date(2027, 3, 1), sample=True, env={})
    assert res["rate"] == Decimal("1492.96") and "다릅니다" in res["warning"]


def test_trade_series_skips_total_row_and_has_12_months():
    rows = trade.load_samples("2208309000", "JP")
    series = trade.build_series(rows)
    assert len(series["table"]) == 12
    assert series["summary"]["last_month"] == "202609"
    assert all(x["ym"] != "-" for x in series["table"])


def test_trade_live_without_key_explains_cause():
    series, msg = trade.get_trend("2208309000", "JP", "202609", sample=False, key="")
    assert series is None and "API 키" in msg


def test_intake_suggests_type_hs_volume_abv():
    import intake
    s = intake.suggest_product("산토리 야마자키 12년 위스키 700ml 43%", "JP")
    assert (s["liquor_type"], s["hs_code"], s["volume_ml"], s["abv_percent"]) == ("whisky", "2208309000", 700, 43.0)
    assert intake.suggest_product("맥캘란 스카치 위스키", "GB")["hs_code"] == "2208301000"
    assert intake.suggest_product("샤또 마고 레드 와인 750ml", "FR")["hs_code"] == "2204211000"
    assert intake.suggest_product("준마이 다이긴조 사케", "JP")["hs_code"] == "2206002010"
    assert intake.suggest_liquor_type("OOO 12년 700ml") is None


def test_brand_hints_find_type_hs_origin_without_type_word():
    """제품명에 주종 단어가 없어도 브랜드·품종으로 주종·HS 코드·원산지를 제안한다."""
    import intake
    cases = {
        "맥캘란 12년 700ml": ("whisky", "2208301000", "GB"),
        "메이커스 마크 750ml": ("whisky", "2208302000", "US"),
        "야마자키 12년": ("whisky", "2208309000", "JP"),
        "제임슨 스탠다드": ("whisky", "2208309000", "IE"),
        "샤또 마고 2015": ("wine", "2204219000", "FR"),
        "카베르네 소비뇽 750ml": ("wine", "2204211000", "KR"),
        "샤르도네 750ml": ("wine", "2204212000", "KR"),
        "닷사이 23 720ml": ("sake", "2206002010", "JP"),
    }
    for name, (t, hs, origin) in cases.items():
        s = intake.suggest_product(name, "KR")
        assert (s["liquor_type"], s["hs_code"]) == (t, hs), name
        assert s["origin_country"] == origin, (name, s["origin_country"])  # 품종은 원산지를 모르므로 구매국(KR) 그대로
    assert intake.suggest_product("글렌피딕 18년 스카치 위스키", "JP")["hs_code"] == "2208301000"
    assert intake.suggest_product("아무개 12년", "JP")["liquor_type"] is None  # 사전에 없으면 모름 -> 주종 선택 안내


def test_english_names_and_countries():
    """영문 제품명·영문 국가명·cl/L 용량 단위도 인식한다."""
    import intake
    cases = {  # 이름: (주종, HS, 원산지, 용량, 도수)
        "Macallan 12 Year Old Single Malt Scotch Whisky 70cl 40%": ("whisky", "2208301000", "GB", 700, 40.0),
        "Yamazaki 12 Year Old Single Malt Whisky 700ml 43%": ("whisky", "2208309000", "JP", 700, 43.0),
        "Maker's Mark Kentucky Straight Bourbon 750ml 45%": ("whisky", "2208302000", "US", 750, 45.0),
        "Jameson Irish Whiskey 1L 40% ABV": ("whisky", "2208309000", "IE", 1000, 40.0),
        "Dassai 23 Junmai Daiginjo 720ml": ("sake", "2206002010", "JP", 720, None),
        "Chateau Margaux 2015 Red Wine 750ml": ("wine", "2204211000", "FR", 750, None),
        "Santa Rita Cabernet Sauvignon 0.75L": ("wine", "2204211000", "KR", 750, None),
        "Kavalan Vinho Barrique Single Malt 700ml": ("whisky", "2208309000", "TW", 700, None),
    }
    for name, (t, hs, origin, vol, abv) in cases.items():
        s = intake.suggest_product(name, "KR")
        assert (s["liquor_type"], s["hs_code"], s["origin_country"], s["volume_ml"], s["abv_percent"]) == (t, hs, origin, vol, abv), name
    # 2차: 맥주·진·보드카·브랜디도 지원한다(주종·품목 코드·브랜드 원산지 제안)
    for name, (t, hs, origin) in {"Asahi Super Dry Beer 500ml": ("beer", "2203000000", "JP"),
                                  "Beefeater Gin 700ml": ("gin", "2208500000", "GB"),
                                  "Absolut Vodka 1L": ("vodka", "2208600000", "SE"),
                                  "Hennessy VSOP Cognac": ("brandy", "2208201000", "FR"),
                                  "Patron Silver Tequila 750ml": ("tequila", "2208907000", "MX"),
                                  "Moet Chandon Imperial Brut Champagne": ("wine", "2204100000", "FR"),
                                  "서울 장수 막걸리 750ml": ("takju", "2206002030", "KR")}.items():
        s = intake.suggest_product(name, "KR")
        assert (s["liquor_type"], s["hs_code"], s["origin_country"], s["unsupported"]) == (t, hs, origin, None), (name, s)
    assert intake.suggest_product("참이슬 소주 360ml", "KR")["unsupported"] == "소주"  # 아직 지원하지 않는 주종
    s = intake.suggest_product("Hakkaisan Ginjo Sake 720ml", "JP")
    assert s["liquor_type"] == "sake" and not s["unsupported"]  # ginjo는 gin이 아님
    assert intake.suggest_product("Sierra Nevada Pale Ale 355ml", "US")["liquor_type"] == "beer"
    assert intake.suggest_liquor_type("진로 이즈 백") is None  # 「진로」의 「진」은 주종이 아님
    for text, code in {"Japan": "JP", "japan": "JP", "USA": "US", "United Kingdom": "GB", "Scotland": "GB",
                       "Vietnam": "VN", "일본": "JP", "jp": "JP", "New Zealand": "NZ"}.items():
        assert intake.normalize_country(text) == code, text


def test_hs_code_alone_decides_type_when_name_unknown(tmp_path):
    """제품명으로 주종을 모를 때 품목 코드(HS)만 직접 줘도 주종이 정해진다."""
    import intake
    assert intake.parse_hs("2208309000 위스키 - 기타") == "2208309000"
    assert intake.parse_hs("2208.30.9000") == "2208309000"
    assert intake.parse_hs("자동 인식") is None and intake.parse_hs("") is None
    try:
        intake.parse_hs("22083")
        assert False
    except ValueError as e:
        assert "10자리" in str(e)
    assert intake.type_from_hs("2204212000") == "wine" and intake.type_from_hs("2203000000") == "beer"
    # 목록에 없어도 같은 품목군의 코드는 직접 입력으로 쓸 수 있다
    assert intake.type_from_hs("2204221000") == "wine" and intake.type_from_hs("2208301090") == "whisky"
    assert intake.type_from_hs("2208209000") == "brandy" and intake.type_from_hs("2208904000") is None  # 소주는 미지원
    try:
        intake.parse_hs("직접 입력…")
        assert False
    except ValueError as e:
        assert "직접 입력" in str(e)
    code = agent.main(["--name", "아무개 12년", "--price", "20000", "--country", "JP", "--hs", "2208309000", "--yes",
                       "--sample", "--out", str(tmp_path)])
    assert code == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["input"]["liquor_type"] == "whisky" and r["input"]["hs_code"] == "2208309000"
    assert agent.main(["--name", "아무개 12년", "--price", "1", "--country", "JP", "--hs", "2208904000", "--yes",
                       "--sample", "--out", str(tmp_path)]) == 2  # 소주 코드는 미지원
    assert agent.main(["--name", "아무개 캔", "--price", "200", "--country", "JP", "--hs", "2203000000", "--yes",
                       "--sample", "--out", str(tmp_path)]) == 2  # 맥주 코드는 지원하지만 용량이 없으면 멈춘다
    assert agent.main(["--name", "아무개 12년", "--price", "1", "--country", "JP", "--type", "wine", "--hs", "2208309000",
                       "--yes", "--sample", "--out", str(tmp_path)]) == 2  # 주종과 코드 불일치


def test_fx_override_and_clear_error_for_unknown_currency(tmp_path):
    code = agent.main(["--name", "야마자키 12년", "--price", "22500", "--country", "JP", "--fx-rate", "8.5", "--yes",
                       "--sample", "--out", str(tmp_path)])
    assert code == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["fx"]["source"] == "사용자 직접 입력" and r["fx"]["rate"] == "8.5"
    import fx
    from datetime import date
    try:
        fx.get_fx("XXX", date(2026, 10, 30), sample=False, env={})
        assert False
    except RuntimeError as e:
        assert "XXX" in str(e) and "API 키 없음" in str(e)  # 원인이 문구에 드러난다


def test_input_validation_regressions():
    """전체 점검(10/30)에서 찾은 결함이 다시 생기지 않게 고정한다."""
    import intake
    import pytest as _p
    for bad in ("-100", "0", "1.2.3", "abc"):
        with _p.raises(ValueError):
            intake.parse_price(bad)
    assert intake.parse_price("22,500엔") == 22500 and intake.parse_price("29.99") == 29.99
    assert [intake.parse_volume(x) for x in ("700", "700ml", "70cl", "1L", "0.75")] == [700, 700, 700, 1000, 750]
    for bad in ("abc", "-700", "0"):
        with _p.raises(ValueError):
            intake.parse_volume(bad)
    assert intake.parse_abv("43%") == 43.0
    with _p.raises(ValueError):
        intake.parse_abv("200")
    assert intake.normalize_currency("YEN") == "JPY" and intake.normalize_currency("엔") == "JPY"
    with _p.raises(ValueError):
        intake.normalize_currency("XX")
    with _p.raises(ValueError):
        intake.check_country(intake.normalize_country("Atlantis"), "Atlantis")
    assert intake.normalize_country("Mexico") == "MX" and intake.normalize_country("태국") == "TH"
    assert intake.CURRENCY_BY_COUNTRY["MX"] == "MXN"  # 2차: 데킬라·맥주 생산국의 이름과 통화
    with _p.raises(ValueError, match="0보다 커야"):
        intake.parse_price("0")
    # 숙성통 표기(ale·rum 캐스크)는 주종으로 보지 않는다. 위스키 브랜드의 진은 진으로 본다
    assert intake.suggest_product("Glen Moray Ale Cask Finish Whisky", "GB")["liquor_type"] == "whisky"
    assert intake.suggest_product("Balvenie 14 Caribbean Rum Cask Scotch Whisky", "GB")["liquor_type"] == "whisky"
    assert intake.suggest_product("Macallan Rum Cask Finish 700ml", "GB")["liquor_type"] == "whisky"
    s = intake.suggest_product("Nikka Coffey Gin 700ml", "JP")
    assert s["liquor_type"] == "gin" and s["hs_code"] == "2208500000" and s["unsupported"] is None


def test_json_input_with_string_numbers_and_bad_date(tmp_path):
    good = dict(load_candidate(), local_price="22,500", volume_ml="700ml")
    p = tmp_path / "s.json"
    p.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    assert agent.main(["--input", str(p), "--sample", "--out", str(tmp_path)]) == 0
    bad = dict(load_candidate(), checked_at="2026/10/27")
    p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert agent.main(["--input", str(p), "--sample", "--out", str(tmp_path)]) == 2
    assert agent.main(["--name", "야마자키 12년 위스키", "--price", "100", "--country", "JP", "--fx-rate", "abc", "--yes",
                       "--sample", "--out", str(tmp_path)]) == 2  # 이전에는 처리 안 된 예외


def test_cli_without_key_switches_to_sample_mode(tmp_path, monkeypatch, capsys):
    """키가 없는 PC에서 --sample 없이 실행해도(README 「실시간 실행」 명령) 시장 추이까지 같은 품질로 나온다."""
    monkeypatch.setattr(agent.fx, "has_api_key", lambda env=None: False)
    assert agent.main(["--input", str(CANDIDATE), "--out", str(tmp_path)]) == 0
    assert "샘플 모드" in capsys.readouterr().out
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["sample_mode"] is True and r["trend"] is not None and r["position"] is not None


def test_live_failure_does_not_use_saved_data_and_explains_cause(monkeypatch, tmp_path):
    """실시간 조회가 실패하면 저장된 자료로 대신하지 않고 원인(호출 한도 소진·인터넷 문제)을 안내한다."""
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(trade, "fetch_live", boom)
    series, msg = trade.get_trend("2208309000", "JP", "202609", sample=False, key="dummy")  # 저장본이 있는 조합이어도
    assert series is None and "호출 한도 소진" in msg and "인터넷" in msg
    # 환율도 마찬가지: 실패하면 멈추고 원인을 알린다(저장된 환율·CSV로 대체하지 않음)
    import urllib.request
    from datetime import date

    def refuse(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    try:
        fx.get_fx("JPY", date(2026, 10, 30), sample=False, env={"DATA_GO_KR_KEY_FX": "dummy"})
        assert False, "실패해야 한다"
    except RuntimeError as e:
        assert "호출 한도 소진" in str(e) and "인터넷" in str(e) and "--fx-rate" in str(e)
    # 명령행: 환율을 받지 못하면 멈춘다(종료코드 3), 환율을 직접 입력하면 계산한다
    monkeypatch.setattr(agent.fx, "has_api_key", lambda env=None: True)
    monkeypatch.setattr(agent.fx, "load_env", lambda path=None: {"DATA_GO_KR_KEY_FX": "d", "DATA_GO_KR_KEY_TRADE": "d"})
    assert agent.main(["--input", str(CANDIDATE), "--out", str(tmp_path)]) == 3
    assert agent.main(["--input", str(CANDIDATE), "--fx-rate", "8.4277", "--out", str(tmp_path)]) == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["trend"] is None and "호출 한도 소진" in r["trend_msg"] and r["fx"]["source"] == "사용자 직접 입력"


def test_load_env_reads_visible_api_keys_file(tmp_path):
    p = tmp_path / "api_keys.env"
    p.write_text("# 주석\nDATA_GO_KR_KEY_FX=abc\nDATA_GO_KR_KEY_TRADE=\n", encoding="utf-8")
    env = fx.load_env(p)
    assert env == {"DATA_GO_KR_KEY_FX": "abc"} or env.get("DATA_GO_KR_KEY_FX") == "abc"
    assert not fx.has_api_key({"DATA_GO_KR_KEY_FX": "abc"})  # 무역통계 키가 없으면 실시간 불가
    assert fx.has_api_key({"DATA_GO_KR_KEY_FX": "a", "DATA_GO_KR_KEY_TRADE": "b"})


def test_gui_fta_questions_are_on_main_screen_and_change_verdict():
    """FTA 질문 2개는 세부 설정이 아니라 메인 화면에 있고, 응답에 따라 판정이 달라진다."""
    import tkinter as tk
    import gui
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.App(root)
        root.update()
        main_labels = []

        def walk(w, inside_adv):
            for c in w.winfo_children():
                if c.winfo_class() == "TLabel" and not inside_adv:
                    main_labels.append(c.cget("text"))
                walk(c, inside_adv or c is app.adv_win)
        walk(root, False)
        assert sum(1 for t in main_labels if t.startswith("FTA 질문")) == 2
        results = {}
        for made, cert in (("모름", "모름"), ("예", "예"), ("예", "아니오")):
            app.v["name"].set("메이커스마크 버번 750ml")
            app.v["price"].set("30")
            app.v["country"].set("미국 (US)")
            app._on_country()
            app.v["made"].set(made)
            app.v["cert"].set(cert)
            r = gui.agent.build_result(app.collect(), True)
            results[(made, cert)] = (r["fta"].verdict, list(r["costs"]))
        assert results[("모름", "모름")] == ("확인 필요", ["협정세율", "일반세율"])
        assert results[("예", "예")] == ("적용 가능", ["협정세율"])
        assert results[("예", "아니오")] == ("적용 불가", ["일반세율"])
    finally:
        root.destroy()


def test_locked_pdf_is_saved_under_new_name(tmp_path):
    inp = load_candidate()
    first = agent.write_outputs(inp, agent.build_result(dict(inp), sample=True), tmp_path)
    with open(first, "rb"):  # 뷰어가 PDF를 연 상태와 같다
        second = agent.write_outputs(inp, agent.build_result(dict(inp), sample=True), tmp_path)
    assert second != first and second.exists()


def test_brand_origin_differs_from_purchase_country_needs_check(tmp_path):
    """일본 판매처에서 버번(메이커스마크)을 사면 원산지(미국)와 구매국이 달라 경유 구매로 판정한다."""
    code = agent.main(["--name", "메이커스마크 750ml", "--price", "4000", "--country", "JP", "--volume", "750",
                       "--certificate", "예", "--made-in-origin", "예", "--yes", "--sample", "--out", str(tmp_path)])
    assert code == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert r["input"]["origin_country"] == "US" and r["fta"]["verdict"] == "확인 필요"
    assert "경유" in r["fta"]["reason"]


def test_name_and_price_only_run(tmp_path):
    """제품명·가격·구매 국가만 주면 나머지 단계가 진행된다."""
    code = agent.main(["--name", "산토리 야마자키 12년 위스키 700ml", "--price", "22,500", "--country", "일본",
                       "--yes", "--sample", "--out", str(tmp_path)])
    assert code == 0
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["input"]["info_confirmed"] is False  # --yes면 미확인 제안값으로 표시
    assert agent.won(Decimal(result["costs"]["협정세율"]["landed_cost"])) == 457530


def test_beer_specific_tax_report_and_volume_required(tmp_path, capsys):
    """2차: 맥주는 종량세로 계산한다. 용량이 없으면 안내하고 멈춘다."""
    code = agent.main(["--name", "아사히 맥주 500ml", "--price", "300", "--country", "JP", "--yes",
                       "--sample", "--out", str(tmp_path)])
    assert code == 0
    r = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    c = r["costs"]["협정세율"]
    assert r["input"]["hs_code"] == "2203000000" and Decimal(r["rates"]["협정세율"]) == Decimal("0.225")
    assert Decimal(c["liquor_tax"]) == Decimal("442.85")  # 0.5L x 885.7원
    assert Decimal(c["edu_tax"]) == Decimal("442.85") * Decimal("0.3")
    doc = next(tmp_path.glob("report_beer_*.html")).read_text(encoding="utf-8")
    assert "종량세" in doc and "리터당 885.7원" in doc
    assert agent.main(["--name", "아사히 맥주", "--price", "300", "--country", "JP", "--yes",
                       "--sample", "--out", str(tmp_path)]) == 2
    assert "용량" in capsys.readouterr().err


def test_skill_report_titles_and_banned_words(tmp_path):
    """스킬 규칙: 제목은 40자 이내·명사 종결, 금지어 0건, 모든 숫자에 출처 줄."""
    import re
    import report_html
    r = agent.build_result(load_candidate(), sample=True)
    doc = report_html.build_html(r)
    titles = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<h[12]>(.*?)</h[12]>", doc)]
    assert len(titles) >= 6
    for t in titles:
        assert len(t) <= 40, t
        assert not t.endswith("다"), t
    ok, text = report_html.run_korean_check(doc, tmp_path)
    assert ok, text
    assert doc.count("출처:") >= 5  # 그림·표마다 출처 줄


def test_skill_report_particles():
    import report_html
    assert report_html.eun("야마자키 12년") == "야마자키 12년은"
    assert report_html.eun("하쿠슈 12") == "하쿠슈 12는" or report_html.eun("하쿠슈 12") == "하쿠슈 12은"
    assert report_html.short_name("산토리 싱글몰트 위스키 야마자키 12년 700ml (JAN 4901777188914)").endswith("12년")


def test_write_outputs_makes_pdf_html_facts(tmp_path):
    code = agent.main(["--input", str(CANDIDATE), "--sample", "--out", str(tmp_path)])
    assert code == 0
    for f in ("report_yamazaki12.html", "report_yamazaki12.pdf", "facts.csv"):
        assert (tmp_path / f).exists(), f
    assert (tmp_path / "report_yamazaki12.pdf").stat().st_size > 5000


def test_pdf_falls_back_to_reportlab_without_browser(tmp_path, monkeypatch):
    """Edge·Chrome이 없는 PC에서도 PDF가 만들어진다(기본 PDF로 대체)."""
    import report_html
    monkeypatch.setattr(report_html, "find_browser", lambda: None)
    code = agent.main(["--input", str(CANDIDATE), "--sample", "--out", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "report_yamazaki12.pdf").stat().st_size > 5000
    assert (tmp_path / "report_yamazaki12.html").exists()


def test_price_position_for_candidate():
    """입력가를 달러/kg로 환산해 시장 평균 수입단가와 견준다(야마자키는 평균보다 훨씬 높음)."""
    r = agent.build_result(load_candidate(), sample=True)
    p = r["position"]
    assert p is not None
    # 과세가격 189,623원 / USD 1,330.52 / (0.7L x (1 - 0.0013x43))kg
    assert abs(p["cand_usd"] - 142.52) < 0.1
    assert 210 < p["unit"] < 222
    assert p["ratio"] > 10 and p["months_below"] == p["months_total"]


def test_price_position_skipped_without_volume():
    inp = load_candidate()
    inp["volume_ml"] = None
    assert agent.build_result(inp, sample=True)["position"] is None


def test_trade_no_data_message():
    series, msg = trade.get_trend("0000000000", "JP", "202609", sample=True)
    assert series is None and "자료 없음" in msg

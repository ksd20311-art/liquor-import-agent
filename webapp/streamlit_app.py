"""웹앱: 설치 없이 브라우저에서 리포트를 만든다(Streamlit).

  로컬 실행: run_webapp.bat 더블클릭  또는  streamlit run webapp/streamlit_app.py
  배포: docs/DEPLOY_WEBAPP.md (API 키는 서버의 Secrets에만 두고 화면·저장소에는 넣지 않는다)

화면 구성: 왼쪽 사이드바에 후보 입력을 고정하고, 오른쪽에 「리포트 만들기 / 월간 변동 알림 / 사용 안내」 탭을 둔다.
계산은 입력 창과 같은 코드(src/)를 쓴다. 실시간 조회에 실패하면 저장된 자료로 대신하지 않고 원인을 안내한다.
리포트는 화면에 전체를 펼쳐 보여 주고, 원하면 PDF로 받아 간다(서버의 Edge·Chrome·Chromium으로 인쇄, 없으면 기본 형식 PDF).
"""
import csv
import html
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 서버에 등록한 키(Secrets)를 환경 변수로 넘긴다. 로컬에서는 api_keys.env/.env를 그대로 쓴다.
try:
    for _k in ("DATA_GO_KR_KEY", "DATA_GO_KR_KEY_FX", "DATA_GO_KR_KEY_TRADE"):
        if _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # secrets 파일이 없는 로컬 실행
    pass

import fx  # noqa: E402
import intake  # noqa: E402
import main as agent  # noqa: E402
import report_html  # noqa: E402
import watch  # noqa: E402

MAX_RUNS = 40  # 한 접속에서 만들 수 있는 리포트 수(공공 API 호출 한도 보호)
COUNTRIES = ["일본 (JP)", "프랑스 (FR)", "미국 (US)", "영국 (GB)", "칠레 (CL)", "이탈리아 (IT)", "스페인 (ES)", "독일 (DE)",
             "아일랜드 (IE)", "호주 (AU)", "캐나다 (CA)", "뉴질랜드 (NZ)", "중국 (CN)", "멕시코 (MX)", "네덜란드 (NL)",
             "벨기에 (BE)", "체코 (CZ)", "태국 (TH)", "베트남 (VN)"]
AUTO = "자동 인식"
e = html.escape
# 리포트와 같은 색(파란색 한 계열)과 모양(결론 띠, 숫자 카드, 가로줄 표)을 화면에도 쓴다
CSS = """<style>
.block-container { padding-top: 2.4rem; max-width: 1240px; }
[data-testid="stSidebar"] { background: #f3f6fa; border-right: 1px solid #c8c9cc; }
@media (min-width: 900px) { [data-testid="stSidebar"] { min-width: 340px; max-width: 340px; } }
.app-head { display: flex; align-items: center; gap: 10px; }
.app-head i { display: inline-block; width: 28px; height: 6px; background: #1e5e9e; }
.app-head b { font-size: 1.3rem; color: #231f20; }
.app-sub { color: #5f636a; font-size: .86rem; margin: .1rem 0 .7rem; }
.side-title { font-weight: 700; font-size: 1.02rem; color: #231f20; margin-bottom: .2rem; }
.side-note { font-size: .8rem; color: #5f636a; line-height: 1.5; }
.cand { font-size: 1.25rem; font-weight: 700; color: #231f20; margin: .2rem 0 0; }
.cand small { display: block; font-size: .82rem; font-weight: 400; color: #5f636a; }
.concl { background: #0f3d6b; color: #fff; padding: 11px 15px; margin: .5rem 0 .7rem; font-size: .95rem; line-height: 1.55; }
.concl small { display: block; color: #c9dcf0; letter-spacing: .04em; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin: 0 0 .9rem; }
.kpi { background: #f3f6fa; border-top: 2px solid #1e5e9e; padding: 10px 14px 9px; }
.kpi span { display: block; font-size: .8rem; color: #5f636a; }
.kpi b { display: block; font-size: 1.6rem; line-height: 1.25; color: #1e5e9e; font-variant-numeric: tabular-nums; }
.kpi small { color: #5f636a; font-size: .78rem; }
table.rt { width: 100%; border-collapse: collapse; font-size: .88rem; margin: .2rem 0 .4rem; }
table.rt th { text-align: left; border-bottom: 1.5px solid #231f20; padding: 6px 8px; }
table.rt td { border-bottom: 1px solid #c8c9cc; padding: 6px 8px; }
table.rt .n { text-align: right; font-variant-numeric: tabular-nums; }
table.rt tr.hl td { background: #e6eef8; font-weight: 700; }
.src { font-size: .76rem; color: #5f636a; }
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: .6rem 0 1rem; }
.step { background: #f3f6fa; border-left: 3px solid #1e5e9e; padding: 10px 14px; font-size: .9rem; color: #231f20; }
.step b { display: block; color: #1e5e9e; }
</style>"""


def pdf_bytes(doc: str, name: str, result: dict = None):
    """리포트 HTML을 PDF로 바꿔 돌려준다: (PDF 내용, 방식). 화면과 같은 모양(html)이 기본이고,
    서버에 브라우저가 없으면 기본 형식(reportlab)으로 대신한다. 둘 다 안 되면 (None, None)."""
    tmp = Path(tempfile.mkdtemp(prefix="liquor_pdf_"))
    try:
        html_path, pdf = tmp / f"{name}.html", tmp / f"{name}.pdf"
        html_path.write_text(doc, encoding="utf-8")
        if report_html.html_to_pdf(html_path, pdf):
            return pdf.read_bytes(), "html"
        if result is not None:
            import report
            report.build_pdf(result, pdf)
            return pdf.read_bytes(), "reportlab"
    except Exception:  # PDF를 못 만들어도 화면 보기와 HTML 받기는 그대로 쓸 수 있게 한다
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return None, None


def show_report(doc: str, extra_px: int = 0):
    """리포트를 화면에 통째로 펼쳐 보여 준다(A4 한 쪽은 약 1,140px). 좁은 화면에서는 안에서 스크롤된다."""
    pages = doc.count('<section class="page')
    st.components.v1.html(doc, height=pages * 1140 + 40 + extra_px, scrolling=True)


def pdf_button(col, label: str, pdf, engine, file_name: str):
    if pdf:
        col.download_button(label, pdf, file_name=file_name, mime="application/pdf", type="primary", use_container_width=True)
    else:
        col.caption("이 서버에서는 PDF를 만들 수 없습니다. HTML을 받아 브라우저에서 열고 인쇄(Ctrl+P)하면 PDF로 저장됩니다.")
    if engine == "reportlab":
        st.caption("이 서버에는 인쇄용 브라우저가 없어 PDF가 기본 형식으로 만들어졌습니다. 화면과 같은 모양은 HTML로 받을 수 있습니다.")


def html_table(head, rows, hl=None, num_from=1) -> str:
    """리포트와 같은 가로줄 표."""
    h = "".join(f'<th class="{"n" if i >= num_from else ""}">{e(str(c))}</th>' for i, c in enumerate(head))
    b = "".join(f'<tr class="{"hl" if hl == ri else ""}">' + "".join(
        f'<td class="{"n" if i >= num_from else ""}">{e(str(c))}</td>' for i, c in enumerate(row)) + "</tr>" for ri, row in enumerate(rows))
    return f'<table class="rt"><tr>{h}</tr>{b}</table>'


def code_of(label: str) -> str:
    return label[label.rfind("(") + 1:label.rfind(")")] if "(" in label else label


def pack(inp: dict, result: dict, doc: str, pdf, engine, sample: bool) -> dict:
    """화면에 쓸 값만 접속 상태에 담는다(리포트와 같은 숫자)."""
    w = report_html.w
    names = list(result["costs"])
    keys = [("과세가격", "taxable_value"), ("관세", "customs"), ("주세", "liquor_tax"), ("교육세", "edu_tax"), ("부가세", "vat"),
            ("통관·국내운송(가정)", "clearance_domestic"), ("도착 원가", "landed_cost"), ("예상 소비자가", "expected_retail")]
    concl = re.search(r'<p class="concl"><b>결론</b>(.*?)</p>', doc, re.S)
    trend = result["trend"]
    return {
        "inp": inp, "doc": doc, "pdf": pdf, "pdf_engine": engine, "sample": sample,
        "lines": agent.summary_lines(result), "facts": report_html.facts_rows(result),
        "result": json.dumps(agent.serialize({k: v for k, v in result.items() if k not in ("rule", "fta")}
                                             | {"fta": result["fta"].__dict__}), ensure_ascii=False, indent=2),
        "costs": {n: (agent.won(c["landed_cost"]), agent.won(c["expected_retail"])) for n, c in result["costs"].items()},
        "rates": {n: float(result["rates"][n]) * 100 for n in names},
        "verdict": result["fta"].verdict, "reason": result["fta"].reason,
        "concl": html.unescape(concl.group(1)) if concl else "",
        "cost_head": ["구분(원)"] + [f"{n} {float(result['rates'][n]) * 100:g}%" for n in names],
        "cost_rows": [[lab] + [w(result["costs"][n][k]) for n in names] for lab, k in keys],
        "trend": ({"months": [f"{x['ym'][:4]}.{x['ym'][4:]}" for x in trend["table"]], "usd": [x["usd"] or 0 for x in trend["table"]],
                   "rows": [[f"{x['ym'][:4]}.{x['ym'][4:]}", f"{x['usd']:,}" if x["usd"] is not None else "자료 없음",
                             f"{x['kg']:,}" if x["kg"] is not None else "-", f"{x['unit_usd_per_kg']:.2f}" if x["unit_usd_per_kg"] else "-",
                             f"{x['yoy_pct']:+.1f}%" if x["yoy_pct"] is not None else "-"] for x in trend["table"]]} if trend else None),
        "trend_msg": result["trend_msg"], "as_of": result["as_of"],
        "fx": f"{inp['currency']} 1단위 {result['fx']['rate']}원 · 적용 주간 {result['fx']['week_start']}~{result['fx']['week_end']}",
    }


st.set_page_config(page_title="수입 주류 원가·시장 리포트 에이전트", page_icon="🧾", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
live = fx.has_api_key()
if "watch_path" not in st.session_state:  # 접속마다 따로 쓰는 알림 목록(서버에 남기지 않는다)
    st.session_state.watch_path = str(Path(tempfile.mkdtemp(prefix="liquor_watch_")) / "watchlist.json")
    st.session_state.runs = 0
WATCH_PATH = Path(st.session_state.watch_path)

# ---- 왼쪽: 후보 입력(항상 보임) ------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="side-title">후보 입력</div><div class="side-note">필수는 제품명, 현지 가격, 구매 국가입니다. 나머지는 비워 두면 자동으로 정합니다.</div>',
                unsafe_allow_html=True)
    with st.form("candidate"):
        name = st.text_input("제품명 (필수)", placeholder="예: Asahi Super Dry 350ml")
        price = st.text_input("현지 가격 (필수)", placeholder="예: 220 (현지 통화로 1병 가격)")
        kind = st.radio("가격 종류", list(intake.PRICE_KINDS.values()), horizontal=True)
        country_label = st.selectbox("구매 국가 (필수)", COUNTRIES)
        c1, c2 = st.columns(2)
        volume = c1.text_input("용량(ml)", placeholder="예: 350")
        margin = c2.text_input("마진율(%)", placeholder="비우면 30%")
        st.caption("맥주·탁주는 용량이 꼭 필요합니다. 제품명에 용량이 있으면 비워도 됩니다.")
        with st.expander("선택 입력 (주종, 품목 코드, FTA 질문)"):
            type_label = st.selectbox("주종", [AUTO] + list(intake.TYPE_NAMES.values()))
            hs_label = st.selectbox("품목 코드(HS)", [AUTO] + [intake.hs_label(c) for c, _, _ in intake.HS_CHOICES])
            hs_text = st.text_input("품목 코드 직접 입력(10자리)", placeholder="예: 2208309000", help="넣으면 위 목록보다 먼저 씁니다")
            made = st.selectbox("FTA 질문 1: 원산지 국가에서 생산된 제품인가", ["모름", "예", "아니오"])
            cert = st.selectbox("FTA 질문 2: 거래처가 원산지증명서를 발급할 수 있나", ["모름", "예", "아니오"])
        with st.expander("세부 설정 (비워 두면 자동)"):
            country_text = st.text_input("구매 국가 직접 입력", placeholder="예: Portugal, PT", help="목록에 없는 국가일 때. 넣으면 위 목록보다 먼저 씁니다")
            domestic = st.text_input("국내 판매가(원)", help="넣으면 국내가 비교(4장)와 가격 판단 결론이 추가됩니다")
            origin = st.text_input("원산지 국가", placeholder="구매 국가와 다를 때만(예: GB)")
            currency = st.text_input("통화", placeholder="예: MXN (보통 자동)")
            abv = st.text_input("도수(%)")
            url = st.text_input("가격 출처 URL")
            fx_rate = st.text_input("과세환율 직접 입력(원/1통화)", help="실시간 환율 조회가 안 될 때만")
        go = st.form_submit_button("리포트 만들기", type="primary", use_container_width=True)
    side_status = st.empty()  # 등록·알림 건수는 아래 탭에서 바뀔 수 있어 화면 맨 끝에서 채운다

# ---- 오른쪽: 머리말과 탭 ---------------------------------------------------------
st.markdown('<div class="app-head"><i></i><b>수입 주류 원가·시장 리포트 에이전트</b></div>'
            '<div class="app-sub">관세사·포워더 견적을 받기 전에, 여러 후보 가운데 견적을 받아 볼 만한 후보를 거르는 1차 검토 도구입니다. '
            "결과는 참고 원가이며 운임·보험료·통관비는 포함하지 않습니다(리포트의 보정표 참고).</div>", unsafe_allow_html=True)
if not live:
    st.warning("API 키가 없어 저장된 실제 API 응답(샘플 모드)으로 계산합니다. 저장된 품목·국가만 시장 추이가 나옵니다.")

form_error = None
if go:
    if st.session_state.runs >= MAX_RUNS:
        form_error = f"이번 접속에서 만들 수 있는 리포트 수({MAX_RUNS}건)를 넘었습니다. 새로 고침한 뒤 다시 시도해 주세요."
    else:
        form = {"name": name, "price": price, "country": country_text.strip() or code_of(country_label), "currency": currency,
                "type": next((k for k, v in intake.TYPE_NAMES.items() if v == type_label), ""),
                "hs": hs_text.strip() or ("" if hs_label == AUTO else hs_label),
                "origin": origin, "volume": volume, "abv": abv, "made": made, "cert": cert, "domestic": domestic,
                "url": url, "fx": fx_rate, "margin": margin, "kind": next(k for k, v in intake.PRICE_KINDS.items() if v == kind)}
        try:
            with st.spinner("과세환율과 무역통계를 조회하고 리포트를 만드는 중입니다..."):
                inp = intake.build_from_form(form)
                result = agent.build_result(inp, sample=not live)
                doc = report_html.build_html(result)
                pdf, engine = pdf_bytes(doc, inp["report_name"], result)
            st.session_state.runs += 1
            st.session_state.last = pack(inp, result, doc, pdf, engine, not live)
        except (ValueError, agent.AgentError) as ex:
            form_error = f"입력 확인: {ex}"
        except RuntimeError as ex:
            form_error = f"중단: {ex}"

tab_report, tab_watch, tab_help = st.tabs(["리포트 만들기", "월간 변동 알림", "사용 안내"])

with tab_report:
    if form_error:
        st.error(form_error)
    last = st.session_state.get("last")
    if not last:
        st.markdown("""<div class="steps">
<div class="step"><b>1 후보 입력</b>왼쪽에 제품명, 현지 가격, 구매 국가를 넣습니다.</div>
<div class="step"><b>2 리포트 만들기</b>버튼을 누르면 환율과 수입 추이를 조회해 원가를 계산합니다.</div>
<div class="step"><b>3 보기와 받기</b>리포트가 이 자리에 펼쳐지고, PDF로 받을 수 있습니다.</div></div>""", unsafe_allow_html=True)
        st.markdown("입력 예시 (가격은 형식을 보여 주는 예시입니다)\n" + html_table(
            ["제품명", "현지 가격", "구매 국가", "비고"],
            [["Asahi Super Dry 350ml", "220", "일본", "맥주(종량세). 용량은 제품명에서 읽음"],
             ["Macallan 12 Scotch Whisky 70cl", "70", "영국", "위스키"],
             ["닷사이 23 준마이 다이긴조 720ml", "6000", "일본", "사케. 마진율 40"]], num_from=9), unsafe_allow_html=True)
        st.caption("화면이 좁아 왼쪽 입력 칸이 보이지 않으면 화면 왼쪽 위의 » 표시를 누르세요.")
    else:
        inp = last["inp"]
        h1, h2, h3 = st.columns([3.2, 1, 1.1])
        h1.markdown(f'<div class="cand">{e(inp["product_name"])}<small>{e(intake.TYPE_NAMES[inp["liquor_type"]])} · 품목 코드 {e(inp["hs_code"])} · '
                    f'원산지 {e(inp["origin_country"])} · 입력가 {inp["local_price"]:,.10g} {e(inp["currency"])}({e(intake.PRICE_KINDS[inp["price_kind"]])}) · '
                    f'{e(last["fx"])}</small></div>', unsafe_allow_html=True)
        pdf_button(h2, "리포트 PDF 받기", last.get("pdf"), last.get("pdf_engine"), f"{inp['report_name']}.pdf")
        if h3.button("월간 알림에 등록", use_container_width=True):
            try:
                item = watch.add(inp, last["sample"], path=WATCH_PATH)
                st.success(f"등록했습니다: [{item['id']}] {item['name']} · 기준 원가 {agent.won(item['baseline']['landed_main']):,}원. 「월간 변동 알림」 탭에서 확인합니다.")
            except (agent.AgentError, RuntimeError, ValueError) as ex:
                st.error(f"등록 실패: {ex}")
        if last["concl"]:
            st.markdown(f'<div class="concl"><small>결론</small>{e(last["concl"])}</div>', unsafe_allow_html=True)
        cards = "".join(f'<div class="kpi"><span>{e(n)} {last["rates"][n]:g}% 도착 원가</span><b>{landed:,}원</b><small>예상 소비자가 {retail:,}원</small></div>'
                        for n, (landed, retail) in last["costs"].items())
        cards += f'<div class="kpi"><span>FTA 판정</span><b>{e(last["verdict"])}</b><small>{e(last["reason"][:38])}</small></div>'
        st.markdown(f'<div class="kpis">{cards}</div>', unsafe_allow_html=True)

        v_report, v_cost, v_trend, v_files = st.tabs(["리포트", "원가 분해", "시장 추이", "요약과 파일"])
        with v_report:
            st.caption("리포트 전체를 바로 볼 수 있습니다. 파일로 필요하면 위의 [리포트 PDF 받기]를 누르세요.")
            show_report(last["doc"])
        with v_cost:
            st.markdown(html_table(last["cost_head"], last["cost_rows"], hl=len(last["cost_rows"]) - 2)
                        + '<div class="src">출처: 본 에이전트 계산(관세청 관세환율정보, 품목번호별 관세율표 2026, 주세법 제8조, 교육세법 제5조). '
                          "운임·보험료·통관비는 가정값(0원)이며 리포트 요약 쪽 보정표로 반영합니다.</div>", unsafe_allow_html=True)
        with v_trend:
            if last["trend"]:
                st.bar_chart({"월": last["trend"]["months"], "수입액(달러)": last["trend"]["usd"]}, x="월", y="수입액(달러)", color="#6f9fd0", height=260)
                st.markdown(html_table(["월", "수입액(달러)", "중량(kg)", "단가(달러/kg)", "전년 동월 대비"], last["trend"]["rows"])
                            + f'<div class="src">출처: 관세청 품목별 국가별 수출입실적(공공데이터포털 15100475), 조회 {e(last["as_of"])}</div>',
                            unsafe_allow_html=True)
            else:
                st.info(last["trend_msg"])
        with v_files:
            for ln in last["lines"]:
                st.write("- " + ln)
            b1, b2, b3 = st.columns(3)
            b1.download_button("리포트 HTML 받기", last["doc"], file_name=f"{inp['report_name']}.html", mime="text/html", use_container_width=True)
            buf = io.StringIO()
            csv.writer(buf).writerows([["항목", "값", "출처", "기준일"]] + last["facts"])
            b2.download_button("근거표(facts.csv) 받기", ("﻿" + buf.getvalue()).encode("utf-8"), file_name="facts.csv", mime="text/csv",
                               use_container_width=True)
            b3.download_button("계산 결과(result.json) 받기", last["result"], file_name="result.json", mime="application/json", use_container_width=True)

with tab_watch:
    st.write("등록한 후보의 도착 원가가 **등록 시점보다 ±5% 이상** 움직이면, 환율·세율·현지가 효과로 나눠 알려 줍니다. "
             "현지가는 자동으로 모으지 않으니 바뀐 값은 직접 넣어 주세요.")
    data = watch.load(WATCH_PATH)
    if not data["items"]:
        st.info("등록한 후보가 없습니다. 「리포트 만들기」에서 리포트를 만든 뒤 [월간 알림에 등록]을 눌러 주세요.")
    else:
        new_prices = {}
        for x in data["items"]:
            b = x["baseline"]
            c1, c2, c3, c4 = st.columns([3, 2.4, 1.4, 0.8])
            c1.markdown(f'**[{x["id"]}] {x["name"]}**')
            c2.markdown(f'<span class="side-note">등록 {x["registered_at"]} · 기준 원가 {agent.won(b["landed_main"]):,}원 · '
                        f'현지가 {x["input"]["local_price"]:,.10g} {b["currency"]}</span>', unsafe_allow_html=True)
            new_prices[x["id"]] = c3.text_input("새 현지가", key=f"np_{x['id']}", placeholder="새 현지가(비우면 그대로)", label_visibility="collapsed")
            if c4.button("삭제", key=f"rm_{x['id']}", use_container_width=True):
                watch.remove(x["id"], path=WATCH_PATH)
                st.rerun()
        c1, c2, c3 = st.columns([1, 2, 1.4])
        th = c1.number_input("알림 기준(±%)", min_value=0.5, max_value=50.0, value=float(data.get("threshold_pct", 5.0)), step=0.5)
        c2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if c2.button("변동 확인하고 알림 리포트 만들기", type="primary", use_container_width=True):
            try:
                with st.spinner("등록 후보를 다시 계산하는 중입니다..."):
                    for wid, val in new_prices.items():
                        if val.strip():
                            watch.update_price(wid, val.strip(), path=WATCH_PATH)
                    results = watch.check(sample=not live, threshold=th, path=WATCH_PATH)
                    day = next((r["record"]["checked_at"] for r in results if "record" in r), date.today().isoformat())
                    alert_doc = watch.build_alert_html(results, day)
                    alert_pdf, alert_engine = pdf_bytes(alert_doc, f"alert_{day.replace('-', '')}")
                    rows = [[r["item"]["id"], r["item"]["name"][:30], f"{agent.won(r['item']['baseline']['landed_main']):,}",
                             f"{agent.won(r['record']['snapshot']['landed_main']):,}", f"{r['record']['vs_baseline']['pct']:+.1f}%",
                             "알림" if r["record"]["alert"] else "기준 이내"] for r in results if "record" in r]
                    st.session_state.alert = {"doc": alert_doc, "pdf": alert_pdf, "pdf_engine": alert_engine, "rows": rows,
                                              "lines": watch.console_lines(results), "day": day, "items": len(results),
                                              "n_alert": sum(1 for r in results if "record" in r and r["record"]["alert"])}
            except (agent.AgentError, RuntimeError, ValueError) as ex:
                st.error(f"중단: {ex}")
    with st.expander("목록 저장과 불러오기 (웹에서는 접속이 끝나면 목록이 지워집니다)"):
        st.download_button("목록 파일 받기(watchlist.json)", WATCH_PATH.read_text(encoding="utf-8") if WATCH_PATH.exists() else "{}",
                           file_name="watchlist.json", mime="application/json")
        up = st.file_uploader("저장해 둔 목록 파일(watchlist.json) 올리기", type="json")
        if up is not None and st.session_state.get("uploaded_name") != up.name + str(up.size):
            try:
                loaded = json.loads(up.getvalue().decode("utf-8-sig"))
                assert isinstance(loaded.get("items"), list)
                watch.save(loaded, WATCH_PATH)
                st.session_state.uploaded_name = up.name + str(up.size)
                st.rerun()
            except Exception:
                st.error("목록 파일을 읽지 못했습니다. 이 화면에서 받은 watchlist.json인지 확인해 주세요.")
    alert = st.session_state.get("alert")
    if alert:
        a0, a1, a2 = st.columns([3.2, 1, 1.1])
        a0.markdown(f'<div class="cand">알림 결과 ({e(alert["day"])})<small>등록 후보 {alert["items"]}건 중 {alert["n_alert"]}건이 기준을 넘었습니다.</small></div>',
                    unsafe_allow_html=True)
        pdf_button(a1, "알림 리포트 PDF 받기", alert.get("pdf"), alert.get("pdf_engine"), f"alert_{alert['day'].replace('-', '')}.pdf")
        a2.download_button("알림 리포트 HTML 받기", alert["doc"], file_name=f"alert_{alert['day'].replace('-', '')}.html", mime="text/html",
                           use_container_width=True)
        st.markdown(html_table(["번호", "후보", "등록 시 원가(원)", "현재 원가(원)", "변동률", "판정"], alert["rows"], num_from=2), unsafe_allow_html=True)
        st.text("\n".join(alert["lines"]))
        st.caption("아래에서 알림 리포트 전체를 바로 볼 수 있습니다.")
        show_report(alert["doc"], extra_px=max(0, alert.get("items", 1) - 3) * 300)  # 후보가 많으면 원인 분해 쪽이 길어진다

with tab_help:
    st.markdown(f"""
**필수 입력은 3칸입니다**: 제품명, 현지 가격(현지 통화 1병 가격), 구매 국가. 왼쪽 「후보 입력」에 넣고 [리포트 만들기]를 누릅니다.

| 칸 | 설명 |
|---|---|
| 제품명 | 주종 단어(위스키·와인·맥주 등)나 브랜드, 용량(700ml·70cl)을 넣으면 자동 인식이 정확해집니다 |
| 가격 종류 | 소매가 / 도매·견적가. 리포트에 표기됩니다(계산식은 같습니다) |
| 용량 | 맥주·탁주는 용량에 세금이 붙는 종량세라 꼭 필요합니다 |
| 마진율 | 예상 소비자가 = 도착 원가 × (1 + 마진율). 비우면 30% 가정 |
| 주종·품목 코드 | 「선택 입력」에 있습니다. 비우면 자동 인식. 지원 주종: {intake.SUPPORTED_TEXT} |
| FTA 질문 | 「선택 입력」에 있습니다. 둘 다 「예」(구매국 = 원산지)면 협정세율, 하나라도 「아니오」면 일반세율, 「모름」이면 두 원가를 함께 표시 |
| 국내 판매가 | 「세부 설정」에 있습니다. 넣으면 국내가 비교(4장)가 추가됩니다 |

- 리포트는 만든 자리에서 화면에 전체가 펼쳐집니다. 파일이 필요하면 [리포트 PDF 받기]로 화면과 같은 모양의 PDF를 받습니다(HTML, 근거표, 계산 결과는 「요약과 파일」에 있습니다).
- 후보를 [월간 알림에 등록]해 두면 「월간 변동 알림」 탭에서 등록 시점 대비 원가 변동과 원인을 확인합니다.
- 과세환율과 수입 추이는 관세청 공공 API로 실시간 조회합니다. 조회에 실패하면 저장된 자료로 대신하지 않고 원인(호출 한도 소진, 인터넷 문제)을 안내합니다.
- 세액과 FTA 판정은 참고용이며 실제 적용은 통관 때 관세사를 통해 확정됩니다.
- 화면이 좁아 왼쪽 입력 칸이 보이지 않으면 화면 왼쪽 위의 » 표시를 누르세요.
""")

# 사이드바 아래 상태 줄: 등록·확인 직후에도 바로 맞는 숫자가 보이게 마지막에 채운다
_n = len(watch.load(WATCH_PATH)["items"]) if WATCH_PATH.exists() else 0
_alert = st.session_state.get("alert")
side_status.markdown(f'<div class="side-note">월간 알림 등록 후보 {_n}건' + (f" · 최근 확인에서 알림 {_alert['n_alert']}건" if _alert else "")
                     + ("<br>실시간 조회 상태입니다." if live else "") + "</div>", unsafe_allow_html=True)

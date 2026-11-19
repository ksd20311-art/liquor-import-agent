"""관세청 품목별 국가별 수출입실적(GW): 최근 12개월 수입액·중량·단가와 전년 동월 대비."""
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
TRADE_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"


def add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[4:6])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}{t % 12 + 1:02d}"


def parse_trade_xml(text: str) -> list:
    """월별 행만 반환(합계 행은 hsCd가 '-'라 제외). 오류 응답이면 빈 리스트."""
    root = ET.fromstring(text)
    if root.findtext(".//resultCode") not in (None, "00"):
        return []
    rows = []
    for it in root.iter("item"):
        ym = it.findtext("year") or ""
        if it.findtext("hsCd") in (None, "-") or not re.fullmatch(r"\d{4}\.\d{2}", ym):
            continue
        rows.append({"ym": ym.replace(".", ""), "usd": int(it.findtext("impDlr") or 0), "kg": int(it.findtext("impWgt") or 0)})
    return rows


def fetch_live(hs: str, country: str, end_ym: str, key: str, save: bool = False) -> list:
    """end_ym 포함 최근 24개월. 조회기간 1년 제한 때문에 2번 호출.
    save=True면 받은 응답(키 제거)을 data/samples에 저장해 키 없는 환경(샘플 모드)에서도 쓸 수 있게 한다."""
    rows = []
    for start, end in ((add_months(end_ym, -23), add_months(end_ym, -12)), (add_months(end_ym, -11), end_ym)):
        q = urllib.parse.urlencode({"serviceKey": key, "strtYymm": start, "endYymm": end, "hsSgn": hs, "cntyCd": country})
        with urllib.request.urlopen(f"{TRADE_URL}?{q}", timeout=60) as r:
            body = r.read().decode("utf-8")
        got = parse_trade_xml(body)
        rows += got
        if save and got:
            SAMPLES.mkdir(parents=True, exist_ok=True)
            (SAMPLES / f"trade_{country}_{hs}_{start}_{end}.xml").write_text(body.replace(key, "***"), encoding="utf-8")
    return rows


def load_samples(hs: str, country: str) -> list:
    rows = []
    for f in sorted(SAMPLES.glob(f"trade_{country}_{hs}_*.xml")):
        rows += parse_trade_xml(f.read_text(encoding="utf-8"))
    return rows


def build_series(rows: list) -> dict:
    """월별 표(최근 12개월)와 전년 대비 요약. 자료가 없으면 None."""
    by_month = {r["ym"]: r for r in rows}
    if not by_month:
        return None
    last = max(by_month)
    months = [add_months(last, -i) for i in range(11, -1, -1)]
    table = []
    for ym in months:
        cur = by_month.get(ym)
        prev = by_month.get(add_months(ym, -12))
        usd = cur["usd"] if cur else None
        kg = cur["kg"] if cur else None
        table.append({
            "ym": ym,
            "usd": usd,
            "kg": kg,
            "unit_usd_per_kg": (usd / kg) if cur and kg else None,
            "yoy_pct": ((usd / prev["usd"] - 1) * 100) if cur and prev and prev["usd"] else None,
        })
    cur12 = [by_month[m] for m in months if m in by_month]
    prev12 = [by_month[m] for m in (add_months(x, -12) for x in months) if m in by_month]
    summary = {
        "last_month": last,
        "usd_12m": sum(r["usd"] for r in cur12),
        "kg_12m": sum(r["kg"] for r in cur12),
        "usd_prev_12m": sum(r["usd"] for r in prev12) if len(prev12) == 12 else None,
        "months_available": len(cur12),
    }
    s = summary
    s["unit_12m"] = (s["usd_12m"] / s["kg_12m"]) if s["kg_12m"] else None
    s["yoy_12m_pct"] = ((s["usd_12m"] / s["usd_prev_12m"] - 1) * 100) if s["usd_prev_12m"] else None
    return {"table": table, "summary": summary}


def get_trend(hs: str, country: str, end_ym: str, sample: bool, key: str = None, save: bool = False):
    """반환: (series 또는 None, 메시지). 실패해도 예외 대신 「자료 없음」 안내."""
    if not sample and not key:
        return None, "API 키가 없어 시장 추이를 조회하지 못했습니다(api_keys.env 설정 또는 --sample 모드 사용)."
    try:
        rows = load_samples(hs, country) if sample else fetch_live(hs, country, end_ym, key or "", save)
    except Exception as e:  # 실시간 조회 실패: 저장된 자료로 몰래 대신하지 않고 원인을 알린다
        return None, (f"무역통계 API 조회에 실패했습니다({type(e).__name__}). 호출 한도 소진이나 인터넷 연결 문제일 수 있으니 "
                      "잠시 후 다시 시도해 주세요. 이 리포트에서는 시장 추이를 비워 둡니다.")
    series = build_series(rows)
    if not series:
        return None, "무역통계 자료 없음(0건). HS 코드부터 확인하세요."
    return series, ""

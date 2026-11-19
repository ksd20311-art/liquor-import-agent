"""관세청 과세환율(수입) 조회. 실시간 모드는 API만 쓰고 실패하면 원인을 알리고 멈춘다(저장본으로 대체하지 않음).
저장본/CSV는 샘플 모드(--sample, 키 없는 PC)에서만 쓴다."""
import csv
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
FX_URL = "https://apis.data.go.kr/1220000/retrieveTrifFxrtInfo/getRetrieveTrifFxrtInfo"


def load_env(path: Path = None) -> dict:
    """키 설정을 읽는다: `.env`와 눈에 보이는 이름의 `api_keys.env`(점 파일은 드라이브 업로드에서 빠질 수 있음), 환경 변수 순."""
    env = {}
    paths = [path] if path is not None else [ROOT / ".env", ROOT / "api_keys.env"]
    for p in paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip():  # 빈 값이 다른 파일의 값을 지우지 않게 한다
                        env[k.strip()] = v.strip()
    for k in ("DATA_GO_KR_KEY", "DATA_GO_KR_KEY_TRADE", "DATA_GO_KR_KEY_FX", "LLM_API_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def has_api_key(env: dict = None) -> bool:
    """실시간 조회에 필요한 키가 있는지(공용 키 하나 또는 환율·무역통계 키 둘 다)."""
    env = env if env is not None else load_env()
    return bool(env.get("DATA_GO_KR_KEY") or (env.get("DATA_GO_KR_KEY_FX") and env.get("DATA_GO_KR_KEY_TRADE")))


API_REASONS = {
    "30": "등록되지 않은 서비스키입니다. 키 값이 잘못 들어갔거나(따옴표·공백 포함 여부), 이 API의 활용 신청이 승인되지 않았는지 확인해 주세요",
    "22": "오늘 호출 한도를 다 썼습니다. 내일 다시 시도해 주세요",
    "29": "호출한 서버의 IP가 차단되었습니다. 공공데이터포털 활용지원센터에 문의가 필요합니다",
    "31": "활용 기간이 끝난 서비스키입니다. 공공데이터포털에서 연장 신청이 필요합니다",
    "32": "등록되지 않은 IP에서 호출했습니다. 공공데이터포털 마이페이지의 IP 설정을 확인해 주세요",
}


def api_error_reason(e: Exception, key: str = "") -> str:
    """API 호출 오류를 사람이 읽을 원인으로 바꾼다. 공공데이터포털은 키 오류도 HTTP 403으로 돌려주므로 응답 본문을 읽어 구분한다."""
    base = f"{type(e).__name__}: {e}"[:80]
    body = ""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        code = msg = ""
        try:
            root = ET.fromstring(body)
            code = root.findtext(".//returnReasonCode") or ""
            msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or ""
        except ET.ParseError:
            pass
        if code or msg:
            base += f" / 응답 코드 {code} {msg}".rstrip() + (f" - {API_REASONS[code]}" if code in API_REASONS else "")
        elif e.code == 403:
            base += " / 응답에 오류 코드가 없음 - 해외 서버(예: 웹앱 서버)의 접속이 막혔을 수 있습니다"
    return base.replace(key, "***") if key else base


def week_start(d: date) -> date:
    """관세환율 적용 주간은 일요일~토요일."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def parse_fx_xml(text: str, currency: str):
    root = ET.fromstring(text)
    if root.findtext(".//resultCode") not in (None, "00"):
        return None
    for item in root.iter("item"):
        if item.findtext("currSgn") == currency:
            return Decimal(item.findtext("fxrt"))
    return None


def fetch_week(on: date, env: dict = None):
    """on이 속한 주간의 수입(과세) 환율 전체를 실시간으로 받는다(주 1회 자동 수집용). 반환: (주 시작일, {통화: 환율})."""
    env = env if env is not None else load_env()
    key = env.get("DATA_GO_KR_KEY_FX") or env.get("DATA_GO_KR_KEY")
    if not key:
        raise RuntimeError("과세환율을 수집하려면 API 키가 필요합니다(api_keys.env 또는 .env).")
    start = week_start(on)
    q = urllib.parse.urlencode({"serviceKey": key, "aplyBgnDt": f"{start:%Y%m%d}", "weekFxrtTpcd": "2"})
    try:
        with urllib.request.urlopen(f"{FX_URL}?{q}", timeout=30) as r:
            body = r.read().decode("utf-8")
    except Exception as e:
        why = api_error_reason(e, key)
        raise RuntimeError(f"과세환율을 실시간으로 받지 못했습니다({why}). 호출 한도 소진이나 인터넷 연결 문제일 수 있으니 잠시 후 다시 시도해 주세요.")
    root = ET.fromstring(body)
    rates = {it.findtext("currSgn"): Decimal(it.findtext("fxrt")) for it in root.iter("item") if it.findtext("currSgn") and it.findtext("fxrt")}
    if not rates:
        raise RuntimeError(f"{start} 주간의 과세환율이 아직 고시되지 않았거나 응답이 비어 있습니다.")
    return start, rates


def _result(rate, start, source, warning=""):
    return {
        "rate": rate,
        "week_start": start.isoformat(),
        "week_end": (start + timedelta(days=6)).isoformat(),
        "source": source,
        "warning": warning,
    }


def _from_csv(currency: str, on: date):
    path = ROOT / "config" / "customs_fx.csv"
    rows = []
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["currency"] == currency]
    if not rows:
        return None
    rows.sort(key=lambda r: r["week_start"])
    for r in rows:
        if r["week_start"] <= on.isoformat() <= r["week_end"]:
            return _result(Decimal(r["krw_per_unit"]) / Decimal(r["unit"]), date.fromisoformat(r["week_start"]),
                           "config/customs_fx.csv(관세청 고시값을 사람이 입력)")
    r = rows[-1]
    return _result(Decimal(r["krw_per_unit"]) / Decimal(r["unit"]), date.fromisoformat(r["week_start"]),
                   "config/customs_fx.csv(관세청 고시값을 사람이 입력)",
                   f"해당 주간 고시값이 없어 가장 최근 고시값({r['week_start']} 주간)을 사용했습니다.")


def get_fx(currency: str, on: date, sample: bool = False, env: dict = None, save: bool = False) -> dict:
    """수입(과세) 과세환율. 반환: rate(원/통화 1단위), week_start, week_end, source, warning."""
    env = env if env is not None else load_env()
    start = week_start(on)

    if sample:
        f = SAMPLES / f"fx_import_{start:%Y%m%d}.xml"
        if f.exists():
            rate = parse_fx_xml(f.read_text(encoding="utf-8"), currency)
            if rate:
                return _result(rate, start, "관세청_관세환율정보 API 저장 응답(data/samples)")
        # 해당 주간 저장본이 없으면 저장된 가장 최근 주간 응답을 쓰고 경고한다(통화가 JPY가 아니어도 동작)
        for f in sorted(SAMPLES.glob("fx_import_*.xml"), reverse=True):
            rate = parse_fx_xml(f.read_text(encoding="utf-8"), currency)
            if rate:
                saved = date(int(f.stem[10:14]), int(f.stem[14:16]), int(f.stem[16:18]))
                return _result(rate, saved, "관세청_관세환율정보 API 저장 응답(data/samples)",
                               f"저장된 환율은 {saved} 주간 값이며 조회한 주간({start})과 다릅니다. 실시간 모드(API 키)에서 최신 값을 받을 수 있습니다.")
        csv_res = _from_csv(currency, on)
        if csv_res:
            return csv_res
        raise RuntimeError(f"{currency} 과세환율을 저장된 자료에서 찾지 못했습니다. 통화 코드를 확인하거나(예: JPY, USD, EUR) "
                           "환율을 직접 입력해 주세요(--fx-rate 또는 입력 창 세부 설정).")

    key = env.get("DATA_GO_KR_KEY_FX") or env.get("DATA_GO_KR_KEY")
    problems = []
    if key:
        for back in range(3):  # 해당 주간 값이 아직 없으면 직전 주간까지 시도
            s = start - timedelta(days=7 * back)
            q = urllib.parse.urlencode({"serviceKey": key, "aplyBgnDt": f"{s:%Y%m%d}", "weekFxrtTpcd": "2"})
            body, last = None, ""
            for _ in range(2):  # 일시적 네트워크 오류는 한 번 더 시도
                try:
                    with urllib.request.urlopen(f"{FX_URL}?{q}", timeout=30) as r:
                        body = r.read().decode("utf-8")
                    break
                except Exception as e:  # 네트워크·인증 오류(키는 메시지에서 가린다)
                    last = api_error_reason(e, key)
                    if isinstance(e, urllib.error.HTTPError):
                        break  # 키·권한 오류는 다시 불러도 같다
                    time.sleep(1)
            if body is None:
                problems.append(f"API 호출 실패({last})")
                break
            rate = parse_fx_xml(body, currency)
            if rate and save:  # 키 없는 환경(샘플 모드)에서 쓸 저장본(키 제거)
                SAMPLES.mkdir(parents=True, exist_ok=True)
                (SAMPLES / f"fx_import_{s:%Y%m%d}.xml").write_text(body.replace(key, "***"), encoding="utf-8")
            if rate:
                warn = "" if back == 0 else f"해당 주간 고시값이 없어 직전 {back}주 전 값을 사용했습니다."
                return _result(rate, s, "관세청_관세환율정보 API(실시간 호출)", warn)
            problems.append(f"{s:%Y-%m-%d} 주간 응답에 {currency} 환율이 없음")
    else:
        problems.append("API 키 없음")

    why = "; ".join(problems)
    # 실시간 조회에 실패했을 때 저장된 자료로 몰래 대신하지 않는다: 원인을 알리고 멈춘다.
    raise RuntimeError(
        f"{currency} 과세환율을 실시간으로 받지 못했습니다({why}). "
        "호출 한도 소진이나 인터넷 연결 문제일 수 있으니 잠시 후 다시 시도해 주세요. "
        "환율을 알고 있으면 직접 입력할 수도 있습니다(--fx-rate 또는 입력 창 세부 설정).")
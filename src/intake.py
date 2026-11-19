"""제품명·현지 가격·구매 국가만으로 후보 입력을 만든다 (워크플로 1~3단계).

2단계 「제품 정보 제안」은 1차에서 규칙 기반이다(키워드로 주종·HS 코드 제안, 이름에서 용량·도수 추출).
제안값은 사용자가 확인·수정하며, --yes로 확인을 건너뛰면 리포트에 「미확인 자동 제안」으로 표시된다.
"""
import re
from datetime import date

COUNTRY_ALIASES = {
    "일본": "JP", "프랑스": "FR", "미국": "US", "칠레": "CL", "이탈리아": "IT", "스페인": "ES",
    "독일": "DE", "영국": "GB", "스코틀랜드": "GB", "호주": "AU", "중국": "CN", "대만": "TW",
    "아일랜드": "IE", "캐나다": "CA", "뉴질랜드": "NZ", "인도": "IN", "튀르키예": "TR", "터키": "TR",
    "베트남": "VN", "네덜란드": "NL", "포르투갈": "PT", "오스트리아": "AT", "벨기에": "BE",
    "멕시코": "MX", "체코": "CZ", "태국": "TH", "필리핀": "PH", "싱가포르": "SG", "러시아": "RU", "스웨덴": "SE",
    "쿠바": "CU", "남아공": "ZA", "남아프리카공화국": "ZA", "아르헨티나": "AR", "브라질": "BR", "폴란드": "PL",
    "덴마크": "DK", "자메이카": "JM", "인도네시아": "ID", "말레이시아": "MY", "콜롬비아": "CO", "페루": "PE",
    "스위스": "CH", "노르웨이": "NO", "헝가리": "HU",
}
CURRENCY_BY_COUNTRY = {
    "JP": "JPY", "US": "USD", "GB": "GBP", "AU": "AUD", "CN": "CNY", "CL": "CLP", "TW": "TWD",
    "CA": "CAD", "NZ": "NZD", "IN": "INR", "TR": "TRY", "VN": "VND",
    # 아래는 관세청 과세환율 고시 통화에 있는 것만 넣었다(2026-11-15 주간 목록 확인)
    "MX": "MXN", "CZ": "CZK", "TH": "THB", "PH": "PHP", "SG": "SGD", "RU": "RUB", "SE": "SEK", "ZA": "ZAR", "AR": "ARS",
    "BR": "BRL", "PL": "PLN", "DK": "DKK", "ID": "IDR", "MY": "MYR", "CO": "COP", "CH": "CHF", "NO": "NOK", "HU": "HUF",
}
CURRENCY_BY_COUNTRY.update({c: "EUR" for c in "AT BE HR CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES".split()})
TYPE_NAMES = {"whisky": "위스키", "wine": "와인", "sake": "사케(청주)", "brandy": "브랜디", "rum": "럼", "gin": "진",
              "vodka": "보드카", "tequila": "데킬라", "beer": "맥주", "takju": "탁주(막걸리)"}
SPECIFIC_TYPES = ("beer", "takju")  # 종량세: 용량이 있어야 주세를 계산한다
# 앞에 있는 주종이 우선한다(예: 「럼 캐스크 위스키」는 위스키). 짧은 영어 단어(gin·rum·ale 등)는 단어 단위로만 찾는다.
TYPE_KEYWORDS = {
    "whisky": ["위스키", "whisky", "whiskey", "ウイスキー", "ウィスキー", "싱글몰트", "single malt", "bourbon", "버번", "스카치", "scotch"],
    "wine": ["와인", "wine", "ワイン", "샤또", "château", "chateau", "포도주", "vin ", "샴페인", "champagne", "스파클링", "sparkling",
             "prosecco", "프로세코", "cava"],
    "sake": ["사케", "청주", "日本酒", "sake", "준마이", "純米", "다이긴조", "大吟醸", "긴조", "吟醸"],
    "brandy": ["브랜디", "brandy", "코냑", "꼬냑", "cognac", "아르마냑", "armagnac", "ブランデー"],
    "vodka": ["보드카", "vodka", "ウォッカ"],
    "tequila": ["데킬라", "테킬라", "tequila", "テキーラ"],
    "rum": ["럼주", "rum", "ラム酒"],
    "gin": ["드라이 진", "드라이진", "gin", "ジン"],
    "beer": ["맥주", "beer", "ビール", "라거", "lager", "에일", "ale", "ipa", "stout", "스타우트", "필스너", "pilsner", "pils",
             "weissbier", "바이젠"],
    "takju": ["막걸리", "탁주", "makgeolli", "takju"],
}
UNSUPPORTED_HINTS = ["소주", "고량주", "백주", "바이주", "리큐르", "약주", "하이볼"]


def _eun(label: str) -> str:
    """조사 은/는을 붙인다(괄호 부분은 무시: 도수(%) -> 도수(%)는)."""
    base = re.sub(r"\(.*?\)\s*$", "", label).strip()
    ch = base[-1:] if base else ""
    batchim = "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
    return label + ("은" if batchim else "는")


def parse_price(text, label="가격") -> float:
    """「22,500」, 「22500엔」, 「29.99」를 숫자로 읽는다. 음수·0·형식 오류는 ValueError(한글 안내)."""
    raw = str(text).strip()
    if re.search(r"^[\s\D]*[-−]", raw):
        raise ValueError(f"{_eun(label)} 0보다 큰 숫자로 입력해 주세요: {raw}")
    s = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    if not s or s.count(".") > 1 or s == ".":
        raise ValueError(f"{label}에서 숫자를 읽지 못했습니다: 「{raw}」 (예: 22500, 22,500, 29.99)")
    v = float(s)
    if v <= 0:
        raise ValueError(f"{_eun(label)} 0보다 커야 합니다: {raw}")
    return v


def parse_number(text, label: str, max_value: float = None) -> float:
    """환율·도수처럼 단위 없는 양수를 읽는다."""
    raw = str(text).strip().replace(",", "")
    m = re.fullmatch(r"([-−]?\d+(?:\.\d+)?)\s*%?", raw)
    if not m:
        raise ValueError(f"{_eun(label)} 숫자로 입력해 주세요: 「{text}」")
    v = float(m.group(1).replace("−", "-"))
    if v <= 0 or (max_value is not None and v > max_value):
        raise ValueError(f"{label} 값이 올바르지 않습니다: {text}" + (f" (0 초과 {max_value:g} 이하)" if max_value else " (0보다 커야 함)"))
    return v


def parse_margin(text) -> float:
    """마진율(%)을 읽는다: 30, 30%, 0 모두 허용(0% 이상 300% 이하)."""
    raw = str(text).strip().replace(",", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%?", raw)
    if not m or float(m.group(1)) > 300:
        raise ValueError(f"마진율은 0~300 사이 숫자(%)로 입력해 주세요: 「{text}」")
    return float(m.group(1))


def parse_abv(text) -> float:
    return parse_number(text, "도수(%)", max_value=100)


def parse_volume(text) -> int:
    """용량을 ml로 읽는다: 700, 700ml, 70cl, 0.7L, 1L. 숫자만 10 미만이면 리터로 본다(예: 0.7 → 700ml)."""
    raw = str(text).strip()
    if re.fullmatch(r"[-−].*", raw):
        raise ValueError(f"용량은 0보다 커야 합니다: {raw}")
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        v = float(raw)
        ml = round(v * 1000) if v < 10 else round(v)
    else:
        ml = extract_volume_abv(raw)[0]
    if not ml or not (10 <= ml <= 5000):
        raise ValueError(f"용량을 읽지 못했습니다: 「{raw}」 (예: 700, 700ml, 70cl, 1L)")
    return ml


CURRENCY_ALIASES = {"YEN": "JPY", "엔": "JPY", "엔화": "JPY", "달러": "USD", "DOLLAR": "USD", "유로": "EUR", "EURO": "EUR",
                    "파운드": "GBP", "POUND": "GBP", "위안": "CNY", "RMB": "CNY"}


def normalize_currency(text: str) -> str:
    """통화 코드(3글자)로 바꾼다. YEN·엔·달러·유로 같은 이름도 받는다."""
    t = (text or "").strip()
    code = CURRENCY_ALIASES.get(t.upper()) or CURRENCY_ALIASES.get(t) or t.upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError(f"통화를 알 수 없습니다: 「{text}」 (3글자 통화 코드로 입력, 예: JPY, USD, EUR)")
    return code


def check_country(code: str, raw: str = "") -> str:
    if not re.fullmatch(r"[A-Z]{2}", code or ""):
        raise ValueError(f"국가를 알 수 없습니다: 「{raw or code}」 (목록의 국가명이나 2글자 국가 코드로 입력, 예: JP, US, MX)")
    return code


EN_COUNTRIES = {
    "japan": "JP", "france": "FR", "usa": "US", "united states": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "britain": "GB", "scotland": "GB", "england": "GB",
    "ireland": "IE", "italy": "IT", "spain": "ES", "germany": "DE", "chile": "CL", "australia": "AU", "canada": "CA",
    "new zealand": "NZ", "china": "CN", "india": "IN", "turkey": "TR", "turkiye": "TR", "vietnam": "VN",
    "viet nam": "VN", "netherlands": "NL", "portugal": "PT", "austria": "AT", "belgium": "BE", "taiwan": "TW",
    "south korea": "KR", "korea": "KR",
    "mexico": "MX", "czech republic": "CZ", "czechia": "CZ", "thailand": "TH", "philippines": "PH", "singapore": "SG",
    "russia": "RU", "sweden": "SE", "cuba": "CU", "south africa": "ZA", "argentina": "AR", "brazil": "BR", "poland": "PL",
    "denmark": "DK", "jamaica": "JM", "indonesia": "ID", "malaysia": "MY", "colombia": "CO", "peru": "PE",
    "switzerland": "CH", "norway": "NO", "hungary": "HU",
}


def normalize_country(text: str) -> str:
    """한글·영문 국가명이나 2글자 코드를 국가 코드로 바꾼다(예: 일본, Japan, jp -> JP)."""
    t = (text or "").strip()
    return COUNTRY_ALIASES.get(t) or EN_COUNTRIES.get(t.lower()) or t.upper()


def suggest_liquor_type(name: str):
    low = name.lower()
    words = set(re.findall(r"[a-z]+", low))
    for ltype, keys in TYPE_KEYWORDS.items():
        for k in keys:
            k = k.lower()
            # 영어 한 단어는 단어 단위로 찾는다(사케의 「ginjo」가 「gin」으로, 「pale」이 「ale」로 오인되지 않게)
            if (k in words) if re.fullmatch(r"[a-z]+", k) else (k in low):
                return ltype
    tokens = set(re.split(r"[\s,()]+", name))  # 한 글자 주종은 낱말일 때만(「진로」의 「진」은 제외)
    return "gin" if "진" in tokens else ("rum" if "럼" in tokens else None)


EN_UNSUPPORTED = ["soju", "baijiu", "liqueur", "highball", "cider", "mead"]
CASK_WORDS = ("cask", "finish", "barrel", "캐스크", "피니시", "배럴")


def unsupported_hint(name: str):
    low = name.lower()
    for w in UNSUPPORTED_HINTS:
        if not w.isascii() and w in low:
            return w.strip()
    # 영문 단어는 단어 경계로 찾는다(예: 사케의 「ginjo」가 「gin」으로 오인되지 않게)
    words = set(re.findall(r"[a-z]+", low))
    return next((w for w in EN_UNSUPPORTED if w in words), None)


# 지원 품목 코드(HS 10자리): 코드를 직접 고르거나 입력하면 주종이 정해진다
HS_CHOICES = [
    ("2208301000", "whisky", "위스키 - 스카치 위스키"),
    ("2208302000", "whisky", "위스키 - 버번 위스키"),
    ("2208303000", "whisky", "위스키 - 호밀(라이) 위스키"),
    ("2208309000", "whisky", "위스키 - 기타(일본·아일랜드·대만 등)"),
    ("2204211000", "wine", "와인 - 붉은 포도주(2L 이하)"),
    ("2204212000", "wine", "와인 - 흰 포도주(2L 이하)"),
    ("2204219000", "wine", "와인 - 기타 포도주(2L 이하)"),
    ("2204100000", "wine", "와인 - 스파클링(샴페인 등)"),
    ("2206002010", "sake", "사케 - 청주"),
    ("2208201000", "brandy", "브랜디 - 포도주 증류주(2208.20.1000)"),
    ("2208209000", "brandy", "브랜디 - 포도주 증류주 기타(2208.20.9000)"),
    ("2208400000", "rum", "럼"),
    ("2208500000", "gin", "진"),
    ("2208600000", "vodka", "보드카"),
    ("2208907000", "tequila", "데킬라"),
    ("2203000000", "beer", "맥주(종량세)"),
    ("2206002030", "takju", "탁주·막걸리(종량세)"),
]
HS_PATTERNS = [(r"220830\d{4}", "whisky"), (r"2204(10|21|22|29)\d{4}", "wine"), (r"220820\d{4}", "brandy"),
               (r"220840\d{4}", "rum"), (r"220850\d{4}", "gin"), (r"220860\d{4}", "vodka"), (r"2203\d{6}", "beer")]


def hs_label(code: str) -> str:
    return next((f"{c} {d}" for c, _, d in HS_CHOICES if c == code), code)


def type_from_hs(hs: str):
    """지원 품목 코드면 주종, 아니면 None. 목록에 없어도 같은 호(위스키 2208.30, 포도주 2204.10·21·22·29 등)는 인정한다."""
    exact = next((t for c, t, _ in HS_CHOICES if c == hs), None)
    if exact:
        return exact
    return next((t for pat, t in HS_PATTERNS if re.fullmatch(pat, hs or "")), None)


SUPPORTED_TEXT = "위스키·와인·사케·브랜디·럼·진·보드카·데킬라·맥주·탁주"
PRICE_KINDS = {"retail": "소매가", "quote": "도매·견적가"}


def parse_price_kind(text) -> str:
    """가격 종류: 소매가(retail) 또는 도매·견적가(quote). 비어 있으면 소매가."""
    t = str(text or "").strip().lower()
    if not t or t in ("retail", "소매", "소매가"):
        return "retail"
    if t in ("quote", "wholesale", "도매", "도매가", "견적", "견적가", "도매·견적가", "도매·견적"):
        return "quote"
    raise ValueError(f"가격 종류를 알 수 없습니다: 「{text}」 (소매가 또는 도매·견적가)")


def parse_hs(text: str):
    """입력 칸의 글자에서 HS 10자리를 읽는다. 비었거나 「자동 인식」이면 None, 형식이 틀리면 ValueError."""
    t = (text or "").strip()
    if not t or t.startswith("자동"):
        return None
    if t.startswith("직접"):
        raise ValueError("「직접 입력」을 골랐습니다. 품목 코드(HS) 10자리를 입력해 주세요(예: 2208309000).")
    m = re.search(r"(?<!\d)(\d{4})[.\-]?(\d{2})[.\-]?(\d{2})[.\-]?(\d{2})(?!\d)", t)
    if not m:
        raise ValueError("품목 코드(HS)는 10자리 숫자로 입력해 주세요(예: 2208309000). 목록에서 골라도 됩니다.")
    return "".join(m.groups())


_BRANDS = None


def load_brand_hints():
    """config/brand_hints.csv: 브랜드·품종 키워드 → 주종·HS 코드·원산지 제안(알려진 항목만)."""
    global _BRANDS
    if _BRANDS is None:
        import csv
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "config" / "brand_hints.csv"
        _BRANDS = []
        if path.exists():
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    for alias in row["aliases"].split("|"):
                        _BRANDS.append((alias.strip().lower().replace(" ", ""), row))
    return _BRANDS


def match_brand(name: str):
    """제품명에 들어 있는 가장 긴 브랜드·품종 키워드의 행을 돌려준다(없으면 None)."""
    norm = re.sub(r"[\s'’`.,·\-]+", "", name.lower())  # 공백·아포스트로피·하이픈은 무시(Maker's Mark = makersmark)
    hits = [(len(a), a, row) for a, row in load_brand_hints() if a and a in norm]
    if not hits:
        return None
    _, alias, row = max(hits)
    return {"alias": alias, "liquor_type": row["liquor_type"], "hs_code": row["hs_code"] or None,
            "origin": row["origin"] or None, "note": row["note"]}


def suggest_hs(ltype: str, name: str, brand_hs=None) -> str:
    low = name.lower()
    if ltype == "whisky":
        if any(w in low for w in ("스카치", "scotch")):
            return "2208301000"
        if any(w in low for w in ("버번", "bourbon")):
            return "2208302000"
        if any(w in low for w in ("라이", "rye")):
            return "2208303000"
        return brand_hs or "2208309000"  # 기타(일본 위스키 등)
    if ltype == "wine":
        if any(w in low for w in ("레드", "red", "붉은", "赤", "rouge", "rosso")):
            return "2204211000"
        if any(w in low for w in ("화이트", "white", "흰", "白", "blanc", "bianco")):
            return "2204212000"
        if any(w in low for w in ("샴페인", "champagne", "스파클링", "sparkling", "prosecco", "프로세코", "cava")):
            return "2204100000"
        return brand_hs or "2204219000"
    fixed = {"sake": "2206002010", "rum": "2208400000", "gin": "2208500000", "vodka": "2208600000",
             "tequila": "2208907000", "beer": "2203000000", "takju": "2206002030"}
    if ltype == "brandy":
        return brand_hs or "2208201000"
    return fixed[ltype]


def extract_volume_abv(name: str):
    """제품명에서 용량(ml)과 도수(%)를 읽는다. 700ml, 70cl, 0.7L, 1L, 1 litre와 40%, 40% ABV, 40도를 지원한다."""
    vol_ml = None
    m = re.search(r"(\d{2,4})\s*ml\b", name, re.I)
    if m:
        vol_ml = int(m.group(1))
    else:
        m = re.search(r"(\d{2,3})\s*cl\b", name, re.I)
        if m:
            vol_ml = int(m.group(1)) * 10
        else:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|ℓ|lt|ltr|liter|litre|리터)\b", name, re.I)
            if m and 0.1 <= float(m.group(1)) <= 5:
                vol_ml = round(float(m.group(1)) * 1000)
    abv = re.search(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|도)(?!\d)", name) or re.search(r"abv\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)", name, re.I)
    return (vol_ml, float(abv.group(1)) if abv else None)


def suggest_product(name: str, country: str) -> dict:
    """제품명으로 주종·HS 코드·원산지·용량·도수를 제안한다. 주종 단어가 없어도 브랜드·품종 사전으로 찾는다."""
    brand = match_brand(name)
    kw_type = suggest_liquor_type(name)
    # 브랜드가 알려진 제품에서 「럼 캐스크」·「와인 캐스크 피니시」 같은 숙성통 표현은 주종으로 보지 않는다.
    if brand and kw_type and kw_type != brand["liquor_type"] and any(c in name.lower() for c in CASK_WORDS):
        kw_type = brand["liquor_type"]
    # 주종 단어가 있으면 미지원 단어가 섞여 있어도 막지 않는다.
    # 주종 단어 없이 미지원 단어(소주·리큐르 등)가 있으면 브랜드가 맞아도 막는다.
    hint = None if kw_type else unsupported_hint(name)
    ltype = kw_type or (brand["liquor_type"] if brand and not hint else None)
    vol, abv = extract_volume_abv(name)
    brand_ok = bool(brand and brand["liquor_type"] == ltype)
    return {
        "liquor_type": ltype,
        "hs_code": suggest_hs(ltype, name, brand["hs_code"] if brand_ok else None) if ltype else None,
        "origin_country": (brand["origin"] if brand_ok and brand["origin"] else country),
        "brand_matched": brand["alias"] if brand_ok else None,
        "volume_ml": vol,
        "abv_percent": abv,
        "unsupported": hint,
    }


def run_name(ltype: str) -> str:
    """실행마다 다른 이름(초 단위)으로 저장해 열려 있는 이전 PDF와 겹치지 않게 한다."""
    from datetime import datetime
    return f"report_{ltype}_{datetime.now():%Y%m%d_%H%M%S}"


def build_from_form(v: dict) -> dict:
    """입력 창·웹 화면 공통: 칸에 적힌 글자로 후보 입력을 만든다. 문제가 있으면 한글 안내(ValueError).
    v: name, price, country(국가 코드나 이름), currency, type(주종 코드 또는 빈칸), hs, origin, volume, abv,
       made, cert, domestic, url, fx, margin, kind(retail/quote) - 모두 문자열, 비어 있으면 자동."""
    v = {k: ("" if x is None else str(x).strip()) for k, x in v.items()}
    g = lambda k: v.get(k, "")  # noqa: E731
    if not g("name"):
        raise ValueError("제품명을 입력해 주세요.")
    if not g("price"):
        raise ValueError("현지 가격을 입력해 주세요.")
    price = parse_price(g("price"), "현지 가격")
    if not g("country"):
        raise ValueError("구매 국가를 선택해 주세요.")
    country = check_country(normalize_country(g("country")), g("country"))
    currency = g("currency") or CURRENCY_BY_COUNTRY.get(country, "")
    if not currency:
        raise ValueError(f"{country}의 통화를 알 수 없습니다. 세부 설정에서 통화 코드(예: MXN)를 입력해 주세요.")
    currency = normalize_currency(currency)

    sug = suggest_product(g("name"), country)
    explicit_type = g("type") or None
    if explicit_type and explicit_type not in TYPE_NAMES:
        raise ValueError(f"지원하지 않는 주종입니다: {explicit_type}")
    hs_in = parse_hs(g("hs"))  # 사용자가 직접 입력·선택한 품목 코드(없으면 None)
    hs_type = type_from_hs(hs_in) if hs_in else None
    if hs_in and not hs_type:
        raise ValueError(f"품목 코드 {hs_in}는 지원 대상({SUPPORTED_TEXT})이 아닙니다. 지원 코드는 목록에서 고를 수 있습니다.")
    if explicit_type and hs_type and explicit_type != hs_type:
        raise ValueError(f"주종({TYPE_NAMES[explicit_type]})과 품목 코드({hs_in})가 맞지 않습니다. 하나만 두거나 서로 맞춰 주세요.")
    ltype = explicit_type or hs_type or sug["liquor_type"]
    if sug["unsupported"] and not (explicit_type or hs_type):
        raise ValueError(f"「{sug['unsupported']}」 계열은 지원 주종({SUPPORTED_TEXT})이 아닙니다.")
    if not ltype:
        raise ValueError("제품명에서 주종을 알 수 없습니다. 주종을 고르거나 품목 코드(HS)를 목록에서 선택·입력해 주세요"
                         "(이름에 위스키·와인·맥주 같은 주종을 넣어도 됩니다).")
    confirmed = bool(hs_in)  # 품목 코드를 사용자가 직접 정한 경우만 「확인」
    hs = hs_in or (sug["hs_code"] if sug["liquor_type"] == ltype else suggest_hs(ltype, g("name")))
    origin = (check_country(normalize_country(g("origin")), g("origin")) if g("origin")
              else (sug["origin_country"] if sug["liquor_type"] == ltype else country))
    vol = parse_volume(g("volume")) if g("volume") else sug["volume_ml"]
    abv = parse_abv(g("abv")) if g("abv") else sug["abv_percent"]
    if ltype in SPECIFIC_TYPES and not vol:
        raise ValueError(f"{_eun(TYPE_NAMES[ltype])} 용량에 세금이 붙는 종량세 주종입니다. 용량(ml)을 입력해 주세요(예: 330, 500).")
    return {
        "product_name": g("name"), "product_name_ko": g("name"), "liquor_type": ltype, "hs_code": hs,
        "origin_country": origin, "purchase_country": country, "currency": currency, "local_price": price,
        "price_source_url": g("url"),
        "domestic_price": parse_price(g("domestic"), "국내 판매가") if g("domestic") else None,
        "volume_ml": vol, "abv_percent": abv, "made_in_origin": g("made") or "모름", "has_certificate": g("cert") or "모름",
        "checked_at": date.today().isoformat(), "report_name": run_name(ltype),
        "fx_override": parse_number(g("fx"), "과세환율") if g("fx") else None,
        "margin_percent": parse_margin(g("margin")) if g("margin") else None,
        "price_kind": parse_price_kind(g("kind")),
        "info_confirmed": confirmed,
        "intake_notes": [f"주종 {TYPE_NAMES[ltype]}", f"HS 코드 {hs}"],
    }


def _ask(label, default=None, yes=False, required=False):
    if yes:
        if required and default in (None, ""):
            raise ValueError(f"{label} 값이 필요합니다(--yes 모드에서는 인자로 줘야 합니다).")
        return default
    shown = f" [{default}]" if default not in (None, "") else ""
    while True:
        ans = input(f"{label}{shown}: ").strip()
        if ans:
            return ans
        if default not in (None, ""):
            return default
        if not required:
            return None
        print("  값을 입력해 주세요.")


def build_candidate(args) -> dict:
    """args: argparse 결과(name, price, currency, country, type, hs, origin, domestic_price, price_url,
    made_in_origin, certificate, yes). 비어 있는 항목은 대화로 묻는다."""
    yes = args.yes
    print("=== 수입 후보 입력 (제품명·현지 가격·구매 국가만 있으면 됩니다) ===") if not yes else None
    name = _ask("제품명", args.name, yes, required=True)
    price = parse_price(_ask("현지 가격(숫자)", args.price, yes, required=True))
    raw_country = _ask("구매 국가(예: JP, FR, US 또는 일본)", args.country, yes, required=True)
    country = check_country(normalize_country(raw_country), raw_country)
    default_cur = args.currency or CURRENCY_BY_COUNTRY.get(country)
    if yes and not default_cur:
        raise ValueError(f"구매 국가 {country}의 통화를 알 수 없습니다. --currency로 통화 코드(예: MXN)를 알려 주세요.")
    currency = normalize_currency(_ask("통화", default_cur, yes, required=True))

    sug = suggest_product(name, country)
    hs_arg = parse_hs(args.hs) if args.hs else None
    if hs_arg and not type_from_hs(hs_arg):
        raise ValueError(f"품목 코드 {hs_arg}는 지원 대상({SUPPORTED_TEXT})이 아닙니다. 지원 코드: "
                         + ", ".join(c for c, _, _ in HS_CHOICES))
    if hs_arg and args.type and type_from_hs(hs_arg) != args.type:
        raise ValueError(f"주종({args.type})과 품목 코드({hs_arg})가 맞지 않습니다.")
    if sug["unsupported"] and not (args.type or hs_arg):
        raise ValueError(f"「{sug['unsupported']}」 계열은 지원 주종({SUPPORTED_TEXT})이 아닙니다.")
    notes = []

    ltype = args.type or type_from_hs(hs_arg) or sug["liquor_type"]
    if not yes:
        if ltype:
            print(f"  → 주종 제안: {TYPE_NAMES[ltype]}")
        else:
            print("  → 제품명에서 주종을 알 수 없습니다. 주종(" + " / ".join(TYPE_NAMES) + ")을 입력하거나 아래 품목 코드 중 하나를 입력하세요.")
            for c, _, d in HS_CHOICES:
                print(f"       {c}  {d}")
        ans = _ask("주종 확인 (" + " / ".join(TYPE_NAMES) + " 또는 품목 코드 10자리)", ltype, yes, required=True).strip().lower()
        if re.fullmatch(r"\d{10}", ans):
            hs_arg = ans
            ans = type_from_hs(ans) or ans
        ltype = ans
    elif not ltype:
        raise ValueError("제품명에서 주종을 알 수 없습니다. --type 주종(" + "|".join(TYPE_NAMES) + ") 또는 --hs 품목코드(10자리)로 알려 주세요.")
    if ltype not in TYPE_NAMES:
        raise ValueError(f"지원하지 않는 주종 또는 품목 코드입니다: {ltype}")
    notes.append(f"주종 {TYPE_NAMES[ltype]}: " + ("인자로 지정" if (args.type or hs_arg) else "제품명·브랜드로 제안"))

    hs = hs_arg or (sug["hs_code"] if sug["liquor_type"] == ltype else suggest_hs(ltype, name))
    if not yes:
        print("  → 품목 코드(HS)는 제품명·브랜드로 제안한 값입니다. 다르면 10자리로 고쳐 주세요." + ("" if hs_arg else ""))
        hs = parse_hs(_ask("HS 코드(10자리)", hs, yes, required=True))
    notes.append(f"HS 코드 {hs}: " + ("인자로 지정" if hs_arg else "규칙 기반 제안"))

    raw_origin = _ask("원산지(생산) 국가 코드", args.origin or sug["origin_country"], yes, required=True)
    origin = check_country(normalize_country(raw_origin), raw_origin)
    vol = parse_volume(args.volume) if getattr(args, "volume", None) else sug["volume_ml"]
    abv = sug["abv_percent"]
    if not yes:
        need_vol = ltype in SPECIFIC_TYPES  # 맥주·탁주는 용량에 세금이 붙어서 꼭 필요하다
        ans = _ask("용량(ml, 맥주·탁주는 필수)" if need_vol else "용량(ml, 모르면 Enter)", vol, yes, required=need_vol)
        vol = parse_volume(ans) if ans not in (None, "") else None
        ans = _ask("도수(%, 모르면 Enter)", abv, yes)
        abv = parse_abv(ans) if ans not in (None, "") else None
        made = _ask("원산지 국가에서 생산된 제품입니까? (예/아니오/모름)", args.made_in_origin or "모름", yes)
        cert = _ask("거래처가 원산지증명서를 발급할 수 있습니까? (예/아니오/모름)", args.certificate or "모름", yes)
        dom = _ask("국내 실제 판매가(원, 없으면 Enter)", args.domestic_price, yes)
        url = _ask("가격 출처 URL(없으면 Enter)", args.price_url, yes)
    else:
        made = args.made_in_origin or "모름"
        cert = args.certificate or "모름"
        dom = args.domestic_price
        url = args.price_url

    today = date.today().isoformat()
    fx_rate = parse_number(args.fx_rate, "과세환율") if getattr(args, "fx_rate", None) else None
    return {
        "product_name": name,
        "product_name_ko": name,
        "liquor_type": ltype,
        "hs_code": hs,
        "origin_country": origin,
        "purchase_country": country,
        "currency": currency,
        "local_price": price,
        "price_source_url": url or "",
        "domestic_price": parse_price(dom, "국내 판매가") if dom else None,
        "volume_ml": vol,
        "abv_percent": abv,
        "made_in_origin": made,
        "has_certificate": cert,
        "checked_at": today,
        "report_name": run_name(ltype),
        "fx_override": fx_rate,
        "margin_percent": parse_margin(args.margin) if getattr(args, "margin", None) not in (None, "") else None,
        "price_kind": parse_price_kind(getattr(args, "price_kind", None)),
        "info_confirmed": not yes,
        "intake_notes": notes,
    }

"""월간 변동 알림: 등록한 후보의 도착 원가가 등록 시점보다 ±5% 이상 움직이면 원인을 나눠 알려 준다.

  python src/watch.py add --input inputs/candidate_whisky.json      후보 등록(지금의 환율·세율·현지가를 기준으로 저장)
  python src/watch.py add --name "Asahi Super Dry 350ml" --price 220 --country 일본
  python src/watch.py list                                          등록 목록
  python src/watch.py price w1 23500                                현지가 갱신(자동 수집하지 않으므로 직접 넣는다)
  python src/watch.py check                                         변동 확인 → 알림 리포트(PDF)
  python src/watch.py collect-fx                                    이번 주 과세환율을 data/fx_history.csv에 쌓는다(주 1회)

원인 분해는 환율 → 세율 → 현지가 순서로 하나씩 바꿔 가며 다시 계산한 차이다(세 효과의 합 = 전체 변동).
"""
import argparse
import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fx  # noqa: E402
import main as agent  # noqa: E402
import tax  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIR = ROOT / "watchlist"
WATCH_FILE = WATCH_DIR / "watchlist.json"
FX_HISTORY = ROOT / "data" / "fx_history.csv"
DEFAULT_THRESHOLD = 5.0
CUR_UNITS = {"JPY": (100, "엔화", "100엔당"), "USD": (1, "달러", "1달러당"), "EUR": (1, "유로", "1유로당"),
             "GBP": (1, "파운드", "1파운드당"), "CNY": (1, "위안화", "1위안당"), "AUD": (1, "호주달러", "1호주달러당"),
             "CAD": (1, "캐나다달러", "1캐나다달러당")}
# 입력에서 알림 계산에 쓰는 항목만 저장한다(리포트 이름·메모 등은 빼고 가볍게)
KEEP_KEYS = ("product_name", "product_name_ko", "liquor_type", "hs_code", "origin_country", "purchase_country", "currency",
             "local_price", "price_kind", "volume_ml", "abv_percent", "made_in_origin", "has_certificate", "margin_percent",
             "price_source_url", "checked_at")


# ---- 저장 --------------------------------------------------------------------
def load(path: Path = None) -> dict:
    path = path or WATCH_FILE
    if not path.exists():
        return {"version": 1, "threshold_pct": DEFAULT_THRESHOLD, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("items 목록이 없음")
    except (OSError, ValueError) as e:  # 손으로 고치다 깨진 파일: 덮어쓰지 않고 알린다
        raise agent.AgentError(f"월간 알림 목록 파일을 읽을 수 없습니다({path.name}: {str(e)[:60]}). "
                               "파일을 고치거나 다른 이름으로 옮긴 뒤 다시 등록해 주세요.")
    return data


def save(data: dict, path: Path = None):
    path = path or WATCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find(data: dict, item_id: str) -> dict:
    item = next((x for x in data["items"] if x["id"] == item_id), None)
    if item is None:
        raise agent.AgentError(f"등록 목록에 「{item_id}」가 없습니다. 목록: " + (", ".join(x["id"] for x in data["items"]) or "비어 있음"))
    return item


# ---- 계산 --------------------------------------------------------------------
def snapshot(inp: dict, sample: bool, as_of: date = None) -> dict:
    """지금(또는 as_of 주간)의 환율·세율·현지가로 원가를 계산해 비교에 필요한 값만 남긴다."""
    r = agent.build_result(dict(inp), sample, as_of=as_of or date.today(), with_trend=False)  # 기준일은 입력의 확인일이 아니라 오늘
    names = list(r["costs"])
    main = "협정세율" if "협정세율" in r["costs"] else names[0]
    c = r["costs"][main]
    return {
        "as_of": r["as_of"], "fx_rate": str(r["fx"]["rate"]), "fx_week_start": r["fx"]["week_start"],
        "fx_week_end": r["fx"]["week_end"], "fx_source": r["fx"]["source"], "fx_warning": r["fx"]["warning"],
        "local_price": float(r["input"]["local_price"]), "currency": r["input"]["currency"],
        "scenario": main, "customs_rate": str(r["rates"][main]), "rates": {n: str(x) for n, x in r["rates"].items()},
        "verdict": r["fta"].verdict, "agreement": r["fta"].agreement,
        "landed": {n: str(x["landed_cost"]) for n, x in r["costs"].items()},
        "landed_main": str(c["landed_cost"]), "expected_retail_main": str(c["expected_retail"]),
        "sample_mode": bool(sample),
    }


def decompose(inp: dict, base: dict, cur: dict) -> dict:
    """등록 시점(base)과 지금(cur)의 원가 차이를 환율·세율·현지가 효과로 나눈다(순서대로 하나씩 바꿔 다시 계산)."""
    rule = tax.load_tax_rules()[inp["liquor_type"]]
    asm = agent.load_assumptions(inp)
    vol = inp.get("volume_ml")

    def landed(price, rate_fx, customs):
        return agent.cost_scenario(price, rate_fx, rule, customs, asm, vol)["landed_cost"]

    p0, p1 = Decimal(str(base["local_price"])), Decimal(str(cur["local_price"]))
    f0, f1 = Decimal(base["fx_rate"]), Decimal(cur["fx_rate"])
    c0, c1 = Decimal(base["customs_rate"]), Decimal(cur["customs_rate"])
    l0, l1 = Decimal(base["landed_main"]), Decimal(cur["landed_main"])
    again = landed(p0, f0, c0)  # 지금의 규칙으로 등록 시점을 다시 계산한 값(주세 규칙·가정값이 바뀌면 l0와 달라진다)
    step_fx = landed(p0, f1, c0)
    step_rate = landed(p0, f1, c1)
    d = {"fx_effect": step_fx - again, "rate_effect": step_rate - step_fx, "price_effect": l1 - step_rate,
         "other_effect": again - l0, "total": l1 - l0}
    out = {k: str(v) for k, v in d.items()}
    out.update({k.replace("effect", "pct") if k != "total" else "pct": float(v / l0 * 100) for k, v in d.items()})
    return out


def _won(x) -> str:
    return f"{agent.won(abs(Decimal(str(x)))):,}"


def messages(inp: dict, base: dict, cur: dict, d: dict, polite: bool = False) -> list:
    """원인별 문장. polite=True면 화면용(습니다), False면 리포트용(다)."""
    up, down, same = ("늘었습니다", "줄었습니다", "같습니다") if polite else ("늘었다", "줄었다", "같다")
    end = "습니다" if polite else "다"
    cur_code = cur["currency"]
    unit, cname, per = CUR_UNITS.get(cur_code, (1, cur_code, f"1{cur_code}당"))
    out = []
    f0, f1 = Decimal(base["fx_rate"]) * unit, Decimal(cur["fx_rate"]) * unit
    fe = Decimal(d["fx_effect"])
    if f0 != f1:
        out.append(f"{cname} 과세환율이 {per} {f0:,.2f}원에서 {f1:,.2f}원으로 {'올라' if f1 > f0 else '내려'} "
                   f"도착 원가가 {_won(fe)}원({d['fx_pct']:+.1f}%) {up if fe > 0 else down}.")
    else:
        out.append(f"{cname} 과세환율은 {per} {f0:,.2f}원으로 등록 시점과 {same}.")
    c0, c1 = float(Decimal(base["customs_rate"]) * 100), float(Decimal(cur["customs_rate"]) * 100)
    re_ = Decimal(d["rate_effect"])
    if c0 != c1:
        s = (f"적용 관세율이 {c0:g}%에서 {c1:g}%로 {'올라' if c1 > c0 else '내려'} "
             f"도착 원가가 {_won(re_)}원({d['rate_pct']:+.1f}%) {up if re_ > 0 else down}.")
        if base["verdict"] != cur["verdict"]:
            s += f" FTA 판정이 「{base['verdict']}」에서 「{cur['verdict']}」로 바뀌었{end}."
        out.append(s)
    else:
        out.append(f"적용 관세율은 {c0:g}%로 변하지 않았{end}.")
    p0, p1 = base["local_price"], cur["local_price"]
    pe = Decimal(d["price_effect"])
    if p0 != p1:
        out.append(f"현지가가 {p0:,.10g}{cur_code}에서 {p1:,.10g}{cur_code}로 {'올라' if p1 > p0 else '내려'} "
                   f"도착 원가가 {_won(pe)}원({d['price_pct']:+.1f}%) {up if pe > 0 else down}.")
    else:
        out.append(f"현지가는 등록한 값 {p0:,.10g}{cur_code} 그대로{'입니다' if polite else '다'}"
                   f"(자동 수집하지 않으므로 직접 갱신해야 반영{'됩니다' if polite else '된다'}).")
    oe = Decimal(d["other_effect"])
    if abs(oe) >= 1:
        out.append(f"주세 규칙이나 가정값이 바뀌어 도착 원가가 {_won(oe)}원({d['other_pct']:+.1f}%) {up if oe > 0 else down}.")
    return out


def backdated(item: dict) -> bool:
    """실제 등록한 날보다 앞선 날짜를 기준일로 삼은 후보인지."""
    return bool(item.get("added_on")) and item["registered_at"] < item["added_on"]


# ---- 동작 --------------------------------------------------------------------
def add(inp: dict, sample: bool = False, as_of: date = None, threshold: float = None, path: Path = None, note: str = "") -> dict:
    """후보를 등록한다. 등록 시점의 환율·세율·현지가·원가가 비교 기준이 된다."""
    data = load(path)
    kept = {k: inp[k] for k in KEEP_KEYS if inp.get(k) not in (None, "")}
    base = snapshot(kept, sample, as_of)
    num = max([int(x["id"][1:]) for x in data["items"] if x["id"][1:].isdigit()] or [0]) + 1
    item = {"id": f"w{num}", "name": kept.get("product_name_ko") or kept["product_name"], "registered_at": base["as_of"],
            "added_on": date.today().isoformat(), "input": kept, "baseline": base, "checks": []}
    if note:
        item["note"] = note
    if threshold is not None:
        item["threshold_pct"] = float(threshold)
    data["items"].append(item)
    save(data, path)
    return item


def update_price(item_id: str, price, path: Path = None) -> dict:
    """현지가를 갱신한다(다음 확인부터 반영). 등록 시점 기준은 그대로 둔다."""
    import intake
    data = load(path)
    item = find(data, item_id)
    try:
        item["input"]["local_price"] = intake.parse_price(price, "현지 가격")
    except ValueError as e:
        raise agent.AgentError(str(e))
    item["input"]["checked_at"] = date.today().isoformat()
    save(data, path)
    return item


def remove(item_id: str, path: Path = None) -> dict:
    data = load(path)
    item = find(data, item_id)
    data["items"].remove(item)
    save(data, path)
    return item


def check(sample: bool = False, as_of: date = None, threshold: float = None, path: Path = None) -> list:
    """등록한 후보를 모두 다시 계산해 등록 시점·직전 확인과 견준다. 결과를 기록하고 목록으로 돌려준다."""
    data = load(path)
    results = []
    for item in data["items"]:
        th = float(threshold if threshold is not None else item.get("threshold_pct", data.get("threshold_pct", DEFAULT_THRESHOLD)))
        try:
            cur = snapshot(item["input"], sample, as_of)
        except (agent.AgentError, RuntimeError, ValueError) as e:  # 한 후보가 실패해도 나머지는 계속 확인한다
            results.append({"item": item, "error": str(e), "threshold": th})
            continue
        base = item["baseline"]
        d = decompose(item["input"], base, cur)
        prev = item["checks"][-1]["snapshot"] if item["checks"] and item["checks"][-1]["snapshot"]["as_of"] != cur["as_of"] else (
            item["checks"][-2]["snapshot"] if len(item["checks"]) > 1 else base)
        prev_l = Decimal(prev["landed_main"])
        rec = {"checked_at": cur["as_of"], "snapshot": cur, "vs_baseline": d, "threshold": th,
               "vs_previous": {"as_of": prev["as_of"], "total": str(Decimal(cur["landed_main"]) - prev_l),
                               "pct": float((Decimal(cur["landed_main"]) - prev_l) / prev_l * 100)},
               "alert": abs(d["pct"]) >= th, "messages": messages(item["input"], base, cur, d)}
        if item["checks"] and item["checks"][-1]["checked_at"] == rec["checked_at"]:
            item["checks"][-1] = rec  # 같은 날 다시 확인하면 덮어쓴다
        else:
            item["checks"].append(rec)
        results.append({"item": item, "record": rec, "threshold": th})
    save(data, path)
    return results


def console_lines(results: list) -> list:
    lines = []
    for r in results:
        item = r["item"]
        if "error" in r:
            lines.append(f"[{item['id']}] {item['name']}: 확인 실패 - {r['error']}")
            continue
        rec, base = r["record"], item["baseline"]
        d = rec["vs_baseline"]
        mark = "알림" if rec["alert"] else "기준 이내"
        lines.append(f"[{item['id']}] {item['name']}: {agent.won(base['landed_main']):,}원 → {agent.won(rec['snapshot']['landed_main']):,}원 "
                     f"({d['pct']:+.1f}%, 기준 ±{r['threshold']:g}%) → {mark}")
        for m in messages(item["input"], base, rec["snapshot"], d, polite=True):
            lines.append("    - " + m)
    return lines


# ---- 리포트 ------------------------------------------------------------------
def build_alert_html(results: list, as_of: str) -> str:
    import report_html as rh
    e, w = rh.e, rh.w
    ok = [r for r in results if "record" in r]
    alerts = [r for r in ok if r["record"]["alert"]]
    n, m = len(results), len(alerts)
    th = ok[0]["threshold"] if ok else DEFAULT_THRESHOLD
    same_th = all(r["threshold"] == th for r in ok)
    th_txt = f"±{th:g}%" if same_th else "후보별 기준"
    title = (f"등록 후보 {n}건 중 {m}건, 기준 {th_txt} 초과 변동" if m else f"등록 후보 {n}건 모두 기준 {th_txt} 이내 변동")
    if ok:
        top = max(ok, key=lambda r: abs(r["record"]["vs_baseline"]["pct"]))
        top_pct = top["record"]["vs_baseline"]["pct"]
        lead = (f"기준일 {as_of}에 등록 후보 {n}건의 도착 원가를 다시 계산한 결과 {m}건이 등록 시점 대비 {th_txt} 기준을 넘었다. "
                f"변동이 가장 큰 후보는 {rh.short_name(top['item']['name']) or top['item']['name']}로 등록 시점보다 {top_pct:+.1f}% 움직였다.")
        k2_big, k2_cmp = f"{top_pct:+.1f}%", f"{rh.short_name(top['item']['name']) or top['item']['name']}, 등록 {top['item']['registered_at']} 대비"
        s0 = ok[0]["record"]["snapshot"]
        k3_big, k3_cmp = f"{s0['fx_week_start'][5:]}~{s0['fx_week_end'][5:]}", f"이번 확인에 쓴 관세청 과세환율 적용 주간({s0['fx_week_start'][:4]}년)"
    else:
        lead = f"기준일 {as_of}에 등록 후보 {n}건을 확인하지 못했다."
        k2_big = k2_cmp = k3_big = k3_cmp = "-"
    rows = []
    for r in results:
        item = r["item"]
        if "error" in r:
            rows.append([item["name"], item["registered_at"], "-", "-", "-", "-", "-", "확인 실패"])
            continue
        rec, base = r["record"], item["baseline"]
        d = rec["vs_baseline"]
        rows.append([rh.short_name(item["name"]) or item["name"], item["registered_at"] + ("(소급)" if backdated(item) else ""), w(base["landed_main"]), w(rec["snapshot"]["landed_main"]),
                     f"{'+' if Decimal(d['total']) >= 0 else '-'}{_won(d['total'])}", f"{d['pct']:+.1f}%",
                     f"{rec['vs_previous']['pct']:+.1f}%", "알림" if rec["alert"] else "기준 이내"])
    backdate_note = (" 등록일에 (소급)이 붙은 후보는 실제 등록한 날보다 앞선 날짜를 기준일로 정해, 그 주의 과세환율로 기준 원가를 계산했다."
                     if any(backdated(r["item"]) for r in results) else "")
    summary = f"""<section class="page"><p class="eyebrow">월간 변동 알림 · {e(as_of)}</p><h2>{e(title)}</h2>
<p class="lead">{e(lead)}</p><div class="keys">
<div class="key"><div class="big num">{m}건 / {n}건</div><div class="cmp">알림 건수 / 등록 후보, 기준 {e(th_txt)}</div><p>등록 시점 원가 대비 변동률이 기준을 넘은 후보의 수다.</p></div>
<div class="key"><div class="big num">{e(k2_big)}</div><div class="cmp">{e(k2_cmp)}</div><p>변동률의 절댓값이 가장 큰 후보의 도착 원가 변동이다.</p></div>
<div class="key"><div class="big num">{e(k3_big)}</div><div class="cmp">{e(k3_cmp)}</div><p>과세환율은 관세청이 매주 고시하는 수입 환율이다.</p></div></div>
<figure style="margin-top:7mm"><figcaption>후보별 도착 원가 변동 (단위: 원, 기준일 {e(as_of)})</figcaption>
{rh.tbl(["후보", "등록일", "등록 시 원가", "현재 원가", "변동액", "등록 대비", "직전 확인 대비", "판정"], rows, num_from=2)}
<p class="source">출처: 본 에이전트 계산(관세청 관세환율정보, 품목번호별 관세율표 2026, 주세법 제8조). 원가는 후보별 주 시나리오(협정세율이 있으면 협정세율) 기준이다.{backdate_note}</p></figure>
<div class="note"><p><b>읽는 법.</b> 등록할 때의 환율·세율·현지가로 계산한 도착 원가를 기준으로, 지금 값으로 다시 계산한 원가가 기준 폭을 넘으면 알림으로 표시한다. 현지가는 자동으로 모으지 않으므로 사용자가 갱신한 값만 반영된다.</p></div></section>"""

    details = ""
    for r in ok:
        item, rec = r["item"], r["record"]
        base, cur, d = item["baseline"], rec["snapshot"], rec["vs_baseline"]
        unit, cname, per = CUR_UNITS.get(cur["currency"], (1, cur["currency"], f"1{cur['currency']}당"))
        f0, f1 = Decimal(base["fx_rate"]) * unit, Decimal(cur["fx_rate"]) * unit

        def eff(key):
            v = Decimal(d[key])
            return f"{'+' if v >= 0 else '-'}{_won(v)}", f"{d[key.replace('effect', 'pct') if key != 'total' else 'pct']:+.1f}%"
        drows = [[f"과세환율({per})", f"{f0:,.2f}원", f"{f1:,.2f}원", *eff("fx_effect")],
                 ["적용 관세율", f"{float(Decimal(base['customs_rate']) * 100):g}% ({base['scenario']})", f"{float(Decimal(cur['customs_rate']) * 100):g}% ({cur['scenario']})", *eff("rate_effect")],
                 ["현지가", f"{base['local_price']:,.10g} {cur['currency']}", f"{cur['local_price']:,.10g} {cur['currency']}", *eff("price_effect")]]
        if abs(Decimal(d["other_effect"])) >= 1:
            drows.append(["주세 규칙·가정값", "-", "-", *eff("other_effect")])
        drows.append(["도착 원가", f"{w(base['landed_main'])}원", f"{w(cur['landed_main'])}원", *eff("total")])
        verdict = "알림" if rec["alert"] else "기준 이내"
        details += f"""<div style="margin-bottom:8mm;page-break-inside:avoid"><h3>{e(item['id'])} · {e(item['name'])} — {e(verdict)} ({d['pct']:+.1f}%, 기준 ±{r['threshold']:g}%)</h3>
<p>{e(' '.join(rec['messages']))}</p>
{rh.tbl(["요인", f"등록 시점({item['registered_at']})", f"현재({cur['as_of']})", "원가 영향(원)", "등록 원가 대비"], drows, hl=len(drows) - 1, num_from=1)}
<p class="source">출처: 본 에이전트 계산. 과세환율은 {e(cur['fx_source'])}, 적용 주간 {e(cur['fx_week_start'])}~{e(cur['fx_week_end'])}. FTA 판정은 등록 시 「{e(base['verdict'])}」, 현재 「{e(cur['verdict'])}」다.{(' 메모: ' + e(item['note'])) if item.get('note') else ''}</p></div>"""
    failed = "".join(f"<p>{e(r['item']['id'])} · {e(r['item']['name'])}: {e(r['error'])}</p>" for r in results if "error" in r)
    detail_page = f"""<section class="page"><p class="eyebrow">원인 분해</p><h2>환율·세율·현지가로 나눈 후보별 변동 원인</h2>
<p class="lead">환율, 세율, 현지가를 차례로 지금 값으로 바꿔 다시 계산한 차이이며 세 효과의 합은 전체 변동과 같다.</p>
{details}{('<h3>확인하지 못한 후보</h3>' + failed) if failed else ''}
<h3>방법과 한계</h3><p class="refs">분해 순서는 환율, 세율, 현지가다. 순서를 바꾸면 요인별 금액이 조금 달라질 수 있으나 합계는 같다. 현지가는 자동 수집하지 않아 사용자가 갱신할 때만 반영된다. 세율은 규칙표(config/fta_rules.csv, tax_rules.csv)를 새 관세율표로 갱신해야 바뀐다. 운임·보험료·통관비는 가정값이며 세액과 FTA 판정은 참고용이다.</p></section>"""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(title)}</title><style>{rh.CSS}</style></head><body>{summary}{detail_page}</body></html>")


def write_report(results: list, as_of: str, out_dir: Path = None) -> dict:
    """알림 리포트(HTML·PDF)와 결과(JSON)를 저장한다. 반환: {html, pdf(없으면 None), korean_check}."""
    import report_html as rh
    out_dir = out_dir or (WATCH_DIR / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"alert_{as_of.replace('-', '')}"
    doc = build_alert_html(results, as_of)
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(doc, encoding="utf-8")
    ok, text = rh.run_korean_check(doc, out_dir)
    (out_dir / "report_body.txt").unlink(missing_ok=True)
    pdf = out_dir / f"{stem}.pdf"
    if pdf.exists():
        try:
            pdf.unlink()
        except PermissionError:  # 뷰어가 열고 있으면 다른 이름으로 저장
            pdf = out_dir / f"{stem}_{datetime.now():%H%M%S}.pdf"
    made = rh.html_to_pdf(html_path, pdf)
    (out_dir / f"{stem}.json").write_text(json.dumps(
        [{"id": r["item"]["id"], "name": r["item"]["name"], **({"error": r["error"]} if "error" in r else r["record"])} for r in results],
        ensure_ascii=False, indent=2), encoding="utf-8")
    return {"html": html_path, "pdf": pdf if made else None, "korean_check": (ok, text)}


# ---- 환율 주 1회 수집 ----------------------------------------------------------
def collect_fx(on: date = None) -> dict:
    """이번 주(또는 on이 속한 주)의 과세환율 전체를 받아 data/fx_history.csv에 쌓는다. 같은 주는 다시 쌓지 않는다."""
    start, rates = fx.fetch_week(on or date.today())
    FX_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if FX_HISTORY.exists():
        with open(FX_HISTORY, encoding="utf-8-sig", newline="") as f:
            seen = {(r["week_start"], r["currency"]) for r in csv.DictReader(f)}
    new = [(c, r) for c, r in sorted(rates.items()) if (start.isoformat(), c) not in seen]
    write_head = not FX_HISTORY.exists()
    with open(FX_HISTORY, "a", encoding="utf-8-sig" if write_head else "utf-8", newline="") as f:
        wr = csv.writer(f)
        if write_head:
            wr.writerow(["week_start", "currency", "krw_per_unit", "source", "collected_at"])
        for c, r in new:
            wr.writerow([start.isoformat(), c, str(r), "관세청_관세환율정보 API(수입·과세)", datetime.now().isoformat(timespec="seconds")])
    return {"week_start": start.isoformat(), "currencies": len(rates), "added": len(new)}


# ---- 명령행 ------------------------------------------------------------------
def _candidate_from_args(a) -> dict:
    if a.input:
        try:
            return json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as e:
            raise agent.AgentError(f"입력 파일을 읽을 수 없습니다({a.input}): {e}")
    import intake
    ns = argparse.Namespace(name=a.name, price=a.price, country=a.country, currency=a.currency, type=a.type, hs=a.hs,
                            origin=a.origin, volume=a.volume, domestic_price=None, price_url=a.price_url,
                            made_in_origin=a.made_in_origin, certificate=a.certificate, yes=True, fx_rate=None,
                            margin=a.margin, price_kind=a.price_kind)
    try:
        return intake.build_candidate(ns)
    except (ValueError, EOFError) as e:
        raise agent.AgentError(str(e))


def main(argv=None):
    ap = argparse.ArgumentParser(description="월간 변동 알림: 등록 후보의 도착 원가 변동과 원인(환율·세율·현지가)을 알려 줍니다.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="후보 등록")
    p.add_argument("--input", help="후보 입력 JSON")
    for flag, hlp in (("--name", "제품명"), ("--price", "현지 가격"), ("--country", "구매 국가"), ("--currency", "통화"),
                      ("--hs", "HS 코드"), ("--origin", "원산지 국가 코드"), ("--volume", "용량(ml)"), ("--margin", "마진율(%)"),
                      ("--price-url", "가격 출처 URL")):
        p.add_argument(flag, dest=flag.strip("-").replace("-", "_"), help=hlp)
    p.add_argument("--type", choices=list(tax.load_tax_rules()))
    p.add_argument("--price-kind", dest="price_kind", choices=["retail", "quote"])
    p.add_argument("--made-in-origin", dest="made_in_origin", choices=["예", "아니오", "모름"])
    p.add_argument("--certificate", choices=["예", "아니오", "모름"])
    p.add_argument("--as-of", dest="as_of", help="등록 기준일(YYYY-MM-DD). 그 주의 과세환율로 기준 원가를 계산합니다")
    p.add_argument("--threshold", type=float, help=f"이 후보의 알림 기준(%%, 기본 {DEFAULT_THRESHOLD:g})")
    p.add_argument("--note", default="", help="메모(예: 가격 출처, 예시 가격 여부). 알림 리포트에 표시됩니다")
    p.add_argument("--sample", action="store_true", help="저장된 API 응답으로 계산")
    sub.add_parser("list", help="등록 목록")
    p = sub.add_parser("price", help="현지가 갱신")
    p.add_argument("id")
    p.add_argument("value")
    p = sub.add_parser("remove", help="등록 삭제")
    p.add_argument("id")
    p = sub.add_parser("check", help="변동 확인과 알림 리포트")
    p.add_argument("--as-of", dest="as_of", help="확인 기준일(YYYY-MM-DD, 기본 오늘)")
    p.add_argument("--threshold", type=float, help="이번 확인에만 쓸 알림 기준(%%)")
    p.add_argument("--sample", action="store_true", help="저장된 API 응답으로 계산")
    p.add_argument("--no-open", dest="no_open", action="store_true", help="리포트를 자동으로 열지 않음")
    p = sub.add_parser("collect-fx", help="이번 주 과세환율 수집(주 1회 실행)")
    p.add_argument("--as-of", dest="as_of", help="수집할 주간에 속한 날짜(YYYY-MM-DD, 기본 오늘)")
    a = ap.parse_args(argv)

    try:
        as_of = date.fromisoformat(a.as_of) if getattr(a, "as_of", None) else None
    except ValueError:
        print(f"[중단] 날짜는 YYYY-MM-DD 형식이어야 합니다: {a.as_of}", file=sys.stderr)
        return 2
    try:
        if a.cmd == "add":
            sample = a.sample or not fx.has_api_key()
            item = add(_candidate_from_args(a), sample, as_of, a.threshold, note=a.note)
            b = item["baseline"]
            print(f"등록: [{item['id']}] {item['name']}")
            print(f"  기준 원가 {agent.won(b['landed_main']):,}원({b['scenario']}), 과세환율 {b['fx_rate']}원/{b['currency']} "
                  f"({b['fx_week_start']}~{b['fx_week_end']}), 현지가 {b['local_price']:,.10g}{b['currency']}")
        elif a.cmd == "list":
            data = load()
            if not data["items"]:
                print("등록한 후보가 없습니다. python src/watch.py add --input inputs/candidate_whisky.json 으로 등록하세요.")
            for x in data["items"]:
                b = x["baseline"]
                last = x["checks"][-1] if x["checks"] else None
                tail = (f" / 최근 확인 {last['checked_at']} {last['vs_baseline']['pct']:+.1f}%" + (" 알림" if last["alert"] else "")) if last else ""
                print(f"[{x['id']}] {x['name']} · 등록 {x['registered_at']} · 기준 원가 {agent.won(b['landed_main']):,}원 · "
                      f"현지가 {x['input']['local_price']:,.10g}{b['currency']}{tail}")
        elif a.cmd == "price":
            item = update_price(a.id, a.value)
            print(f"[{item['id']}] 현지가를 {item['input']['local_price']:,.10g}{item['input']['currency']}로 갱신했습니다. check에서 반영됩니다.")
        elif a.cmd == "remove":
            item = remove(a.id)
            print(f"[{item['id']}] {item['name']} 등록을 삭제했습니다.")
        elif a.cmd == "check":
            if not load()["items"]:
                print("등록한 후보가 없습니다. 먼저 add로 등록하세요.")
                return 0
            sample = a.sample or not fx.has_api_key()
            results = check(sample, as_of, a.threshold)
            day = next((r["record"]["checked_at"] for r in results if "record" in r), (as_of or date.today()).isoformat())
            rep = write_report(results, day)
            print("\n".join(console_lines(results)))
            print(f"알림 리포트: {rep['pdf'] or rep['html']}")
            if not a.no_open and hasattr(__import__("os"), "startfile"):
                __import__("os").startfile(rep["pdf"] or rep["html"])
        elif a.cmd == "collect-fx":
            r = collect_fx(as_of)
            print(f"과세환율 수집: {r['week_start']} 주간, 통화 {r['currencies']}개 중 {r['added']}개 새로 저장 → {FX_HISTORY}")
    except agent.AgentError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

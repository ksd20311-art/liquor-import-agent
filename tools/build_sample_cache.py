"""키 없는 PC(샘플 모드)에서도 주요 제품 조합의 시장 추이가 나오도록 관세청 무역통계 응답을 미리 저장한다.

사용: python tools/build_sample_cache.py   (.env에 키 필요, 실시간으로 받아 data/samples/에 저장, 키는 저장 파일에서 제거)
- 대상: 1차 지원 주종(위스키·와인·사케)의 HS 코드 × 주요 수입 원산지
- 최근 24개월(직전 달까지)을 2번 호출로 받는다. 제출·배포 직전에 다시 실행하면 기준월이 최신으로 갱신된다.
"""
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import fx  # noqa: E402
import trade  # noqa: E402

WHISKY_ORIGINS = ["GB", "US", "JP", "IE", "FR", "CA", "DE", "AU", "NL", "IT", "ES"]
WINE_ORIGINS = ["FR", "IT", "ES", "US", "CL", "AU", "DE", "PT", "NZ", "AR", "ZA"]
COMBOS = (
    [(hs, o) for hs in ("2208301000", "2208302000", "2208303000", "2208309000") for o in WHISKY_ORIGINS]
    + [(hs, o) for hs in ("2204211000", "2204212000", "2204219000") for o in WINE_ORIGINS]
    + [("2206002010", "JP"), ("2206002010", "KR")]
)


def main():
    env = fx.load_env()
    key = env.get("DATA_GO_KR_KEY_TRADE") or env.get("DATA_GO_KR_KEY")
    if not key:
        sys.exit("API 키가 없습니다. .env에 키를 넣고 다시 실행하세요.")
    today = date.today()
    end_ym = trade.add_months(f"{today:%Y%m}", -1)
    saved, empty, failed = 0, 0, 0
    for i, (hs, o) in enumerate(COMBOS, 1):
        try:
            rows = trade.fetch_live(hs, o, end_ym, key, save=True)
        except Exception as e:  # 한 조합의 실패가 전체를 막지 않게 한다
            failed += 1
            print(f"[{i}/{len(COMBOS)}] {o} {hs}: 실패 {type(e).__name__}")
            continue
        if rows:
            saved += 1
        else:
            empty += 1
        print(f"[{i}/{len(COMBOS)}] {o} {hs}: {'저장 ' + str(len(rows)) + '행' if rows else '수입 실적 없음'}")
        time.sleep(0.2)
    print(f"완료: 저장 {saved}개 조합, 실적 없음 {empty}개, 실패 {failed}개 (기준월 {end_ym})")


if __name__ == "__main__":
    main()

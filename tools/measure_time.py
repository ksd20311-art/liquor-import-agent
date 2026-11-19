"""후보 1건 처리 시간을 잰다(11월 성공 기준: 1분 이내, 사람 확인 시간 제외). 실시간 조회를 포함한다.

  python tools/measure_time.py     → docs/verification/TIMING.md
"""
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import main as agent  # noqa: E402

lines = []
for f in ("inputs/candidate_whisky.json", "inputs/candidate_beer.json"):
    inp = json.loads((ROOT / f).read_text(encoding="utf-8"))
    t = time.perf_counter()
    r = agent.build_result(inp, sample=False)
    calc = time.perf_counter() - t
    out = Path(tempfile.mkdtemp())
    t = time.perf_counter()
    agent.write_outputs(inp, r, out)
    files = time.perf_counter() - t
    lines.append(f"| {f} | {calc:.1f}초 | {files:.1f}초 | {calc + files:.1f}초 | {'실시간' if not r['sample_mode'] else '샘플'} |")
doc = ["# 처리 시간 측정", "", f"측정: {datetime.now():%Y-%m-%d %H:%M}, 이 PC에서 한 번씩 실행한 값입니다(인터넷 속도와 PC에 따라 달라짐).", "",
       "| 입력 | 계산(환율·무역통계 조회 포함) | 리포트 파일 생성(HTML·PDF·근거표) | 합계 | 모드 |", "|---|---|---|---|---|", *lines, "",
       "기준: 후보 1건 1분 이내(사람이 입력·확인하는 시간 제외).", ""]
(ROOT / "docs" / "verification" / "TIMING.md").write_text("\n".join(doc), encoding="utf-8")
print("\n".join(doc))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""한글 산출물 자가 검문소.
사용법:  python3 check_korean.py 파일.md
        cat 글.txt | python3 check_korean.py -
딜로이트 코리아 보고서 339건(649만 자) 실측 기준으로 위반을 잡는다.
종료코드 1 = 금지 위반 있음(내보내면 안 됨).
"""
import sys, os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
# Windows 기본 인코딩은 cp949라 인코딩을 지정하지 않으면 여기서 죽는다.
# 2026-09-06까지 이 검사기가 Windows에서 한 번도 실행되지 못한 원인이다.
BAN = json.load(open(os.path.join(HERE, 'measure_ban.json'), encoding='utf-8'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
FIX = {"해자":0,"대전환":49,"드라이버":3,"랜딩":17,"모멘텀":40,
       "게임의룰":48,"이니셔티브":269,"오케스트레이션":124}

def load_terms():
    banned, warn = {}, {}
    for g, rows in BAN['groups'].items():
        if g.startswith('정상 대조군'):
            continue
        for w, c in rows:
            key = re.sub(r'[~,·]', '', w)
            c = FIX.get(key, c)
            (banned if c <= 5 else warn if c <= 100 else {})[key] = (g, c)
    return banned, warn

BANNED, WARN = load_terms()

def read(argv):
    if len(argv) < 2 or argv[1] == '-':
        return sys.stdin.read()
    return open(argv[1], encoding='utf-8', errors='ignore').read()

def strip_quotes(t):
    """금지어를 예시로 인용한 자리는 검사에서 뺀다.
    코드블록(```), 인라인 백틱(`), 표 안의 인용은 저자가 일부러 적은 것이다."""
    t = re.sub(r'\A---\n.*?\n---\n', ' ', t, flags=re.S)   # 스킬 프런트매터
    t = re.sub(r'```.*?```', ' ', t, flags=re.S)
    t = re.sub(r'`[^`\n]*`', ' ', t)
    return t

def sentences(t):
    t = re.sub(r'\s+', ' ', t)
    out = []
    for s in re.split(r'(?<=[다요음임][.])\s+|(?<=[.!?])\s+(?=[가-힣])', t):
        s = s.strip()
        if len(s) >= 10:
            out.append(s)
    return out

def main():
    text = read(sys.argv)
    if re.search(r'<!--\s*korean-check:\s*off\s*-->', text):
        print("이 문서는 규칙서·인용 대장이므로 어휘 검사를 건너뛴다.")
        return 0
    scan = strip_quotes(text)
    flat = re.sub(r'\s+', '', scan)
    hits, warns = [], []
    for w, (g, c) in BANNED.items():
        n = flat.count(w)
        if n:
            hits.append((n, w, g, c))
    for w, (g, c) in WARN.items():
        n = flat.count(w)
        if n:
            warns.append((n, w, g, c))
    hits.sort(reverse=True); warns.sort(reverse=True)

    print("=" * 62)
    print("한글 검문소 — 딜로이트 339건 실측 기준")
    print("=" * 62)

    if hits:
        print("\n[금지어 위반] 코퍼스 등장 5회 이하. 반드시 고친다.")
        for n, w, g, c in hits:
            print("  x %-16s 내 글 %2d회 / 코퍼스 %d회   (%s)" % (w, n, c, g))
    else:
        print("\n[금지어 위반] 없음.")

    if warns:
        print("\n[주의어] 대체어가 있으면 바꾼다.")
        for n, w, g, c in warns[:25]:
            print("  ! %-16s 내 글 %2d회 / 코퍼스 %d회   (%s)" % (w, n, c, g))

    # 문장 길이
    ss = sentences(text)
    ui = [s2 for s2 in ss if len(s2) < 25 and not s2.endswith('.')]
    ss = [s2 for s2 in ss if s2 not in ui]
    if ui:
        print("\n[화면 라벨] %d개는 버튼·항목 이름으로 보여 문장 길이 계측에서 뺐다." % len(ui))
    if ss:
        L = sorted(len(s) for s in ss)
        med = L[len(L) // 2]
        long_n = sum(1 for x in L if x > 160)
        short_n = sum(1 for x in L if x < 25)
        print("\n[문장 길이] 문장 %d개, 중앙값 %d자 (기준 74자, 정상대 54~100자)" % (len(ss), med))
        if med < 40:
            print("  ! 너무 짧다. 명사 나열·단답 문체일 가능성이 높다.")
        if med > 120:
            print("  ! 너무 길다. 한 문장에 여러 주장이 섞였을 가능성이 높다.")
        print("  - 160자 초과 문장 %d개, 25자 미만 문장 %d개" % (long_n, short_n))

    # 제목 검사
    heads = [l.strip() for l in text.split('\n') if l.strip().startswith('#')]
    if heads:
        bad = []
        for h in heads:
            body = re.sub(r'^#+\s*', '', h)
            if re.search(r'[—–]|->|→', body):
                bad.append((body, "줄표·화살표로 끊었다. 코퍼스 제목의 4.6%만 기호를 쓰고 대부분 범위 표시다"))
            elif re.search(r'다$', body):
                bad.append((body, "서술형 종결. 실측 제목의 2.6%뿐이고 77.2%가 명사 종결이다"))
            elif len(body) > 40:
                bad.append((body, "40자 초과. 실측 제목 90%가 41자 이내다"))
        print("\n[제목] %d개 검사" % len(heads))
        if bad:
            for b, why in bad:
                print("  ! %-34s %s" % (b[:34], why))
            print("  (제목은 경고만 낸다. 규칙서·지침서의 명령형 제목은 예외다.)")
        else:
            print("  이상 없음.")

    # 치환 뒤 남는 조사 오류
    JOSA_BAD = [("이유이", "이유가"), ("값이이", "값이"), ("것이이", "것이"),
                ("분류이", "분류가"), ("기준이이", "기준이"), ("구조이", "구조가"),
                ("을을", "을"), ("를를", "를")]
    found = [(a, b) for a, b in JOSA_BAD if a in scan]
    if found:
        print("\n[조사 오류] 낱말을 바꾼 뒤 조사가 남았다.")
        for a, b in found:
            print("  x %s  ->  %s" % (a, b))

    # 구어·겸양
    spoken = [w for w in ["같은데요", "인 것 같습니다", "해보았습니다", "살펴보겠습니다",
                          "알아보겠습니다", "정리해보면", "드리고자", "말씀드리면"] if w in text]
    if spoken:
        print("\n[구어·겸양] " + ", ".join(spoken))

    print("\n" + "=" * 62)
    if hits:
        print("판정: 내보내지 마라. 금지어 %d종을 먼저 고친다." % len(hits))
        return 1
    print("판정: 금지어 없음. 통과.")
    return 0

if __name__ == '__main__':
    sys.exit(main())

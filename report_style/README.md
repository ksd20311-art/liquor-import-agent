# deloitte-report-ko: 딜로이트형 한국어 보고서 스킬

Claude Code에서 쓰는 스킬이다. 조사·공시·설문 자료로 딜로이트 코리아 보고서 형식의 한국어 보고서(HTML, 인쇄하면 PDF)를 만든다.

## 설치

1. 이 폴더(`deloitte-report-ko`)를 내 프로젝트 폴더의 `.claude/skills/` 안에 넣는다. 폴더가 없으면 만든다.
   예: `내프로젝트/.claude/skills/deloitte-report-ko/SKILL.md`
2. Claude Code를 그 프로젝트 폴더에서 다시 연다.
3. 「사실 목록 facts.csv로 딜로이트 스타일 보고서를 만들어 줘」처럼 요청하면 스킬이 불린다.

## 폴더 구성

| 파일 | 내용 |
|---|---|
| `SKILL.md` | 보고서 뼈대, 제목·문장·그림표·판면 규칙, 만드는 순서, 완료 기준 |
| `assets/layout.md` | 딜로이트 보고서 482건의 쪽 크기·여백·글자 크기·글꼴·색·그림표 계측값 |
| `assets/titles.md` | 제목 10,192개 계측과 제목 짓는 절차 |
| `assets/narration.md` | 문장 47,348개 계측, 끝맺음, 문단 전개 순서 |
| `assets/banned_words.md` | 보고서에 쓰지 않는 표현과 실제 등장 횟수 |
| `scripts/check_korean.py` | 본문 검사기. `python3 scripts/check_korean.py 본문.txt` |
| `template/report.html` | A4 세로 보고서 틀(표지·요약·본문·시사점·출처) |

## 지킬 것

- 딜로이트 이름·로고·초록 브랜드색은 쓰지 않는다. 형식만 빌린다.
- 출처가 없는 숫자는 보고서에 넣지 않는다.
- 딜로이트 보고서 원본 PDF는 교수가 따로 준 Dropbox 링크에서 받는다. 이 스킬에는 원본이 들어 있지 않고 계측값만 들어 있다.

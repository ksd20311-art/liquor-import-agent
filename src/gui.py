"""입력 창: 제품명·현지 가격·구매 국가 3칸만 넣고 버튼을 누르면 리포트 PDF를 만든다.
주종·HS 코드·원산지·통화는 자동으로 정하고, 바꾸고 싶을 때만 [세부 설정]을 펼친다.
만든 후보는 [월간 알림에 등록]으로 저장해 두고 [월간 변동 확인]으로 환율·세율·현지가 변동을 본다.
실행: run_gui.bat 더블클릭 또는 python src/gui.py
"""
import os
import re
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fx  # noqa: E402
import intake  # noqa: E402
import main as agent  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COUNTRY_CHOICES = ["일본 (JP)", "프랑스 (FR)", "미국 (US)", "칠레 (CL)", "이탈리아 (IT)", "스페인 (ES)",
                   "독일 (DE)", "영국 (GB)", "아일랜드 (IE)", "호주 (AU)", "캐나다 (CA)", "뉴질랜드 (NZ)",
                   "중국 (CN)", "인도 (IN)", "튀르키예 (TR)", "베트남 (VN)", "멕시코 (MX)", "네덜란드 (NL)",
                   "벨기에 (BE)", "체코 (CZ)", "태국 (TH)", "필리핀 (PH)", "싱가포르 (SG)", "스웨덴 (SE)"]
TYPE_LABELS = {v: k for k, v in intake.TYPE_NAMES.items()}
YNU = ["모름", "예", "아니오"]
AUTO = "자동 인식"
MANUAL = "직접 입력…"
KIND_LABELS = {"소매가": "retail", "도매·견적가": "quote"}


def country_code(text: str) -> str:
    m = re.search(r"\(([A-Za-z]{2})\)", text or "")
    return m.group(1).upper() if m else intake.normalize_country(text or "")


def has_api_key() -> bool:
    return fx.has_api_key()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("수입 주류 원가·시장 리포트 에이전트")
        root.geometry("760x640")
        self.base_h = 640
        self.v = {k: tk.StringVar() for k in
                  ("name", "price", "country", "currency", "type", "hs", "origin", "volume", "abv",
                   "made", "cert", "domestic", "url", "fx", "margin", "kind")}
        self.v["country"].set(COUNTRY_CHOICES[0])
        self.v["type"].set(AUTO)
        self.v["hs"].set(AUTO)
        self.v["made"].set("모름")
        self.v["cert"].set("모름")
        self.v["kind"].set("소매가")
        self.last_inp = None
        self.force_sample = tk.BooleanVar(value=False)
        self.save_samples = tk.BooleanVar(value=False)
        self.show_adv = tk.BooleanVar(value=False)
        self.pdf = None
        self._build()
        self._on_country()

    # ---- 화면 ----
    def _row(self, parent, r, label, widget):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10), pady=4)
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    def _build(self):
        f = ttk.Frame(self.root, padding=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="제품명, 현지 가격, 구매 국가만 넣으면 나머지는 자동으로 정합니다.",
                  font=("", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        a = ttk.Frame(f)
        a.grid(row=1, column=0, sticky="ew")
        a.columnconfigure(1, weight=1)
        name = ttk.Entry(a, textvariable=self.v["name"])
        self._row(a, 0, "제품명", name)
        pk = ttk.Frame(a)  # 가격과 가격 종류를 한 줄에 둔다
        price = ttk.Entry(pk, textvariable=self.v["price"], width=22)
        price.pack(side="left")
        ttk.Label(pk, text="     가격 종류 ").pack(side="left")
        ttk.Combobox(pk, textvariable=self.v["kind"], values=list(KIND_LABELS), state="readonly", width=12).pack(side="left")
        self._row(a, 1, "현지 가격(숫자)", pk)
        cb = ttk.Combobox(a, textvariable=self.v["country"], values=COUNTRY_CHOICES)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_country())
        cb.bind("<FocusOut>", lambda e: self._on_country())
        self._row(a, 2, "구매 국가", cb)
        self.cur_label = ttk.Label(a, text="", foreground="#5f636a")
        self.cur_label.grid(row=3, column=1, sticky="w")
        self._row(a, 4, "주종", ttk.Combobox(a, textvariable=self.v["type"], values=[AUTO] + list(TYPE_LABELS), state="readonly"))
        hs_cb = ttk.Combobox(a, textvariable=self.v["hs"],
                             values=[AUTO] + [intake.hs_label(c) for c, _, _ in intake.HS_CHOICES] + [MANUAL])
        hs_cb.bind("<<ComboboxSelected>>", lambda e: self._on_hs_select(hs_cb))
        self._row(a, 5, "품목 코드(HS)", hs_cb)
        self.hs_hint = ttk.Label(a, text="", foreground="#b3541e", wraplength=700, justify="left")
        self.hs_hint.grid(row=11, column=0, columnspan=2, sticky="w")
        vm = ttk.Frame(a)  # 용량과 마진율을 한 줄에 둬서 창 높이를 늘리지 않는다
        ttk.Entry(vm, textvariable=self.v["volume"], width=10).pack(side="left")
        ttk.Label(vm, text="     마진율(%, 선택) ").pack(side="left")
        ttk.Entry(vm, textvariable=self.v["margin"], width=8).pack(side="left")
        ttk.Label(vm, text=" 비우면 30% 가정", foreground="#5f636a").pack(side="left")
        self._row(a, 6, "용량(ml, 맥주·탁주는 필수)", vm)
        self._row(a, 7, "FTA 질문 1: 원산지 국가에서 생산된 제품인가",
                  ttk.Combobox(a, textvariable=self.v["made"], values=YNU, state="readonly", width=10))
        self._row(a, 8, "FTA 질문 2: 거래처가 원산지증명서를 발급할 수 있나",
                  ttk.Combobox(a, textvariable=self.v["cert"], values=YNU, state="readonly", width=10))
        ttk.Label(a, text="FTA 판정: 둘 다 「예」(구매국=원산지)이면 협정세율 적용 가능 / 하나라도 「아니오」이면 일반세율 / "
                          "「모름」이면 협정·일반 두 원가를 나란히 표시(확인 필요)",
                  foreground="#b3541e", wraplength=700, justify="left").grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(a, text="주종·품목 코드는 제품명·브랜드로 자동 인식합니다(모르면 주종을 고르거나 코드를 선택·직접 입력). "
                          "용량은 이름에 없으면 입력해야 가격 위치를 계산합니다. "
                          "마진율은 도착 원가에 붙일 마진으로, 예상 소비자가 = 도착 원가 × (1 + 마진율)입니다.",
                  foreground="#5f636a", wraplength=700, justify="left").grid(row=10, column=0, columnspan=2, sticky="w", pady=(2, 0))
        for w_ in (name, price):
            w_.bind("<Return>", lambda e: self.on_generate())
        name.focus_set()

        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="ew", pady=10)
        ttk.Checkbutton(bar, text="세부 설정 보기", variable=self.show_adv, command=self._toggle_adv).pack(side="left")
        self.mode_label = ttk.Label(bar, text="", foreground="#5f636a")
        self.mode_label.pack(side="left", padx=14)
        ttk.Button(bar, text="리포트 만들기", command=self.on_generate).pack(side="right")

        # 세부 설정은 메인 창을 키우지 않도록 별도 작은 창으로 띄운다(화면 배율이 커도 넘치지 않음)
        self.adv_win = tk.Toplevel(self.root)
        self.adv_win.title("세부 설정 (비워 두면 자동)")
        self.adv_win.geometry("600x460")
        self.adv_win.withdraw()
        self.adv_win.protocol("WM_DELETE_WINDOW", self._close_adv)
        self.adv = ttk.Frame(self.adv_win, padding=14)
        self.adv.pack(fill="both", expand=True)
        self.adv.columnconfigure(1, weight=1)
        ttk.Button(self.adv, text="제품명으로 제안 받기", command=self.suggest).grid(row=0, column=1, sticky="w", pady=3)
        self._row(self.adv, 1, "통화", ttk.Entry(self.adv, textvariable=self.v["currency"], width=10))
        self._row(self.adv, 4, "원산지 국가 코드", ttk.Entry(self.adv, textvariable=self.v["origin"], width=10))
        self._row(self.adv, 5, "도수(%)", ttk.Entry(self.adv, textvariable=self.v["abv"], width=10))
        self._row(self.adv, 8, "국내 판매가(원)", ttk.Entry(self.adv, textvariable=self.v["domestic"]))
        self._row(self.adv, 9, "가격 출처 URL", ttk.Entry(self.adv, textvariable=self.v["url"]))
        self._row(self.adv, 12, "과세환율 직접 입력(원/1통화)", ttk.Entry(self.adv, textvariable=self.v["fx"], width=14))
        ttk.Checkbutton(self.adv, text="샘플 모드로 실행(저장된 API 응답 사용)", variable=self.force_sample).grid(row=10, column=1, sticky="w", pady=3)
        ttk.Checkbutton(self.adv, text="받은 API 응답을 샘플로 저장(키 없는 PC에서 같은 제품 재현용)", variable=self.save_samples).grid(row=11, column=1, sticky="w", pady=3)

        self.out = tk.Text(f, height=6, wrap="word", state="disabled")
        self.out.grid(row=4, column=0, sticky="nsew")
        f.rowconfigure(4, weight=1)
        e = ttk.Frame(f)
        e.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.btn_pdf = ttk.Button(e, text="PDF 열기", command=self.open_pdf, state="disabled")
        self.btn_pdf.pack(side="left")
        ttk.Button(e, text="결과 폴더 열기", command=self.open_folder).pack(side="left", padx=6)
        ttk.Button(e, text="월간 변동 확인", command=self.open_watch).pack(side="right")
        self.btn_watch = ttk.Button(e, text="월간 알림에 등록", command=self.add_watch, state="disabled")
        self.btn_watch.pack(side="right", padx=6)

    def _pair(self, parent):
        fr = ttk.Frame(parent)
        ttk.Entry(fr, textvariable=self.v["volume"], width=8).pack(side="left")
        ttk.Label(fr, text=" / ").pack(side="left")
        ttk.Entry(fr, textvariable=self.v["abv"], width=8).pack(side="left")
        return fr

    def _on_hs_select(self, combo):
        """목록에서 「직접 입력…」을 고르면 칸을 비우고 바로 10자리를 칠 수 있게 한다."""
        if self.v["hs"].get() == MANUAL:
            self.v["hs"].set("")
            combo.focus_set()
            combo.icursor("end")
            self.hs_hint.configure(text="품목 코드(HS) 10자리를 직접 입력하세요(예: 2208309000). 위스키 2208.30·와인 2204.21/22/29·청주 2206.00.2010 계열을 쓸 수 있습니다.")
        else:
            self.hs_hint.configure(text="")

    def _toggle_adv(self):
        """「세부 설정 보기」를 켜면 별도 창을 열고, 끄면 닫는다."""
        if self.show_adv.get():
            self.adv_win.deiconify()
            self.adv_win.lift()
            self.root.update_idletasks()
            self.adv_win.geometry(f"+{self.root.winfo_x() + 60}+{max(self.root.winfo_y() + 40, 0)}")
        else:
            self.adv_win.withdraw()

    def _close_adv(self):
        self.show_adv.set(False)
        self.adv_win.withdraw()

    def _on_country(self):
        code = country_code(self.v["country"].get())
        cur = intake.CURRENCY_BY_COUNTRY.get(code, "")
        if not self.v["currency"].get() or self.v["currency"].get() in intake.CURRENCY_BY_COUNTRY.values():
            self.v["currency"].set(cur)
        self.cur_label.configure(text=f"통화: {self.v['currency'].get() or '확인 필요'} (국가에서 자동)")
        live = has_api_key()
        self.mode_label.configure(text="실시간 모드(API 키 있음)" if live else "샘플 모드(API 키 없음, 저장된 응답 사용)")

    def _say(self, text: str):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", text)
        self.out.configure(state="disabled")

    # ---- 동작 ----
    def suggest(self):
        name = self.v["name"].get().strip()
        if not name:
            messagebox.showinfo("안내", "제품명을 먼저 입력해 주세요.")
            return
        country = country_code(self.v["country"].get())
        s = intake.suggest_product(name, country)
        if s["unsupported"]:
            messagebox.showinfo("안내", f"「{s['unsupported']}」 계열은 지원 주종({intake.SUPPORTED_TEXT})이 아닙니다.")
            return
        self.v["type"].set(next((k for k, x in TYPE_LABELS.items() if x == s["liquor_type"]), AUTO))
        self.v["hs"].set(intake.hs_label(s["hs_code"]) if s["hs_code"] else AUTO)
        self.v["origin"].set(s["origin_country"])
        self.v["volume"].set("" if s["volume_ml"] is None else str(s["volume_ml"]))
        self.v["abv"].set("" if s["abv_percent"] is None else f"{s['abv_percent']:g}")
        self._say("제안값을 채웠습니다. 확인하고 필요하면 고친 뒤 [리포트 만들기]를 누르세요.")

    def collect(self) -> dict:
        v = {k: x.get().strip() for k, x in self.v.items()}
        v["type"] = TYPE_LABELS.get(v["type"], "")
        v["kind"] = KIND_LABELS.get(v["kind"], "retail")
        if v["country"]:
            v["country"] = country_code(v["country"]) or v["country"]
        if v["origin"]:
            v["origin"] = country_code(v["origin"]) or v["origin"]
        try:
            return intake.build_from_form(v)
        except ValueError as e:
            if "통화를 알 수 없습니다" in str(e):  # 통화 칸이 있는 세부 설정 창을 열어 준다
                self.show_adv.set(True)
                self._toggle_adv()
            raise

    def generate(self, sample: bool = None) -> list:
        """입력 검증 후 리포트를 만들고 요약 문장 목록을 돌려준다. 예외는 호출한 쪽에서 처리."""
        inp = self.collect()
        use_sample = (self.force_sample.get() or not has_api_key()) if sample is None else sample
        result = agent.build_result(inp, use_sample, self.save_samples.get())
        self.pdf = agent.write_outputs(inp, result, ROOT / "outputs" / "runs" / inp["report_name"])
        self.last_inp, self.last_sample = inp, use_sample
        auto = (f"자동으로 정한 값: 주종 {intake.TYPE_NAMES[inp['liquor_type']]}, HS 코드 {inp['hs_code']}, "
                f"원산지 {inp['origin_country']}, 증명서 응답 「{inp['has_certificate']}」"
                + ("" if inp["info_confirmed"] else " (주종·코드는 화면에서 확인·수정 가능)"))
        return [auto] + agent.summary_lines(result)

    def on_generate(self):
        self._say("계산 중입니다...")
        self.root.update_idletasks()
        try:
            lines = self.generate()
        except (ValueError, agent.AgentError, RuntimeError) as e:
            self._say(f"중단: {e}")
            messagebox.showerror("입력 확인", str(e))
            return
        except Exception as e:  # 예기치 못한 오류도 화면에 보여 준다
            self._say(f"오류: {type(e).__name__}: {e}")
            messagebox.showerror("오류", f"{type(e).__name__}: {e}")
            return
        self._say("리포트를 만들었습니다.\n" + f"파일: {self.pdf}\n\n" + "\n".join(lines))
        self.btn_pdf.configure(state="normal")
        self.btn_watch.configure(state="normal")
        self.open_pdf()

    # ---- 월간 알림 ----
    def add_watch(self):
        """방금 리포트를 만든 후보를 월간 알림에 등록한다(지금의 환율·세율·현지가가 비교 기준)."""
        import watch
        if not self.last_inp:
            messagebox.showinfo("안내", "먼저 [리포트 만들기]로 후보를 계산해 주세요.")
            return
        try:
            item = watch.add(self.last_inp, self.last_sample)
        except (agent.AgentError, RuntimeError, ValueError) as e:
            messagebox.showerror("등록 실패", str(e))
            return
        b = item["baseline"]
        self._say(f"월간 알림에 등록했습니다: [{item['id']}] {item['name']}\n"
                  f"기준 원가 {agent.won(b['landed_main']):,}원({b['scenario']}), 과세환율 {b['fx_rate']}원/{b['currency']}, "
                  f"현지가 {b['local_price']:,.10g}{b['currency']}\n"
                  "[월간 변동 확인]을 누르면 등록 시점 대비 변동과 원인(환율·세율·현지가)을 알림 리포트로 봅니다.")

    def open_watch(self):
        """등록 목록 창: 후보별 현지가를 고치고(선택) 변동을 확인한다."""
        import watch
        data = watch.load()
        win = tk.Toplevel(self.root)
        win.title("월간 변동 확인")
        win.geometry("720x420")
        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        if not data["items"]:
            ttk.Label(f, text="등록한 후보가 없습니다.\n리포트를 만든 뒤 [월간 알림에 등록]을 눌러 주세요.", justify="left").grid(row=0, column=0, sticky="w")
            return
        ttk.Label(f, text="등록 시점 원가와 지금 원가를 견줘 ±5% 이상 움직이면 알림으로 표시합니다. "
                          "현지가는 자동으로 모으지 않으니, 바뀐 후보는 「새 현지가」 칸에 넣어 주세요(비우면 그대로).",
                  wraplength=680, justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for col, head in enumerate(("후보", "등록일 · 기준 원가", "현지가", "새 현지가")):
            ttk.Label(f, text=head, font=("", 9, "bold")).grid(row=1, column=col, sticky="w", padx=(0, 10))
        entries = {}
        for i, x in enumerate(data["items"], start=2):
            b = x["baseline"]
            ttk.Label(f, text=f"[{x['id']}] {x['name'][:34]}").grid(row=i, column=0, sticky="w", padx=(0, 10), pady=2)
            ttk.Label(f, text=f"{x['registered_at']} · {agent.won(b['landed_main']):,}원").grid(row=i, column=1, sticky="w", padx=(0, 10))
            ttk.Label(f, text=f"{x['input']['local_price']:,.10g} {b['currency']}").grid(row=i, column=2, sticky="w", padx=(0, 10))
            var = tk.StringVar()
            ttk.Entry(f, textvariable=var, width=12).grid(row=i, column=3, sticky="w")
            entries[x["id"]] = var
        out = tk.Text(f, height=8, wrap="word", state="disabled")
        out.grid(row=len(data["items"]) + 3, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        f.rowconfigure(len(data["items"]) + 3, weight=1)

        def say(text):
            out.configure(state="normal")
            out.delete("1.0", "end")
            out.insert("end", text)
            out.configure(state="disabled")

        def run():
            say("확인 중입니다...")
            win.update_idletasks()
            try:
                for wid, var in entries.items():
                    if var.get().strip():
                        watch.update_price(wid, var.get().strip())
                sample = self.force_sample.get() or not has_api_key()
                results = watch.check(sample)
                day = next((r["record"]["checked_at"] for r in results if "record" in r), date.today().isoformat())
                rep = watch.write_report(results, day)
            except (agent.AgentError, RuntimeError, ValueError) as e:
                say(f"중단: {e}")
                return
            say("\n".join(watch.console_lines(results)) + f"\n\n알림 리포트: {rep['pdf'] or rep['html']}")
            os.startfile(rep["pdf"] or rep["html"])

        ttk.Button(f, text="변동 확인하고 알림 리포트 만들기", command=run).grid(row=len(data["items"]) + 2, column=0, columnspan=4, sticky="e", pady=(8, 0))

    def open_pdf(self):
        if self.pdf and Path(self.pdf).exists():
            os.startfile(self.pdf)

    def open_folder(self):
        folder = ROOT / "outputs"
        if folder.exists():
            os.startfile(folder)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

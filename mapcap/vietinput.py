"""Gõ tiếng Việt ngay trong ô nhập của app (Telex / VNI), không cần bộ gõ ngoài.

Vì sao cần: AoE-MapCap chạy quyền Admin (để đọc bộ nhớ game) còn UniKey / EVKey thường chạy quyền thường; Windows
(UIPI) chặn chương trình quyền thường gửi phím vào cửa sổ quyền Admin nên gõ "aa" vẫn ra "aa" (người dùng 13/11/2026: ô
ghi chú báo cáo hack không gõ được tiếng Việt). App tự ghép dấu theo đúng kiểu gõ đang đặt trong UniKey (đọc registry
HKCU\\Software\\PkLong\\UniKey: InputMethod 0 = Telex, 1 = VNI; ModernStyle = kiểu bỏ dấu oà / uý), mặc định Telex.

    compose(word, key, method, modern) -> từ mới, hoặc None nếu phím không tạo dấu (cứ chèn phím như thường)
    attach(widget)                      -> gắn vào tk.Text / ttk.Entry

Nếu bộ gõ ngoài vẫn gửi được chữ có dấu (UniKey chạy quyền Admin) thì ô nhập nhận ký tự ngoài ASCII: app thôi tự ghép
để không ghép hai lần.
"""
TONES = {"a": "aáàảãạ", "ă": "ăắằẳẵặ", "â": "âấầẩẫậ", "e": "eéèẻẽẹ", "ê": "êếềểễệ", "i": "iíìỉĩị",
         "o": "oóòỏõọ", "ô": "ôốồổỗộ", "ơ": "ơớờởỡợ", "u": "uúùủũụ", "ư": "ưứừửữự", "y": "yýỳỷỹỵ"}
REV = {ch: (base, t) for base, forms in TONES.items() for t, ch in enumerate(forms)}
MARKED = "ăâêôơư"
TELEX_TONE = {"s": 1, "f": 2, "r": 3, "x": 4, "j": 5, "z": 0}
VNI_TONE = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "0": 0}
HAT = {"a": "â", "e": "ê", "o": "ô"}             # Telex aa ee oo, VNI 6
HORN = {"o": "ơ", "u": "ư"}                        # Telex w, VNI 7
BREVE = {"a": "ă"}                                 # Telex w, VNI 8
UNMARK = {"â": "a", "ê": "e", "ô": "o", "ơ": "o", "ư": "u", "ă": "a"}
MAX_WORD = 12


def _parse(word):
    """-> ([chữ gốc thường], [hoa?], thanh của từ (0 = không))."""
    bases, upper, tone = [], [], 0
    for ch in word:
        lo = ch.lower()
        b, t = REV.get(lo, (lo, 0))
        bases.append(b)
        upper.append(ch != lo)
        tone = tone or t
    return bases, upper, tone


def _cluster(bases):
    """Chỉ số các nguyên âm của cụm nguyên âm cuối (bỏ u của "qu", i của "gi" khi còn nguyên âm khác)."""
    end = len(bases)
    while end > 0 and bases[end - 1] not in TONES:
        end -= 1
    start = end
    while start > 0 and bases[start - 1] in TONES:
        start -= 1
    cl = list(range(start, end))
    if len(cl) > 1 and start > 0 and ((bases[start] == "u" and bases[start - 1] == "q") or
                                      (bases[start] == "i" and bases[start - 1] == "g")):
        cl = cl[1:]
    return cl


def _tone_pos(bases, cl, modern):
    marked = [i for i in cl if bases[i] in MARKED]
    if marked:
        return marked[-1]                           # ươ -> ơ, uô -> ô, ưa -> ư
    if len(cl) == 1:
        return cl[0]
    if len(cl) == 2:
        if cl[-1] < len(bases) - 1:                 # có phụ âm cuối: toán, hoàn
            return cl[1]
        pair = bases[cl[0]] + bases[cl[1]]
        return cl[1] if modern and pair in ("oa", "oe", "uy") else cl[0]     # kiểu cũ: hòa, thủy; kiểu mới: hoà, thuỷ
    return cl[1]                                    # oai, uya...: nguyên âm giữa


def _build(bases, upper, tone, modern):
    cl = _cluster(bases)
    pos = _tone_pos(bases, cl, modern) if (tone and cl) else -1
    out = []
    for i, b in enumerate(bases):
        ch = TONES[b][tone] if i == pos else b
        out.append(ch.upper() if upper[i] else ch)
    return "".join(out)


def compose(word, key, method="telex", modern=False):
    """Ghép phím `key` vào `word` (từ đang gõ, không có khoảng trắng). Trả từ mới nếu phím tạo / đổi / gỡ dấu, None nếu
    phím không liên quan (người gọi cứ chèn phím). Gõ lặp phím dấu thì gỡ dấu và ra chính phím đó (aaa -> aa, ass -> as)."""
    if not word or len(key) != 1 or len(word) > MAX_WORD or not all(c.isalpha() for c in word):
        return None
    k = key.lower()
    bases, upper, tone = _parse(word)
    cl = _cluster(bases)
    telex = method != "vni"

    # ---- thanh
    tones = TELEX_TONE if telex else VNI_TONE
    if k in tones:
        t = tones[k]
        if not cl:
            return None
        if t == 0:
            return _build(bases, upper, 0, modern) if tone else None
        if t == tone:                               # lặp: gỡ thanh, ra phím
            return _build(bases, upper, 0, modern) + key
        return _build(bases, upper, t, modern)

    # ---- đ
    if (telex and k == "d") or (not telex and k == "9"):
        if "đ" in bases:
            i = bases.index("đ")
            bases[i] = "d"
            return _build(bases, upper, tone, modern) + key
        if "d" in bases and (bases[0] == "d" or not telex):
            bases[bases.index("d")] = "đ"
            return _build(bases, upper, tone, modern)
        return None

    # ---- mũ (â ê ô) / móc (ơ ư) / trăng (ă): áp vào cụm nguyên âm cuối; đã có đúng dấu đó thì gỡ và ra phím
    bs = [bases[i] for i in cl]

    def done():
        return _build(bases, upper, tone, modern)

    def last(ch):
        return cl[len(bs) - 1 - bs[::-1].index(ch)] if ch in bs else None

    def undo(marks):
        hit = [i for i in cl if bases[i] in marks]
        if not hit:
            return None
        for i in hit:
            bases[i] = UNMARK[bases[i]]
        return done() + key

    def hat(targets):
        cand = [i for i in cl if bases[i] in targets]
        if cand:
            bases[cand[-1]] = HAT[bases[cand[-1]]]
            return done()
        return undo([HAT[t] for t in targets])

    def horn(with_breve):
        for j in range(len(cl) - 1):                # uo -> ươ, ưo -> ươ
            if bs[j] in "uư" and bs[j + 1] == "o":
                bases[cl[j]], bases[cl[j + 1]] = "ư", "ơ"
                return done()
        if with_breve and "a" in bs:                # Telex w: mua -> mưa (u đứng trước a cuối từ), còn lại a -> ă
            i = last("a")
            j = cl.index(i)
            if j > 0 and bs[j - 1] == "u" and i == len(bases) - 1:
                bases[cl[j - 1]] = "ư"
            else:
                bases[i] = "ă"
            return done()
        if "o" in bs:
            bases[last("o")] = "ơ"
            return done()
        if "u" in bs and "ư" not in bs:
            bases[cl[bs.index("u")]] = "ư"          # uu -> ưu (lưu)
            return done()
        return undo("ơưă" if with_breve else "ơư")

    if telex:
        if k in HAT:                                # aa, ee, oo
            return hat(k)
        if k == "w":
            return horn(True)
        return None
    if k == "6":
        return hat("aeo")
    if k == "7":
        return horn(False)
    if k == "8":
        if "a" in bs:
            bases[last("a")] = "ă"
            return done()
        return undo("ă")
    return None


def unikey_settings():
    """(kiểu gõ, bỏ dấu kiểu mới?) theo UniKey trên máy; không đọc được: Telex, kiểu cũ."""
    method, modern = "telex", False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\PkLong\UniKey") as k:
            try:
                method = "vni" if int(winreg.QueryValueEx(k, "InputMethod")[0]) == 1 else "telex"
            except (OSError, ValueError, TypeError):
                pass
            try:
                modern = bool(int(winreg.QueryValueEx(k, "ModernStyle")[0]))
            except (OSError, ValueError, TypeError):
                pass
    except (OSError, ImportError):
        pass
    return method, modern


class VietInput:
    """Gắn bộ gõ vào một tk.Text hoặc ttk.Entry / tk.Entry. `enabled` (hàm -> bool) cho ô tích bật / tắt."""

    def __init__(self, widget, enabled=None, method=None, modern=None):
        m, md = unikey_settings()
        self.w = widget
        self.method = method or m
        self.modern = md if modern is None else modern
        self.enabled = enabled or (lambda: True)
        self.external = False            # bộ gõ ngoài đang gửi được chữ có dấu: thôi tự ghép
        self.is_text = widget.winfo_class() == "Text"
        widget.bind("<KeyPress>", self._key, add="+")

    def _word(self):
        w = self.w
        if self.is_text:
            if w.tag_ranges("sel"):
                return None
            line = w.get("insert linestart", "insert")
        else:
            if w.selection_present():
                return None
            line = w.get()[:w.index("insert")]
        n = 0
        while n < len(line) and n < MAX_WORD and line[len(line) - 1 - n].isalpha():
            n += 1
        return line[len(line) - n:] if n else ""

    def _key(self, e):
        ch = e.char
        if not ch or len(ch) != 1:
            return None
        if ord(ch) > 127:                # chữ có dấu tới từ bộ gõ ngoài
            self.external = True
            return None
        if self.external or not self.enabled() or (e.state & 0x4) or (e.state & 0x20000) or not ch.isprintable():
            return None                  # Ctrl / Alt
        word = self._word()
        if not word:
            return None
        new = compose(word, ch, self.method, self.modern)
        if new is None:
            return None
        w = self.w
        if self.is_text:
            w.delete(f"insert - {len(word)} chars", "insert")
            w.insert("insert", new)
            w.see("insert")
        else:
            i = w.index("insert")
            w.delete(i - len(word), i)
            w.insert(i - len(word), new)
        return "break"


def attach(widget, enabled=None, method=None, modern=None):
    return VietInput(widget, enabled, method, modern)

"""檢查內容檔與網站是否符合AGENTS.md的規則。規則代碼R01–R21對應AGENTS.md第11節。

用法：
  python3 tools/check.py                    # 全部檢查（內容檔、log.md、原始資料、docs/是否最新）
  python3 tools/check.py content/窩.md       # 只檢查一個內容檔（聊天介面寫好的檔案先用這個）
  python3 tools/check.py --no-docs          # 不檢查docs/（build.py建置前用）
有錯誤時結束代碼是1。
"""
from __future__ import annotations

import argparse
import filecmp
import re
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from datetime import date
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas  # noqa: E402

PROPORTION_WORDS = ["絕大多數", "大多數", "大部分", "大多", "多數", "多半", "集中", "幾乎", "普遍", "少數", "居多",
                    "很多", "許多", "不少"]
QUOTE_RE = re.compile(r"「([^「」]*)」")
OLD_TERMS = ("番", "山胞", "土著")      # 原住民族的舊稱
OLD_TERM_OK_RE = re.compile("番薯|番茄|番麥|番石榴")     # 含「番」但不是舊稱的詞
CN_NUM = "一二三四五六七八九十百千萬兩幾"
# 國字數量：量詞含縣市、縣、市、鄉、鎮，另外抓「一半」「X分之」。前面是「第」或數字時不算，
# 「第二個」「第十二個」這類序數才不會從中間的「二個」開始比對
CN_QTY_RE = re.compile(
    rf"(?<![第{CN_NUM}])(?:[{CN_NUM}]+[多餘]?(?:處|個|筆|座|成|倍|縣市|縣|市|鄉|鎮)|一半|[{CN_NUM}]+分之)")
LONE_ONE_RE = re.compile(r"一(?:處|個|筆|座|縣市|縣|市|鄉|鎮)")       # 前面是「每」「同」時（每一處、同一個）不是在講數量
LONE_ONE_OK = ("每", "同")
# 一個標記代表兩個縣市（鄉鎮）：副詞和標記之間可以隔0–4個不是標點的字，例如「都超過{{比例:A}}」
SHARED_PH_RE = re.compile(
    r"(皆|都|均|各|同樣|一樣)[^，。、：；！？「」『』（）{}｛｝\s]{0,4}\{\{\s*(縣市|比例|占總數|鄉鎮)\s*[:：]([^{}]*)\}\}")
RANK_SENT_RE = re.compile(r"[^。！？]*[。！？]?")      # R21的句子只用。！？切，分句再用，：；切
CJK = r"㐀-鿿"
SHORT_COUNTIES = ["基隆", "臺北", "台北", "新北", "桃園", "新竹", "苗栗", "臺中", "台中", "彰化", "南投", "雲林", "嘉義",
                  "臺南", "台南", "高雄", "屏東", "宜蘭", "花蓮", "臺東", "台東", "澎湖", "金門", "連江"]
SHORT_COUNTY_RE = re.compile("(" + "|".join(SHORT_COUNTIES) + ")(?![縣市])")
EMOJI_RE = re.compile("[\u2600-\u27BF\u2B00-\u2BFF\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF]")
LOG_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (新增|修改|規則|程式|資料)｜(.+?)\s*$")
LOG_ACTIONS = "新增、修改、規則、程式、資料"

HINTS = {
    "R01": "檔名要是content/<字>.md，並和前置資料的「字」一致。",
    "R02": "前置資料照AGENTS.md第5.1節：兩條---之間，一行一個「欄位: 值」。",
    "R03": "換一個資料裡至少有20處的字（用tools/prepare.py看數量）。",
    "R04": "分類只能用：" + "、".join(atlas.CATEGORIES) + "。",
    "R05": "標題最多12字、不加標點；摘要只寫一句、以「。」結尾、最多60字。",
    "R06": "相關字用「、」分隔，每個是單一漢字，不能和本字相同，而且資料裡至少20處（以後才能做成頁面）。",
    "R07": "日期寫成YYYY-MM-DD，更新日期不能早於建立日期。",
    "R08": "段落只能是「## 字義」「## 分布」「## 代表地名」「## 延伸觀察」，照這個順序，前三個必填。",
    "R09": "字義80–300字、分布60–300字、延伸觀察最多300字（數字標記算2字）。",
    "R10": "代表地名3–6個，每行「- P編號 地名（縣市鄉鎮）」，從資料包第5節抄；要含本字、有由來、至少兩個縣市，地名和村里沒有缺字（?）。",
    "R11": "只能用AGENTS.md第5.3節的數字標記，縣市寫全名、鄉鎮寫成縣市＋鄉鎮；一個標記只代表它寫的縣市，兩個縣市要各寫一個；資料包提醒缺字偏多時，分布段要用{{缺字}}說明。",
    "R12": "數量一律用數字標記；年代等數字只能出現在「」逐字引用裡；不要寫「三百多處」「九成」這類國字數量。地名和引文裡的國字照寫，「每一處」「同一個」可以寫；要說幾個縣市，就直接列出縣市名。",
    "R13": "「」裡只能放：本字、單一漢字、相關字、資料裡的地名、同一段{{由來含:詞}}的詞，或本頁代表地名由來的逐字片段（原文的「」改成『』）；引文要接在它出自的那一處後面，不要引用有缺字（?）的片段。",
    "R14": "縣市寫全名；摘要、分布、延伸觀察提到資料包標「可直接提」以外的縣市，同一段要附上它的{{縣市:X}}或{{比例:X}}（同一段有{{鄉鎮:X}}標記的鄉鎮名稱不算）。",
    "R15": "用到" + "、".join(PROPORTION_WORDS) + "的句子，要有數字標記支撐。",
    "R16": "用「臺」不用「台」；中文和英數字、數字標記之間不空格；用全形標點；不要HTML、Markdown粗體、連結、emoji；「番」「山胞」「土著」只出現在引號裡。",
    "R20": "AGENTS.md第5.5節的範例要和content/窩.md完全相同；第2節的筆數和第5.3節例子的值要和資料一致；第6節R15的詞要和check.py一致。改了其中一邊就同步另一邊。",
    "R21": "「最多」「最高」「最少」「最低」說的縣市或鄉鎮，要和資料包第2、3節的表一致（比例只算至少5處的縣市）；並列的都要寫出來。",
    "R17": "在log.md最後加一筆「## [YYYY-MM-DD] 新增｜<字>」，修改既有字用「## [YYYY-MM-DD] 修改｜<字>」；"
           "下一行用「- 」寫一句說明，日期依序往下。動作只用" + LOG_ACTIONS + "。",
    "R18": "不要修改data/raw/的檔案；若是換新版資料，照AGENTS.md第9節更新data/SOURCE.md。",
    "R19": "執行python3 tools/build.py重新產生docs/，不要手改docs/。",
}


@dataclass
class Problem:
    path: str
    line: int
    code: str
    msg: str
    level: str = "錯誤"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(atlas.ROOT))
    except ValueError:
        return str(path)


def strip_quotes(text: str) -> str:
    return QUOTE_RE.sub("", text)


def strip_ph(text: str) -> str:
    return atlas.PH_RE.sub("", text)


def mask_quotes(text: str) -> str:
    """「」裡的文字換成等長的〇；切句、分句、找地名時，引號裡的字才不會被當成說明文字。"""
    return QUOTE_RE.sub(lambda m: "「" + "〇" * len(m.group(1)) + "」", text)


def mask_ph(text: str) -> str:
    """數字標記整個換成等長的〇，位置和原文對得上。"""
    return atlas.PH_RE.sub(lambda m: "〇" * len(m.group(0)), text)


def mask_names(text: str, pattern: Optional[re.Pattern]) -> str:
    return pattern.sub(lambda m: "〇" * len(m.group(0)), text) if pattern else text


def names_re(names) -> Optional[re.Pattern]:
    """比對一組名稱的正規式，長的先比。"""
    names = sorted(set(names), key=len, reverse=True)
    return re.compile("|".join(map(re.escape, names))) if names else None


def spans(text: str, delims: str):
    """依delims切開，回傳每一段的(起點, 終點)，不含切開用的標點，和re.split的切法相同。"""
    out, start = [], 0
    for m in re.finditer(f"[{delims}]", text):
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(text)))
    return out


def context(text: str, start: int, end: int, width: int = 6) -> str:
    """錯誤訊息用的前後文：start到end前後各width個字，不切斷數字標記。"""
    a, b = max(0, start - width), min(len(text), end + width)
    for m in atlas.PH_RE.finditer(text):
        if m.start() < a < m.end():
            a = m.start()
        if m.start() < b < m.end():
            b = m.end()
    return ("…" if a > 0 else "") + text[a:b] + ("…" if b < len(text) else "")


def unique(items) -> list:
    return list(dict.fromkeys(items))


@lru_cache(maxsize=1)
def town_re() -> Optional[re.Pattern]:
    """資料裡的鄉鎮全名（縣市＋鄉鎮，例如新北市新店區）。"""
    return names_re(atlas.town_names())


@lru_cache(maxsize=1)
def short_county_mask_re() -> Optional[re.Pattern]:
    """比對縣市簡稱前要遮掉的名稱：比簡稱長、又含簡稱的地名（例如澎湖厝、新北投）和鄉鎮全名。
    地名剛好等於簡稱的（例如桃園、雲林）不遮，「數量最多的是雲林」才抓得到。"""
    longer = {n for n in atlas.all_place_names() if any(s in n and len(n) > len(s) for s in SHORT_COUNTIES)}
    return names_re(longer | set(atlas.town_names()))


def village_names() -> set:
    out = set()
    for p in atlas.load_places():
        out.update(v for v in re.split(r"[,，、\s]+", p.village) if v)
    return out


@lru_cache(maxsize=1)
def tai_names_re() -> Optional[re.Pattern]:
    """資料裡含「台」的地名（例如砲台、台北街仔），寫地名時不算「台」。"""
    return names_re(n for n in set(atlas.all_place_names()) | village_names() if "台" in n)


def pick_place(cands: List[atlas.Place], before: str) -> List[atlas.Place]:
    """同名的代表地名：看地名前面緊接的是哪一處的縣市＋鄉鎮、鄉鎮或縣市；判斷不出來就全部都算。"""
    if len(cands) > 1:
        for key in (lambda p: p.county + p.town, lambda p: p.town, lambda p: p.county):
            hit = [p for p in cands if before.endswith(key(p))]
            if hit:
                return hit
    return cands


def prose_blocks(doc: atlas.Doc):
    """要檢查文字規則的區塊：(行號, 欄位或段落名稱, 文字)。"""
    if "摘要" in doc.meta:
        v, ln = doc.meta["摘要"]
        yield ln, "摘要", v
    for sec in doc.sections:
        if sec.title in ("字義", "分布", "延伸觀察"):
            for ln, text in sec.paragraphs:
                yield ln, sec.title, text


def check_doc(path: Path) -> List[Problem]:
    doc = atlas.parse_doc(path)
    P: List[Problem] = []
    rp = rel(path)

    def add(line, code, msg, level="錯誤"):
        P.append(Problem(rp, line, code, msg, level))

    for ln, code, msg in doc.problems:
        add(ln, code, msg)

    # R02欄位
    for k, (_, ln) in doc.meta.items():
        if k not in atlas.META_KEYS:
            add(ln, "R02", f"不認得的欄位「{k}」，可用的欄位：{'、'.join(atlas.META_KEYS)}")
    for k in atlas.REQUIRED_META:
        if not doc.get(k):
            add(1, "R02", f"缺少必填欄位「{k}」")
    char = doc.char
    # R01、R03字
    if char and path.stem != char:
        add(doc.meta["字"][1], "R01", f"檔名是「{path.name}」，但「字」寫的是「{char}」")
    if path.parent.resolve() != atlas.CONTENT_DIR.resolve():
        add(1, "R01", "內容檔要放在content/資料夾")
    st = None
    if char:
        if not (1 <= len(char) <= 2 and all(atlas.HAN_RE.fullmatch(c) for c in char)):
            add(doc.meta["字"][1], "R03", f"「字」要是一到兩個漢字：{char}")
        else:
            st = atlas.char_stats(char)
            if st.total < atlas.MIN_PLACES:
                add(doc.meta["字"][1], "R03", f"含「{char}」的聚落只有{st.total}處，少於{atlas.MIN_PLACES}處")
    # R04
    if doc.get("分類") and doc.get("分類") not in atlas.CATEGORIES:
        add(doc.meta["分類"][1], "R04", f"分類「{doc.get('分類')}」不在規定的類別裡")
    # R05
    title = doc.get("標題")
    if title:
        ln = doc.meta["標題"][1]
        if len(title) > 12:
            add(ln, "R05", f"標題有{len(title)}字，最多12字")
        if re.search(r"[，。、：；！？「」『』（）,.:;!?(){}｛｝]", title):     # 含{}：標題不寫數字標記
            add(ln, "R05", "標題不加標點")
    summary = doc.get("摘要")
    if summary:
        ln = doc.meta["摘要"][1]
        if not summary.endswith("。") or summary.count("。") != 1:
            add(ln, "R05", "摘要只寫一句，以「。」結尾")
        if atlas.text_length(summary) > 60:
            add(ln, "R05", f"摘要有{atlas.text_length(summary)}字，最多60字")
    # R06
    if "相關字" in doc.meta:
        ln = doc.meta["相關字"][1]
        seen = set()
        for r in doc.related:
            if not (len(r) == 1 and atlas.HAN_RE.fullmatch(r)):
                add(ln, "R06", f"相關字要是單一漢字：{r}")
            elif r == char:
                add(ln, "R06", "相關字不能是本字")
            elif atlas.char_counts().get(r, 0) < atlas.MIN_PLACES:
                add(ln, "R06", f"相關字「{r}」在資料裡只有{atlas.char_counts().get(r, 0)}處，少於{atlas.MIN_PLACES}處，以後不能做成頁面")
            elif r in seen:
                add(ln, "R06", f"相關字重複：{r}")
            seen.add(r)
    # R07
    dates = {}
    for k in ("建立", "更新"):
        v = doc.get(k)
        if v:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                    raise ValueError
                dates[k] = date.fromisoformat(v)
            except ValueError:
                add(doc.meta[k][1], "R07", f"{k}日期要寫成YYYY-MM-DD：{v}")
    if len(dates) == 2 and dates["更新"] < dates["建立"]:
        add(doc.meta["更新"][1], "R07", "更新日期早於建立日期")
    # R08段落
    titles = [s.title for s in doc.sections]
    for s in doc.sections:
        if s.title not in atlas.SECTIONS:
            add(s.line, "R08", f"不認得的段落「{s.title}」")
        elif titles.count(s.title) > 1:
            add(s.line, "R08", f"段落「{s.title}」重複")
    known = [t for t in titles if t in atlas.SECTIONS]
    if known != sorted(known, key=atlas.SECTIONS.index):
        add(doc.sections[0].line if doc.sections else 1, "R08", "段落順序要是：字義、分布、代表地名、延伸觀察")
    for t in atlas.REQUIRED_SECTIONS:
        if t not in titles:
            add(1, "R08", f"缺少「## {t}」段落")
    for s in doc.sections:
        if s.title == "代表地名" and s.paragraphs:
            add(s.paragraphs[0][0], "R08", "「代表地名」只能放「- P編號 地名（縣市鄉鎮）」清單，不能有其他文字")
        if s.title in ("字義", "分布", "延伸觀察") and s.items:
            add(s.items[0][0], "R08", f"「{s.title}」要寫成段落，不用清單")
    # R09字數
    for t, lo, hi in (("字義", 80, 300), ("分布", 60, 300), ("延伸觀察", 0, 300)):
        s = doc.section(t)
        if s:
            n = sum(atlas.text_length(x) for _, x in s.paragraphs)
            if n < lo or n > hi:
                add(s.line, "R09", f"「{t}」有{n}字，要在{lo}–{hi}字之間")
    # R10代表地名
    reps = doc.representative()
    rep_places = []
    if doc.section("代表地名"):
        if not 3 <= len(reps) <= 6:
            add(doc.section("代表地名").line, "R10", f"代表地名有{len(reps)}個，要3–6個")
        seen = set()
        for ln, place, raw in reps:
            m = atlas.ITEM_RE.match(raw)
            if not m:
                add(ln, "R10", f"格式要是「- P編號 地名（縣市鄉鎮）」：{raw}")
                continue
            pid, name, loc = m.groups()
            if place is None:
                new = atlas.pid_alias().get(pid)
                if new:
                    add(ln, "R10", f"{pid}已和{new}合併成一處（同名紀錄的合併方式見AGENTS.md第2節），請改用{new}")
                else:
                    add(ln, "R10", f"資料裡沒有編號{pid}")
                continue
            if pid in seen:
                add(ln, "R10", f"{pid}重複")
            seen.add(pid)
            if name != place.name or loc != place.loc:
                add(ln, "R10", f"{pid}在資料裡是「{place.name}（{place.loc}）」，不是「{name}（{loc}）」")
            if char and char not in place.name:
                add(ln, "R10", f"{place.name}不含「{char}」")
            if not place.has_meaning:
                add(ln, "R10", f"{place.name}沒有官方由來，不能當代表地名")
            if atlas.is_garbled(place.name) or atlas.is_garbled(place.village):
                add(ln, "R10", f"{place.name}（{place.full_loc}）的地名或村里在原始資料裡有缺字（?），不要當代表地名")
            rep_places.append(place)
        if len({p.county for p in rep_places}) < 2 and len(reps) >= 3:
            add(doc.section("代表地名").line, "R10", "代表地名至少要來自兩個縣市")
    sources = [atlas.norm_match(m) for p in rep_places for m, _ in p.real_meanings]
    rep_by_name = {}
    for p in rep_places:
        rep_by_name.setdefault(p.name, []).append(p)
    rep_name_re = names_re(rep_by_name)
    names_ok = {char, *doc.related} | set(atlas.all_place_names())
    allowed_counties = set(st.allowed_counties()) if st else set(atlas.COUNTIES)
    # R11–R16文字規則
    if "標題" in doc.meta:
        check_numbers(doc.meta["標題"][1], "標題", title, add)          # R12
        check_style(doc.meta["標題"][1], title, add)
    for ln, where, text in prose_blocks(doc):
        masked = mask_quotes(text)          # 引號裡的字換成〇；切句、分句、找地名都用這份
        for key in atlas.PH_RE.findall(text):                         # R11
            if st is not None:
                _, err = atlas.eval_placeholder(key, st)
                if err:
                    add(ln, "R11", err)
        if re.search(r"[{}｛｝]", strip_ph(text)):
            add(ln, "R11", "數字標記格式不完整，要寫成{{…}}")
        terms = set()
        for k in atlas.PH_RE.findall(text):
            kind, sep, arg = k.replace("：", ":").partition(":")
            if sep and kind.strip() == "由來含":
                terms.add(arg.strip())
        # R13：在整段文字上找引號；引文要比對前面最近提到的代表地名（可以跨句，不跨段）。
        # 引號內容剛好是代表地名時（例如含「番」的地名只能寫在引號裡），這個引號也算提到那一處。
        plain = mask_ph(masked)
        quotes = list(QUOTE_RE.finditer(text))
        mentions = [(m.start(), m.group(0)) for m in rep_name_re.finditer(plain)] if rep_name_re else []
        mentions = sorted(mentions + [(qm.start(), qm.group(1)) for qm in quotes if qm.group(1) in rep_by_name])
        for qm in quotes:
            q = qm.group(1)
            if not q.strip():
                add(ln, "R13", "空的引號")
                continue
            if q in names_ok or q in terms or (len(q) == 1 and atlas.HAN_RE.fullmatch(q)):
                continue
            if atlas.is_garbled(q):
                add(ln, "R13", f"引文有缺字（?），換一段沒有缺字的：「{q}」")
                continue
            nq = atlas.norm_match(q)
            if not any(nq in s for s in sources):
                add(ln, "R13", f"引號內的文字在代表地名的由來裡找不到：「{q}」")
                continue
            prior = [(pos, name) for pos, name in mentions if pos < qm.start()]
            if prior:
                pos, name = prior[-1]
                cands = pick_place(rep_by_name[name], plain[:pos])
                if not any(nq in atlas.norm_match(m) for p in cands for m, _ in p.real_meanings):
                    label = cands[0].loc + name if len(cands) == 1 < len(rep_by_name[name]) else name
                    add(ln, "R13", f"「{q}」不在前面提到的{label}的由來裡；引文要接在它出自的那一處後面")
        check_numbers(ln, where, text, add)                           # R12
        check_shared(ln, masked, add)                                 # R11
        bare = strip_ph(strip_quotes(text))
        ph_counties = set()
        no_towns = bare                     # 同一段有{{鄉鎮:X}}標記的鄉鎮名稱，裡面的縣市不算另外提到
        for k in atlas.PH_RE.findall(text):
            kind, sep, arg = k.replace("：", ":").partition(":")
            if sep and kind.strip() in ("縣市", "比例", "占總數"):
                ph_counties.update(x.strip() for x in arg.split("+"))
            elif sep and kind.strip() == "鄉鎮":
                no_towns = no_towns.replace(arg.strip(), "〇" * len(arg.strip()))
        if where in ("摘要", "分布", "延伸觀察"):                         # R14
            for c in atlas.COUNTIES:
                if c in no_towns and c not in allowed_counties and c not in ph_counties:
                    add(ln, "R14", f"提到「{c}」，但它不是數量或比例前五名，同一段要附上{{{{縣市:{c}}}}}或{{{{比例:{c}}}}}")
        # R14縣市簡稱（警告）：先遮掉比簡稱長的地名（澎湖厝）和鄉鎮全名（桃園市桃園區）
        for m in SHORT_COUNTY_RE.finditer(mask_names(plain, short_county_mask_re())):
            short = m.group(1)
            full = "或".join(c for c in atlas.COUNTIES if c.startswith(short.replace("台", "臺")))
            add(ln, "R14", f"「{short}」如果指的是縣市，請寫全名（{full}）：{context(text, m.start(), m.end())}", "警告")
        for a, b in spans(masked, "。！？；"):                            # R15
            words = [w for w in PROPORTION_WORDS if w in masked[a:b]]
            if words and not atlas.PH_RE.search(masked[a:b]):
                add(ln, "R15", f"「{words[0]}」這句沒有數字標記：{text[a:b].strip()[:30]}")
        check_style(ln, text, add)
    check_ranks(doc, st, add)
    if st is not None and st.missing_note:
        dist = doc.section("分布")
        if dist and not any("缺字" in k for _, t in dist.paragraphs for k in atlas.PH_RE.findall(t)):
            add(dist.line, "R11", f"有{st.missing}處地名有缺字（?）而由來提到「{char}」，占總數的{atlas.fmt_pct(st.missing / st.total)}；"
                "分布段要用{{缺字}}說明數量可能偏少")
    return P


RANK_WORDS = {"最多": ("count", "top"), "最少": ("count", "bottom"), "最高": ("ratio", "top"), "最低": ("ratio", "bottom")}


def rank_set_ok(claimed: List[str], values: dict, end: str):
    """claimed是不是數值前（或後）len(claimed)名；並列的都要寫出來，少寫一個也不成立。
    回傳（是否成立, 正確的名單，含全部並列者）。"""
    k = len(claimed)
    ordered = sorted(values, key=lambda x: -values[x] if end == "top" else values[x])
    if not ordered:
        return True, []
    thr = values[ordered[min(k, len(ordered)) - 1]]
    right = [x for x in ordered if (values[x] >= thr if end == "top" else values[x] <= thr)]
    return set(claimed) == set(right), right


def rank_message(word: str, what: str, claimed: List[str], right: List[str], label: str, but: str = "") -> str:
    """R21的訊息：寫錯的列出正確名單；寫對但漏了並列的，列出漏寫的和全部並列者（不截斷）。"""
    if all(c in right for c in claimed):
        missing = [x for x in right if x not in claimed]
        return f"「{word}」{what}還有{'、'.join(missing)}並列，要一起寫出來；{label}{'、'.join(right)}"
    return f"「{word}」{what}寫的是{'、'.join(claimed)}，{but}{label}{'、'.join(right)}"


def check_ranks(doc: atlas.Doc, st: Optional[atlas.CharStats], add) -> None:
    """R21：「最多」「最高」說的縣市、鄉鎮要和資料一致，並列的都要寫出來。
    句子只用。！？切，分句用，：；切（「；比例也最高」沿用同一句前一分句的縣市）；引號裡的字先換成〇。
    分句裡的鄉鎮看{{鄉鎮:…}}標記和「縣市＋鄉鎮」全名，鄉鎮全名裡的縣市不算縣市名次。"""
    if st is None:
        return
    counts = {c: n for c, n in st.by_county.items() if n > 0}
    ratios = {c: st.ratio(c) for c, n in st.by_county.items() if n >= atlas.RATIO_MIN_COUNT}
    towns = dict(st.by_town)
    for ln, where, text in prose_blocks(doc):
        if where not in ("摘要", "分布", "延伸觀察"):
            continue
        for sent in RANK_SENT_RE.findall(mask_quotes(text)):
            prev: List[str] = []
            for clause in re.split(r"[，：；]", sent):
                plain = strip_quotes(clause)
                found = []                                  # (位置, 鄉鎮, 是不是標記)
                for m in atlas.PH_RE.finditer(plain):
                    kind, sep, arg = m.group(1).replace("：", ":").partition(":")
                    if sep and kind.strip() == "鄉鎮":
                        found.append((m.start(), arg.strip(), True))
                words = mask_ph(plain)
                for m in town_re().finditer(words):
                    found.append((m.start(), m.group(0), False))
                words = mask_names(words, town_re())        # 鄉鎮全名裡的縣市不算
                found.sort()
                tw = unique(t for _, t, _ in found)
                marked = {t for _, t, is_mark in found if is_mark}
                no_mark = unique(t for _, t, is_mark in found if not is_mark and t not in marked)
                cs = sorted({c for c in atlas.COUNTIES if c in words}, key=words.index)
                for word, (metric, end) in RANK_WORDS.items():
                    if word not in words:
                        continue
                    if no_mark:
                        add(ln, "R21", f"講鄉鎮名次要給每個鄉鎮各寫一個{{{{鄉鎮:縣市鄉鎮}}}}，和「{word}」寫在同一個分句"
                            f"（沒有標記的：{'、'.join(no_mark)}）")
                        continue
                    if metric == "count" and "比例" in words:
                        metric = "ratio"
                    if tw and ("鄉鎮" in words or not cs):
                        ok, right = rank_set_ok(tw, towns, end)
                        if not ok:
                            add(ln, "R21", rank_message(word, "的鄉鎮", tw, right, "資料裡是"))
                        continue
                    claimed = cs or prev
                    if not claimed:
                        continue
                    values = ratios if metric == "ratio" else counts
                    few = [c for c in claimed if metric == "ratio" and c not in ratios]
                    if few:
                        add(ln, "R21", f"「{word}」提到的{'、'.join(few)}不到{atlas.RATIO_MIN_COUNT}處，不列入比例排名")
                        continue
                    ok, right = rank_set_ok(claimed, values, end)
                    if not ok:
                        name = "比例" if metric == "ratio" else "數量"
                        add(ln, "R21", rank_message(word, "", claimed, right, f"{name}{word}的是", "但"))
                prev = cs or prev


@lru_cache(maxsize=1)
def numeral_place_names() -> List[str]:
    """地名本身就有國字數量的（例如三座厝、雲林縣斗六市、三鎮村），寫地名時不算國字數量。
    包含聚落名、鄉鎮（全名和只寫鄉鎮）、村里。"""
    names = set(atlas.all_place_names()) | set(atlas.town_names()) | village_names()
    names |= {p.town for p in atlas.load_places()}
    return sorted((n for n in names if CN_QTY_RE.search(n)), key=len, reverse=True)


def check_numbers(ln: int, where: str, text: str, add) -> None:
    """R12：直接寫出的數字和國字數量；引號裡和地名裡的不算，「每一處」「同一個」不算。"""
    bare = strip_ph(strip_quotes(text))
    for m in re.finditer(r"[0-9０-９]+", bare):
        add(ln, "R12", f"{where}裡有直接寫出的數字「{m.group(0)}」")
    cn = bare
    for n in numeral_place_names():
        if n in cn:
            cn = cn.replace(n, "〇" * len(n))
    for m in CN_QTY_RE.finditer(cn):
        if LONE_ONE_RE.fullmatch(m.group(0)) and cn[m.start() - 1:m.start()] in LONE_ONE_OK:
            continue
        add(ln, "R12", f"{where}裡用國字寫數量「{m.group(0)}」")


def check_shared(ln: int, masked: str, add) -> None:
    """R11：「A和B都有{{比例:A}}」這類寫法，一個標記代表了兩個縣市（或鄉鎮）。
    同一句在副詞前面寫了兩個以上縣市（或鄉鎮）、標記卻只寫一個時才算。縣市看副詞所在的分句；
    這個分句在副詞前面沒有縣市時（例如「雲林縣與新竹市，兩地各有…」），看前面最近有縣市的分句。
    副詞和標記之間有縣市（例如「首都臺北市有{{縣市:臺北市}}」）不算。"""
    plain = mask_ph(masked)

    def names(kind, text):
        if kind == "鄉鎮":
            return unique(town_re().findall(text))
        rest = mask_names(text, town_re())             # 鄉鎮全名裡的縣市不算
        return [c for c in atlas.COUNTIES if c in rest]

    for a, b in spans(masked, "。！？；"):
        for m in SHARED_PH_RE.finditer(masked, a, b):
            kind, args = m.group(2), [x.strip() for x in m.group(3).split("+") if x.strip()]
            gap = plain[m.end(1):m.start(0) + m.group(0).index("{{")]
            if len(args) != 1 or names("鄉鎮", gap) or names("縣市", gap):
                continue
            clauses = re.split(r"[，：]", plain[a:m.start()])
            found = []
            for clause in reversed(clauses):            # 副詞所在的分句，或前面最近有縣市（鄉鎮）的分句
                found = names(kind, clause)
                if found:
                    break
            if len(found) >= 2:
                unit = "鄉鎮" if kind == "鄉鎮" else "縣市"
                add(ln, "R11", f"「{masked[m.start():m.start(3)]}…」：一個數字標記只代表它寫的{unit}，兩個{unit}要各寫一個標記")


def check_style(ln: int, text: str, add) -> None:
    body = strip_quotes(text)
    tai = mask_names(mask_ph(mask_quotes(text)), tai_names_re())   # 引號裡、數字標記裡、資料裡含「台」的地名不算
    m = re.search("台", tai)
    if m:
        add(ln, "R16", f"用「臺」不用「台」：{context(text, m.start(), m.end(), 4)}")
    for w in OLD_TERMS:
        if w in (OLD_TERM_OK_RE.sub("", body) if w == "番" else body):
            add(ln, "R16", f"「{w}」這類舊稱只能出現在「」逐字引用或地名引號裡，說明文字用「原住民族」或由來裡的族名")
    t = atlas.PH_RE.sub("〇", body)
    if re.search(rf"[{CJK}〇）」』，。、：；][ \t　]+[A-Za-z0-9]|[A-Za-z0-9][ \t　]+[{CJK}〇（「『]", t) \
            or re.search(rf"[{CJK}][ \t　]+〇|〇[ \t　]+[{CJK}]", t) \
            or re.search(rf"[{CJK}][ \t　]+[{CJK}]", t):
        add(ln, "R16", "中文和英數字、數字標記、中文之間不要空格")
    if re.search(rf"[{CJK}〇][,.;:?!()]|[,.;:?!()][{CJK}〇]", t):
        add(ln, "R16", "中文旁邊要用全形標點（，。；：？！（））")
    if re.search(r"<[a-zA-Z/]|\*\*|\[[^\]]*\]\(|`|!\[", text):
        add(ln, "R16", "不要用HTML、Markdown粗體、連結或圖片")
    if EMOJI_RE.search(text):
        add(ln, "R16", "不要用emoji")


def check_log(chars: List[str], level: str = "錯誤") -> List[Problem]:
    P = []
    if not atlas.LOG_MD.exists():
        return [Problem("log.md", 1, "R17", "找不到log.md", level)]
    lines = atlas.LOG_MD.read_text(encoding="utf-8").split("\n")
    added, last = {}, None
    for i, line in enumerate(lines, start=1):
        if not line.startswith("## "):
            continue
        m = LOG_RE.match(line)
        if not m:
            P.append(Problem("log.md", i, "R17", f"紀錄標題格式要是「## [YYYY-MM-DD] 動作｜對象」，動作只用{LOG_ACTIONS}：{line}", level))
            continue
        d, action, target = m.groups()
        try:
            date.fromisoformat(d)
        except ValueError:
            P.append(Problem("log.md", i, "R17", f"日期{d}不存在：{line}", level))
        else:
            if last and d < last:
                P.append(Problem("log.md", i, "R17", f"日期{d}比上一筆{last}早，新的紀錄要加在最後", level))
            last = d
        if not (i < len(lines) and lines[i].startswith("- ")):
            P.append(Problem("log.md", i, "R17", f"紀錄標題的下一行要用「- 」寫一句說明：{line}", level))
        target = target.strip()
        if action == "新增":
            if target in added:
                P.append(Problem("log.md", i, "R17", f"「新增｜{target}」第{added[target]}行已經記過；修改既有字用「修改｜{target}」", level))
            else:
                added[target] = i
    for c in chars:
        if c not in added:
            P.append(Problem("log.md", 1, "R17", f"沒有「新增｜{c}」的紀錄", level))
    return P


def check_raw() -> List[Problem]:
    """R18：data/raw/的每個檔，SHA-256要和data/SOURCE.md裡「## 檔名」那一節記的相同。"""
    text = atlas.SOURCE_MD.read_text(encoding="utf-8") if atlas.SOURCE_MD.exists() else ""
    recorded = {}
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        name, _, body = sec.partition("\n")
        m = re.search(r"SHA-256[：:]\s*([0-9a-fA-F]{64})", body)
        recorded[name.strip()] = m.group(1).lower() if m else None
    raw_dir = atlas.RAW_CSV.parent
    P = []
    for f in sorted(raw_dir.iterdir()):
        if not f.is_file() or f.name.startswith("."):           # .DS_Store這類系統檔不算
            continue
        where = f"data/raw/{f.name}"
        if f.name not in recorded:
            P.append(Problem(where, 1, "R18", f"data/SOURCE.md沒有記錄{f.name}（要有「## {f.name}」一節和SHA-256）"))
        elif recorded[f.name] is None:
            P.append(Problem(where, 1, "R18", f"data/SOURCE.md的「## {f.name}」一節沒有寫SHA-256"))
        elif atlas.file_sha256(f) != recorded[f.name]:
            P.append(Problem(where, 1, "R18", f"{f.name}的SHA-256和data/SOURCE.md記錄的不同"))
    for name, sha in recorded.items():
        if sha and not (raw_dir / name).is_file():
            P.append(Problem(f"data/raw/{name}", 1, "R18", f"data/SOURCE.md記錄了{name}，但data/raw/裡沒有這個檔"))
    return P


def check_agents_example() -> List[Problem]:
    path = atlas.ROOT / "AGENTS.md"
    if not path.exists():
        return [Problem("AGENTS.md", 1, "R20", "找不到AGENTS.md")]
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!-- 範例開始：content/(.+?)\.md -->\n```markdown\n(.*?)```\n<!-- 範例結束 -->", text, re.S)
    if not m:
        return [Problem("AGENTS.md", 1, "R20", "找不到第5.5節的範例區塊")]
    line = text[:m.start()].count("\n") + 1
    target = atlas.CONTENT_DIR / f"{m.group(1)}.md"
    if not target.exists():
        return [Problem("AGENTS.md", line, "R20", f"範例指向的content/{m.group(1)}.md不存在")]
    P = []
    if m.group(2).strip() != target.read_text(encoding="utf-8").strip():
        P.append(Problem("AGENTS.md", line, "R20", f"第5.5節的範例和content/{m.group(1)}.md不一致"))
    lines = text.split("\n")
    for i, ln_text in enumerate(lines, start=1):
        mm = re.search(r"([\d,]+)筆合併成([\d,]+)處", ln_text)
        if mm:
            want = (atlas.fmt_int(atlas.raw_record_count()), atlas.fmt_int(len(atlas.load_places())))
            if (mm.group(1), mm.group(2)) != want:
                P.append(Problem("AGENTS.md", i, "R20", f"寫的是{mm.group(1)}筆合併成{mm.group(2)}處，資料算出來是{want[0]}筆合併成{want[1]}處"))
        mm = re.search(r"「([^「」]+)」這些詞，同一句要有數字標記", ln_text)
        if mm and mm.group(1).split("、") != PROPORTION_WORDS:
            P.append(Problem("AGENTS.md", i, "R20", "第6節R15列的詞和check.py的PROPORTION_WORDS不一致"))
        mm = re.match(r"^\| `\{\{(.+?)\}\}` \| .*? \| ([^|]+?) \|$", ln_text)
        if mm:
            val, err = atlas.eval_placeholder(mm.group(1), atlas.char_stats(m.group(1)))
            if err is None and val != mm.group(2).strip():
                P.append(Problem("AGENTS.md", i, "R20", f"第5.3節例子{{{{{mm.group(1)}}}}}寫的是{mm.group(2).strip()}，「{m.group(1)}」現在算出來是{val}"))
    return P


def check_docs() -> List[Problem]:
    import build  # 延後載入，避免循環
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "docs"
        build.build(out, quiet=True)
        P = []
        cmp = filecmp.dircmp(out, atlas.DOCS_DIR) if atlas.DOCS_DIR.exists() else None
        if cmp is None:
            return [Problem("docs/", 1, "R19", "還沒有docs/，請先執行build.py")]

        def walk(c, prefix=""):
            for name in c.left_only:
                P.append(Problem("docs/" + prefix + name, 1, "R19", "建置結果有這個檔，docs/沒有"))
            for name in c.right_only:
                P.append(Problem("docs/" + prefix + name, 1, "R19", "docs/多了這個檔，建置結果沒有（是不是手動加的？）"))
            _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
            for name in mismatch + errors:
                P.append(Problem("docs/" + prefix + name, 1, "R19", "和重新建置的結果不同"))
            for name, sub in c.subdirs.items():
                walk(sub, prefix + name + "/")
        walk(cmp)
        return P


def run(paths: Optional[List[Path]] = None, docs: bool = True) -> List[Problem]:
    single = paths is not None
    files = paths if single else atlas.content_files()
    P: List[Problem] = []
    for f in files:
        if not f.exists():
            P.append(Problem(str(f), 1, "R01", "找不到這個檔案"))
            continue
        P += check_doc(f)
    chars = [atlas.parse_doc(f).char or f.stem for f in files if f.exists()]
    P += check_log(chars, "警告" if single else "錯誤")
    if not single:
        P += check_raw()
        P += check_agents_example()
        stems = [f.stem for f in files]
        for s in set(stems):
            if stems.count(s) > 1:
                P.append(Problem(f"content/{s}.md", 1, "R01", "同一個字有兩個內容檔"))
        if docs and not any(p.level == "錯誤" for p in P):
            P += check_docs()
    return P


def report(P: List[Problem]) -> int:
    P.sort(key=lambda p: (p.path, p.line, p.code))
    shown = set()
    for p in P:
        print(f"{p.path}:{p.line}  {p.code}  {p.level}：{p.msg}")
        if p.code not in shown:
            print(f"    → {HINTS[p.code]}")
            shown.add(p.code)
    errors = sum(p.level == "錯誤" for p in P)
    warns = len(P) - errors
    print(f"結果：{errors}個錯誤、{warns}個警告" + ("，通過" if errors == 0 else ""))
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description="檢查內容檔與網站是否符合AGENTS.md")
    ap.add_argument("files", nargs="*", help="只檢查這些內容檔")
    ap.add_argument("--no-docs", action="store_true", help="不檢查docs/是否最新")
    args = ap.parse_args()
    paths = [Path(f) for f in args.files] if args.files else None
    sys.exit(report(run(paths, docs=not args.no_docs)))


if __name__ == "__main__":
    main()

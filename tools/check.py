"""檢查內容檔與網站是否符合 AGENTS.md 的規則。規則代碼 R01–R20 對應 AGENTS.md 第11節。

用法：
  python3 tools/check.py                    # 全部檢查（內容檔、log.md、原始資料、docs/ 是否最新）
  python3 tools/check.py content/窩.md       # 只檢查一個內容檔（聊天介面寫好的檔案先用這個）
  python3 tools/check.py --no-docs          # 不檢查 docs/（build.py 建置前用）
有錯誤時結束代碼是1。
"""
from __future__ import annotations

import argparse
import filecmp
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas  # noqa: E402

PROPORTION_WORDS = ["絕大多數", "大多數", "大部分", "大多", "多數", "多半", "集中", "幾乎", "普遍", "少數", "居多",
                    "很多", "許多", "不少"]
QUOTE_RE = re.compile(r"「([^「」]*)」")
CN_QTY_RE = re.compile(r"[一二三四五六七八九十百千萬兩幾]+[多餘]?(?:處|個|筆|座|成|倍)")
CJK = r"㐀-鿿"
SHORT_COUNTY_RE = re.compile(
    r"(基隆|臺北|台北|新北|桃園|新竹|苗栗|臺中|台中|彰化|南投|雲林|嘉義|臺南|台南|高雄|屏東|宜蘭|花蓮|臺東|台東|澎湖|金門|連江)(?![縣市])")
LOG_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (新增|修改|規則|程式|資料)｜(.+?)\s*$")

HINTS = {
    "R01": "檔名要是 content/<字>.md，並和前置資料的「字」一致。",
    "R02": "前置資料照AGENTS.md第5.1節：兩條---之間，一行一個「欄位: 值」。",
    "R03": "換一個資料裡至少有20處的字（用 tools/prepare.py 看數量）。",
    "R04": "分類只能用：" + "、".join(atlas.CATEGORIES) + "。",
    "R05": "標題最多12字、不加標點；摘要只寫一句、以「。」結尾、最多60字。",
    "R06": "相關字用「、」分隔，每個是單一漢字，不能和本字相同。",
    "R07": "日期寫成YYYY-MM-DD，更新日期不能早於建立日期。",
    "R08": "段落只能是「## 字義」「## 分布」「## 代表地名」「## 延伸觀察」，照這個順序，前三個必填。",
    "R09": "字義80–300字、分布60–300字、延伸觀察最多300字（數字標記算2字）。",
    "R10": "代表地名3–6個，每行「- P編號 地名（縣市鄉鎮）」，從資料包第5節抄；要含本字、有由來、至少兩個縣市。",
    "R11": "只能用AGENTS.md第5.3節的數字標記，縣市寫全名、鄉鎮寫成縣市＋鄉鎮。",
    "R12": "數量一律用數字標記；年代等數字只能出現在「」逐字引用裡；不要寫「三百多處」這類國字數量。",
    "R13": "「」裡只能放：本字、相關字、資料裡的地名，或本頁代表地名由來的逐字片段（原文的「」改成『』）。",
    "R14": "縣市寫全名；摘要、分布、延伸觀察提到資料包標「可直接提」以外的縣市，同一段要附上它的{{縣市:X}}或{{比例:X}}。",
    "R15": "用到多數、大多、集中、幾乎、普遍、少數、很多、許多、不少這類詞的句子，要有數字標記支撐。",
    "R16": "用「臺」不用「台」；中文和英數字、數字標記之間不空格；用全形標點；不要HTML、Markdown粗體、連結、emoji；「番」只出現在引號裡。",
    "R20": "AGENTS.md第5.5節的範例要和content/窩.md完全相同；改了其中一個就同步另一個。",
    "R17": "在 log.md 最後加一筆「## [YYYY-MM-DD] 新增｜<字>」，日期依序往下。",
    "R18": "不要修改 data/raw/ 的檔案；若是換新版資料，照AGENTS.md第9節更新 data/SOURCE.md。",
    "R19": "執行 python3 tools/build.py 重新產生 docs/，不要手改 docs/。",
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

    # R02 欄位
    for k, (_, ln) in doc.meta.items():
        if k not in atlas.META_KEYS:
            add(ln, "R02", f"不認得的欄位「{k}」，可用的欄位：{'、'.join(atlas.META_KEYS)}")
    for k in atlas.REQUIRED_META:
        if not doc.get(k):
            add(1, "R02", f"缺少必填欄位「{k}」")
    char = doc.char
    # R01、R03 字
    if char and path.stem != char:
        add(doc.meta["字"][1], "R01", f"檔名是「{path.name}」，但「字」寫的是「{char}」")
    if path.parent.resolve() != atlas.CONTENT_DIR.resolve():
        add(1, "R01", "內容檔要放在 content/ 資料夾")
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
        if re.search(r"[，。、：；！？「」『』（）,.:;!?()]", title):
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
    # R08 段落
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
    # R09 字數
    for t, lo, hi in (("字義", 80, 300), ("分布", 60, 300), ("延伸觀察", 0, 300)):
        s = doc.section(t)
        if s:
            n = sum(atlas.text_length(x) for _, x in s.paragraphs)
            if n < lo or n > hi:
                add(s.line, "R09", f"「{t}」有{n}字，要在{lo}–{hi}字之間")
    # R10 代表地名
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
            if "?" in place.name:
                add(ln, "R10", f"{place.name}的字在原始資料裡有缺字（?），不要當代表地名")
            rep_places.append(place)
        if len({p.county for p in rep_places}) < 2 and len(reps) >= 3:
            add(doc.section("代表地名").line, "R10", "代表地名至少要來自兩個縣市")
    sources = [atlas.norm_match(m) for p in rep_places for m, _ in p.real_meanings]
    names_ok = {char, *doc.related} | set(atlas.all_place_names())
    allowed_counties = set(st.allowed_counties()) if st else set(atlas.COUNTIES)
    # R11–R16 文字規則
    if "標題" in doc.meta:
        check_style(doc.meta["標題"][1], title, add)
    for ln, where, text in prose_blocks(doc):
        for key in atlas.PH_RE.findall(text):                         # R11
            if st is not None:
                _, err = atlas.eval_placeholder(key, st)
                if err:
                    add(ln, "R11", err)
        for q in QUOTE_RE.findall(text):                               # R13
            if not q.strip():
                add(ln, "R13", "空的引號")
            elif q in names_ok or (len(q) == 1 and atlas.HAN_RE.fullmatch(q)):
                continue
            elif not any(atlas.norm_match(q) in s for s in sources):
                add(ln, "R13", f"引號內的文字在代表地名的由來裡找不到：「{q}」")
        bare = strip_ph(strip_quotes(text))
        for m in re.finditer(r"[0-9０-９]+", bare):                     # R12
            add(ln, "R12", f"{where}裡有直接寫出的數字「{m.group(0)}」")
        for m in CN_QTY_RE.finditer(bare):
            add(ln, "R12", f"{where}裡用國字寫數量「{m.group(0)}」")
        ph_counties = set()
        for k in atlas.PH_RE.findall(text):
            kind, sep, arg = k.replace("：", ":").partition(":")
            if sep and kind.strip() in ("縣市", "比例", "占總數"):
                ph_counties.update(x.strip() for x in arg.split("+"))
        if where in ("摘要", "分布", "延伸觀察"):                         # R14
            for c in atlas.COUNTIES:
                if c in bare and c not in allowed_counties and c not in ph_counties:
                    add(ln, "R14", f"提到「{c}」，但它不是數量或比例前五名，同一段要附上{{{{縣市:{c}}}}}或{{{{比例:{c}}}}}")
        for m in SHORT_COUNTY_RE.finditer(bare):
            add(ln, "R14", f"「{m.group(1)}」如果指的是縣市，請寫全名（例如{m.group(1).replace('台', '臺')}縣或{m.group(1).replace('台', '臺')}市）", "警告")
        for sent in re.split(r"[。！？；]", text):                       # R15
            words = [w for w in PROPORTION_WORDS if w in strip_quotes(sent)]
            if words and not atlas.PH_RE.search(sent):
                add(ln, "R15", f"「{words[0]}」這句沒有數字標記：{sent.strip()[:30]}")
        check_style(ln, text, add)
    return P


def check_style(ln: int, text: str, add) -> None:
    body = strip_quotes(text)
    for m in re.finditer(r"台(?=[灣北中南東])", body):
        add(ln, "R16", "用「臺」不用「台」")
        break
    if "番" in body:
        add(ln, "R16", "「番」這類舊稱只能出現在「」逐字引用或地名引號裡，說明文字用「原住民族」或由來裡的族名")
    t = atlas.PH_RE.sub("〇", body)
    if re.search(rf"[{CJK}〇）」』，。、：；][ \t　]+[A-Za-z0-9]|[A-Za-z0-9][ \t　]+[{CJK}〇（「『]", t) \
            or re.search(rf"[{CJK}][ \t　]+〇|〇[ \t　]+[{CJK}]", t) \
            or re.search(rf"[{CJK}][ \t　]+[{CJK}]", t):
        add(ln, "R16", "中文和英數字、數字標記、中文之間不要空格")
    if re.search(rf"[{CJK}〇][,;:?!()]|[,;:?!()][{CJK}〇]", t):
        add(ln, "R16", "中文旁邊要用全形標點（，；：？！（））")
    if re.search(r"<[a-zA-Z/]|\*\*|\[[^\]]*\]\(|`|!\[", text):
        add(ln, "R16", "不要用HTML、Markdown粗體、連結或圖片")
    if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text):
        add(ln, "R16", "不要用emoji")


def check_log(chars: List[str], level: str = "錯誤") -> List[Problem]:
    P = []
    if not atlas.LOG_MD.exists():
        return [Problem("log.md", 1, "R17", "找不到 log.md", level)]
    added, last = set(), None
    for i, line in enumerate(atlas.LOG_MD.read_text(encoding="utf-8").split("\n"), start=1):
        if line.startswith("## "):
            m = LOG_RE.match(line)
            if not m:
                P.append(Problem("log.md", i, "R17", f"紀錄標題格式要是「## [YYYY-MM-DD] 新增｜字」：{line}", level))
                continue
            d, action, target = m.groups()
            if last and d < last:
                P.append(Problem("log.md", i, "R17", f"日期{d}比上一筆{last}早，新的紀錄要加在最後", level))
            last = d
            if action == "新增":
                added.add(target.strip())
    for c in chars:
        if c not in added:
            P.append(Problem("log.md", 1, "R17", f"沒有「新增｜{c}」的紀錄", level))
    return P


def check_raw() -> List[Problem]:
    sha = atlas.file_sha256(atlas.RAW_CSV)
    text = atlas.SOURCE_MD.read_text(encoding="utf-8") if atlas.SOURCE_MD.exists() else ""
    if sha not in text:
        return [Problem("data/raw/settlements-2026.csv", 1, "R18", "原始資料的SHA-256和 data/SOURCE.md 記錄的不同")]
    return []


def check_agents_example() -> List[Problem]:
    path = atlas.ROOT / "AGENTS.md"
    if not path.exists():
        return [Problem("AGENTS.md", 1, "R20", "找不到 AGENTS.md")]
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!-- 範例開始：content/(.+?)\.md -->\n```markdown\n(.*?)```\n<!-- 範例結束 -->", text, re.S)
    if not m:
        return [Problem("AGENTS.md", 1, "R20", "找不到第5.5節的範例區塊")]
    line = text[:m.start()].count("\n") + 1
    target = atlas.CONTENT_DIR / f"{m.group(1)}.md"
    if not target.exists():
        return [Problem("AGENTS.md", line, "R20", f"範例指向的 content/{m.group(1)}.md 不存在")]
    if m.group(2).strip() != target.read_text(encoding="utf-8").strip():
        return [Problem("AGENTS.md", line, "R20", f"第5.5節的範例和 content/{m.group(1)}.md 不一致")]
    return []


def check_docs() -> List[Problem]:
    import build  # 延後載入，避免循環
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "docs"
        build.build(out, quiet=True)
        P = []
        cmp = filecmp.dircmp(out, atlas.DOCS_DIR) if atlas.DOCS_DIR.exists() else None
        if cmp is None:
            return [Problem("docs/", 1, "R19", "還沒有 docs/，請先執行 build.py")]

        def walk(c, prefix=""):
            for name in c.left_only:
                P.append(Problem("docs/" + prefix + name, 1, "R19", "建置結果有這個檔，docs/ 沒有"))
            for name in c.right_only:
                P.append(Problem("docs/" + prefix + name, 1, "R19", "docs/ 多了這個檔，建置結果沒有（是不是手動加的？）"))
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
    ap = argparse.ArgumentParser(description="檢查內容檔與網站是否符合 AGENTS.md")
    ap.add_argument("files", nargs="*", help="只檢查這些內容檔")
    ap.add_argument("--no-docs", action="store_true", help="不檢查 docs/ 是否最新")
    args = ap.parse_args()
    paths = [Path(f) for f in args.files] if args.files else None
    sys.exit(report(run(paths, docs=not args.no_docs)))


if __name__ == "__main__":
    main()

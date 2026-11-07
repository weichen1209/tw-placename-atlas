"""臺灣地名用字地圖的共用函式：讀原始資料、去重、統計、解析內容檔、地圖投影。

只用 Python 標準函式庫（3.9 以上）。build.py、check.py、prepare.py 都從這裡取資料，
同一個數字只在這裡算一次。
"""
from __future__ import annotations

import csv
import hashlib
import html
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "data" / "raw" / "settlements-2026.csv"
GEO_JSON = ROOT / "data" / "geo" / "counties.json"
SOURCE_MD = ROOT / "data" / "SOURCE.md"
CONTENT_DIR = ROOT / "content"
DOCS_DIR = ROOT / "docs"
LOG_MD = ROOT / "log.md"
REPO_URL = "https://github.com/weichen1209/tw-placename-atlas"

# 縣市：資料裡的正式名稱，由北到南、本島到離島
COUNTIES = [
    "基隆市", "臺北市", "新北市", "桃園市", "新竹市", "新竹縣", "苗栗縣", "臺中市",
    "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "臺南市", "高雄市", "屏東縣",
    "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
]
CATEGORIES = ["地形", "水利", "開墾", "居所", "軍事", "族群", "方位", "產業", "植物", "動物"]
MIN_PLACES = 20          # 少於這個數量的字不做頁面
TOP_N = 5                # 數量或比例前幾名的縣市可以直接寫
RATIO_MIN_COUNT = 5      # 比例排名只算這個字至少出現5處的縣市

HAN_RE = re.compile(r"[㐀-䶿一-鿿\U00020000-\U0003134f]")


# ---------------------------------------------------------------- 文字處理
def clean_text(s: str) -> str:
    """官方由來的顯示用文字：解碼 &#24269; 這類編碼、<br> 換成換行、去掉其他標籤。"""
    s = html.unescape(s or "")
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    lines = [ln.strip() for ln in s.replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def norm_match(s: str) -> str:
    """比對引文用：去掉所有空白，『』視同「」。"""
    s = clean_text(s).replace("『", "「").replace("』", "」")
    return re.sub(r"\s+", "", s)


def is_ref(text: str) -> bool:
    """只寫「詳見某里」的由來不算有由來。"""
    t = text.strip()
    return t.startswith("詳見") and len(t) <= 25


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_pct(r: float) -> str:
    if 0 < r < 0.0005:
        return "不到0.1%"
    return f"{r * 100:.1f}%"


# ---------------------------------------------------------------- 原始資料
@dataclass
class Place:
    pid: str                      # P＋第一筆紀錄在CSV的資料列號（5位數）
    name: str                     # NFKC 正規化後的地名
    county: str
    town: str
    village: str
    lon: Optional[float]
    lat: Optional[float]
    meanings: List[Tuple[str, str]] = field(default_factory=list)  # (由來, 來源)

    @property
    def loc(self) -> str:
        return f"{self.county}{self.town}"

    @property
    def full_loc(self) -> str:
        return f"{self.county}{self.town}{self.village}"

    @property
    def real_meanings(self) -> List[Tuple[str, str]]:
        return [(m, s) for m, s in self.meanings if not is_ref(m)]

    @property
    def has_meaning(self) -> bool:
        return bool(self.real_meanings)

    @property
    def has_xy(self) -> bool:
        return self.lon is not None and self.lat is not None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_places() -> Tuple[Place, ...]:
    """讀原始CSV，把同一縣市、鄉鎮、村里裡同名的紀錄合併成一處。"""
    groups: Dict[tuple, Place] = {}
    with open(RAW_CSV, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            name = unicodedata.normalize("NFKC", row["PlaceName"].strip())
            key = (name, row["County"], row["Town"], row["Village"])
            p = groups.get(key)
            if p is None:
                p = Place(f"P{i:05d}", name, row["County"], row["Town"], row["Village"],
                          _float(row["Longitude"]), _float(row["Latitude"]))
                groups[key] = p
            elif not p.has_xy and _float(row["Longitude"]) is not None:
                p.lon, p.lat = _float(row["Longitude"]), _float(row["Latitude"])
            text = clean_text(row["PlaceMean"])
            if text and all(norm_match(text) != norm_match(m) for m, _ in p.meanings):
                p.meanings.append((text, row["DataSource"].strip()))
    return tuple(sorted(groups.values(), key=lambda p: p.pid))


@lru_cache(maxsize=1)
def raw_record_count() -> int:
    """原始CSV的紀錄筆數（由來裡有換行，所以不能用行數算）。"""
    with open(RAW_CSV, encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


@lru_cache(maxsize=1)
def place_index() -> Dict[str, Place]:
    return {p.pid: p for p in load_places()}


@lru_cache(maxsize=1)
def county_totals() -> Dict[str, int]:
    c = Counter(p.county for p in load_places())
    return {k: c.get(k, 0) for k in COUNTIES}


@lru_cache(maxsize=1)
def all_place_names() -> frozenset:
    return frozenset(p.name for p in load_places())


@lru_cache(maxsize=1)
def town_names() -> frozenset:
    return frozenset(p.county + p.town for p in load_places())


@lru_cache(maxsize=1)
def char_counts() -> Counter:
    """每個漢字出現在幾處聚落的地名裡（同一地名重複的字只算一次）。"""
    c = Counter()
    for p in load_places():
        for ch in set(HAN_RE.findall(p.name)):
            c[ch] += 1
    return c


# ---------------------------------------------------------------- 統計
@dataclass
class CharStats:
    char: str
    hits: List[Place]
    by_county: Dict[str, int]
    by_town: Counter

    @property
    def total(self) -> int:
        return len(self.hits)

    @property
    def with_meaning(self) -> int:
        return sum(p.has_meaning for p in self.hits)

    @property
    def with_xy(self) -> int:
        return sum(p.has_xy for p in self.hits)

    def ratio(self, county: str) -> float:
        t = county_totals()[county]
        return self.by_county.get(county, 0) / t if t else 0.0

    def top_by_count(self, n: int = TOP_N) -> List[str]:
        rows = [(c, k) for c, k in self.by_county.items() if k > 0]
        rows.sort(key=lambda x: (-x[1], COUNTIES.index(x[0])))
        return [c for c, _ in rows[:n]]

    def top_by_ratio(self, n: int = TOP_N) -> List[str]:
        rows = [c for c, k in self.by_county.items() if k >= RATIO_MIN_COUNT]
        rows.sort(key=lambda c: (-self.ratio(c), COUNTIES.index(c)))
        return rows[:n]

    def allowed_counties(self) -> List[str]:
        out = self.top_by_count()
        for c in self.top_by_ratio():
            if c not in out:
                out.append(c)
        return out

    def meaning_contains(self, word: str) -> int:
        w = norm_match(word)
        return sum(any(w in norm_match(m) for m, _ in p.real_meanings) for p in self.hits)


@lru_cache(maxsize=256)
def char_stats(char: str) -> CharStats:
    hits = [p for p in load_places() if char in p.name]
    by_county = {c: 0 for c in COUNTIES}
    for p in hits:
        by_county[p.county] = by_county.get(p.county, 0) + 1
    by_town = Counter(p.county + p.town for p in hits)
    return CharStats(char, hits, by_county, by_town)


# ---------------------------------------------------------------- 數字標記
PH_RE = re.compile(r"\{\{([^{}]*)\}\}")
PH_HELP = {
    "總數": "含這個字的聚落數",
    "全部聚落": "全臺聚落總數",
    "占全部": "總數占全臺聚落的百分比",
    "有由來": "其中有官方由來的聚落數",
    "有座標": "其中有經緯度、畫得上地圖的聚落數",
    "縣市:X": "X縣市裡含這個字的聚落數（X可以寫成A+B，表示合計）",
    "比例:X": "X縣市的聚落裡，含這個字的百分比",
    "占總數:X": "X縣市占這個字總數的百分比",
    "鄉鎮:X": "X鄉鎮（寫成縣市＋鄉鎮，例如新竹縣關西鎮）裡含這個字的聚落數",
    "由來含:X": "官方由來裡出現X這個詞的聚落數",
}


def eval_placeholder(key: str, st: CharStats) -> Tuple[Optional[str], Optional[str]]:
    """回傳（顯示的數字, 錯誤訊息）。"""
    key = key.strip()
    places = load_places()
    if key == "總數":
        return fmt_int(st.total), None
    if key == "全部聚落":
        return fmt_int(len(places)), None
    if key == "占全部":
        return fmt_pct(st.total / len(places)), None
    if key == "有由來":
        return fmt_int(st.with_meaning), None
    if key == "有座標":
        return fmt_int(st.with_xy), None
    if ":" in key or "：" in key:
        kind, _, arg = key.replace("：", ":").partition(":")
        kind, arg = kind.strip(), arg.strip()
        if kind in ("縣市", "比例", "占總數"):
            names = [x.strip() for x in arg.split("+")]
            for n in names:
                if n not in COUNTIES:
                    return None, f"沒有「{n}」這個縣市（要寫資料裡的全名，例如臺南市）"
            if len(set(names)) != len(names):
                return None, f"縣市重複：{arg}"
            k = sum(st.by_county.get(n, 0) for n in names)
            if kind == "縣市":
                return fmt_int(k), None
            if kind == "比例":
                t = sum(county_totals()[n] for n in names)
                return fmt_pct(k / t if t else 0.0), None
            return fmt_pct(k / st.total if st.total else 0.0), None
        if kind == "鄉鎮":
            if arg not in town_names():
                return None, f"沒有「{arg}」這個鄉鎮（要寫成縣市＋鄉鎮，例如新竹縣關西鎮）"
            return fmt_int(st.by_town.get(arg, 0)), None
        if kind == "由來含":
            if not arg:
                return None, "由來含後面要寫要找的詞"
            return fmt_int(st.meaning_contains(arg)), None
    return None, f"不認得的標記{{{{{key}}}}}；可用的標記見AGENTS.md第5.3節"


# ---------------------------------------------------------------- 內容檔
META_KEYS = ["字", "標題", "摘要", "分類", "相關字", "建立", "更新"]
REQUIRED_META = ["字", "標題", "摘要", "分類", "建立", "更新"]
SECTIONS = ["字義", "分布", "代表地名", "延伸觀察"]
REQUIRED_SECTIONS = ["字義", "分布", "代表地名"]
ITEM_RE = re.compile(r"^-\s*(P\d{5})\s*(\S+?)（(.+?)）\s*$")


@dataclass
class Section:
    title: str
    line: int
    paragraphs: List[Tuple[int, str]] = field(default_factory=list)   # (行號, 文字)
    items: List[Tuple[int, str]] = field(default_factory=list)        # (行號, 原始行)


@dataclass
class Doc:
    path: Path
    meta: Dict[str, Tuple[str, int]] = field(default_factory=dict)    # 欄位 → (值, 行號)
    sections: List[Section] = field(default_factory=list)
    problems: List[Tuple[int, str, str]] = field(default_factory=list)  # (行號, 代碼, 訊息)

    def get(self, key: str, default: str = "") -> str:
        return self.meta.get(key, (default, 0))[0]

    def section(self, title: str) -> Optional[Section]:
        for s in self.sections:
            if s.title == title:
                return s
        return None

    @property
    def char(self) -> str:
        return self.get("字")

    @property
    def related(self) -> List[str]:
        raw = self.get("相關字")
        return [x.strip() for x in re.split(r"[、,，\s]+", raw) if x.strip()]

    def representative(self) -> List[Tuple[int, Optional[Place], str]]:
        """代表地名：(行號, Place或None, 原始行)。"""
        sec = self.section("代表地名")
        out = []
        if not sec:
            return out
        idx = place_index()
        for line_no, raw in sec.items:
            m = ITEM_RE.match(raw)
            out.append((line_no, idx.get(m.group(1)) if m else None, raw))
        return out


def parse_doc(path: Path) -> Doc:
    doc = Doc(path)
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    i = 0
    if not lines or lines[0].strip() != "---":
        doc.problems.append((1, "R02", "第一行要是「---」，前置資料寫在兩條---之間"))
    else:
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            raw = lines[i]
            if raw.strip():
                m = re.match(r"^\s*([^:：]+?)\s*[:：]\s*(.*?)\s*$", raw)
                if not m:
                    doc.problems.append((i + 1, "R02", f"前置資料要寫成「欄位: 值」：{raw.strip()}"))
                else:
                    k, v = m.group(1), m.group(2)
                    if k in doc.meta:
                        doc.problems.append((i + 1, "R02", f"欄位「{k}」重複"))
                    doc.meta[k] = (v, i + 1)
            i += 1
        if i >= len(lines):
            doc.problems.append((1, "R02", "前置資料缺少結尾的「---」"))
        i += 1
    current: Optional[Section] = None
    buf: List[Tuple[int, str]] = []

    def flush():
        if buf and current is not None:
            text = "".join(t.strip() for _, t in buf)
            current.paragraphs.append((buf[0][0], text))
        buf.clear()

    for j in range(i, len(lines)):
        raw = lines[j]
        s = raw.strip()
        if s.startswith("## "):
            flush()
            current = Section(s[3:].strip(), j + 1)
            doc.sections.append(current)
        elif s.startswith("#"):
            flush()
            doc.problems.append((j + 1, "R08", f"只能用「## 段落名稱」當標題：{s}"))
        elif not s:
            flush()
        elif current is None:
            doc.problems.append((j + 1, "R08", "前置資料之後要先接「## 字義」，不能有其他文字"))
        elif s.startswith("- ") or s.startswith("-P") or s == "-":
            flush()
            current.items.append((j + 1, s))
        else:
            buf.append((j + 1, s))
    flush()
    return doc


def content_files() -> List[Path]:
    return sorted(CONTENT_DIR.glob("*.md"), key=lambda p: p.name)


def text_length(text: str) -> int:
    """字數：數字標記算2個字，空白不算。"""
    t = PH_RE.sub("〇〇", text)
    return len(re.sub(r"\s", "", t))


# ---------------------------------------------------------------- 地圖投影
@dataclass(frozen=True)
class View:
    lon0: float
    lat1: float
    k: float          # 每緯度幾像素
    lat_c: float      # 經度縮放用的中心緯度
    x0: float = 0.0
    y0: float = 0.0
    w: float = 0.0
    h: float = 0.0
    label: str = ""

    def project(self, lon: float, lat: float) -> Tuple[float, float]:
        kx = self.k * math.cos(math.radians(self.lat_c))
        return (self.x0 + (lon - self.lon0) * kx, self.y0 + (self.lat1 - lat) * self.k)


MAP_W, MAP_H = 764, 1044
MAIN_VIEW = View(lon0=119.28, lat1=25.34, k=300.0, lat_c=23.6, w=MAP_W, h=MAP_H)
INSET_VIEWS = {
    "連江縣": View(lon0=119.88, lat1=26.40, k=300.0, lat_c=26.16, x0=16, y0=30,
                 w=0.65 * 300 * math.cos(math.radians(26.16)), h=0.48 * 300, label="連江縣"),
    "金門縣": View(lon0=118.20, lat1=24.53, k=600.0, lat_c=24.45, x0=16, y0=214,
                 w=0.30 * 600 * math.cos(math.radians(24.45)), h=0.15 * 600, label="金門縣（放大兩倍）"),
    "烏坵": View(lon0=119.43, lat1=25.005, k=600.0, lat_c=24.99, x0=196, y0=214,
               w=0.06 * 600 * math.cos(math.radians(24.99)), h=0.035 * 600, label="烏坵"),
}


def view_for(county: str, lon: Optional[float] = None) -> View:
    """金門縣的烏坵鄉離金門本島很遠，另外畫一個小框。"""
    if county == "金門縣" and lon is not None and lon > 119.0:
        return INSET_VIEWS["烏坵"]
    return INSET_VIEWS.get(county, MAIN_VIEW) if county != "烏坵" else MAIN_VIEW


def project_place(p: Place) -> Optional[Tuple[float, float]]:
    if not p.has_xy:
        return None
    return view_for(p.county, p.lon).project(p.lon, p.lat)

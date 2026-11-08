"""把content/*.md和原始資料組成網站，輸出到docs/（GitHub Pages的來源資料夾）。

用法：python3 tools/build.py
建置前會先跑check.py（R19除外），有錯誤就停止，不會產生網頁。
docs/裡的檔案全部由這支程式產生，不要手改。
"""
from __future__ import annotations

import html
import json
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path
from string import Template
from typing import Dict, List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas  # noqa: E402

TEMPLATES = atlas.ROOT / "templates"
ASSETS = atlas.ROOT / "assets"
SCALE = 2                 # 點圖用2倍解析度
DOT_R = 3.0               # 本頁的字的點半徑（地圖座標）
esc = html.escape

# 地圖用色。底圖SVG和PNG點圖是用<img>、<image>載入的檔案，吃不到style.css的變數，
# 所以顏色集中寫在這裡；頁面其他顏色都用style.css開頭的變數。
MAP_LAND = "#ebe3d3"            # 底圖的陸地
MAP_BORDER = "#c4b49b"          # 縣市界線
MAP_INSET_BOX = "#b3a48b"       # 左上角離島小框的框線
MAP_INSET_LABEL = "#7d7266"     # 離島小框的名稱
BASE_DOT_RGB = (128, 108, 86)   # 單字頁地圖的淡色點：全臺有座標的聚落
MINI_DOT_RGB = (181, 51, 46)    # 首頁小地圖的紅點：地名含這個字的聚落


# ---------------------------------------------------------------- PNG（標準函式庫）
def png_bytes(w: int, h: int, rgba: bytearray) -> bytes:
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def dots_png(points, scale: float, radius: float, color, alpha: float) -> bytes:
    w, h = round(atlas.MAP_W * scale), round(atlas.MAP_H * scale)
    cover = bytearray(w * h)
    r = radius
    offs = [(dx, dy) for dy in range(-int(r) - 1, int(r) + 2) for dx in range(-int(r) - 1, int(r) + 2)
            if dx * dx + dy * dy <= r * r]
    for x, y in points:
        cx, cy = round(x * scale), round(y * scale)
        for dx, dy in offs:
            px, py = cx + dx, cy + dy
            if 0 <= px < w and 0 <= py < h:
                i = py * w + px
                if cover[i] < 250:
                    cover[i] += 1
    lut = [round(255 * (1 - (1 - alpha) ** n)) for n in range(256)]
    rgba = bytearray(w * h * 4)
    cr, cg, cb = color
    for i, n in enumerate(cover):
        if n:
            j = i * 4
            rgba[j], rgba[j + 1], rgba[j + 2], rgba[j + 3] = cr, cg, cb, lut[n]
    return png_bytes(w, h, rgba)


# ---------------------------------------------------------------- 共用
def tpl(name: str) -> Template:
    return Template((TEMPLATES / name).read_text(encoding="utf-8"))


def page(out: Path, root: str, title: str, description: str, body: str, active: str,
         body_class: str = "", scripts: str = "") -> None:
    nav = {k: ('aria-current="page"' if k == active else "") for k in ("index", "rank", "about")}
    text = tpl("base.html").substitute(
        title=esc(title), description=esc(description), root=root, body=body, body_class=body_class,
        nav_index=nav["index"], nav_rank=nav["rank"], nav_about=nav["about"], repo=atlas.REPO_URL,
        scripts=scripts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def find_source(q: str, reps: List[atlas.Place]):
    nq = atlas.norm_match(q)
    for p in reps:
        for m, _ in p.real_meanings:
            if nq in atlas.norm_match(m):
                return p
    return None


def meaning_terms(text: str) -> set:
    """同一段{{由來含:詞}}算的詞，取法和check.py的R13相同。"""
    terms = set()
    for k in atlas.PH_RE.findall(text):
        kind, sep, arg = k.replace("：", ":").partition(":")
        if sep and kind.strip() == "由來含":
            terms.add(arg.strip())
    return terms


def render_text(text: str, st: atlas.CharStats, reps: List[atlas.Place], related: Sequence[str] = ()) -> str:
    """數字標記換成數字；代表地名由來的逐字引文畫底線，並註明引自哪一處。
    本字、相關字、單一漢字、資料裡的地名、同一段{{由來含:詞}}算的詞不是引文，不畫底線。"""
    not_cite = {st.char, *related} | meaning_terms(text)
    out, pos = [], 0
    for m in re.finditer(r"\{\{([^{}]*)\}\}|「([^「」]*)」", text):
        out.append(esc(text[pos:m.start()]))
        if m.group(1) is not None:
            val, _ = atlas.eval_placeholder(m.group(1), st)
            out.append(f'<span class="num">{esc(val or "")}</span>')
        else:
            q = m.group(2)
            src = (find_source(q, reps)
                   if len(q) > 1 and q not in not_cite and q not in atlas.all_place_names() else None)
            if src:
                out.append(f'「<span class="cite" title="引自{esc(src.name)}（{esc(src.loc)}）的官方由來">{esc(q)}</span>」')
            else:
                out.append(f"「{esc(q)}」")
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def plain_text(text: str, st: atlas.CharStats) -> str:
    """數字標記換成數字的純文字，給網頁說明（meta description）用。"""
    return re.sub(r"\{\{([^{}]*)\}\}", lambda m: atlas.eval_placeholder(m.group(1), st)[0] or "", text)


def paragraphs(sec, st, reps, related=()) -> str:
    if not sec:
        return ""
    return "\n".join(f"<p>{render_text(t, st, reps, related)}</p>" for _, t in sec.paragraphs)


def meaning_html(text: str) -> str:
    return "<br>".join(esc(x) for x in text.split("\n"))


def load_docs() -> List[atlas.Doc]:
    docs = [atlas.parse_doc(p) for p in atlas.content_files()]
    return sorted(docs, key=lambda d: (atlas.CATEGORIES.index(d.get("分類")) if d.get("分類") in atlas.CATEGORIES else 99,
                                       -atlas.char_stats(d.char).total))


def log_entries():
    import check
    entries = []
    if atlas.LOG_MD.exists():
        cur = None
        for line in atlas.LOG_MD.read_text(encoding="utf-8").split("\n"):
            m = check.LOG_RE.match(line)
            if m:
                cur = {"date": m.group(1), "action": m.group(2), "target": m.group(3), "notes": []}
                entries.append(cur)
            elif cur and line.startswith("- "):
                cur["notes"].append(line[2:].strip())
    return entries


# ---------------------------------------------------------------- 地圖
def basemap_svg(geo: dict) -> str:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {geo["width"]} {geo["height"]}" '
             f'width="{geo["width"]}" height="{geo["height"]}">',
             f'<g fill="{MAP_LAND}" stroke="{MAP_BORDER}" stroke-width="0.6" stroke-linejoin="round">']
    for c in atlas.COUNTIES:
        if geo["counties"].get(c):
            parts.append(f'<path d="{geo["counties"][c]}"/>')
    parts.append(f'</g><g fill="none" stroke="{MAP_INSET_BOX}" stroke-width="0.8">')
    for ins in geo["insets"]:
        parts.append(f'<rect x="{ins["x"] - 6}" y="{ins["y"] - 6}" width="{ins["w"] + 12}" height="{ins["h"] + 12}" rx="3"/>')
    parts.append(f'</g><g font-family="sans-serif" font-size="12" fill="{MAP_INSET_LABEL}">')
    for ins in geo["insets"]:
        parts.append(f'<text x="{ins["x"] - 4}" y="{ins["y"] - 10}">{esc(ins["label"])}</text>')
    parts.append("</g></svg>")
    return "".join(parts)


def map_svg(st: atlas.CharStats, root: str) -> str:
    dots = []
    for p in st.hits:
        xy = atlas.project_place(p)
        if xy:
            dots.append(f'<circle cx="{xy[0]:.1f}" cy="{xy[1]:.1f}" r="{DOT_R}" data-p="{p.pid}" data-c="{p.county}">'
                        f'<title>{esc(p.name)}（{esc(p.loc)}）</title></circle>')
    return (f'<svg class="map" viewBox="0 0 {atlas.MAP_W} {atlas.MAP_H}" role="img" aria-labelledby="map-t">'
            f'<title id="map-t">地名含「{esc(st.char)}」的聚落分布圖</title>'
            f'<image href="{root}assets/basemap.svg" x="0" y="0" width="{atlas.MAP_W}" height="{atlas.MAP_H}"/>'
            f'<image href="{root}assets/base-dots.png" x="0" y="0" width="{atlas.MAP_W}" height="{atlas.MAP_H}"/>'
            f'<g class="dots">{"".join(dots)}</g></svg>')


def county_table(st: atlas.CharStats) -> str:
    rows = [c for c in atlas.COUNTIES if st.by_county[c] > 0]
    rows.sort(key=lambda c: (-st.by_county[c], atlas.COUNTIES.index(c)))
    max_n = max((st.by_county[c] for c in rows), default=1)
    max_r = max((st.ratio(c) for c in rows), default=1) or 1
    out = ['<table class="county-table"><caption>各縣市的數量與比例（比例＝該縣市聚落中地名含這個字的比例）</caption>',
           '<thead><tr><th scope="col">縣市</th><th scope="col">數量</th><th scope="col">比例</th></tr></thead><tbody>']
    for c in rows:
        n, r = st.by_county[c], st.ratio(c)
        out.append(f'<tr data-c="{c}" tabindex="0"><th scope="row">{c}</th>'
                   f'<td><span class="bar n" style="--w:{n / max_n * 100:.1f}%"></span><span class="v">{n}</span></td>'
                   f'<td><span class="bar r" style="--w:{r / max_r * 100:.1f}%"></span><span class="v">{atlas.fmt_pct(r)}</span></td></tr>')
    zero = [c for c in atlas.COUNTIES if st.by_county[c] == 0]
    out.append("</tbody></table>")
    if zero:
        out.append(f'<p class="table-note">沒有出現的縣市：{"、".join(zero)}</p>')
    return "".join(out)


# ---------------------------------------------------------------- 各頁
def build_zi(doc: atlas.Doc, docs_by_char: Dict[str, atlas.Doc], out: Path) -> None:
    st = atlas.char_stats(doc.char)
    reps = [p for _, p, _ in doc.representative() if p]
    cards = []
    for p in reps:
        ms = "".join(f'<blockquote><p>{meaning_html(m)}</p><footer>來源：{esc(src)}</footer></blockquote>'
                     for m, src in p.real_meanings)
        cards.append(f'<li class="place-card"><h3>{esc(p.name)}</h3><p class="loc">{esc(p.full_loc)}</p>{ms}</li>')
    extra = doc.section("延伸觀察")
    extra_html = (f'<section class="zi-section"><h2>延伸觀察</h2><div class="prose">{paragraphs(extra, st, reps, doc.related)}</div></section>'
                  if extra else "")
    rel = []
    for r in doc.related:
        if r in docs_by_char:
            rel.append(f'<a class="rel" href="{esc(r)}.html"><b>{esc(r)}</b><span>{esc(docs_by_char[r].get("標題"))}</span></a>')
        else:
            rel.append(f'<span class="rel none"><b>{esc(r)}</b><span>{atlas.fmt_int(atlas.char_counts().get(r, 0))}處・尚未收錄</span></span>')
    related_html = (f'<section class="zi-section"><h2>相關字</h2><div class="rel-list">{"".join(rel)}</div></section>'
                    if rel else "")
    src_url = f"{atlas.REPO_URL}/blob/main/content/{doc.char}.md"
    body = tpl("zi.html").substitute(
        char=esc(doc.char), cat=esc(doc.get("分類")), title=esc(doc.get("標題")),
        summary=render_text(doc.get("摘要"), st, reps, doc.related),
        total=atlas.fmt_int(st.total), share=atlas.fmt_pct(st.total / len(atlas.load_places())),
        with_meaning=atlas.fmt_int(st.with_meaning), with_xy=atlas.fmt_int(st.with_xy),
        map_svg=map_svg(st, "../"), county_table=county_table(st),
        dist_prose=paragraphs(doc.section("分布"), st, reps, doc.related),
        meaning_prose=paragraphs(doc.section("字義"), st, reps, doc.related),
        cards="".join(cards), extra_section=extra_html, related_section=related_html,
        src_url=src_url, created=esc(doc.get("建立")), updated=esc(doc.get("更新")))
    page(out / "zi" / f"{doc.char}.html", "../", f"{doc.char}：{doc.get('標題')}｜臺灣地名用字地圖",
         plain_text(doc.get("摘要"), st), body, "", "page-zi",
         '<script src="../assets/zi.js" defer></script>')
    data = {}
    for p in st.hits:
        if p.has_xy:
            # 只寫了「詳見…」的聚落也照原文給面板顯示（{{有由來}}仍然不算它）
            data[p.pid] = [p.name, p.full_loc, [[m, s] for m, s in (p.real_meanings or p.meanings)]]
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / f"{doc.char}.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    pts = [atlas.project_place(p) for p in st.hits if p.has_xy]
    (out / "assets" / "mini").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "mini" / f"{doc.char}.png").write_bytes(dots_png(pts, 0.4, 1.2, MINI_DOT_RGB, 0.85))


def build_index(docs: List[atlas.Doc], out: Path) -> None:
    places = atlas.load_places()
    cats = [c for c in atlas.CATEGORIES if any(d.get("分類") == c for d in docs)]
    chips = ['<button type="button" class="chip" aria-pressed="true" data-cat="">全部</button>'] + [
        f'<button type="button" class="chip" aria-pressed="false" data-cat="{c}">{c}</button>' for c in cats]
    cards = []
    for d in docs:
        st = atlas.char_stats(d.char)
        cards.append(
            f'<li class="tile" data-cat="{esc(d.get("分類"))}"><a href="zi/{esc(d.char)}.html">'
            f'<span class="tile-top"><span class="tzg" aria-hidden="true">{esc(d.char)}</span>'
            f'<span class="tile-text"><span class="sr-only">{esc(d.char)}：</span>'
            f'<span class="tile-title">{esc(d.get("標題"))}</span>'
            f'<span class="tile-count">{atlas.fmt_int(st.total)}處</span></span></span>'
            f'<span class="tile-map"><img src="assets/basemap.svg" alt="" loading="lazy">'
            f'<img src="assets/mini/{esc(d.char)}.png" alt="" loading="lazy"></span></a></li>')
    pages = {d.char: d.get("標題") for d in docs}
    candidates = sum(1 for ch, n in atlas.char_counts().items() if n >= atlas.MIN_PLACES)
    body = tpl("index.html").substitute(
        n_raw=atlas.fmt_int(atlas.raw_record_count()), n_places=atlas.fmt_int(len(places)),
        n_meaning=atlas.fmt_int(sum(p.has_meaning for p in places)),
        n_pages=len(docs), n_candidates=atlas.fmt_int(candidates), chips="".join(chips), cards="".join(cards),
        pages_json=esc(json.dumps(pages, ensure_ascii=False, sort_keys=True), quote=False))
    page(out / "index.html", "", "臺灣地名用字地圖", "一個字一頁，看一個字在臺灣聚落地名裡的分布與官方由來。",
         body, "index", "page-index", '<script src="assets/index.js" defer></script>')
    counts = {ch: n for ch, n in atlas.char_counts().items()}
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "char-counts.json").write_text(
        json.dumps(counts, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")


def build_rank(docs: List[atlas.Doc], out: Path) -> None:
    have = {d.char: d for d in docs}
    ranked = sorted(atlas.char_counts().items(), key=lambda x: (-x[1], x[0]))
    eligible = [(ch, n) for ch, n in ranked if n >= atlas.MIN_PLACES]
    items = []
    for i, (ch, n) in enumerate(eligible[:150], start=1):
        if ch in have:
            items.append(f'<li class="done"><a href="zi/{esc(ch)}.html" title="{esc(have[ch].get("標題"))}">'
                         f'<span class="rk">{i}</span><b>{esc(ch)}</b>'
                         f'<span class="n">{atlas.fmt_int(n)}處</span><span class="t">已收錄</span></a></li>')
        else:
            items.append(f'<li><div><span class="rk">{i}</span><b>{esc(ch)}</b><span class="n">{atlas.fmt_int(n)}處</span>'
                         f'<span class="t">尚未收錄</span></div></li>')
    body = tpl("rank.html").substitute(
        n_eligible=atlas.fmt_int(len(eligible)), n_pages=len(docs), min_places=atlas.MIN_PLACES, items="".join(items),
        repo=atlas.REPO_URL)
    page(out / "rank.html", "", "用字排行｜臺灣地名用字地圖", "臺灣聚落地名最常用的字，與還沒有說明頁的字。",
         body, "rank", "page-rank")


def merge_example(places) -> str:
    """跨最多村里合併成一處的聚落，給關於頁說明合併方式。
    同一鄉鎮登記同名的村里可能更多：由來不同的會另算一處，所以句子寫明合併的條件。"""
    p = max(places, key=lambda p: (len(p.more_villages), -int(p.pid[1:])))
    cond = "由來相同" if p.has_meaning else "都沒有由來"
    return f"{esc(p.county + p.town)}{len(p.more_villages) + 1}個村里登記、{cond}的「{esc(p.name)}」合併成一處"


def build_about(docs: List[atlas.Doc], out: Path) -> None:
    places = atlas.load_places()
    log_html = []
    for e in reversed(log_entries()):
        target = e["target"]
        link = (f'<a href="zi/{esc(target)}.html">{esc(target)}</a>'
                if e["action"] in ("新增", "修改") and any(d.char == target for d in docs) else esc(target))
        notes = "".join(f"<li>{esc(n)}</li>" for n in e["notes"])
        log_html.append(f'<li><time>{e["date"]}</time><span class="act">{e["action"]}</span>{link}'
                        f'{"<ul>" + notes + "</ul>" if notes else ""}</li>')
    body = tpl("about.html").substitute(
        n_raw=atlas.fmt_int(atlas.raw_record_count()), n_places=atlas.fmt_int(len(places)),
        n_xy=atlas.fmt_int(sum(p.has_xy for p in places)),
        n_meaning=atlas.fmt_int(sum(p.has_meaning for p in places)),
        sha=atlas.file_sha256(atlas.RAW_CSV)[:12], repo=atlas.REPO_URL, log="".join(log_html),
        min_places=atlas.MIN_PLACES, merge_example=merge_example(places))
    page(out / "about.html", "", "關於與規則｜臺灣地名用字地圖", "資料來源、計算方式、頁面怎麼產生，以及給AI的規則。",
         body, "about", "page-about")


def build(out: Path = atlas.DOCS_DIR, quiet: bool = False) -> None:
    docs = load_docs()
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    for f in sorted(ASSETS.iterdir()):
        if f.is_file():
            shutil.copyfile(f, out / "assets" / f.name)
    geo = json.loads(atlas.GEO_JSON.read_text(encoding="utf-8"))
    (out / "assets" / "basemap.svg").write_text(basemap_svg(geo), encoding="utf-8")
    pts = [atlas.project_place(p) for p in atlas.load_places() if p.has_xy]
    (out / "assets" / "base-dots.png").write_bytes(dots_png(pts, SCALE, 1.6, BASE_DOT_RGB, 0.24))
    by_char = {d.char: d for d in docs}
    for d in docs:
        build_zi(d, by_char, out)
    build_index(docs, out)
    build_rank(docs, out)
    build_about(docs, out)
    if not quiet:
        n = sum(1 for _ in out.rglob("*") if _.is_file())
        print(f"完成：{len(docs)}個字的頁面，docs/共{n}個檔案")


def main():
    import check
    problems = [p for p in check.run(docs=False) if p.level == "錯誤" and p.code != "R19"]
    if problems:
        check.report(problems)
        sys.exit("內容檢查沒有通過，先修正上面的錯誤再建置。")
    build()


if __name__ == "__main__":
    main()

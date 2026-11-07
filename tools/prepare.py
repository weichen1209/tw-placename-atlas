"""產生一個字的資料包（Markdown），給寫內容檔的人或AI看。

用法：
  python3 tools/prepare.py 窩              # 印在畫面上
  python3 tools/prepare.py 窩 --out packs/窩.md
  python3 tools/prepare.py 窩 --all --out packs/窩.md   # 第5節列出全部候選，不限每縣市6處
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas  # noqa: E402

STOP = set("""故名 得名 地名 聚落 位於 此地 因此 所以 稱為 名稱 之意 此處 本地 早期 當時 早年 附近 該地 地方
一帶 因為 由來 而得 故稱 稱之 以前 後來 這裡 因而 而名 名為 之名 故以 以此 故而 其地 此一 此名 即為 一說 二說
相傳 據說 傳說 指的 所謂 一個 也就 就是 由於 而來 而成 成為 形成 當地 地區 地勢 居住 現今 今日 目前 以及 之後
之地 的地 地的 的意 意思 為主 主要 已經 另有 有人 之一 其中 民國 日治 時期 清代 年間""".split())
PER_COUNTY = 6
MAX_CANDIDATES = 60


def theme_words(st: atlas.CharStats, n: int, top: int):
    c = Counter()
    for p in st.hits:
        grams = set()
        for m, _ in p.real_meanings:
            text = "".join(atlas.HAN_RE.findall(m))
            for i in range(len(text) - n + 1):
                g = text[i:i + n]
                if st.char in g or any(w in g for w in STOP if len(w) <= n):
                    continue
                grams.add(g)
        c.update(grams)
    return [(g, k) for g, k in c.most_common(top) if k >= 3]


def pick_candidates(st: atlas.CharStats, show_all: bool = False):
    pool = [p for p in st.hits if p.has_meaning and not atlas.is_garbled(p.name) and not atlas.is_garbled(p.village)]
    # 由來裡的「窩」如果只是地名的一部分（例如大窩、五結鄉），不算有解釋這個字
    names = sorted({p.name for p in st.hits if len(p.name) > len(st.char)}
                   | {t for t in atlas.town_names() if st.char in t}, key=len, reverse=True)
    name_re = re.compile("|".join(map(re.escape, names))) if names else None
    strong_re = re.compile(re.escape(st.char) + r"[」』]?(?:字|者|，|,|是|指|為|即|乃|意|係|：|:|，即)")

    def score(p):
        text = "".join(m for m, _ in p.real_meanings)
        bare = name_re.sub("〇", text) if name_re else text
        strong = bool(strong_re.search(bare))
        explains = st.char in bare
        return (not strong, not explains, -min(len(text), 160), p.pid)

    by_county = {}
    for p in sorted(pool, key=score):
        by_county.setdefault(p.county, []).append(p)
    order = sorted(by_county, key=lambda c: (-st.by_county[c], atlas.COUNTIES.index(c)))
    if show_all:
        chosen = list(pool)
    else:
        chosen = []
        for c in order:                      # 每個縣市先放一處
            chosen.append(by_county[c][0])
        for c in order:                      # 再依縣市數量補到每縣市最多 PER_COUNTY 處
            for p in by_county[c][1:PER_COUNTY]:
                if len(chosen) >= MAX_CANDIDATES:
                    break
                chosen.append(p)
        chosen = chosen[:MAX_CANDIDATES]
    chosen.sort(key=lambda p: (order.index(p.county), score(p)))
    return pool, chosen


def build_pack(char: str, show_all: bool = False) -> str:
    st = atlas.char_stats(char)
    total_all = len(atlas.load_places())
    sha = atlas.file_sha256(atlas.RAW_CSV)[:12]
    out = []
    w = out.append
    w(f"# 資料包：{char}")
    w("")
    w(f"- 資料：內政部「臺灣地區地名資料_聚落類」2026-09-24版（SHA-256前12碼{sha}）；同名紀錄照AGENTS.md第2節合併，共{atlas.fmt_int(total_all)}處。")
    w(f"- 產生方式：python3 tools/prepare.py {char}{' --all' if show_all else ''}")
    w("- 數字只能用數字標記寫進內容檔（建置時才換成數字），不要把表格裡的數字直接抄進去。")
    w("- 引號「」裡的由來要從第5節逐字複製；原文的「」改成『』。")
    w("")
    if st.total < atlas.MIN_PLACES:
        w(f"注意：含「{char}」的聚落只有{st.total}處，少於{atlas.MIN_PLACES}處，依AGENTS.md不做這個字。")
        w("")
    w("## 1. 總覽")
    w("")
    w("| 數字標記 | 目前的值 | 意思 |")
    w("|---|---|---|")
    for key, val in [("總數", st.total), ("全部聚落", total_all)]:
        w(f"| {{{{{key}}}}} | {atlas.fmt_int(val)} | {atlas.PH_HELP[key]} |")
    w(f"| {{{{占全部}}}} | {atlas.fmt_pct(st.total / total_all)} | {atlas.PH_HELP['占全部']} |")
    w(f"| {{{{有由來}}}} | {atlas.fmt_int(st.with_meaning)} | {atlas.PH_HELP['有由來']} |")
    w(f"| {{{{有座標}}}} | {atlas.fmt_int(st.with_xy)} | {atlas.PH_HELP['有座標']} |")
    w(f"| {{{{缺字}}}} | {atlas.fmt_int(st.missing)} | {atlas.PH_HELP['缺字']} |")
    w("")
    if st.missing >= atlas.MISSING_NOTE_MIN and st.missing / st.total >= atlas.MISSING_NOTE_RATIO:
        w(f"注意：{{{{缺字}}}}占{{{{總數}}}}的{atlas.fmt_pct(st.missing / st.total)}，"
          "這個字的數量可能偏少；分布段要用{{缺字}}說明（AGENTS.md第6節）。")
        w("")
    allowed = st.allowed_counties()
    w("## 2. 各縣市")
    w("")
    w(f"可以直接提的縣市（數量前五名：{'、'.join(st.top_by_count())}；"
      f"比例前五名，只算至少{atlas.RATIO_MIN_COUNT}處的縣市：{'、'.join(st.top_by_ratio()) or '無'}）。"
      "其他縣市要提，同一段要附上它的{{縣市:X}}或{{比例:X}}。")
    w("")
    w("| 縣市 | 數量 {{縣市:X}} | 該縣市聚落數 | 比例 {{比例:X}} | 可直接提 |")
    w("|---|---|---|---|---|")
    rows = sorted(atlas.COUNTIES, key=lambda c: (-st.by_county[c], atlas.COUNTIES.index(c)))
    for c in rows:
        w(f"| {c} | {st.by_county[c]} | {atlas.county_totals()[c]} | {atlas.fmt_pct(st.ratio(c))} | {'是' if c in allowed else ''} |")
    w("")
    w("## 3. 數量最多的鄉鎮（前10）")
    w("")
    w("| 鄉鎮標記 | 數量 |")
    w("|---|---|")
    for town, k in st.by_town.most_common(10):
        w(f"| {{{{鄉鎮:{town}}}}} | {k} |")
    w("")
    w("## 4. 由來裡常出現的詞（出現在幾處的由來裡）")
    w("")
    w("要寫「由來提到某個詞的有幾處」，用{{由來含:詞}}，任何詞都可以算，不限下面這些。")
    w("")
    for n in (2, 3):
        words = theme_words(st, n, 15)
        w(f"- {n}個字：" + ("、".join(f"{g}（{k}）" for g, k in words) if words else "無"))
    w("")
    pool, chosen = pick_candidates(st, show_all)
    skipped = st.with_meaning - len(pool)
    w(f"## 5. 候選代表地名（列出{len(chosen)}處）")
    w("")
    w(f"有官方由來的{{{{有由來}}}}是{atlas.fmt_int(st.with_meaning)}處"
      + (f"，扣掉地名或村里有缺字（?）、不能當代表地名的{skipped}處，可選的有{len(pool)}處。" if skipped
         else f"，都可以當代表地名。")
      + ("這裡全部列出。" if show_all or len(chosen) == len(pool)
         else f"這裡每個縣市最多列{PER_COUNTY}處，由來有解釋這個字的排前面；要看全部，加上--all重新產生。"))
    w("")
    w("內容檔的代表地名照「- P編號 地名（縣市鄉鎮）」抄寫，例如「- "
      f"{chosen[0].pid} {chosen[0].name}（{chosen[0].loc}）」。" if chosen else "沒有可用的代表地名。")
    w("")
    current = None
    for p in chosen:
        if p.county != current:
            current = p.county
            w(f"### {current}")
            w("")
        w(f"- {p.pid}｜{p.name}｜{p.full_loc}")
        for m, src in p.real_meanings:
            text = re.sub(r"\n+", "／", m)
            note = "，有缺字?，含?的片段不要引用" if atlas.is_garbled(m) else ""
            w(f"  - 由來（{src}{note}）：{text}")
    w("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="產生一個字的資料包")
    ap.add_argument("char", help="要做的字，例如 窩")
    ap.add_argument("--out", help="寫到檔案，不指定就印在畫面上")
    ap.add_argument("--all", action="store_true", help="第5節列出全部候選代表地名")
    args = ap.parse_args()
    char = args.char.strip()
    if not char or not all(atlas.HAN_RE.fullmatch(c) for c in char) or len(char) > 2:
        sys.exit("請給一到兩個漢字，例如：python3 tools/prepare.py 窩")
    text = build_pack(char, args.all)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"寫入 {args.out}（{len(text):,}字）")
    else:
        print(text)


if __name__ == "__main__":
    main()

// 單字頁的互動：點地圖上的紅點看官方由來；滑過縣市表的一列，地圖只亮那個縣市的點。
(() => {
  const art = document.querySelector("article[data-char]");
  if (!art) return;
  const char = art.dataset.char;
  const svg = art.querySelector("svg.map");
  const panel = document.getElementById("place-panel");
  const table = art.querySelector(".county-table");
  const dots = svg ? Array.from(svg.querySelectorAll("circle[data-p]")) : [];
  let data = null;
  let current = null;

  const load = () =>
    data
      ? Promise.resolve(data)
      : fetch("../data/" + encodeURIComponent(char) + ".json")
          .then((r) => {
            if (!r.ok) throw new Error(String(r.status));
            return r.json();
          })
          .then((d) => (data = d));

  dots.forEach((c) => {
    c.setAttribute("tabindex", "0");
    c.setAttribute("role", "button");
    c.setAttribute("aria-label", c.querySelector("title").textContent + "，看官方由來");
  });

  function show(c) {
    if (current) current.classList.remove("on");
    current = c;
    c.classList.add("on");
    c.parentNode.appendChild(c); // 選到的點畫在最上層
    const name = panel.querySelector(".pp-name");
    const loc = panel.querySelector(".pp-loc");
    const body = panel.querySelector(".pp-body");
    name.textContent = c.querySelector("title").textContent;
    loc.textContent = "";
    body.textContent = "讀取由來…";
    panel.hidden = false;
    load()
      .then((d) => {
        const rec = d[c.dataset.p];
        body.textContent = "";
        if (!rec) {
          body.textContent = "找不到這一處的資料。";
          return;
        }
        name.textContent = rec[0];
        loc.textContent = rec[1];
        if (!rec[2].length) {
          const p = document.createElement("p");
          p.className = "pp-none";
          p.textContent = "官方資料沒有記載這一處的由來。";
          body.append(p);
          return;
        }
        rec[2].forEach(([text, src]) => {
          const bq = document.createElement("blockquote");
          const p = document.createElement("p");
          text.split("\n").forEach((line, i) => {
            if (i) p.append(document.createElement("br"));
            p.append(line);
          });
          const f = document.createElement("footer");
          f.textContent = "來源：" + src;
          bq.append(p, f);
          body.append(bq);
        });
      })
      .catch(() => {
        body.textContent = "讀不到由來資料，請重新整理頁面後再點一次。";
      });
  }

  if (svg && panel) {
    svg.addEventListener("click", (e) => {
      const c = e.target.closest("circle[data-p]");
      if (c) show(c);
    });
    svg.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("circle[data-p]")) {
        e.preventDefault();
        show(e.target);
      }
    });
    panel.querySelector(".pp-close").addEventListener("click", () => {
      panel.hidden = true;
      if (current) {
        current.classList.remove("on");
        current.focus();
        current = null;
      }
    });
  }

  if (svg && table) {
    const rows = Array.from(table.querySelectorAll("tr[data-c]"));
    const highlight = (county) => {
      svg.classList.toggle("filtering", Boolean(county));
      dots.forEach((d) => d.classList.toggle("dim", Boolean(county) && d.dataset.c !== county));
      rows.forEach((tr) => tr.classList.toggle("hl", tr.dataset.c === county));
    };
    rows.forEach((tr) => {
      tr.addEventListener("mouseenter", () => highlight(tr.dataset.c));
      tr.addEventListener("focus", () => highlight(tr.dataset.c));
      tr.addEventListener("mouseleave", () => highlight(null));
      tr.addEventListener("blur", () => highlight(null));
    });
  }
})();

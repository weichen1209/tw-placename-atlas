// 首頁：依分類篩選小地圖、查一個字出現在幾處聚落。
(() => {
  const chips = Array.from(document.querySelectorAll(".chip"));
  const tiles = Array.from(document.querySelectorAll(".tile"));

  const filter = (cat) => {
    chips.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cat === cat)));
    tiles.forEach((t) => {
      t.hidden = Boolean(cat) && t.dataset.cat !== cat;
    });
  };
  chips.forEach((b) => b.addEventListener("click", () => filter(b.dataset.cat)));
  const m = decodeURIComponent(location.hash).match(/^#cat=(.+)$/);
  if (m && chips.some((b) => b.dataset.cat === m[1])) filter(m[1]);

  const form = document.getElementById("lookup-form");
  if (!form) return;
  const input = document.getElementById("lookup");
  const out = document.getElementById("lookup-result");
  const pages = JSON.parse(document.getElementById("pages-data").textContent);
  const min = Number(form.dataset.min);
  const han = /^[㐀-䶿一-鿿\u{20000}-\u{3134F}]$/u; // 和atlas.py的HAN_RE同一個範圍
  let counts = null;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input.value.trim();
    if (!v) {
      out.textContent = "請輸入一個字。";
      return;
    }
    if (pages[v]) {
      location.href = "zi/" + encodeURIComponent(v) + ".html";
      return;
    }
    if (Array.from(v).length !== 1) {
      out.textContent = "這裡只能查單一個字。";
      return;
    }
    if (!han.test(v)) {
      out.textContent = "請輸入一個漢字。";
      return;
    }
    (counts ? Promise.resolve(counts) : fetch("data/char-counts.json").then((r) => r.json()).then((d) => (counts = d)))
      .then((d) => {
        const n = d[v] || 0;
        if (!n) out.textContent = "資料裡沒有地名含「" + v + "」的聚落。";
        else if (n < min) out.textContent = "地名含「" + v + "」的聚落有" + n + "處，少於" + min + "處，不做說明頁。";
        else out.textContent = "地名含「" + v + "」的聚落有" + n + "處，還沒有說明頁，可以照AGENTS.md新增。";
      })
      .catch(() => {
        out.textContent = "讀不到統計資料，請重新整理頁面後再查一次。";
      });
  });
})();

# 臺灣地名用字地圖

一個字一頁，看一個字在臺灣聚落地名裡的分布，並引用內政部記載的地名由來說明這個字的意思。

- 網站：https://weichen1209.github.io/tw-placename-atlas/
- 給AI的規則：[AGENTS.md](AGENTS.md)（[CLAUDE.md](CLAUDE.md)只引用它，不另寫規則）
- 變更紀錄：[log.md](log.md)

## 怎麼運作

```
data/raw/            內政部原始資料，不修改
  │  tools/prepare.py <字>   產生資料包：數字標記、各縣市數量、候選代表地名與由來
  ▼
content/<字>.md      依AGENTS.md撰寫；數量寫成{{總數}}這類標記，由來逐字引用
  │  tools/check.py          逐條檢查規則R01–R20，錯誤附代碼和改法
  │  tools/build.py          把標記換成數字，畫地圖和縣市表
  ▼
docs/                GitHub Pages從這裡發佈
```

數字全部由程式從原始資料計算，內容檔裡不寫死數字；引號裡的由來會和原始資料逐字比對。所以不管是人還是AI新增頁面，都照同一份規則、過同一套檢查。

## 在自己的電腦上執行

需要Python 3.9以上，不用安裝其他套件。

```
python3 tools/prepare.py 圍 --out packs/圍.md
python3 tools/check.py
python3 tools/build.py
python3 -m http.server 8000 -d docs
```

依序是：產生「圍」的資料包、檢查全部內容、重新產生網站、在`http://localhost:8000`預覽。新增一個字的完整步驟見AGENTS.md第4節。

## 資料來源與授權

- 內政部「臺灣地區地名資料_聚落類」（[政府資料開放平臺53677](https://data.gov.tw/dataset/53677)，2026-09-24版）
- 內政部「直轄市、縣市界線(TWD97經緯度)」1140318版（[政府資料開放平臺7442](https://data.gov.tw/dataset/7442)）

兩份資料依[政府資料開放授權條款第1版](https://data.gov.tw/license)使用，下載日期與SHA-256記在[data/SOURCE.md](data/SOURCE.md)。網頁字型為LXGW WenKai TC（SIL Open Font License），由Google Fonts載入。

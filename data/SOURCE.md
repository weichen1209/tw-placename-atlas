# 原始資料來源

data/raw/的檔案下載後沒有修改過；tools/check.py會比對下面記錄的SHA-256（規則R18）。換新版資料的做法見AGENTS.md第9節。

## settlements-2026.csv

- 名稱：臺灣地區地名資料_聚落類（檔名「臺灣地區地名資料_聚落類2026年」）
- 提供機關：內政部
- 資料集頁面：https://data.gov.tw/dataset/53677
- 下載網址：https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/4A5AB0C9-0395-4B04-AE50-02624075516F/resource/9E43B451-3177-4CEC-8765-C601660A88E4/download
- 資料集更新日期：2026-09-24；下載日期：2026-11-07
- 授權：政府資料開放授權條款－第1版（https://data.gov.tw/license）
- 格式：CSV（UTF-8，有BOM），37,720筆。欄位：Type、PlaceName、ChinesePhonetic、CommonPhonetic、AnotherName、County、CountyCode、Town、TownCode、Village、PlaceMean、Longitude、Latitude、DataSource
- SHA-256：5f69906f594a2d79338c0caf8bc8dd7ad2bc30823598f04df70f6722279a5efb

## county-boundary-1140318.zip

- 名稱：直轄市、縣市界線(TWD97經緯度)，1140318版SHP格式
- 提供機關：內政部
- 資料集頁面：https://data.gov.tw/dataset/7442
- 下載日期：2026-11-07
- 授權：政府資料開放授權條款－第1版
- 用途：tools/make_geo.py轉成data/geo/counties.json（投影並簡化過的SVG路徑）
- SHA-256：9ff4d337e03a711d7e17caaf4d0c46a0fe2c6bd3660b321a2e35123030d8491c

## 顯名方式

網站每一頁的頁尾都寫「資料來源：內政部」與兩份資料的名稱，並說明依政府資料開放授權條款第1版使用。

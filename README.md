# 校務公開資料儀表板：校際比較

東海大學與一般大學的校際比較儀表板，資料來自教育部「大學校院校務資訊公開平台」公開統計。

## 結構

| 路徑 | 內容 |
|---|---|
| `data/dashboard.json` | 各指標、學制、年度的比較資料（含口徑摘要，為原始來源） |
| `data/notes.json` | 卡片分組與各指標說明文字 |
| `src/index.html` | 頁面範本（樣式與程式，無外部資源） |
| `tools/config.py` | 口徑設定：報表清單、欄名前綴、學制、指標區塊、排名參數（fetch、compute 共用） |
| `tools/fetch.py` | 下載平台報表到 `data/raw/<年>/`（不進版控） |
| `tools/compute.py` | 依口徑把 `data/raw/<年>/` 算成 `data/dashboard.json` |
| `tools/build.py` | 產生 `dist/index.html` |
| `.github/workflows/pages.yml` | 發布到 GitHub Pages（推送到 claude/main 自動發布，也可手動重跑） |

## 這個工具做什麼、不做什麼

- **做**：把 `data/` 裡**已經算好**的比較結果放進頁面範本，產生一個單一檔案的網頁 `dist/index.html`。
- **不做**：`build.py` 不會下載資料，也不會重新計算名次。要更新數字，先用 `fetch.py`、`compute.py`
  更新 `data/dashboard.json`，再重新建置。

## 每年更新

流程：fetch → compute → build → 人工檢查 → commit 並推送（推送到 claude/main 就會自動發布，推送前請確認）。

```bash
python tools/fetch.py --folder 115
python tools/compute.py
python tools/build.py
```

- `--folder` 是平台網址 `.../static_file/<編號>/` 的資料夾編號，每年要到平台確認（114 學年度資料為 `114`）。
  檔名須與平台完全一致；平台更名時會出現 HTTP 404，請改 `tools/config.py` 的 `name`。
- `compute.py` 預設讀 `data/raw/` 下最新的年資料夾，「資料更新日期」預設為今天（`--date YYYYMMDD` 可指定）。
  內建檢查：欄名對應、缺值字串、東海每年在母體、比較結果可追溯到完整排名、東海數值直接回查原始 CSV；
  任一不通過即中止。系所報表驗算不一致只提醒，交付前須查明。
- `python tools/compute.py --check` 只比對、不寫檔：算出的結果與現有 `data/dashboard.json` 不同時列出差異。
  例：用 2026-10-28／29 下載的原始報表執行 `python tools/compute.py --raw data/raw/2026 --date 20261029 --check`，
  結果與目前的 `data/dashboard.json` 逐位元組相同。
- 口徑（`tools/config.py` 的報表、區塊、學制、代碼對照）有變動時，先經確認再改。
- 下載新年度資料前，先列出檔案清單請負責人同意。
- Windows 請把 `python3` 改成 `python`；`compute.py` 需要 pandas、numpy。

## 建置與本機預覽

```bash
python3 tools/build.py
python3 -m http.server -d dist 8000
```

Windows 請把 `python3` 改成 `python`。也可以直接用瀏覽器開啟 `dist/index.html`（不需要伺服器）。

`build.py` 會：

- 只放入頁面用得到的欄位，內部區塊編號換成中性代號；
- 逐值比對交付檔與 `data/`，任何數值不同即中止；
- 交付檔若含內部編號或外部資源請求即中止。

## 注意

- 只放公開平台資料；校內資料不得放入本儲存庫。
- GitHub Pages 網站本身是公開的（即使儲存庫為私人），推送前請確認。
- 交付的網頁不放內部編號（B01～B17、口徑決策編號），`build.py` 會檢查。
- `data/raw/` 不進版控；原始報表由 `fetch.py` 下載到本機。`fetch.py` 尚未實際連線測試過，第一次使用時請留意輸出。
- 計算方式整理自校務研究組原始專案（`校務研究AgentTeam\專案\115學年度_校務公開資料儀表板`）。
  原始專案只能讀、不能改；口徑以 `tools/config.py` 與 `data/dashboard.json` 的「口徑摘要」為準。

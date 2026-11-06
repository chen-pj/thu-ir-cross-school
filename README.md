# 校務公開資料儀表板：校際比較

東海大學與一般大學的校際比較儀表板，資料來自教育部「大學校院校務資訊公開平台」公開統計。

## 結構

| 路徑 | 內容 |
|---|---|
| `data/dashboard.json` | 各指標、學制、年度的比較資料（含口徑摘要，為原始來源） |
| `data/notes.json` | 卡片分組與各指標說明文字 |
| `src/index.html` | 頁面範本（樣式與程式，無外部資源） |
| `tools/build.py` | 產生 `dist/index.html` |
| `.github/workflows/pages.yml` | 發布到 GitHub Pages（僅手動觸發） |

## 建置與本機預覽

```bash
python3 tools/build.py
python3 -m http.server -d dist 8000
```

`build.py` 會：

- 只放入頁面用得到的欄位，內部區塊編號換成中性代號；
- 逐值比對交付檔與 `data/`，任何數值不同即中止；
- 交付檔若含內部編號或外部資源請求即中止。

## 注意

- 只放公開平台資料；校內資料不得放入本儲存庫。
- GitHub Pages 網站本身是公開的（即使儲存庫為私人），發布前請確認。

# 交接說明（給下一個工作階段）

## 已完成（分支 `claude/gracious-cori-c3co2j`）
- 由 claude.ai Artifact「校務公開資料儀表板：校際比較」拆出 `data/`、`src/`、`tools/build.py`、`.github/workflows/pages.yml`。
- 已移除 AI 問答（`sample`）、three.js 外部請求、只給 AI 用的全排名資料。
- `build.py`：只放頁面用得到的欄位；內部區塊編號 B01～B17 改中性代號 m1～m17；逐值比對 2,822 個值與 `data/` 一致；含內部編號或外部請求即中止。
- 畫面文字與原版逐行比對 39 個畫面相同，只改一句：B08 說明「見合併區塊 B14 與資料檔」→「見「學生參與競賽、論文出版」卡片」。
- 320～1920px 七種寬度測試：無橫向捲動、無錯誤、外部請求 0。

## 尚未發布
- 儲存庫為私人；Pages 未開。使用者要「全部寫好後再一次公開」，發布需使用者同意。
- 發布步驟：合併到 `main` → Settings → Pages 設 Source 為 GitHub Actions → Actions 手動 Run workflow。
- 公開性尚未決定：私人庫用 Pages 需 Pro/Team，且網站本身公開；或改公開庫；或不發布只傳 `dist/index.html`。

## 每年半自動更新（2026-11-06 完成）
- 已整理成 `tools/config.py`、`tools/fetch.py`、`tools/compute.py`；用 2026 原始報表算出的 `data/dashboard.json` 與現有檔案逐位元組相同（SHA256 f24a53f6…）。
- `data/raw/` 不進版控（.gitignore）。fetch.py 尚未實際連線測試（下載需先經同意）。

## 原本的規劃
- 原始流程在 `D:\校務研究\AI agent 主題\校務研究AgentTeam\專案\115學年度_校務公開資料儀表板`。**只能讀，不能刪改。**
- 目標：整理成 `tools/fetch.py`（下載平台報表到 `data/raw/<年度>/`）與 `tools/compute.py`（依口徑算出 `data/dashboard.json`），
  並驗證用現有原始報表算出的結果與目前 `data/dashboard.json` 完全一致。
- 口徑見 `data/dashboard.json` 的「口徑摘要」；口徑與數字不可更動。
- 每年流程：fetch → compute → build → 人工檢查 → 手動發布（不做全自動排程）。

## 注意
- 校內資料不能放進儲存庫；只放教育部平台公開資料。
- 交付檔不放內部編號。

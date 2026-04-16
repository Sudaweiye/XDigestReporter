# XDigestReporter 使用說明

## 功能
- 勾選要追蹤的 X 帳號
- 僅抓取當天推文（Asia/Shanghai 時區），每個帳號最多 20 條
- X API 省量策略：
  - 本地 `user_id` 快取（避免重複查詢使用者）
  - 批次使用者名稱解析（每次最多 100 個）
  - 當天以 `since_id` 增量抓取（同一天只抓新增推文）
- 對每條推文輸出：原文 + 簡體中文翻譯
- 使用 GPT-5.3-Codex 生成帳號層級摘要、評價、核心熱點
- 生成全域熱點總結
- 同時生成 Markdown 報告與 LaTeX 編譯後的 PDF 報告
- 支援每日定時執行（Windows 工作排程）
- X API 預算閘門（按「每次請求估算成本」累計）

## 必要條件
- X Bearer Token
- 本機可用的 `codex` 命令（已登入）
- 預設模型：`gpt-5.3-codex`
- 已安裝 LaTeX 編譯器（建議 TeX Live，需可用 `xelatex`）

## 執行
1. 開啟 `XDigestReporter.exe`
2. 填寫 X Token（不需要 OpenAI API Key）
3. 勾選帳號
4. 點擊「立即生成報告」

報告輸出目錄：`dist/reports/`

每次生成會輸出三份檔案（同名不同副檔名）：
- `x_digest_*.md`
- `x_digest_*.tex`
- `x_digest_*.pdf`（由 LaTeX 編譯，包含日期與浮水印 `Jinge Guo專用`）

## 打包
```powershell
cd E:\XDigestReporter
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

可執行檔：`E:\XDigestReporter\dist\XDigestReporter.exe`

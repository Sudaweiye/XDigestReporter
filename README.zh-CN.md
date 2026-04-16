# XDigestReporter 使用说明

## 功能
- 勾选要追踪的 X 账号
- 仅抓取当天推文（Asia/Shanghai 时区），每个账号最多 20 条
- X API 省量策略：
  - 本地 `user_id` 缓存（避免重复查用户）
  - 批量用户名解析（最多 100 个一次请求）
  - 当天 `since_id` 增量抓取（同一天只拉新增推文）
- 对每条推文输出：原文 + 简体中文翻译
- 使用 GPT-5.3-Codex 生成账号级总结、评价、核心热点
- 生成全局热点总结
- 同时生成 Markdown 报告与 LaTeX 编译后的 PDF 报告
- 支持每日定时运行（Windows 任务计划）
- X API 预算闸门（按“每次请求估算成本”累计）

## 必填
- X Bearer Token
- 本机可用的 `codex` 命令（已登录）
- Model 默认：`gpt-5.3-codex`
- 已安装 LaTeX 编译器（推荐 TeX Live，需 `xelatex` 可用）

## 运行
1. 打开 `XDigestReporter.exe`
2. 填写 X Token（无需 OpenAI API Key）
3. 勾选账号
4. 点击“立即生成报告”

报告输出目录：`dist/reports/`

每次生成会输出三份文件（同名不同后缀）：
- `x_digest_*.md`
- `x_digest_*.tex`
- `x_digest_*.pdf`（由 LaTeX 编译，包含日期与水印 `Jinge Guo專用`）

## 打包
```powershell
cd E:\XDigestReporter
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

可执行文件：`E:\XDigestReporter\dist\XDigestReporter.exe`

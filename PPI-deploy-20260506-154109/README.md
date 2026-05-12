# PPI Calculator

飞书多维表格 + LorealGPT 视觉理解的 PPI 计算器。

## 本地安全配置

1. 复制 `.env.example` 为 `.env`。
2. 在 `.env` 里填写飞书自建应用和 LorealGPT 凭据。
3. `.env` 已加入 `.gitignore`，不要把它上传或发给别人。

## 推荐架构

- 飞书多维表格作为用户界面：用户选择需要更新的记录。
- 本地或云端服务负责计算：读取记录、调用 LorealGPT、查 RSP、计算 PPI、写回表格。
- 飞书脚本/插件只负责触发服务端任务，不保存任何密钥。

## POC 顺序

1. 验证飞书应用可以读取 Base 表结构。
2. 读取 `PPI CALCULATOR` 的 `Link` 字段，确认链接数量。
3. 读取 `RSP REFERENCE` 并建立 RSP 查询表。
4. 用 1 条链接验证 LorealGPT 视觉识别 payload。
5. 写回 1 条记录的结果。
6. 扩展到用户选择的记录批量更新。

## 本地扩展按钮

进入 `base-extension` 后运行：

```bash
npm install
npm run dev
```

把终端显示的本地 URL，例如 `http://localhost:5173/`，粘贴到飞书多维表格的“扩展脚本 / 添加脚本”入口中。

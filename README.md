# 咖啡知识 FAQ 机器人

基于 RAG（Retrieval-Augmented Generation）的咖啡知识智能问答机器人。
通过飞书 WebSocket 长连接接收消息，从本地 Markdown 知识库检索内容，由本地 Ollama LLM 生成严格不幻觉的回答。

> 中文文档 · [English README](README_en.md)

---

## 功能特性

- **本地 RAG**：FAISS + `moka-ai/m3e-base` 向量检索 + 本地 Ollama 生成，全程私有部署
- **反幻觉**：严格 prompt（只许引用、禁止编造）+ `temperature=0.3` + 相似度阈值 `0.6`；检索不到 / 答非所问统一回复"暂无此信息"
- **飞书接入**：lark-oapi WebSocket 长连接，私聊直接回复，群聊需 `@小光咖啡百科`
- **反馈闭环**：所有"暂无此信息"自动入 `feedbacks/feedback_YYYYMMDD.jsonl`，并通过飞书互动卡片推送管理员
- **卡片按钮标记**：管理员点击「✓ 已处理 / ✗ 已忽略」按钮即可标记状态（中文：`待处理 / 已处理 / 已忽略`），卡片原地刷新
- **管理员命令**：飞书私聊机器人即可执行 `反馈列表 / 标记 <id> <状态> [备注] / 绑定管理员 / 帮助`
- **Webhook 兜底**：未配置 WebSocket 时退化为 webhook（仅查看、无按钮）

---

## 目录结构

```
FAQ机器人/
├── config/
│   └── settings.py          # pydantic-settings 配置（读取 .env）
├── src/
│   ├── indexer.py           # FAISS 索引构建
│   ├── retriever.py         # 向量检索 + 相似度过滤
│   ├── generator.py         # Ollama 调用 + 严格 prompt
│   ├── handler.py           # RAG 流程编排（含 no_info 判定）
│   ├── feishu_client.py     # 飞书 SDK 封装（发送/回复/卡片）
│   ├── feishu_ws.py         # 飞书 WebSocket + 命令解析 + 卡片回调
│   ├── feedback.py          # 反馈收集 / 状态标记 / 卡片构建
│   ├── notifier.py          # 通知发送
│   ├── scheduler.py         # 定时任务（如索引重建）
│   └── logger.py            # 日志
├── coffee/                  # 咖啡知识库（Markdown，需挂载/复制进来）
├── data/                    # FAISS 索引持久化
├── feedbacks/               # 反馈 jsonl（运行时生成）
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── main.py
```

---

## 快速开始

### 1. 克隆并配置

```bash
git clone <repo> faq-robot && cd faq-robot
cp .env.example .env
# 编辑 .env，填入飞书 app_id/app_secret、Ollama 地址、知识库主机路径
```

### 2. 准备知识库

把咖啡知识 Markdown 文件放进 `./coffee/`（或挂载已有目录到 `/app/coffee`）。
按 `##` 二级标题分块，例：

```markdown
# 咖啡产地

## 埃塞俄比亚

耶加雪菲是埃塞俄比亚的著名咖啡产地……

## 肯尼亚

肯尼亚咖啡以其浓郁的果香闻名……
```

### 3. Docker 启动（推荐）

```bash
docker compose up -d --build
docker logs faq-robot -f
```

健康检查：`curl http://localhost:8081/health`

### 4. 本地运行

```bash
pip install -r requirements.txt
python main.py --rebuild   # 首次构建索引
python main.py --ws         # 启动 WebSocket 服务
python main.py "耶加雪菲是什么咖啡？"   # CLI 单次问答
```

---

## 配置说明（.env）

| 变量 | 必填 | 说明 |
|---|---|---|
| `FEISHU_APP_ID` | ✅ | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用 App Secret |
| `OLLAMA_BASE_URL` | ✅ | Ollama 服务地址，例：`http://localhost:11434` |
| `OLLAMA_MODEL` | ✅ | 模型名，例：`qwen2.5:7b-instruct` |
| `EMBEDDING_MODEL` | | 向量模型，默认 `moka-ai/m3e-base` |
| `SIMILARITY_THRESHOLD` | | 检索相似度阈值，默认 `0.6` |
| `TOP_K` | | 检索 Top-K，默认 `3` |
| `COFFEE_HOST_PATH` | | 宿主机知识库目录绝对路径，挂载到 `/app/coffee` |
| `FEISHU_ADMIN_OPEN_ID` | | 管理员 open_id（接收反馈卡片，可通过 `绑定管理员` 命令自动写入） |
| `FEISHU_ADMIN_CHAT_ID` | | 管理员群 chat_id（备选） |
| `FEISHU_WEBHOOK_URL` | | webhook 兜底地址（无 WebSocket 时使用） |

---

## 飞书使用方式

### 普通用户

- **私聊**：直接发问题
- **群聊**：`@小光咖啡百科 + 问题`（机器人名称需与代码中一致，可在 [src/feishu_ws.py:105](src/feishu_ws.py#L105) 调整）

### 管理员命令（私聊机器人）

| 命令 | 作用 |
|---|---|
| `绑定管理员` 或 `我是管理员` | 将当前账号 open_id 写入 `.env`，后续反馈卡片发到这里 |
| `反馈列表` 或 `待处理反馈` | 列出最近 10 条待处理反馈 |
| `标记 <id> <状态> [备注]` | 例：`标记 fb-20260603-001 已处理 已加入知识库` |
| `帮助` / `help` | 显示命令清单 |

### 反馈卡片按钮

每条新反馈会推送互动卡片到管理员，含两个按钮：
- **✓ 已处理**（绿色）→ 卡片置绿
- **✗ 已忽略**（灰色）→ 卡片置灰

点击后按钮消失、状态原地更新。前提：飞书开发者后台已订阅 **卡片回传交互（card.action.trigger）** 事件。

---

## 反幻觉机制

LLM 默认会按训练知识"自信编造"。本项目通过三层防御：

1. **Prompt 严格化**（[src/generator.py:8](src/generator.py#L8)）
   - 明确禁止使用模型自身知识
   - 不得改写、补充、推测
   - 不能直接回答 → 必须返回"暂无此信息"
2. **低 temperature**（`0.3`）：减少发散
3. **检索阈值**（`SIMILARITY_THRESHOLD=0.6`）：相似度不足时不进入生成阶段，直接 `no_context`

实测效果（[test_e2e.py](test_e2e.py)）：

| 问题 | 之前 | 现在 |
|---|---|---|
| 卢旺达基伍湖风味特点 | 编造"柑橘、草莓" | 暂无此信息 ✓ |
| 区块链是什么 | 给出区块链定义 | 暂无此信息 ✓ |
| 哥斯达黎加塔拉珠海拔 | 正常 | 1500-1950m ✓ |

---

## 数据与隐私

- `.env`、`*.log`、`feedbacks/`、`memory/`、`debug_*.py` 均已加入 `.gitignore`
- 知识库路径 `COFFEE_HOST_PATH` 不应硬编码进仓库，通过环境变量传入
- Ollama 服务运行在本地/局域网，知识库内容不出本地

---

## 技术栈

- **检索**：FAISS（内积）+ sentence-transformers（`moka-ai/m3e-base`）
- **生成**：Ollama + Qwen2.5 系列
- **消息**：lark-oapi WebSocket
- **存储**：JSONL（反馈）/ FAISS bin（索引）
- **运行时**：Python 3.11 + Docker

---

## License

MIT

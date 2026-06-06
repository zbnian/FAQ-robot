# 咖啡知识 FAQ 机器人

基于 RAG（Retrieval-Augmented Generation）的咖啡知识智能问答机器人。
通过飞书 / 企业微信智能机器人长连接接收消息，从本地 Markdown 知识库检索内容，由本地 Ollama LLM 生成严格不幻觉的回答。

> 中文文档 · [English README](README_en.md)

---

## 功能特性

- **本地 RAG**：FAISS + `moka-ai/m3e-base` 向量检索 + 本地 Ollama 生成，全程私有部署
- **反幻觉**：严格 prompt（只许引用、禁止编造）+ `temperature=0.3` + 相似度阈值 `0.6`；检索不到 / 答非所问统一回复"暂无此信息"
- **飞书接入**：lark-oapi WebSocket 长连接，私聊直接回复，群聊需 `@小光咖啡百科`
- **企业微信接入**：[智能机器人长连接](https://developer.work.weixin.qq.com/document/path/101463)（`wss://openws.work.weixin.qq.com`），无需公网 IP；私聊直接回复，群聊需 `@小光咖啡百科`；**反馈回路仍走飞书**
- **反馈闭环**：所有"暂无此信息"自动入 `feedbacks/feedback_YYYYMMDD.jsonl`，并通过飞书互动卡片推送管理员
- **卡片按钮标记**：管理员点击「✓ 已处理 / ✗ 已忽略」按钮即可标记状态（中文：`待处理 / 已处理 / 已忽略`），卡片原地刷新
- **管理员命令**：飞书私聊机器人即可执行 `反馈列表 / 标记 <id> <状态> [备注] / 帮助`；admin open_id 需在 `.env` 中配置 `FEISHU_ADMIN_OPEN_ID`
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
│   ├── wecom_ws.py          # 企业微信智能机器人长连接（不接管 admin / 反馈）
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
| `FEISHU_ADMIN_OPEN_ID` | | 管理员 open_id（接收反馈卡片，应用机器人后台获取 `ou_xxx`） |
| `FEISHU_ADMIN_CHAT_ID` | | 管理员群 chat_id（备选） |
| `FEISHU_WEBHOOK_URL` | | webhook 兜底地址（无 WebSocket 时使用） |
| `WECOM_BOT_ID` | | 企业微信智能机器人 ID（长连接专用，凭证缺失则跳过企微通道） |
| `WECOM_SECRET` | | 企业微信智能机器人密钥（**与回调模式 Token/EncodingAESKey 不同**） |

---

## 飞书使用方式

### 普通用户

- **私聊**：直接发问题
- **群聊**：`@小光咖啡百科 + 问题`（机器人名称需与代码中一致，可在 [src/feishu_ws.py:105](src/feishu_ws.py#L105) 调整）

### 管理员命令（私聊机器人）

| 命令 | 作用 |
|---|---|
| `反馈列表` 或 `待处理反馈` | 列出最近 10 条待处理反馈 |
| `标记 <id> <状态> [备注]` | 例：`标记 fb-20260603-001 已处理 已加入知识库` |
| `帮助` / `help` | 显示命令清单 |

管理员 open_id 需在 `.env` 中配置 `FEISHU_ADMIN_OPEN_ID`（应用机器人后台获取，格式 `ou_xxxxxxxx`）。配置后所有反馈卡片走长连接推送，无需绑定命令。

### 反馈卡片按钮

每条新反馈会推送互动卡片到管理员，含两个按钮：
- **✓ 已处理**（绿色）→ 卡片置绿
- **✗ 已忽略**（灰色）→ 卡片置灰

点击后按钮消失、状态原地更新。前提：飞书开发者后台已订阅 **卡片回传交互（card.action.trigger）** 事件。

---

## 企业微信使用方式

### 通道定位

企业微信**只作为问题接收通道**：
- 用户问"区块链是什么" → 企微收 → RAG 回答（"暂无此信息"）→ 企微回复
- 反馈收集 / 标记 / 绑定管理员 → **仍走飞书**

为什么这样切：飞书有 admin、互动卡片、按钮回调，闭环完整；企微智能机器人没有 admin 概念，把反馈塞进企微反而要重造一套 UI。

### 通道配置

`.env` 增 2 个变量（**与回调模式 Token/EncodingAESKey 不同**）：

```bash
WECOM_BOT_ID=your_bot_id
WECOM_SECRET=your_bot_secret
```

管理后台获取：企业微信管理后台 → 应用 → 智能机器人 → 机器人详情，复制"机器人 ID"和"长连接密钥"。无需配置回调 URL，**WebSocket 是出方向连接**。

### 用户使用

- **私聊**：直接发问题
- **群聊**：`@小光咖啡百科 + 问题`（与飞书同名字，触发词检测在 [src/wecom_ws.py:62](src/wecom_ws.py#L62)）

### 启动行为

| `FEISHU_*` 配置 | `WECOM_*` 配置 | 行为 |
|---|---|---|
| ✅ | ✅ | 双通道并行 |
| ✅ | ❌ | 仅飞书（默认部署） |
| ❌ | ✅ | 仅企微 |
| ❌ | ❌ | 启动失败（提示"至少需要飞书或企微之一"） |

### 约束

- 同一时间只允许一个长连接，**新连接会踢旧** —— 不要在同一台机器上跑多份
- 30s 心跳，断线 SDK 内置指数退避重连
- 同一会话 30 条/分钟、1000 条/小时上限

### 运维提示

> ⚠️ **改了 `.env` 后必须 `--force-recreate`**，否则新环境变量不生效。

普通 `docker compose up -d` 不会因为 `env_file` 变化而重建容器 —— 它只检查 `docker-compose.yml` / Dockerfile / 挂载文件变化。`env_file` 是在 `docker compose up` 时由 compose 进程读取并注入到容器的环境变量里，**容器内部看不到 `.env` 文件本身**，所以改 `.env` 后：

- ✅ 正确：`docker compose up -d --force-recreate`（强制重建容器，env 重新注入）
- ❌ 错误：`docker compose up -d`（容器显示 `Running`，但用的是**旧 env** —— `restart`/`watch` 都救不了，因为环境变量是容器创建时定的）

同理适用于轮换 `FEISHU_APP_SECRET` / `WECOM_SECRET` 等任何 secret：改 `.env` → `--force-recreate` → 看 `Authentication successful` 日志确认。

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
- **消息**：lark-oapi WebSocket（飞书）/ wecom-aibot-python-sdk WebSocket（企微）
- **存储**：JSONL（反馈）/ FAISS bin（索引）
- **运行时**：Python 3.11 + Docker

---

## License

MIT

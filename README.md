# 咖啡知识 FAQ 机器人

基于 RAG 的咖啡知识智能问答机器人，接入飞书 WebSocket，实时回答用户提问。

## 功能特性

- **智能问答**：基于咖啡知识库（coffee/*.md）回答用户问题
- **飞书接入**：通过 WebSocket 长连接接收飞书消息并回复
- **向量检索**：使用 FAISS + sentence-transformers 实现语义搜索
- **来源标注**：回答注明知识库来源
- **反馈收集**：无法回答的问题记录到 feedback 目录

## 目录结构

```
FAQ机器人/
├── config/
│   └── settings.py      # 配置文件
├── src/
│   ├── indexer.py       # FAISS 索引构建
│   ├── retriever.py     # 向量检索
│   ├── generator.py     # LLM 生成回答
│   ├── handler.py       # 消息处理
│   ├── feishu_client.py # 飞书客户端
│   ├── feishu_ws.py     # 飞书 WebSocket
│   ├── feedback.py      # 反馈收集
│   ├── notifier.py      # 通知发送
│   └── scheduler.py     # 定时任务
├── coffee/              # 咖啡知识库
├── data/                # FAISS 索引数据
├── feedbacks/           # 用户反馈记录
└── main.py              # 入口文件
```

## 快速启动

### Docker 部署

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker logs faq-robot -f
```

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 修改 .env 配置
cp .env.example .env
# 编辑 .env 填入飞书凭证

# 启动服务
python main.py --ws
```

## 配置说明

在 `.env` 文件中配置：

```env
# 飞书配置
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# Ollama 配置（可选）
OLLAMA_BASE_URL=http://192.168.31.147:56789
OLLAMA_MODEL=qwen2.5:3b-instruct

# 向量模型
EMBEDDING_MODEL=moka-ai/m3e-base
```

## 知识库格式

知识库位于 `coffee/` 目录，使用 Markdown 格式。按 `##` 二级标题分块：

```markdown
# 咖啡产地

## 埃塞俄比亚

耶加雪菲是埃塞俄比亚的著名咖啡产地...

## 肯尼亚

肯尼亚咖啡以其浓郁的果香闻名...
```

## 使用方式

在飞书中：
- 直接发送消息提问
- 或 @机器人 + 问题

示例问题：
- "耶加雪菲是什么咖啡？"
- "中国有产出咖啡豆吗？"
- "非洲有什么咖啡产国？"

## API 接口

启动后提供 HTTP 接口：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/ask` | POST | 问答接口 |
| `/feedback` | POST | 反馈提交 |

## 技术栈

- **向量检索**：FAISS + sentence-transformers
- **LLM**：Ollama + Qwen2.5
- **消息通道**：飞书 WebSocket 长连接
- **框架**：Python + lark-oapi SDK
# Nexent 平台功能讲解大纲

> **文档目的**：为内部培训和技术分享提供完整的讲解框架，涵盖功能介绍、技术原理和关键代码解读

---

## 目录

1. [平台概述](#一平台概述)
2. [部署与初始化](#二部署与初始化)
3. [Docker容器架构详解](#三docker容器架构详解)
4. [登录与鉴权系统](#四登录与鉴权系统)
5. [模型配置](#五模型配置)
6. [知识库管理](#六知识库管理)
7. [MCP工具接入](#七mcp工具接入)
8. [智能体创建与管理](#八智能体创建与管理)
9. [智能体市场](#九智能体市场)
10. [智能体空间](#十智能体空间)
11. [对话与聊天功能](#十一对话与聊天功能)
12. [记忆管理](#十二记忆管理)
13. [系统监控](#十三系统监控)
14. [数据处理引擎](#十四数据处理引擎)
15. [语音与多模态服务](#十五语音与多模态服务)
16. [北向接口与配置服务](#十六北向接口与配置服务)
17. [用户管理与分权分域](#十七用户管理与分权分域)
18. [总结与展望](#十八总结与展望)

---

## 一、平台概述

### 1.1 产品定位
- **核心理念**：一个提示词，无限种可能
- **产品定位**：零代码智能体自动生成平台
- **核心价值**：无需复杂编排或拖拉拽，纯语言即可开发任意智能体

### 1.2 七大核心特性
| 特性 | 说明 |
|------|------|
| 智能体提示词自动生成 | 将自然语言转化为可执行的Agent提示词 |
| 可扩展数据处理引擎 | 支持20+数据格式，OCR和表格结构提取 |
| 个人级知识库 | 实时导入、自动总结、知识溯源 |
| 互联网知识搜索 | 连接5+网络搜索提供商 |
| 知识级可追溯性 | 提供精确引用，事实可验证 |
| 多模态理解与对话 | 支持语音、文本、图片输入输出 |
| MCP工具生态系统 | 符合MCP规范的Python插件体系 |

### 1.3 技术栈概览

**前端技术栈**
- Next.js 15.5.9 + React 18.2.0
- Ant Design 6.1.3 + TailwindCSS
- TypeScript + Zustand状态管理

**后端技术栈**
- FastAPI + SQLAlchemy
- PostgreSQL + Redis
- Ray分布式计算 + LangChain

**核心依赖**
- OpenAI SDK / smolagents
- Elasticsearch向量数据库
- MinIO对象存储

### 1.4 项目架构图
- 展示 `assets/architecture_zh.png` 架构图
- 讲解各服务组件的交互关系

---

## 二、部署与初始化

### 2.1 部署版本选择

| 版本 | 特点 | 适用场景 |
|------|------|----------|
| **Speed版本** | 轻量快速部署，无租户隔离 | 个人用户、小团队 |
| **Full版本** | 完整功能，企业级租户管理 | 企业级应用、多团队协作 |

### 2.2 部署模式选择

| 模式 | 特点 | 适用场景 |
|------|------|----------|
| **开发模式** | 暴露所有服务端口 | 开发调试 |
| **生产模式** | 仅暴露端口3000 | 生产环境 |
| **基础设施模式** | 仅启动基础设施服务 | 独立部署前端/后端 |

### 2.3 核心服务架构

```
应用服务层:
├── nexent-config (5010)    - 配置服务
├── nexent-runtime (5014)   - 运行时服务
├── nexent-mcp (5011)       - MCP服务
├── nexent-northbound (5013) - 北向服务
├── nexent-web (3000)       - 前端界面
└── nexent-data-process (5012) - 数据处理服务

基础设施层:
├── nexent-elasticsearch (9210) - 搜索引擎
├── nexent-postgresql (5434)    - 主数据库
├── nexent-minio (9010/9011)    - 对象存储
├── redis (6379)                - 缓存服务
├── supabase-kong (8000/8443)   - API网关
└── supabase-auth (9999)        - 认证服务(Full版)
```

### 2.4 部署关键步骤

#### 功能讲解
1. 环境准备：Docker & Docker Compose安装
2. 配置文件：`.env` 环境变量配置
3. 执行部署：`bash deploy.sh` 交互式部署
4. 服务验证：健康检查与状态确认

#### 技术讲解
- Docker Compose服务编排原理
- 环境变量注入与服务依赖管理
- 健康检查机制实现

#### 关键代码解读
```bash
# deploy.sh 核心逻辑
# 文件位置: docker/deploy.sh

# 1. 版本选择
echo "请选择部署版本: 1) Speed  2) Full"
read version_choice

# 2. 模式选择  
echo "请选择部署模式: 1) 开发模式  2) 生产模式"
read mode_choice

# 3. 启动服务
docker-compose -f docker-compose.yml up -d
```

### 2.5 超级管理员账号获取

#### 功能讲解
- 默认邮箱：`suadmin@nexent.com`
- 密码获取：首次部署时用户输入，仅在首次生成时显示
- 权限范围：系统最高权限，可管理所有租户

#### 技术讲解
- Supabase Auth用户创建流程
- 用户租户关系表初始化

#### 关键代码解读
```bash
# 文件位置: docker/deploy.sh (第956-1010行)

# 1. 检查超级管理员是否已存在
check_super_admin_user_exists() {
    curl -s "http://kong:8000/auth/v1/users" \
        -H "apikey: ${SUPABASE_KEY}" | jq -r '.[] | select(.email=="suadmin@nexent.com")'
}

# 2. 创建超级管理员
curl -X POST http://kong:8000/auth/v1/signup \
    -H "apikey: ${SUPABASE_KEY}" \
    -d '{"email":"suadmin@nexent.com","password":"xxx","email_confirm":true}'

# 3. 插入用户租户关系
INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email) 
VALUES ('${user_id}', '', 'SU', '${email}')
```

---

## 三、Docker容器架构详解

### 3.1 Docker Compose文件概览

| 文件 | 用途 |
|------|------|
| `docker-compose.yml` | 开发环境主配置，包含完整服务栈和端口映射 |
| `docker-compose.prod.yml` | 生产环境配置，无外部端口暴露 |
| `docker-compose.dev.yml` | 开发调试配置，支持代码热重载 |
| `docker-compose-monitoring.yml` | 可观测性监控栈 |
| `docker-compose-supabase.yml` | Supabase认证服务（开发环境） |

### 3.2 服务依赖关系图

```
                                    ┌─────────────────────┐
                                    │    nexent-web       │
                                    │   (前端服务:3000)    │
                                    └─────────┬───────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
          ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
          │  nexent-config  │      │ nexent-runtime  │      │ nexent-northbound │
          │  (配置:5010)    │      │  (运行时:5014)  │      │   (北向API:5013)   │
          └────────┬────────┘      └────────┬────────┘      └────────┬────────┘
                   │                        │                        │
                   └────────────────────────┼────────────────────────┘
                                            │
                                            ▼
                              ┌─────────────────────────┐
                              │  nexent-elasticsearch   │
                              │    (搜索引擎:9210)      │
                              │    [健康检查依赖]       │
                              └─────────────────────────┘
```

### 3.3 基础设施层容器

#### 3.3.1 nexent-elasticsearch
| 属性 | 值 |
|------|-----|
| **端口** | 9210:9200 (HTTP API), 9310:9300 (集群通信) |
| **作用** | 全文搜索引擎，存储知识库索引和对话记录 |
| **健康检查** | `curl -sf -u elastic:${ELASTIC_PASSWORD} http://localhost:9200/_cluster/health` |
| **关键配置** | 单节点模式、XPack安全启用、JVM内存配置 |

#### 3.3.2 nexent-postgresql
| 属性 | 值 |
|------|-----|
| **端口** | 5434:5432 |
| **作用** | 主数据库，存储用户数据、Agent配置、知识库元数据、对话记录等 |
| **初始化** | 执行 `init.sql` 创建表结构 |
| **关键表** | conversation_record_t, model_record_t, knowledge_record_t, ag_tenant_agent_t 等 |

#### 3.3.3 redis
| 属性 | 值 |
|------|-----|
| **端口** | 6379:6379 |
| **作用** | 消息队列Broker、缓存、Celery任务队列后端 |
| **健康检查** | `redis-cli ping` |
| **持久化** | AOF + RDB混合持久化 |

#### 3.3.4 nexent-minio
| 属性 | 值 |
|------|-----|
| **端口** | 9010:9000 (API), 9011:9001 (Console) |
| **作用** | 对象存储服务，存储用户上传文件、知识库文档、预览文件等 |
| **初始化** | 自动创建默认bucket、配置生命周期规则（preview/目录7天过期） |

### 3.4 应用服务层容器

#### 3.4.1 nexent-config
| 属性 | 值 |
|------|-----|
| **端口** | 5010:5010 |
| **作用** | 配置管理服务，提供模型配置、知识库管理、Agent配置等API |
| **入口文件** | `backend/config_service.py` |
| **依赖** | nexent-elasticsearch (健康检查) |
| **特殊挂载** | Docker socket（用于MCP容器管理） |

#### 3.4.2 nexent-runtime
| 属性 | 值 |
|------|-----|
| **端口** | 5014:5014 |
| **作用** | 运行时服务，处理Agent执行、WebSocket通信、实时对话流 |
| **入口文件** | `backend/runtime_service.py` |
| **依赖** | nexent-elasticsearch (健康检查) |

#### 3.4.3 nexent-mcp
| 属性 | 值 |
|------|-----|
| **端口** | 5011:5011 |
| **作用** | MCP服务，提供工具调用能力，支持本地和远程MCP服务 |
| **入口文件** | `backend/mcp_service.py` |
| **依赖** | nexent-elasticsearch (健康检查) |
| **技术栈** | FastMCP, SSE传输协议 |

#### 3.4.4 nexent-northbound
| 属性 | 值 |
|------|-----|
| **端口** | 5013:5013 |
| **作用** | 北向API服务，提供外部系统集成接口 |
| **入口文件** | `backend/northbound_service.py` |
| **依赖** | nexent-elasticsearch (健康检查) |

#### 3.4.5 nexent-data-process
| 属性 | 值 |
|------|-----|
| **端口** | 5012:5012 (API), 5555:5555 (Flower), 8265:8265 (Ray Dashboard) |
| **作用** | 数据处理服务，负责文档解析、向量化、知识库构建等异步任务 |
| **入口文件** | `backend/data_process_service.py` |
| **依赖** | redis (健康检查), nexent-elasticsearch (健康检查) |
| **技术栈** | Ray分布式计算、Celery任务队列、Flower监控 |

#### 3.4.6 nexent-web
| 属性 | 值 |
|------|-----|
| **端口** | 3000:3000 |
| **作用** | 前端Web应用，Next.js应用提供用户界面 |
| **依赖** | 无显式依赖，但需要后端服务运行 |
| **环境变量** | HTTP_BACKEND, WS_BACKEND, MINIO_ENDPOINT, MARKET_BACKEND |

### 3.5 Supabase认证服务栈

| 服务 | 容器名称 | 端口 | 作用 |
|------|----------|------|------|
| **kong** | supabase-kong-mini | 8000:8000, 8443:8443 | API网关，路由和认证 |
| **auth** | supabase-auth-mini | 内部 | GoTrue认证服务，处理用户注册/登录 |
| **db** | supabase-db-mini | 5436:5436 | Supabase专用PostgreSQL数据库 |

### 3.6 监控服务栈

| 服务 | 容器名称 | 端口 | 作用 |
|------|----------|------|------|
| **jaeger** | nexent-jaeger | 16686:16686 (UI), 14268 (HTTP) | 分布式链路追踪 |
| **prometheus** | nexent-prometheus | 9090:9090 | 指标收集和存储 |
| **grafana** | nexent-grafana | 3005:3000 | 可视化仪表盘 |
| **otel-collector** | nexent-otel-collector | 4317:4317 (gRPC), 4318:4318 (HTTP) | OpenTelemetry数据收集 |

### 3.7 Dockerfile镜像构建

| Dockerfile | 基础镜像 | 用途 | 关键特性 |
|------------|----------|------|----------|
| `make/main/Dockerfile` | python:3.10-slim | nexent-config, runtime, mcp, northbound | uv包管理、SDK集成、tiktoken预下载 |
| `make/web/Dockerfile` | node:20-alpine | nexent-web | 多阶段构建、BuildKit缓存优化 |
| `make/data_process/Dockerfile` | python:3.10-slim | nexent-data-process | LibreOffice、CLIP模型、NLTK数据 |

### 3.8 启动顺序

```
1. 基础设施层（无依赖）
   ├── nexent-elasticsearch
   ├── nexent-postgresql
   ├── redis
   └── nexent-minio

2. 应用服务层（依赖ES健康检查）
   ├── nexent-config
   ├── nexent-runtime
   ├── nexent-mcp
   ├── nexent-northbound
   └── nexent-data-process (额外依赖redis)

3. 前端层
   └── nexent-web

4. 可选服务
   ├── nexent-openssh-server (profile: terminal)
   └── 监控栈
```

### 3.9 数据持久化

| 服务 | 容器路径 | 宿主机路径 |
|------|----------|------------|
| Elasticsearch | /usr/share/elasticsearch/data | ${ROOT_DIR}/elasticsearch |
| PostgreSQL | /var/lib/postgresql/data | ${ROOT_DIR}/postgresql/data |
| Redis | /data | ${ROOT_DIR}/redis |
| MinIO | /etc/minio/data | ${ROOT_DIR}/minio/data |

### 3.10 关键代码文件

| 文件 | 功能 |
|------|------|
| `docker/docker-compose.yml` | 开发环境主配置 |
| `docker/docker-compose.prod.yml` | 生产环境配置 |
| `docker/deploy.sh` | 部署脚本 |
| `docker/init.sql` | 数据库初始化脚本 |
| `make/main/Dockerfile` | 主服务镜像构建 |
| `make/web/Dockerfile` | 前端镜像构建 |
| `make/data_process/Dockerfile` | 数据处理服务镜像构建 |

---

## 四、登录与鉴权系统

### 4.1 认证架构

#### 功能讲解
- **认证服务**：基于Supabase Auth
- **认证方式**：JWT Token验证
- **会话管理**：Token刷新机制

#### 技术讲解
- JWT Token结构解析
- Token签名验证流程
- 会话过期与刷新策略

#### 关键代码解读
```python
# 文件位置: backend/utils/auth_utils.py (第283-331行)

def _extract_user_id_from_jwt_token(authorization: str) -> Optional[str]:
    """从JWT Token中提取用户ID"""
    # 1. 格式化Token
    token = authorization.replace("Bearer ", "")
    
    # 2. 解码验证JWT
    decoded = jwt.decode(
        token,
        SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_exp": True, "verify_aud": False}
    )
    
    # 3. 提取用户ID
    return decoded.get("sub")
```

### 4.2 认证API端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/user/signup` | POST | 用户注册（支持邀请码） |
| `/user/signin` | POST | 用户登录 |
| `/user/logout` | POST | 用户登出 |
| `/user/session` | GET | 获取当前会话 |
| `/user/current_user_info` | GET | 获取当前用户信息 |
| `/user/refresh_token` | POST | 刷新Token |

### 4.3 Speed模式（无认证模式）

#### 功能讲解
- 适用场景：个人使用、快速体验
- 特点：无需登录，自动使用默认用户

#### 关键代码解读
```python
# 文件位置: backend/consts/const.py (第96-97行)
DEPLOYMENT_VERSION = os.getenv("DEPLOYMENT_VERSION", "speed")
IS_SPEED_MODE = DEPLOYMENT_VERSION == "speed"

# 文件位置: backend/utils/auth_utils.py (第345-348行)
if IS_SPEED_MODE:
    return DEFAULT_USER_ID, DEFAULT_TENANT_ID
```

---

## 五、模型配置

### 5.1 支持的模型提供商

| 提供商 | API基础URL | 说明 |
|--------|------------|------|
| **SiliconFlow** | `https://api.siliconflow.cn/v1/` | 国内AI模型平台 |
| **OpenAI** | - | OpenAI官方API |
| **DashScope** | `https://dashscope.aliyuncs.com/compatible-mode/v1/` | 阿里云灵积平台 |
| **TokenPony** | `https://api.tokenpony.cn/v1/` | TokenPony平台 |
| **ModelEngine** | 动态配置 | 企业内部模型引擎 |
| **OpenAI-API-Compatible** | 用户自定义 | 兼容OpenAI API的自定义服务 |

### 5.2 模型类型详解

| 类型 | 说明 | 用途 |
|------|------|------|
| `llm` | 大语言模型 | 文本对话、推理、工具调用 |
| `embedding` | 文本向量模型 | 文本向量化，用于知识库检索 |
| `multi_embedding` | 多模态向量模型 | 支持文本、图像等多模态向量化 |
| `rerank` | 重排序模型 | 搜索结果重排序优化 |
| `vlm` | 视觉语言模型 | 图像理解、视觉问答 |
| `stt` | 语音转文字模型 | 语音识别 |
| `tts` | 文字转语音模型 | 语音合成 |

### 5.3 大语言模型(LLM)详解

#### 功能讲解
- **核心作用**：智能体的"大脑"，负责理解用户意图、推理决策、工具调用
- **应用场景**：对话问答、文档总结、代码生成、任务规划

#### 技术讲解
- Temperature参数：控制输出随机性（0-1，越低越确定）
- Top_p参数：控制输出多样性（核采样）
- Max_tokens：控制最大输出长度

#### 关键代码解读
```python
# 文件位置: sdk/nexent/core/models/openai_llm.py

class OpenAIModel(OpenAIServerModel):
    def __init__(self, 
                 observer: MessageObserver = MessageObserver, 
                 temperature=0.2,      # 采样温度
                 top_p=0.95,          # Top-p采样
                 ssl_verify=True,      # SSL验证
                 model_factory: Optional[str] = None, 
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
```

### 5.4 向量模型详解

#### 功能讲解
- **核心作用**：将文本转换为向量表示，用于语义搜索
- **应用场景**：知识库索引、语义检索、相似度计算

#### 技术讲解
- 向量维度：不同模型输出维度不同（如1024、1536）
- 分块处理：大文本自动分块向量化
- 相似度计算：余弦相似度

#### 关键代码解读
```python
# 文件位置: sdk/nexent/core/models/embedding_model.py

class TextEmbedding:
    """文本向量模型"""
    def __call__(self, input: str | list[str]) -> list[float]:
        return self.model.embed(input)

class MultimodalEmbedding:
    """多模态向量模型"""
    def __call__(self, input: list[dict]) -> list[float]:
        # input: [{"text": "内容"}, {"image": "图片URL"}]
        return self.model.embed(input)
```

### 5.5 模型健康检查

#### 功能讲解
- 连接性检测：验证模型API是否可用
- 向量维度检测：自动识别向量模型输出维度
- 配置验证：添加模型前的预检查

#### 关键代码解读
```python
# 文件位置: backend/services/model_health_service.py

async def check_model_connectivity(model_config: dict) -> bool:
    """检测模型连接性"""
    try:
        response = await client.chat.completions.create(
            model=model_config["model_name"],
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10
        )
        return True
    except Exception:
        return False
```

### 5.6 数据库模型

```python
# 文件位置: backend/database/db_models.py (第136-171行)

class ModelRecord(TableBase):
    model_id = Column(Integer, primary_key=True)
    model_repo = Column(String(100))      # 模型仓库路径
    model_name = Column(String(100))      # 模型名称
    model_factory = Column(String(100))   # 模型提供商
    model_type = Column(String(100))      # 模型类型
    api_key = Column(String(500))         # API密钥
    base_url = Column(String(500))        # API基础URL
    max_tokens = Column(Integer)          # 最大token数
    display_name = Column(String(100))    # 显示名称
    connect_status = Column(String(100))  # 连接状态
```

---

## 六、知识库管理

### 6.1 支持的知识库类型

| 类型 | 描述 | 实现类 |
|------|------|--------|
| `elasticsearch` | 默认向量数据库 | ElasticSearchCore |
| `datamate` | 外部知识库集成 | DataMateCore |
| `dify` | Dify知识库同步 | DifySearchTool |

### 6.2 向量数据库架构

#### 功能讲解
- 抽象工厂模式设计
- 统一的向量数据库接口
- 支持多种后端扩展

#### 关键代码解读
```python
# 文件位置: sdk/nexent/vector_database/base.py

class VectorDatabaseCore(ABC):
    """向量数据库操作的抽象基类"""
    
    @abstractmethod
    def create_index(self, index_name: str, embedding_dim: int) -> bool:
        """创建索引"""
    
    @abstractmethod
    def vectorize_documents(self, index_name: str, embedding_model, documents: List[Dict]) -> int:
        """文档向量化入库"""
    
    @abstractmethod
    def semantic_search(self, index_names: List[str], query_text: str, embedding_model, top_k: int) -> List[Dict]:
        """语义搜索"""
    
    @abstractmethod
    def hybrid_search(self, index_names: List[str], query_text: str, embedding_model, top_k: int, weight: float) -> List[Dict]:
        """混合搜索"""
```

### 6.3 文档分片功能

#### 功能讲解
- **目的**：将长文档切分为适合检索的小块
- **策略**：basic（基础）、by_title（按标题）、none（不分块）

| 策略 | 描述 | 适用场景 |
|------|------|----------|
| `basic` | 根据内容长度自动分块 | 大多数文档 |
| `by_title` | 以标题为界限分块 | 结构化文档、技术文档 |
| `none` | 返回单个完整块 | 短文档 |

#### 技术讲解
- 分块参数：max_characters（最大字符数）、new_after_n_chars（分块阈值）
- 处理器：UnstructuredProcessor（通用）、OpenPyxlProcessor（Excel）

#### 关键代码解读
```python
# 文件位置: sdk/nexent/data_process/unstructured_processor.py

def _process_file(self, file_data: bytes, chunking_strategy: str, filename: str):
    # 1. 使用unstructured库进行文档分区
    elements = partition(file=file_io, filename=filename)
    
    # 2. 根据策略处理分区元素
    if chunking_strategy == "none":
        return self._create_single_document(elements, filename)
    else:
        return self._create_chunked_documents(elements, filename)

# 分块参数配置
default_params = {
    "max_characters": 1536,      # 每个块最大字符数
    "new_after_n_chars": 1024,   # 达到此字符数后开始新块
}
```

### 6.4 文档总结功能

#### 功能讲解
- **目的**：自动生成知识库摘要，帮助用户快速了解内容
- **方法**：Map-Reduce架构 + K-means聚类

#### 技术讲解
```
总结流程:
┌─────────────────────────────────────────────────────────────┐
│  1. 从ES获取文档样本                                          │
│  2. 计算文档级嵌入向量                                        │
│  3. K-means聚类分组                                          │
│  4. Map阶段：总结每个文档                                     │
│  5. Reduce阶段：合并文档总结为聚类总结                        │
│  6. 合并所有聚类总结                                          │
└─────────────────────────────────────────────────────────────┘
```

#### 关键代码解读
```python
# 文件位置: backend/utils/document_vector_utils.py

def extract_representative_chunks_smart(chunks: List[Dict], max_chunks: int = 3):
    """
    智能提取代表性分块策略：
    1. 始终包含第一个分块（通常包含标题/摘要）
    2. 提取关键词密度最高的分块（重要内容）
    3. 包含最后一个分块（可能包含结论）
    """
    selected = [chunks[0]]  # 第一个分块
    
    # 计算关键词密度
    keyword_scores = [calculate_keyword_density(chunk) for chunk in chunks]
    top_indices = sorted(range(len(keyword_scores)), key=lambda i: keyword_scores[i], reverse=True)
    
    # 选择高分块
    for idx in top_indices:
        if idx not in [0, len(chunks)-1] and len(selected) < max_chunks:
            selected.append(chunks[idx])
    
    selected.append(chunks[-1])  # 最后一个分块
    return selected
```

### 6.5 知识库搜索模式

| 模式 | 描述 | 特点 |
|------|------|------|
| `hybrid` | 混合搜索 | 结合精确匹配和语义搜索，可配置权重 |
| `accurate` | 精确搜索 | 基于关键词的模糊文本匹配 |
| `semantic` | 语义搜索 | 基于向量相似度的语义搜索 |

#### 关键代码解读
```python
# 文件位置: sdk/nexent/core/tools/knowledge_base_search_tool.py

class KnowledgeBaseSearchTool(Tool):
    name = "knowledge_base_search"
    description = "基于你的查询词在本地知识库中进行搜索"
    
    def forward(self, query: str) -> str:
        if self.search_mode == "hybrid":
            return self.search_hybrid(query, self.index_names)
        elif self.search_mode == "accurate":
            return self.search_accurate(query, self.index_names)
        elif self.search_mode == "semantic":
            return self.search_semantic(query, self.index_names)
```

### 6.6 支持的文件格式

```
文档格式: .txt, .pdf, .docx, .doc, .html, .htm, .md, .rtf, .odt, .pptx, .ppt
表格格式: .xlsx, .xls
```

---

## 七、MCP工具接入

### 7.1 MCP概述

#### 功能讲解
- **MCP (Model Context Protocol)**：连接AI与外部系统的开放标准
- **核心能力**：
  - Tools：可由LLM调用的函数
  - Resources：可读取的文件型数据
  - Prompts：服务器可共享的模板

#### 技术讲解
- MCP协议相当于AI的"USB-C"
- 统一的工具发现和调用机制
- 支持多种传输协议

### 7.2 本地MCP工具

#### 功能讲解
- 内置于平台的工具集合
- 包括：知识库搜索、网络搜索、终端工具等

#### 关键代码解读
```python
# 文件位置: backend/tool_collection/mcp/local_mcp_service.py

from fastmcp import FastMCP

local_mcp_service = FastMCP("local")

@local_mcp_service.tool(name="knowledge_base_search",
                        description="在本地知识库中搜索")
async def knowledge_search(query: str) -> str:
    return search_result
```

### 7.3 外部MCP工具接入

#### 功能讲解
- 支持接入第三方MCP服务器
- 支持Docker容器化部署MCP服务

#### 接入方式

**方式一：URL接入**
```
输入MCP服务器URL → 健康检查 → 工具发现 → 注册使用
```

**方式二：Docker镜像部署**
```
上传.tar镜像文件 → 启动容器 → 自动注册 → 工具发现
```

#### 关键代码解读
```python
# 文件位置: backend/services/remote_mcp_service.py

async def add_remote_mcp_server_list(
    tenant_id: str,
    remote_mcp_server: str,        # MCP服务器URL
    remote_mcp_server_name: str,   # 服务名称
    authorization_token: str = None,
):
    # 1. 检查名称重复
    if check_mcp_name_exists(remote_mcp_server_name, tenant_id):
        raise MCPNameIllegal("MCP name already exists")
    
    # 2. 健康检查
    if not await mcp_server_health(remote_mcp_server, authorization_token):
        raise MCPConnectionError("MCP connection failed")
    
    # 3. 写入数据库
    create_mcp_record(mcp_data={...}, tenant_id=tenant_id)
```

### 7.4 MCP传输协议

| 协议 | URL特征 | 说明 |
|------|---------|------|
| SSE | 以`/sse`结尾 | Server-Sent Events |
| StreamableHttp | 以`/mcp`结尾或默认 | HTTP流式传输 |

#### 关键代码解读
```python
# 文件位置: backend/services/tool_configuration_service.py (第509-543行)

async def _call_mcp_tool(mcp_url: str, tool_name: str, inputs: Dict, authorization_token: str):
    """调用MCP工具的核心方法"""
    # 根据URL选择传输协议
    if url.endswith("/sse"):
        transport = SSETransport(url=url, headers=headers)
    else:
        transport = StreamableHttpTransport(url=url, headers=headers)
    
    client = Client(transport=transport)
    async with client:
        result = await client.call_tool(name=tool_name, arguments=inputs)
        return result.content[0].text
```

### 7.5 内置工具列表

| 工具名称 | 功能描述 |
|---------|---------|
| knowledge_base_search | 知识库搜索 |
| tavily_search | Tavily网络搜索 |
| exa_search | Exa网络搜索 |
| terminal_tool | 终端命令执行 |
| weather_tool | 天气查询 |
| ... | 20+工具 |

---

## 八、智能体创建与管理

### 8.1 智能体创建流程

#### 功能讲解
```
创建流程:
┌─────────────────────────────────────────────────────────────┐
│  1. 填写基本信息（名称、描述）                                 │
│  2. 选择模型（LLM/VLM）                                       │
│  3. 配置工具（启用/禁用）                                     │
│  4. 编写提示词（手动/AI生成）                                 │
│  5. 配置子智能体（可选）                                      │
│  6. 设置权限（私有/组级）                                     │
│  7. 测试验证                                                  │
│  8. 发布版本                                                  │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 智能体必填项

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 智能体内部名称（英文） |
| display_name | 是 | 智能体显示名称 |
| description | 是 | 智能体描述 |
| model_id | 是 | 关联的模型ID |
| max_steps | 否 | 最大执行步数，默认5 |
| duty_prompt | 否 | 职责提示词 |
| constraint_prompt | 否 | 约束提示词 |
| few_shots_prompt | 否 | 示例提示词 |

#### 关键代码解读
```python
# 文件位置: sdk/nexent/core/agents/agent_model.py (第36-44行)

class AgentConfig(BaseModel):
    name: str = Field(description="Agent name")           # 必填
    description: str = Field(description="Agent description")  # 必填
    tools: List[ToolConfig] = Field(description="Tool list")   # 必填
    max_steps: int = Field(default=5)                     # 可选
    model_name: str = Field(description="Model alias")    # 必填
    prompt_templates: Optional[Dict] = None               # 可选
    managed_agents: List[AgentConfig] = []                # 可选
```

### 8.3 提示词AI生成

#### 功能讲解
- **输入**：任务描述
- **输出**：
  - duty_prompt（职责提示词）
  - constraint_prompt（约束提示词）
  - few_shots_prompt（示例提示词）
  - agent_var_name（智能体变量名）
  - agent_display_name（智能体显示名）
  - agent_description（智能体描述）

#### 技术讲解
- 多线程并发生成各部分提示词
- 流式返回生成结果

#### 关键代码解读
```python
# 文件位置: backend/services/prompt_service.py (第59-224行)

def generate_and_save_system_prompt_impl(agent_id, model_id, task_description, ...):
    # 并发生成各部分提示词
    prompt_configs = [
        ("duty", prompt_for_generate["DUTY_SYSTEM_PROMPT"]),
        ("constraint", prompt_for_generate["CONSTRAINT_SYSTEM_PROMPT"]),
        ("few_shots", prompt_for_generate["FEW_SHOTS_SYSTEM_PROMPT"]),
        ("agent_var_name", prompt_for_generate["AGENT_VARIABLE_NAME_SYSTEM_PROMPT"]),
        ("agent_display_name", prompt_for_generate["AGENT_DISPLAY_NAME_SYSTEM_PROMPT"]),
        ("agent_description", prompt_for_generate["AGENT_DESCRIPTION_SYSTEM_PROMPT"]),
    ]
    
    # 多线程并发
    for tag, sys_prompt in prompt_configs:
        thread = threading.Thread(target=run_and_flag, args=(tag, sys_prompt))
        thread.start()
    
    # 流式返回
    yield from _stream_results(produce_queue, latest, stop_flags, threads)
```

### 8.4 提示词模板结构

```yaml
# 文件位置: backend/prompts/manager_system_prompt_template_zh.yaml

system_prompt: |-
  你是一个{{ duty }}。
  
  ## 约束条件
  {{ constraint }}
  
  ## 示例
  {{ few_shots }}
  
  ## 可用工具
  {% for tool in tools.values() %}
  - {{ tool.name }}: {{ tool.description }}
  {% endfor %}
  
  ## 可用助手
  {% for agent in managed_agents.values() %}
  - {{ agent.name }}: {{ agent.description }}
  {% endfor %}
```

### 8.5 版本管理

#### 功能讲解
- **草稿版本**：version_no = 0，编辑状态
- **发布版本**：version_no >= 1，已发布状态

#### 版本操作
| 操作 | 说明 |
|------|------|
| 发布版本 | 将草稿保存为新版本 |
| 回滚版本 | 回退到指定历史版本 |
| 版本比较 | 对比两个版本差异 |
| 禁用版本 | 禁用指定版本 |

#### 关键代码解读
```python
# 文件位置: backend/services/agent_version_service.py

def publish_version_impl(agent_id, tenant_id, version_name, release_note):
    # 1. 获取草稿数据
    agent_draft, tools_draft, relations_draft = query_agent_draft(agent_id, tenant_id)
    
    # 2. 计算新版本号
    new_version_no = get_next_version_no(agent_id, tenant_id)
    
    # 3. 创建快照
    insert_agent_snapshot(agent_snapshot)
    insert_tool_snapshot(tool_snapshot)
    insert_relation_snapshot(rel_snapshot)
    
    # 4. 更新当前版本号
    update_agent_current_version(agent_id, tenant_id, new_version_no)
```

### 8.6 智能体运行时构建

#### 关键代码解读
```python
# 文件位置: backend/agents/create_agent_info.py (第72-208行)

async def create_agent_config(agent_id, tenant_id, user_id, language, version_no):
    # 1. 获取智能体基本信息
    agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    
    # 2. 递归创建子智能体配置
    sub_agent_ids = query_sub_agents_id_list(agent_id, tenant_id, version_no)
    managed_agents = []
    for sub_agent_id in sub_agent_ids:
        sub_config = await create_agent_config(sub_agent_id, ...)
        managed_agents.append(sub_config)
    
    # 3. 创建工具配置列表
    tool_list = await create_tool_config_list(agent_id, tenant_id, user_id, version_no)
    
    # 4. 构建系统提示词
    system_prompt = Template(prompt_template["system_prompt"]).render({
        "duty": duty_prompt,
        "constraint": constraint_prompt,
        "few_shots": few_shots_prompt,
        "tools": {tool.name: tool for tool in tool_list},
        "managed_agents": {agent.name: agent for agent in managed_agents},
    })
    
    return AgentConfig(
        name=agent_info["name"],
        description=agent_info["description"],
        tools=tool_list,
        max_steps=agent_info.get("max_steps", 10),
        managed_agents=managed_agents
    )
```

---

## 九、智能体市场

### 9.1 功能概述

#### 功能讲解
- **定位**：汇集官方与社区创作者打造的高质量智能体平台
- **价值**：用户可直接使用预构建智能体，或将其作为子智能体组合
- **特点**：精选推荐、分类浏览、一键安装

### 9.2 核心功能

#### 9.2.1 探索与发现
- **分类浏览**：按使用场景分类浏览智能体
- **搜索功能**：支持按名称或描述搜索
- **精选智能体**：横向滚动展示精选推荐
- **标签过滤**：按标签筛选智能体

#### 9.2.2 智能体详情展示
详情弹窗包含以下标签页：
- **基础信息**：名称、作者、描述、分类、标签、下载次数
- **模型配置**：最大步数、推荐模型
- **提示词**：职责、约束、示例提示词
- **工具**：配置的工具列表及参数
- **MCP服务器**：配置的MCP服务器信息

#### 9.2.3 智能体安装流程
```
安装流程:
┌─────────────────────────────────────────────────────────────┐
│  1. 选择模型：为智能体配置模型（统一配置或分别配置）           │
│  2. 配置本地工具：补充本地工具的许可                          │
│  3. 配置外部MCP工具：补充MCP工具的许可                        │
│  4. 安装完成：智能体自动出现在智能体空间                      │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 API接口

```typescript
// 文件位置: frontend/services/api.ts (第242-262行)
market: {
  agents: (params?) => `${API_BASE_URL}/market/agents`,
  agentDetail: (agentId) => `${API_BASE_URL}/market/agents/${agentId}`,
  categories: `${API_BASE_URL}/market/categories`,
  tags: `${API_BASE_URL}/market/tags`,
  mcpServers: (agentId) => `${API_BASE_URL}/market/agents/${agentId}/mcp_servers`,
}
```

### 9.4 关键代码文件

| 文件 | 功能 |
|------|------|
| [frontend/app/[locale]/market/page.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/market/page.tsx) | 智能体市场页面 |
| [frontend/app/[locale]/market/components/MarketAgentDetailModal.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/market/components/MarketAgentDetailModal.tsx) | 详情弹窗组件 |
| [frontend/types/market.ts](file:///Users/gerui/nexent/frontend/types/market.ts) | 市场类型定义 |
| [frontend/services/marketService.ts](file:///Users/gerui/nexent/frontend/services/marketService.ts) | 市场API服务 |

---

## 十、智能体空间

### 10.1 功能概述

#### 功能讲解
- **定位**：用户管理所有已开发智能体的中心
- **展示方式**：卡片形式展示所有智能体及详细配置
- **核心功能**：删除、导出、查看关系、快速对话

### 10.2 智能体卡片展示

每个智能体卡片包含：
- **智能体图标**：自动生成的头像
- **智能体名称**：显示名称
- **智能体作者**：作者信息
- **智能体描述**：功能描述
- **智能体状态**：可用/不可用状态
- **NEW标记**：新导入的智能体显示NEW标记

### 10.3 管理操作

| 操作 | 功能描述 |
|------|----------|
| **查看详情** | 点击卡片查看完整配置信息 |
| **编辑** | 跳转到智能体开发页面修改 |
| **删除** | 删除智能体（不可撤销） |
| **导出** | 导出为JSON配置文件 |
| **查看关系** | 查看智能体与工具/子智能体的协作关系 |
| **对话** | 跳转到对话页面使用该智能体 |

### 10.4 创建与导入

#### 功能讲解
- **创建智能体**：跳转到智能体开发页面创建新智能体
- **导入智能体**：从JSON文件导入智能体配置

#### 关键代码解读
```python
# 文件位置: backend/services/agent_service.py (第990-1152行)

async def export_agent_impl(agent_id: int, authorization: str) -> str:
    """导出指定智能体及其所有子智能体的配置信息"""
    # 递归导出所有子智能体
    # 返回JSON格式配置

async def import_agent_impl(agent_info: ExportAndImportDataFormat, authorization: str):
    """使用DFS导入智能体"""
    # 解析JSON配置
    # 递归创建智能体和子智能体
```

### 10.5 智能体详情弹窗

详情弹窗包含以下标签页：
- **基础信息**：ID、名称、显示名称、描述、状态
- **模型配置**：业务逻辑模型、模型名称、最大步数
- **提示词**：职责、约束、示例提示词
- **工具**：配置的工具列表
- **子智能体**：配置的子智能体列表

### 12.6 关键代码文件

| 文件 | 功能 |
|------|------|
| [frontend/app/[locale]/space/page.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/space/page.tsx) | 智能体空间页面 |
| [frontend/app/[locale]/space/components/AgentCard.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/space/components/AgentCard.tsx) | 智能体卡片组件 |
| [frontend/app/[locale]/space/components/AgentDetailModal.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/space/components/AgentDetailModal.tsx) | 详情弹窗组件 |

---

## 十一、对话与聊天功能

### 11.1 对话管理实现

#### 功能讲解
- **对话创建**：创建新对话记录
- **消息保存**：保存用户和助手消息
- **历史记录**：获取完整对话历史
- **标题生成**：使用LLM自动生成对话标题

#### 消息单元类型
```python
# 支持的消息类型
- string/final_answer: 文本内容
- search_content: 搜索结果
- picture_web: 图片内容
- model_output: 模型输出
- model_output_thinking: 思考过程
- model_output_code: 代码输出
```

### 11.2 API接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/conversation/create` | PUT | 创建新对话 |
| `/conversation/list` | GET | 获取对话列表 |
| `/conversation/{conversation_id}` | GET | 获取对话历史 |
| `/conversation/rename` | POST | 重命名对话 |
| `/conversation/{conversation_id}` | DELETE | 删除对话 |
| `/conversation/generate_title` | POST | 生成对话标题 |

### 11.3 流式响应实现

#### 功能讲解
- **实时更新**：使用SSE实时推送消息
- **增量渲染**：逐步显示AI思考过程和回答
- **超时控制**：120秒超时自动停止
- **错误恢复**：网络中断自动重连

#### 关键代码解读
```python
# 文件位置: backend/agents/agent_run_manager.py (第10-69行)

class AgentRunManager:
    """单例模式管理Agent运行实例"""
    _instances: Dict[str, "AgentRunManager"] = {}
    
    def get_instance(self, conversation_id: str) -> "AgentRunManager":
        # 支持并发多个对话的流式响应
        # 提供停止机制
```

```typescript
// 文件位置: frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx (第35-953行)

function handleStreamResponse(reader, updateMessage, signal):
    // 处理流式响应数据
    // 支持消息类型: model_output, model_output_thinking, search_content, final_answer等
```

### 11.4 多模态对话支持

#### 图片支持
- 支持格式：jpg, jpeg, png, gif, webp, svg, bmp
- 文件大小限制：10MB
- 功能：预览、拖拽上传、点击放大

#### 文件支持
```
文档类型: pdf, doc, docx, xls, xlsx, csv, ppt, pptx, txt, md
代码文件: js, ts, jsx, tsx, py, css, html, json, xml
```

#### 语音支持
- **STT**：WebSocket实时语音识别
- **TTS**：WebSocket流式语音合成

### 11.5 聊天界面功能

#### 核心组件
- **ChatInterface**：主聊天界面组件
- **ChatInput**：输入组件（支持文本、文件、语音）
- **ChatStreamMain**：流式消息显示
- **ChatSidebar**：对话列表侧边栏
- **ChatRightPanel**：搜索结果面板

#### 交互功能
- 消息点赞/踩功能
- 消息复制
- 图片预览
- 文件附件展示
- 代码高亮显示
- 思考过程折叠展示

### 10.6 关键代码文件

| 文件 | 功能 |
|------|------|
| [backend/services/conversation_management_service.py](file:///Users/gerui/nexent/backend/services/conversation_management_service.py) | 对话管理服务 |
| [backend/apps/conversation_management_app.py](file:///Users/gerui/nexent/backend/apps/conversation_management_app.py) | 对话API |
| [frontend/app/[locale]/chat/internal/chatInterface.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/chat/internal/chatInterface.tsx) | 聊天界面 |
| [frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx) | 流式处理 |

---

## 十二、记忆管理

### 12.1 功能概述

#### 功能讲解
- **核心价值**：为智能体提供持久化的上下文感知能力
- **作用**：实现跨对话会话的知识累积与检索
- **效果**：提升人机交互的连贯性和个性化程度

### 12.2 四层记忆层级

| 层级 | 作用域 | 存储内容 | 适用场景 | 管理权限 |
|------|--------|----------|----------|----------|
| **租户级** | 组织全局 | 企业标准流程、合规政策 | 企业知识管理 | 租户管理员 |
| **智能体级** | 特定智能体 | 专业领域知识、技能模板 | 专业技能积累 | 租户管理员 |
| **用户级** | 特定用户 | 个人偏好、使用习惯 | 个性化服务 | 用户自己 |
| **用户-智能体级** | 用户+智能体 | 协作历史、个性化事实 | 深度协作 | 用户自己 |

**记忆优先级**：租户级 → 用户-智能体级 → 用户级 → 智能体级

### 12.3 记忆搜索与存储机制

#### 存储机制
- **向量数据库**：使用Elasticsearch作为向量存储后端
- **索引命名规则**：`mem0_{model_repo}_{model_name}_{embedding_dims}`
- **LLM推理**：添加记忆时可选择启用LLM进行智能提取

#### 搜索机制
```python
# 文件位置: sdk/nexent/memory/memory_service.py

async def search_memory_in_levels(query_text, memory_config, tenant_id, 
                                   user_id, agent_id, top_k=5, threshold=0.65):
    # 并发搜索多个层级
    # 合并结果并标记memory_level
    # 返回带层级标签的结果列表
```

### 12.4 API接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/memory/config/load` | GET | 加载用户配置 |
| `/memory/config/set` | POST | 设置配置项 |
| `/memory/add` | POST | 添加记忆 |
| `/memory/search` | POST | 语义搜索 |
| `/memory/list` | GET | 列出记忆 |
| `/memory/delete/{memory_id}` | DELETE | 删除记忆 |
| `/memory/clear` | DELETE | 清除记忆 |

### 12.5 关键代码解读

```python
# 文件位置: sdk/nexent/memory/memory_core.py

class MemoryCore:
    """记忆实例管理 - 单例模式"""
    _instances: Dict[str, "MemoryCore"] = {}
    
    def get_memory_instance(self, config_hash: str) -> "AsyncMemory":
        # 通过配置哈希实现实例缓存
        # 集成mem0的AsyncMemory类
```

```python
# 文件位置: backend/utils/memory_utils.py

def build_memory_config(tenant_id):
    # 组装LLM配置（用于记忆推理）
    # 组装Embedding配置（用于向量化）
    # 组装Elasticsearch配置（用于向量存储）
```

### 11.6 关键代码文件

| 文件 | 功能 |
|------|------|
| [sdk/nexent/memory/memory_core.py](file:///Users/gerui/nexent/sdk/nexent/memory/memory_core.py) | 记忆实例管理 |
| [sdk/nexent/memory/memory_service.py](file:///Users/gerui/nexent/sdk/nexent/memory/memory_service.py) | 高级CRUD操作 |
| [backend/services/memory_config_service.py](file:///Users/gerui/nexent/backend/services/memory_config_service.py) | 用户配置服务 |
| [backend/apps/memory_config_app.py](file:///Users/gerui/nexent/backend/apps/memory_config_app.py) | 记忆API |

---

## 十三、系统监控

### 13.1 功能概述

#### 功能讲解
- **定位**：企业级LLM性能监控系统
- **核心指标**：Token生成速度、TTFT（首个Token延迟）
- **技术栈**：OpenTelemetry + Jaeger + Prometheus + Grafana

### 13.2 监控组件

| 组件 | 端口 | 用途 |
|------|------|------|
| **Jaeger** | 16686 (UI), 14268 (Collector) | 分布式链路追踪 |
| **Prometheus** | 9090 | 指标收集与存储 |
| **Grafana** | 3005 | 可视化仪表板 |
| **OpenTelemetry Collector** | 4317 (gRPC), 4318 (HTTP) | 高级数据收集 |

### 13.3 核心监控指标

| 指标名称 | 描述 | 重要性 |
|----------|------|--------|
| `llm_token_generation_rate` | Token生成速度 | ⭐⭐⭐ |
| `llm_time_to_first_token_seconds` | 首个Token延迟（TTFT） | ⭐⭐⭐ |
| `llm_request_duration_seconds` | 完整请求时长 | ⭐⭐⭐ |
| `llm_total_tokens` | 输入/输出Token计数 | ⭐⭐ |
| `llm_error_count` | LLM调用错误计数 | ⭐⭐⭐ |

### 13.4 使用方式

#### 装饰器方式（推荐）
```python
from utils.monitoring import monitoring_manager

# API端点监控
@monitoring_manager.monitor_endpoint("my_service.my_function")
async def my_api_function():
    return {"status": "ok"}

# LLM调用监控
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    return llm_response
```

#### 上下文管理器方式
```python
with monitor.trace_llm_request("custom_operation", "my_model") as span:
    result = process_data()
    monitor.add_span_event("processing_completed")
```

### 13.5 监控特性

1. **自动启停设计**：根据环境变量自动启用/禁用
2. **依赖可选**：OpenTelemetry依赖可选安装
3. **FastAPI集成**：自动注入应用监控
4. **优雅降级**：禁用时静默无影响

### 13.6 访问地址

| 界面 | URL |
|------|-----|
| Grafana仪表板 | http://localhost:3005 |
| Jaeger追踪 | http://localhost:16686 |
| Prometheus指标 | http://localhost:9090 |

### 13.7 关键代码文件

| 文件 | 功能 |
|------|------|
| [sdk/nexent/monitor/monitoring.py](file:///Users/gerui/nexent/sdk/nexent/monitor/monitoring.py) | 核心监控实现 |
| [backend/utils/monitoring.py](file:///Users/gerui/nexent/backend/utils/monitoring.py) | 后端全局监控管理器 |
| [docker/docker-compose-monitoring.yml](file:///Users/gerui/nexent/docker/docker-compose-monitoring.yml) | 监控服务编排 |

---

## 十四、数据处理引擎

### 14.1 架构概述

#### 功能讲解
- **架构模式**：分布式异步任务架构
- **核心技术**：Celery + Redis + Ray
- **处理流程**：链式任务模式

### 14.2 任务流程

```
process (process_q) → forward (forward_q)
```

| 任务类型 | 功能描述 |
|---------|---------|
| **process任务** | 处理文件并提取文本/chunks，使用Ray Actor分布式处理 |
| **forward任务** | 向量化并存储chunks到Elasticsearch |
| **process_and_forward任务** | 组合任务，创建process→forward链 |

### 14.3 支持的文件类型

```
Excel文件: .xlsx, .xls (使用OpenPyxlProcessor)
通用文件: .txt, .pdf, .docx, .doc, .html, .htm, .md, .rtf, .odt, .pptx, .ppt (使用UnstructuredProcessor)
```

### 14.4 API接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/tasks` | POST | 创建数据处理任务 |
| `/tasks/process` | POST | 同步处理文件 |
| `/tasks/batch` | POST | 批量创建任务 |
| `/tasks/load_image` | GET | 加载图片并返回base64 |
| `/tasks/convert_to_pdf` | POST | Office文档转PDF |

### 14.5 关键代码解读

```python
# 文件位置: backend/data_process/tasks.py (第224-511行)

@celery_app.task(bind=True, queue='process_q')
def process_task(self, file_path, chunking_strategy, ...):
    # 1. 从MinIO下载文件
    # 2. 使用Ray Actor进行分布式处理
    # 3. 将chunks存储到Redis供后续使用
```

```python
# 文件位置: backend/data_process/tasks.py (第514-966行)

@celery_app.task(bind=True, queue='forward_q')
def forward_task(self, task_id, index_name, ...):
    # 1. 从Redis获取chunks
    # 2. 向量化处理
    # 3. 存储到Elasticsearch
```

### 15.6 关键代码文件

| 文件 | 功能 |
|------|------|
| [backend/data_process/app.py](file:///Users/gerui/nexent/backend/data_process/app.py) | Celery配置 |
| [backend/data_process/tasks.py](file:///Users/gerui/nexent/backend/data_process/tasks.py) | 任务定义 |
| [backend/data_process/ray_actors.py](file:///Users/gerui/nexent/backend/data_process/ray_actors.py) | Ray Actor |
| [sdk/nexent/data_process/core.py](file:///Users/gerui/nexent/sdk/nexent/data_process/core.py) | SDK核心 |

---

## 十五、语音与多模态服务

### 15.1 语音服务架构

#### 功能讲解
- **STT（语音转文字）**：实时流式识别、文件识别
- **TTS（文字转语音）**：流式合成、完整合成
- **技术实现**：WebSocket + 字节跳动火山引擎

### 15.2 STT实现

#### 配置参数
```python
class STTConfig(BaseModel):
    appid: str
    token: str
    ws_url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    format: str = "pcm"  # 支持wav, mp3, pcm
    rate: int = 16000
    streaming: bool = True
    compression: bool = True  # GZIP压缩
```

#### 核心功能
- **实时流式识别**：通过WebSocket接收音频流
- **文件识别**：支持WAV/MP3/PCM格式
- **协议处理**：自定义二进制协议

### 15.3 TTS实现

#### 配置参数
```python
@dataclass
class TTSConfig:
    appid: str
    token: str
    cluster: str
    voice_type: str
    speed_ratio: float
    host: str = "openspeech.bytedance.com"
```

#### 核心功能
- **流式合成**：支持流式返回音频chunks
- **完整合成**：返回完整音频数据

### 15.4 图像服务

#### 功能讲解
- **图片代理服务**：从URL加载图片，返回base64或流式响应
- **VLM模型获取**：获取租户配置的视觉语言模型
- **格式转换**：支持RGBA→RGB转换

### 15.5 API接口

| 端点 | 类型 | 功能 |
|------|------|------|
| `/voice/stt/ws` | WebSocket | 实时语音识别 |
| `/voice/tts/ws` | WebSocket | 流式语音合成 |
| `/voice/connectivity` | POST | 服务连通性检测 |
| `/image` | GET | 图片代理服务 |

### 14.6 关键代码文件

| 文件 | 功能 |
|------|------|
| [backend/services/voice_service.py](file:///Users/gerui/nexent/backend/services/voice_service.py) | 语音服务封装 |
| [sdk/nexent/core/models/stt_model.py](file:///Users/gerui/nexent/sdk/nexent/core/models/stt_model.py) | STT模型 |
| [sdk/nexent/core/models/tts_model.py](file:///Users/gerui/nexent/sdk/nexent/core/models/tts_model.py) | TTS模型 |
| [backend/services/image_service.py](file:///Users/gerui/nexent/backend/services/image_service.py) | 图像服务 |

---

## 十六、北向接口与配置服务

### 16.1 北向服务概述

#### 功能讲解
- **定位**：为合作伙伴提供的外部API接口服务
- **端口**：独立运行在端口5013
- **功能**：Agent对话、会话管理等核心功能

### 16.2 认证机制

#### 双重认证
```python
# 1. AK/SK签名认证
- X-Access-Key: 访问密钥
- X-Timestamp: 时间戳（防重放攻击，有效期300秒）
- X-Signature: HMAC-SHA256签名

# 2. JWT Token认证
- Authorization: Bearer <jwt_token>
```

### 16.3 核心特性

#### 幂等性控制
```python
# 幂等性键生成
def _build_idempotency_key(*parts: Any) -> str:
    # 组合 tenant_id + conversation_id + agent_id + query
    # 长文本(>64字符)使用SHA256哈希

# 幂等性管理
_IDEMPOTENCY_RUNNING: Dict[str, float] = {}  # 运行中的请求
_IDEMPOTENCY_TTL_SECONDS_DEFAULT = 600       # 默认TTL 10分钟
```

#### 速率限制
```python
_RATE_LIMIT_PER_MINUTE = 120  # 每租户每分钟120次请求
```

#### ID映射机制
```python
# 外部会话ID <-> 内部会话ID映射
# 保护内部数据结构
```

### 16.4 API接口

| 接口路径 | 方法 | 功能描述 |
|---------|------|---------|
| `/nb/v1/health` | GET | 健康检查 |
| `/nb/v1/chat/run` | POST | 启动流式对话 |
| `/nb/v1/chat/stop/{conversation_id}` | GET | 停止对话 |
| `/nb/v1/conversations/{conversation_id}` | GET | 获取会话历史 |
| `/nb/v1/conversations` | GET | 列出所有会话 |
| `/nb/v1/agents` | GET | 获取Agent列表 |

### 16.5 配置服务

#### 功能讲解
- **端口**：运行在端口5010
- **功能**：全局配置、模型配置、租户配置管理

#### 租户配置管理器
```python
class TenantConfigManager:
    """租户配置管理器 - 从数据库按需读取配置"""
    
    def load_config(self, tenant_id: str) -> dict:
        """加载租户所有配置"""
        
    def get_model_config(self, key: str, tenant_id: str) -> dict:
        """获取模型配置"""
        
    def set_single_config(self, user_id, tenant_id, key, value):
        """设置单个配置项"""
```

### 16.6 初始化设置流程

```
Setup流程:
┌─────────────────────────────────────────────────────────────┐
│  1. Models (模型配置) → 配置LLM、Embedding等模型              │
│  2. Knowledges (知识库配置) → 创建和配置知识库                │
│  3. Agents (Agent配置) → 创建或导入智能体                    │
│  完成后跳转到聊天页面                                         │
└─────────────────────────────────────────────────────────────┘
```

### 16.7 关键代码文件

| 文件 | 功能 |
|------|------|
| [backend/services/northbound_service.py](file:///Users/gerui/nexent/backend/services/northbound_service.py) | 北向业务逻辑 |
| [backend/apps/northbound_app.py](file:///Users/gerui/nexent/backend/apps/northbound_app.py) | 北向API路由 |
| [backend/services/config_sync_service.py](file:///Users/gerui/nexent/backend/services/config_sync_service.py) | 配置同步服务 |
| [backend/services/tenant_service.py](file:///Users/gerui/nexent/backend/services/tenant_service.py) | 租户服务 |
| [frontend/app/[locale]/setup/page.tsx](file:///Users/gerui/nexent/frontend/app/[locale]/setup/page.tsx) | 初始化设置页面 |

---

## 十七、用户管理与分权分域

### 17.1 角色体系

| 角色 | 代码 | 职责描述 |
|------|------|----------|
| **超级管理员** | `SU` | 可创建不同租户，管理所有租户资源 |
| **管理员** | `ADMIN` | 负责租户内的资源管理和权限分配 |
| **开发者** | `DEV` | 可创建和编辑智能体、知识库等资源 |
| **普通用户** | `USER` | 仅可使用平台功能，无创建和编辑权限 |

### 17.2 租户隔离机制

#### 功能讲解
- **租户**：最上层的资源隔离单位
- **隔离范围**：智能体、知识库、模型、MCP工具
- **特点**：不同租户数据完全隔离、互不可见

### 17.3 用户组管理

#### 功能讲解
- **目的**：租户内的用户分组，控制资源可见性
- **操作**：创建组、添加用户、移除用户

#### 关键代码解读
```python
# 文件位置: backend/services/group_service.py

def create_group(tenant_id, group_name, group_description, user_id):
    # 权限检查：仅SU和ADMIN可创建
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError()
    # 创建组
    group_id = add_group(tenant_id, group_name, group_description)
```

### 17.4 邀请码机制

#### 功能讲解
- **目的**：控制新用户注册和角色分配
- **类型**：
  - ADMIN_INVITE：管理员邀请
  - DEV_INVITE：开发者邀请
  - USER_INVITE：普通用户邀请

#### 关键代码解读
```python
# 文件位置: backend/services/invitation_service.py

def signup_user_with_invitation(email, password, invite_code):
    # 根据邀请码类型确定用户角色
    if code_type == "ADMIN_INVITE":
        user_role = "ADMIN"
    elif code_type == "DEV_INVITE":
        user_role = "DEV"
    else:
        user_role = "USER"
    
    # 创建用户并加入指定组
    insert_user_tenant(user_id, tenant_id, user_role, email)
    add_user_to_groups(user_id, group_ids)
```

### 17.5 权限分类

#### 可见性权限（VISIBILITY）
- 控制左侧导航菜单的可见性
- 格式：`LEFT_NAV_MENU:/chat`

#### 资源权限（RESOURCE）
- 控制对各类资源的操作权限
- 格式：`permission_type:permission_subtype`
- 示例：`AGENT:CREATE`、`KNOWLEDGE:UPDATE`

### 17.6 数据库表结构

#### 用户租户关系表
```sql
-- 文件位置: docker/init.sql (第540-565行)

CREATE TABLE nexent.user_tenant_t (
    user_tenant_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_role VARCHAR(30) DEFAULT 'USER',  -- SU, ADMIN, DEV, USER
    user_email VARCHAR(255),
    create_time TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, tenant_id)
);
```

#### 角色权限表
```sql
-- 文件位置: docker/init.sql (第801-1003行)

CREATE TABLE nexent.role_permission_t (
    role_permission_id SERIAL PRIMARY KEY,
    user_role VARCHAR(30) NOT NULL,        -- SU, ADMIN, DEV, USER
    permission_category VARCHAR(30),        -- VISIBILITY, RESOURCE
    permission_type VARCHAR(30),            -- LEFT_NAV_MENU, AGENT, KB, etc.
    permission_subtype VARCHAR(30)          -- CREATE, READ, UPDATE, DELETE
);
```

### 17.7 资源权限配置

#### 智能体权限设置
| 权限级别 | 说明 |
|----------|------|
| 仅创建者可见 | 只有创建者和管理员可查看和编辑 |
| 指定用户组-只读 | 用户组内开发者可见、可发布，不可编辑删除 |

#### 知识库权限设置
| 权限级别 | 说明 |
|----------|------|
| 私有 | 只有创建者和管理员可查看和管理 |
| 指定用户组-只读 | 指定用户组可见，不可编辑删除 |
| 指定用户组-可编辑 | 指定用户组可见且可编辑删除 |

### 17.8 权限检查实现

#### 关键代码解读
```python
# 文件位置: backend/services/user_management_service.py (第389-439行)

async def get_user_info(user_id: str) -> Optional[Dict[str, Any]]:
    """获取用户信息，包括权限和可访问路由"""
    # 1. 获取用户租户关系
    user_tenant = get_user_tenant_by_user_id(user_id)
    user_role = user_tenant["user_role"]
    
    # 2. 从数据库获取用户权限
    permission_records = session.query(RolePermission).filter(
        RolePermission.user_role == user_role
    ).all()
    
    # 3. 格式化权限数据
    permissions_data = format_role_permissions(permissions)
    
    return {
        "user": {
            "user_id": user_id,
            "user_role": user_role,
            "permissions": permissions_data["permissions"],
            "accessibleRoutes": permissions_data["accessibleRoutes"]
        }
    }
```

---

## 十八、总结与展望

### 18.1 核心价值总结
- **零代码开发**：降低智能体开发门槛
- **MCP生态**：丰富的工具扩展能力
- **企业级特性**：完善的权限管理和多租户隔离

### 18.2 关键技术亮点
- 基于LangChain/smolagents的智能体框架
- Elasticsearch向量数据库的高效检索
- Map-Reduce架构的知识库总结
- MCP协议的统一工具接入

### 18.3 扩展阅读
- 项目文档：`/doc` 目录
- 架构图：`assets/architecture_zh.png`
- API文档：启动服务后访问 `/docs`

---

## 附录：关键代码文件索引

### 核心模块

| 功能模块 | 文件路径 |
|---------|----------|
| 部署脚本 | `docker/deploy.sh` |
| 数据库初始化 | `docker/init.sql` |
| 认证工具 | `backend/utils/auth_utils.py` |
| 用户管理服务 | `backend/services/user_management_service.py` |

### 模型配置

| 功能模块 | 文件路径 |
|---------|----------|
| 模型管理服务 | `backend/services/model_management_service.py` |
| 模型健康检查 | `backend/services/model_health_service.py` |
| LLM模型实现 | `sdk/nexent/core/models/openai_llm.py` |
| 向量模型实现 | `sdk/nexent/core/models/embedding_model.py` |

### 知识库

| 功能模块 | 文件路径 |
|---------|----------|
| 向量数据库服务 | `backend/services/vectordatabase_service.py` |
| 向量数据库抽象 | `sdk/nexent/vector_database/base.py` |
| Elasticsearch实现 | `sdk/nexent/vector_database/elasticsearch_core.py` |
| 知识库搜索工具 | `sdk/nexent/core/tools/knowledge_base_search_tool.py` |

### MCP工具

| 功能模块 | 文件路径 |
|---------|----------|
| MCP工具配置 | `backend/services/tool_configuration_service.py` |
| 远程MCP服务 | `backend/services/remote_mcp_service.py` |
| 本地MCP服务 | `backend/tool_collection/mcp/local_mcp_service.py` |

### 智能体

| 功能模块 | 文件路径 |
|---------|----------|
| 智能体服务 | `backend/services/agent_service.py` |
| 智能体版本管理 | `backend/services/agent_version_service.py` |
| 提示词服务 | `backend/services/prompt_service.py` |
| 智能体配置构建 | `backend/agents/create_agent_info.py` |
| 智能体模型定义 | `sdk/nexent/core/agents/agent_model.py` |

### 智能体市场与空间

| 功能模块 | 文件路径 |
|---------|----------|
| 智能体市场页面 | `frontend/app/[locale]/market/page.tsx` |
| 市场详情弹窗 | `frontend/app/[locale]/market/components/MarketAgentDetailModal.tsx` |
| 智能体空间页面 | `frontend/app/[locale]/space/page.tsx` |
| 智能体卡片组件 | `frontend/app/[locale]/space/components/AgentCard.tsx` |

### 对话与聊天

| 功能模块 | 文件路径 |
|---------|----------|
| 对话管理服务 | `backend/services/conversation_management_service.py` |
| 对话API | `backend/apps/conversation_management_app.py` |
| 聊天界面 | `frontend/app/[locale]/chat/internal/chatInterface.tsx` |
| 流式处理 | `frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx` |
| Agent运行管理 | `backend/agents/agent_run_manager.py` |

### 记忆管理

| 功能模块 | 文件路径 |
|---------|----------|
| 记忆实例管理 | `sdk/nexent/memory/memory_core.py` |
| 记忆服务 | `sdk/nexent/memory/memory_service.py` |
| 记忆配置服务 | `backend/services/memory_config_service.py` |
| 记忆API | `backend/apps/memory_config_app.py` |

### 系统监控

| 功能模块 | 文件路径 |
|---------|----------|
| 核心监控实现 | `sdk/nexent/monitor/monitoring.py` |
| 后端监控管理器 | `backend/utils/monitoring.py` |
| 监控服务编排 | `docker/docker-compose-monitoring.yml` |

### 数据处理

| 功能模块 | 文件路径 |
|---------|----------|
| Celery配置 | `backend/data_process/app.py` |
| 任务定义 | `backend/data_process/tasks.py` |
| Ray Actor | `backend/data_process/ray_actors.py` |
| SDK核心 | `sdk/nexent/data_process/core.py` |

### 语音与多模态

| 功能模块 | 文件路径 |
|---------|----------|
| 语音服务封装 | `backend/services/voice_service.py` |
| STT模型 | `sdk/nexent/core/models/stt_model.py` |
| TTS模型 | `sdk/nexent/core/models/tts_model.py` |
| 图像服务 | `backend/services/image_service.py` |

### 北向接口与配置

| 功能模块 | 文件路径 |
|---------|----------|
| 北向业务逻辑 | `backend/services/northbound_service.py` |
| 北向API路由 | `backend/apps/northbound_app.py` |
| 配置同步服务 | `backend/services/config_sync_service.py` |
| 租户服务 | `backend/services/tenant_service.py` |
| 初始化设置页面 | `frontend/app/[locale]/setup/page.tsx` |

# Elasticsearch 向量数据库

一个用于 Elasticsearch 的向量搜索和文档管理服务，支持通过 `EmbeddingAdapter` 网关适配器（Jina、OpenAI 兼容、DashScope、SiliconFlow 等）生成嵌入向量。

## 环境设置

1. 安装依赖:

```bash
pip install elasticsearch
```

2. 连接凭据通过构造函数参数传入（SDK 不读取环境变量，环境变量由服务层读取后传给 SDK）：

```python
vdb_core = ElasticSearchCore(
    host="https://localhost:9200",
    api_key="your_api_key",
)
```

嵌入模型通过 `nexent.core.gateway.modality` 中的 `EmbeddingAdapter` 适配器传入，例如 `JinaEmbeddingAdapter`、`OpenAICompatibleEmbeddingAdapter` 等。

## Docker 部署指南

### 前置条件

1. 安装Docker
   - 访问 [Get Docker](https://www.docker.com/products/docker-desktop) 安装Docker
   - 如果使用Docker Desktop，请确保分配至少4GB内存
   - 可以在Docker Desktop的 **Settings > Resources** 中调整内存使用

2. 创建Docker网络
   ```bash
   docker network create elastic
   ```

### Elasticsearch部署

1. 拉取Elasticsearch镜像
   ```bash
   docker pull docker.elastic.co/elasticsearch/elasticsearch:8.17.4
   ```

2. 启动Elasticsearch容器 (静默模式，等待3-5分钟)
   ```bash
   docker run -d --name es01 --net elastic -p 9200:9200 -m 6GB -e "xpack.ml.use_auto_machine_memory_percent=true" docker.elastic.co/elasticsearch/elasticsearch:8.17.4
   ```

3. 查看Elasticsearch日志
   ```bash
   docker logs -f es01
   ```

4. 重置密码（确认Yes）
   ```bash
   docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic
   ```

5. 保存重要信息
   - 容器启动时会显示 `elastic` 用户密码和Kibana的注册令牌
   - 建议将密码保存为环境变量：
     ```bash
     export ELASTIC_PASSWORD="your_password"
     ```

6. 复制SSL证书
   ```bash
   docker cp es01:/usr/share/elasticsearch/config/certs/http_ca.crt .
   ```

7. 验证部署
   ```bash
   curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD https://localhost:9200 -k
   ```

8. 获取api_key
    ```bash
    curl --cacert http_ca.crt \
      -u elastic:$ELASTIC_PASSWORD \
      --request POST \
      --url https://localhost:9200/_security/api_key \
      --header 'Content-Type: application/json' \
      --data '{
          "name": "取个名字"
        }'
    ```

9. 检验key有效
    ```bash
   curl --request GET \
    --url https://XXX.XX.XXX.XX:9200/_cluster/health \
    --header 'Authorization: ApiKey API-KEY'
   ```

### Kibana部署 (可选)

1. 拉取Kibana镜像
   ```bash
   docker pull docker.elastic.co/kibana/kibana:8.17.4
   ```

2. 启动Kibana容器
   ```bash
   docker run -d --name kib01 --net elastic -p 5601:5601 docker.elastic.co/kibana/kibana:8.17.4
   ```

3. 查看Kibana日志
   ```bash
   docker logs -f kib01
   ```

4. 配置Kibana
   - 生成令牌，运行：
     ```bash
     docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s kibana
     ```
   - 在浏览器中，访问http://localhost:5601输入生成的注册令牌
   - 可能需要`docker logs -f kib01`查看验证码

5. 使用elastic用户和之前生成的密码登录Kibana

### 常用管理命令

```bash
# 停止容器
docker stop es01
docker stop kib01

# 删除容器
docker rm es01
docker rm kib01

# 删除网络
docker network rm elastic
```

### 生产环境注意事项

1. 数据持久化
   - 必须绑定数据卷到 `/usr/share/elasticsearch/data`
   - 启动命令示例:
     ```bash
     docker run -d --name es01 --net elastic -p 9200:9200 -m 6GB -v es_data:/usr/share/elasticsearch/data docker.elastic.co/elasticsearch/elasticsearch:8.17.4
     ```

2. 内存配置
   - 根据实际需求调整容器内存限制
   - 建议至少分配6GB内存

3. 故障排除
   - 内存不足: 检查Docker Desktop的内存设置
   - 端口冲突: 确保9200端口未被占用
   - 证书问题: 确保正确复制了SSL证书
   - 昇腾服务器vm.max_map_count问题:
     ```bash
     # 错误信息
     # node validation exception: bootstrap checks failed
     # max virtual memory areas vm.max_map_count [65530] is too low, increase to at least [262144]
     
     # 解决方案（在宿主机执行）：
     sudo sysctl -w vm.max_map_count=262144
     
     # 永久生效，编辑 /etc/sysctl.conf 添加：
     vm.max_map_count=262144
     
     # 然后执行：
     sudo sysctl -p
     ```

### 远程部署调试指南

当Elasticsearch部署在远程服务器上时，可能会遇到一些网络访问的问题。以下是常见问题和解决方案：

1. 远程访问被拒绝
   - 症状：curl请求返回 "Connection reset by peer"
   - 解决方案：
     ```bash
     # 使用SSH隧道进行端口转发
     ssh -L 9200:localhost:9200 user@remote_server
     
     # 在新终端中通过本地端口访问
     curl -H "Authorization: ApiKey your_api_key" https://localhost:9200/_cluster/health\?pretty -k
     ```

2. 网络配置检查清单
   - 确保远程服务器的防火墙允许9200端口访问
     ```bash
     # 对于使用iptables的系统
     sudo iptables -A INPUT -p tcp --dport 9200 -j ACCEPT
     sudo service iptables save
     ```
   
   - 检查Elasticsearch网络配置
     ```yaml
     # elasticsearch.yml 配置示例
     network.host: 0.0.0.0
     http.cors.enabled: true
     http.cors.allow-origin: "*"
     ```

3. 安全配置建议
   - 在生产环境中，建议：
     - 限制CORS的 `allow-origin` 为特定域名
     - 使用反向代理（如Nginx）管理SSL终端
     - 配置适当的网络安全组规则
     - 使用SSL证书而不是自签名证书

4. 使用环境变量
   - 在 `.env` 文件中配置远程连接：
     ```
     ELASTICSEARCH_HOST=https://remote_server:9200
     ELASTICSEARCH_API_KEY=your_api_key
     ```
   
   - 如果使用SSH隧道，可以保持使用localhost：
     ```
     ELASTICSEARCH_HOST=https://localhost:9200
     ```

5. 故障排除命令
   ```bash
   # 检查端口监听状态
   netstat -tulpn | grep 9200
   
   # 检查ES日志
   docker logs es01
   
   # 测试SSL连接
   openssl s_client -connect remote_server:9200
   ```

## 核心组件

- `elasticsearch_core.py`: 主类 `ElasticSearchCore`，包含所有 Elasticsearch 操作
- `base.py`: 抽象基类 `VectorDatabaseCore`，定义向量库统一接口（便于扩展其他后端）
- `datamate_core.py`: `DataMateCore`，DataMate 向量库实现（`nexent.vector_database` 默认导出）
- `utils.py`: 数据格式化和查询构建的工具函数

嵌入向量由 `nexent.core.gateway.modality` 中的 `EmbeddingAdapter` 适配器（如 `JinaEmbeddingAdapter`、`OpenAICompatibleEmbeddingAdapter`、`DashScopeEmbeddingAdapter`、`SiliconflowEmbeddingAdapter`）生成。

## 使用示例

### 基本初始化

```python
from nexent.vector_database.elasticsearch_core import ElasticSearchCore

# 直接指定凭据（host 与 api_key 为必填参数）
vdb_core = ElasticSearchCore(
    host="https://localhost:9200",
    api_key="your_api_key",
    verify_certs=False,
    ssl_show_warn=False,
)
```

### 索引管理

```python
# 创建新的向量索引（embedding_dim 可选，未指定时使用嵌入模型维度）
vdb_core.create_index("my_documents")

# 列出所有用户索引
indices = vdb_core.get_user_indices()
print(indices)

# 检查索引是否存在
exists = vdb_core.check_index_exists("my_documents")
print(exists)

# 删除索引
vdb_core.delete_index("my_documents")
```

### 文档操作

```python
from nexent.core.gateway.model_context import EmbeddingContext
from nexent.core.gateway.modality import OpenAICompatibleEmbeddingAdapter

# 构造嵌入模型适配器
embedding_model = OpenAICompatibleEmbeddingAdapter(EmbeddingContext(
    model_name="your-embedding-model",
    base_url="https://your-embedding-api/v1/embeddings",
    api_key="your_api_key",
    modality="embedding",
    factory="openai",
    embedding_dim=1024,
))

# 索引文档（自动生成嵌入向量，batch_size 默认为 64）
documents = [
    {
        "id": "doc1",
        "title": "文档 1",
        "file": "文件1.txt",
        "path_or_url": "https://example.com/doc1",
        "content": "这是文档 1 的内容",
        "process_source": "Web",
        "embedding_model_name": "your-embedding-model",  # 指定嵌入模型
        "file_size": 1024,  # 文件大小（字节）
        "create_time": "2023-06-01T10:30:00"  # 文件创建时间
    },
    {
        "id": "doc2",
        "title": "文档 2",
        "file": "文件2.txt",
        "path_or_url": "https://example.com/doc2",
        "content": "这是文档 2 的内容",
        "process_source": "Web"
        # 如果未提供其他字段，将使用默认值
    }
]
total_indexed = vdb_core.vectorize_documents(
    "my_documents", embedding_model, documents, batch_size=64
)
print(f"成功索引了 {total_indexed} 个文档")

# 通过 URL 或路径删除文档
deleted_count = vdb_core.delete_documents("my_documents", "https://example.com/doc1")
print(f"删除了 {deleted_count} 个文档")
```

### 搜索功能

```python
# 文本精确搜索（index_names 为索引名列表，支持多索引）
results = vdb_core.accurate_search(["my_documents"], "示例查询", top_k=5)
for result in results:
    print(f"得分: {result['score']}, 文档: {result['document']['title']}")

# 语义向量搜索（需要传入嵌入模型）
results = vdb_core.semantic_search(["my_documents"], "示例查询", embedding_model, top_k=5)
for result in results:
    print(f"得分: {result['score']}, 文档: {result['document']['title']}")

# 混合搜索（weight_accurate 可选，默认自动推断：查询含数字时偏向精确搜索 0.7，否则 0.3）
results = vdb_core.hybrid_search(
    ["my_documents"],
    "示例查询",
    embedding_model,
    top_k=5,
    weight_accurate=0.3  # 精确搜索权重为0.3，向量搜索权重为0.7
)
for result in results:
    print(f"得分: {result['score']}, 文档: {result['document']['title']}")
```

### 统计和监控

```python
# 获取索引统计信息
stats = vdb_core.get_indices_detail(["my_documents"])
print(stats)

# 获取文件列表及详细信息
file_details = vdb_core.get_documents_detail("my_documents")
print(file_details)

# 统计索引中的文档数量
doc_count = vdb_core.count_documents("my_documents")
print(doc_count)

# 分页获取索引中的文本块
chunks = vdb_core.get_index_chunks("my_documents", page=1, page_size=10)
print(chunks)
```

## ElasticSearchCore 主要功能

ElasticSearchCore 类提供了以下主要功能:

- **索引管理**: 创建和删除索引，检查索引是否存在，获取用户索引列表
- **文档操作**: 批量索引带有嵌入向量的文档，删除指定文档，以及单个文本块的增删改查（`create_chunk` / `update_chunk` / `delete_chunk`）
- **搜索操作**: 提供精确文本搜索、语义向量搜索、以及混合搜索（支持可选的 ES filter 过滤）
- **统计和监控**: 获取索引统计数据（`get_indices_detail`）、文件列表信息（`get_documents_detail`）、文档计数（`count_documents`）

### 高级功能示例

```python
# 获取索引的文件列表及详细信息（返回字段: path_or_url, filename, file_size, create_time）
files = vdb_core.get_documents_detail("my_documents")
for file in files:
    print(f"文件路径: {file['path_or_url']}")
    print(f"文件名: {file['filename']}")
    print(f"文件大小: {file['file_size']} 字节")
    print(f"创建时间: {file['create_time']}")
    print("---")

# 获取所有索引的综合统计信息
all_stats = vdb_core.get_indices_detail(["my_documents", "other_index"])
for index_name, stats in all_stats.items():
    print(f"索引: {index_name}")
    print(f"文档数: {stats['base_info']['doc_count']}")
    print(f"使用的嵌入模型: {stats['base_info'].get('embedding_model')}")
    print("---")
```

## REST API

SDK 本身不内置 REST 服务。当前仓库中，知识库相关的 REST API 由后端服务提供（如 `backend/apps/northbound_knowledge_app.py`），包括：

- **POST** `/indices/{index_name}`: 创建索引
- **DELETE** `/indices/{index_name}`: 删除索引
- **POST** `/indices/search/hybrid`: 混合搜索
- **DELETE** `/indices/{index_name}/documents?path_or_url=...&scope=...`: 删除文档
  - `scope=source_only`: 仅删除 MinIO 源文件，保留 ES 中的切片与向量（检索仍可用，预览不可用）
  - `scope=full`: 删除 ES 文档、MinIO 源文件，并清理相关 Redis 任务记录
- **GET** `/indices/{index_name}/files`: 获取索引文件列表

具体的请求/响应格式以 `backend/apps/northbound_knowledge_app.py` 中的路由定义为准。

## 许可证

该项目根据 MIT 许可证授权 - 详情请参阅 LICENSE 文件。 

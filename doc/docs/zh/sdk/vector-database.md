# Elasticsearch 向量数据库

一个用于 Elasticsearch 的向量搜索和文档管理服务，支持 Jina 嵌入模型集成。

## 环境设置

1. 创建一个包含凭据的 `.env` 文件:

```
ELASTICSEARCH_HOST=https://localhost:9200
ELASTICSEARCH_API_KEY=your_api_key_here
JINA_API_URL=https://api.jina.ai/v1/embeddings
JINA_MODEL=jian_model_name
JINA_API_KEY=your_jina_api_key_here
```

2. 安装依赖:

```bash
pip install elasticsearch python-dotenv requests fastapi uvicorn
```

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
   - 确保远程服务器的防火墙允许9201端口访问
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

- `elasticsearch_core.py`: 主类，包含所有 Elasticsearch 操作
- `embedding_model.py`: 处理使用 Jina AI 模型生成嵌入向量
- `utils.py`: 数据格式化和显示的工具函数
- `vectordatabase_service.py`: FastAPI 服务，提供 REST API 接口

## 使用示例

### 基本初始化

```python
from nexent.vector_database.elasticsearch_core import ElasticSearchCore

# 使用 .env 文件中的凭据初始化
vdb_core = ElasticSearchCore()

# 或直接指定凭据
vdb_core = ElasticSearchCore(
    host="https://localhost:9200",
    api_key="your_api_key",
    verify_certs=False,
    ssl_show_warn=False,
)
```

### 索引管理

```python
# 创建新的向量索引
vdb_core.create_index("my_documents")

# 列出所有用户索引
indices = vdb_core.get_user_indices()
print(indices)

# 获取所有索引的统计信息
all_indices_stats = vdb_core.get_all_indices_stats()
print(all_indices_stats)

# 删除索引
vdb_core.delete_index("my_documents")

# 创建测试知识库
index_name, doc_count = vdb_core.create_test_knowledge_base()
print(f"创建了测试知识库 {index_name}，包含 {doc_count} 个文档")
```

### 文档操作

```python
# 索引文档（自动生成嵌入向量）
documents = [
    {
        "id": "doc1",
        "title": "文档 1",
        "file": "文件1.txt",
        "path_or_url": "https://example.com/doc1",
        "content": "这是文档 1 的内容",
        "process_source": "Web",
        "embedding_model_name": "jina-embeddings-v2-base-en",  # 指定嵌入模型
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
# 支持批量处理，默认批处理大小为3000
total_indexed = vdb_core.vectorize_documents("my_documents", documents, batch_size=3000)
print(f"成功索引了 {total_indexed} 个文档")

# 通过 URL 或路径删除文档
deleted_count = vdb_core.delete_documents("my_documents", "https://example.com/doc1")
print(f"删除了 {deleted_count} 个文档")
```

### 搜索功能

```python
# 文本精确搜索
results = vdb_core.accurate_search("my_documents", "示例查询", top_k=5)
for result in results:
    print(f"得分: {result['score']}, 文档: {result['document']['title']}")

# 语义向量搜索
results = vdb_core.semantic_search("my_documents", "示例查询", top_k=5)
for result in results:
    print(f"得分: {result['score']}, 文档: {result['document']['title']}")

# 混合搜索
results = vdb_core.hybrid_search(
    "my_documents",
    "示例查询",
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

# 获取嵌入模型信息
embedding_model = vdb_core.get_embedding_model_info("my_documents")
print(f"使用的嵌入模型: {embedding_model}")

# 打印所有索引信息
vdb_core.print_all_indices_info()
```

## ElasticSearchCore 主要功能

ElasticSearchCore 类提供了以下主要功能:

- **索引管理**: 创建和删除索引，获取用户索引列表和统计信息
- **文档操作**: 批量索引带有嵌入向量的文档，删除指定文档
- **搜索操作**: 提供精确文本搜索、语义向量搜索、以及混合搜索
- **统计和监控**: 获取索引统计数据，查看数据源、创建时间和文件列表等信息

### 新增高级功能

```python
# 获取索引的文件列表及详细信息
files = vdb_core.get_documents_detail("my_documents")
for file in files:
    print(f"文件路径: {file['path_or_url']}")
    print(f"文件名: {file['file']}")
    print(f"文件大小: {file['file_size']} 字节")
    print(f"创建时间: {file['create_time']}")
    print("---")

# 获取嵌入模型信息
model_info = vdb_core.get_embedding_model_info("my_documents")
print(f"使用的嵌入模型: {model_info}")

# 获取所有索引的综合统计信息
all_stats = vdb_core.get_all_indices_stats()
for index_name, stats in all_stats.items():
    print(f"索引: {index_name}")
    print(f"文档数: {stats['base_info']['doc_count']}")
    print(f"唯一源数量: {stats['base_info']['unique_sources_count']}")
    print(f"使用的嵌入模型: {stats['base_info']['embedding_model']}")
    print("---")
```

## API 服务接口

通过 `vectordatabase_service.py` 提供的 FastAPI 服务，可使用 REST API 访问上述所有功能。

### 服务启动

```bash
python -m nexent.service.vectordatabase_service
```

服务默认在 `http://localhost:8000` 运行。

### API 接口文档

#### 健康检查

- **GET** `/health`: 检查 API 和 Elasticsearch 连接状态
  - 返回示例: `{"status": "healthy", "elasticsearch": "connected", "indices_count": 5}`

#### 索引管理
- **POST** `/indices/{index_name}`: 创建索引
  - 参数: 
    - `index_name`: 索引名称 (路径参数)
    - `embedding_dim`: 向量化维度 (查询参数，可选)
  - 返回示例: `{"status": "success", "message": "Index my_documents created successfully"}`

- **DELETE** `/indices/{index_name}`: 删除索引
  - 参数: `index_name`: 索引名称 (路径参数)
  - 返回示例: `{"status": "success", "message": "Index my_documents deleted successfully"}`

- **GET** `/indices`: 列出所有索引，可选包含详细统计信息
  - 参数: 
    - `pattern`: 索引名称匹配模式 (查询参数，默认为 "*")
    - `include_stats`: 是否包含索引统计信息 (查询参数，默认为 false)
  - 基本返回示例: `{"indices": ["index1", "index2"], "count": 2}`
  - 包含统计信息的返回示例:
  ```json
  {
    "indices": ["index1", "index2"],
    "count": 2,
    "indices_info": [
      {
        "name": "index1",
        "stats": {
          "base_info": {
            "doc_count": 100,
            "unique_sources_count": 10,
            "store_size": "1.2 MB",
            "process_source": "Web",
            "embedding_model": "jina-embeddings-v2-base-en",
            "creation_date": "2023-06-01 12:00:00",
            "update_date": "2023-06-02 15:30:00"
          },
          "search_performance": {
            "total_search_count": 150,
            "hit_count": 120
          }
        }
      },
      {
        "name": "index2",
        "stats": { "..." }
      }
    ]
  }
  ```

- **GET** `/indices/{index_name}/info`: 获取索引的综合信息
  - 参数: 
    - `index_name`: 索引名称 (路径参数)
    - `include_files`: 是否包含文件列表信息 (查询参数，默认为 true)
    - `include_chunks`: 是否包含文本块信息 (查询参数，默认为 false)
  - 返回综合信息，包括基本信息、搜索性能、字段列表、文件列表和文本块列表
  - 返回示例:
  ```json
  {
    "base_info": {
      "doc_count": 100,
      "unique_sources_count": 10,
      "store_size": "1.2 MB",
      "process_source": "Web",
      "embedding_model": "jina-embeddings-v2-base-en",
      "embedding_dim": 1024,
      "creation_date": "2023-06-01 12:00:00",
      "update_date": "2023-06-02 15:30:00"
    },
    "search_performance": {
      "total_search_count": 150,
      "hit_count": 120
    },
    "fields": ["id", "title", "content", "embedding", "embedding_model_name", "file_size", "create_time", "..."],
    "files": [
      {
        "path_or_url": "https://example.com/doc1",
        "file": "文件1.txt",
        "file_size": 1024,
        "create_time": "2023-06-01T10:30:00",
        "chunks_count": 6,
        "status": "PROCESSING",
        "chunks": []
      },
      {
        "path_or_url": "https://example.com/doc2",
        "file": "文件2.txt",
        "file_size": 2048,
        "create_time": "2023-06-01T11:45:00",
        "chunks_count": 10,
        "status": "WAITING",
        "chunks": []
      },
      {
        "path_or_url": "https://example.com/doc3",
        "file": "文件3.txt",
        "file_size": 0,
        "create_time": "2023-06-01T12:00:00",
        "chunks_count": 0,
        "status": "COMPLETED",
        "chunks": [
                {
                    "id": "task-0",
                    "title": "title-0",
                    "content": "content-0",
                    "create_time": "2023-06-01T12:30:00"
                },
                {
                    "id": "task-1",
                    "title": "title-1",
                    "content": "content-1",
                    "create_time": "2023-06-01T12:30:00"
                }
            ],
      }
    ]
  }
  ```
  - 文件状态说明：
    - `WAITING`: 文件正在等待处理
    - `PROCESSING`: 文件正在被处理
    - `FORWARDING`: 文件正在被转发到向量知识库服务
    - `COMPLETED`: 文件已完成处理并成功入库
    - `FAILED`: 文件处理失败
  - 文件列表包含：
    - 已存在于ES中的文件（状态为 COMPLETED 或活跃任务中的状态）
    - 正在数据清洗服务中处理但尚未进入ES的文件（状态为 WAITING/PROCESSING/FORWARDING/FAILED）

#### 文档操作

- **POST** `/indices/{index_name}/documents`: 索引文档
  - 参数:
    - `index_name`: 索引名称 (路径参数)
    - `data`: 包含任务ID和文档的请求体 (IndexingRequest)
    - `embedding_model_name`: 指定要使用的嵌入模型名称 (查询参数，可选)
  - IndexingRequest 格式示例:
  ```json
  {
    "task_id": "task-123",
    "index_name": "my_documents",
    "results": [
      {
        "metadata": {
          "title": "文档标题",
          "filename": "文件名.txt",
          "languages": ["zh"],
          "author": "作者",
          "file_size": 1024,
          "creation_date": "2023-06-01T10:30:00"
        },
        "source": "https://example.com/doc1",
        "source_type": "url", 
        "text": "文档内容"
      }
    ],
    "embedding_dim": 1024
  }
  ```
  - 返回示例: 
  ```json
  {
    "success": true,
    "message": "Successfully indexed 1 documents",
    "total_indexed": 1,
    "total_submitted": 1
  }
  ```

- **DELETE** `/indices/{index_name}/documents`: 删除文档
  - 参数:
    - `index_name`: 索引名称 (路径参数)
    - `path_or_url`: 文档路径或URL (查询参数)
  - 返回示例: `{"status": "success", "deleted_count": 1}`

#### 搜索操作

- **POST** `/indices/search/accurate`: 精确文本搜索
  - 请求体 (SearchRequest):
  ```json
  {
    "index_names": ["index1", "index2"],
    "query": "搜索关键词",
    "top_k": 5
  }
  ```
  - 返回格式:
  ```json
  {
    "results": [
      {
        "id": "doc1",
        "title": "文档标题",
        "file": "文件名.txt",
        "path_or_url": "https://example.com/doc1",
        "content": "文档内容",
        "process_source": "Web",
        "embedding_model_name": "jina-embeddings-v2-base-en",
        "file_size": 1024,
        "create_time": "2023-06-01T10:30:00",
        "score": 0.95,
        "index": "index1"
      },
      {
        "id": "doc2",
        "title": "文档标题",
        "file": "文件名.txt",
        "path_or_url": "https://example.com/doc2",
        "content": "文档内容",
        "process_source": "Web",
        "embedding_model_name": "jina-embeddings-v2-base-en",
        "file_size": 1024,
        "create_time": "2023-06-01T10:30:00",
        "score": 0.85,
        "index": "index2"
      }
    ],
    "total": 2,
    "query_time_ms": 25.4
  }
  ```

- **POST** `/indices/search/semantic`: 语义向量搜索
  - 请求体格式与精确搜索相同 (SearchRequest)
  - 返回格式与精确搜索相同，但基于语义相似度评分

- **POST** `/indices/search/hybrid`: 混合搜索
  - 请求体 (HybridSearchRequest):
  ```json
  {
    "index_names": ["index1", "index2"],
    "query": "搜索关键词",
    "top_k": 5,
    "weight_accurate": 0.3
  }
  ```
  - 返回格式与精确搜索相同，但包含详细的得分信息：
  ```json
  {
    "results": [
      {
        "id": "doc1",
        "title": "文档标题",
        "file": "文件名.txt",
        "path_or_url": "https://example.com/doc1",
        "content": "文档内容",
        "process_source": "Web",
        "embedding_model_name": "jina-embeddings-v2-base-en",
        "file_size": 1024,
        "create_time": "2023-06-01T10:30:00",
        "score": 0.798,
        "index": "index1",
        "score_details": {
          "accurate": 0.80,
          "semantic": 0.90
        }
      },
      {
        "id": "doc2",
        "title": "文档标题",
        "file": "文件名.txt",
        "path_or_url": "https://example.com/doc2",
        "content": "文档内容",
        "process_source": "Web",
        "embedding_model_name": "jina-embeddings-v2-base-en",
        "file_size": 1024,
        "create_time": "2023-06-01T10:30:00",
        "score": 0.756,
        "index": "index1",
        "score_details": {
          "accurate": 0.60,
          "semantic": 0.90
        }
      }
    ],
    "total": 2,
    "query_time_ms": 35.2
  }
  ```

### API 使用示例

#### 使用 curl 请求示例

```bash
# 健康检查
curl -X GET "http://localhost:8000/health"

# 列出所有索引（包含统计信息）
curl -X GET "http://localhost:8000/indices?include_stats=true"

# 获取索引详细信息（包含文本块列表）
curl -X GET "http://localhost:8000/indices/my_documents/info?include_chunks=true"

# 精确搜索（支持多索引搜索）
curl -X POST "http://localhost:8000/indices/search/accurate" \
  -H "Content-Type: application/json" \
  -d '{
    "index_names": ["my_documents", "other_index"],
    "query": "示例查询",
    "top_k": 3
  }'

# 语义搜索（支持多索引搜索）
curl -X POST "http://localhost:8000/indices/search/semantic" \
  -H "Content-Type: application/json" \
  -d '{
    "index_names": ["my_documents", "other_index"],
    "query": "相似含义查询",
    "top_k": 3
  }'

# 混合搜索（支持多索引搜索）
curl -X POST "http://localhost:8000/indices/search/hybrid" \
  -H "Content-Type: application/json" \
  -d '{
    "index_names": ["my_documents", "other_index"],
    "query": "示例查询",
    "top_k": 3,
    "weight_accurate": 0.3
  }'

# 删除文档
curl -X DELETE "http://localhost:8000/indices/my_documents/documents?path_or_url=https://example.com/doc1"

# 创建索引
curl -X POST "http://localhost:8000/indices/my_documents"

# 删除索引
curl -X DELETE "http://localhost:8000/indices/my_documents"
```

#### 使用 Python requests 示例

```python
import requests
import json
import time

BASE_URL = "http://localhost:8000"

# 当前时间，ISO格式
current_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

# 准备 IndexingRequest
indexing_request = {
    "task_id": f"task-{int(time.time())}",
    "index_name": "my_documents",
    "results": [
        {
            "metadata": {
                "title": "示例文档",
                "filename": "example.txt",
                "language": "zh",
                "author": "作者",
                "file_size": 1024,
                "creation_date": current_time
            },
            "source": "https://example.com/doc1",
            "text": "这是一个示例文档"
        }
    ],
    "embedding_dim": 1024
}

# 索引文档
response = requests.post(
    f"{BASE_URL}/indices/my_documents/documents",
    json=indexing_request,
    params={
        "embedding_model_name": "jina-embeddings-v2-base-en"  # 可选参数：指定嵌入模型
    }
)
print(response.json())

# 获取索引信息，包含文件列表
response = requests.get(
    f"{BASE_URL}/indices/my_documents/info",
    params={"include_files": True}
)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

# 获取所有索引信息，包含统计
response = requests.get(
    f"{BASE_URL}/indices",
    params={"include_stats": True}
)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

# 精确搜索
response = requests.post(
    f"{BASE_URL}/indices/search/accurate",
    json={
        "index_names": ["my_documents", "other_index"],
        "query": "示例内容",
        "top_k": 3
    }
)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

# 语义搜索
response = requests.post(
    f"{BASE_URL}/indices/search/semantic",
    json={
        "index_names": ["my_documents", "other_index"],
        "query": "示例内容",
        "top_k": 3
    }
)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

# 混合搜索
response = requests.post(
    f"{BASE_URL}/indices/search/hybrid",
    json={
        "index_names": ["my_documents", "other_index"],
        "query": "示例内容",
        "top_k": 3,
        "weight_accurate": 0.3
    }
)
print(json.dumps(response.json(), indent=2, ensure_ascii=False))
```

## 完整示例

查看 ElasticSearchCore 类的 main 函数，了解完整功能演示:

```python
# 初始化 ElasticSearchCore
vdb_core = ElasticSearchCore()

# 获取或创建测试知识库
index_name = "sample_articles"

# 列出所有用户索引
user_indices = vdb_core.get_user_indices()
for idx in user_indices:
    print(f"  - {idx}")

# 执行搜索
if index_name in user_indices:
    # 精确搜索
    query = "Doctor"
    accurate_results = vdb_core.accurate_search(index_name, query, top_k=2)
    
    # 语义搜索
    query = "medical professionals in London"
    semantic_results = vdb_core.semantic_search(index_name, query, top_k=2)

    # 混合搜索
    query = "medical professionals in London"
    semantic_results = vdb_core.hybrid_search(index_name, query, top_k=2, weight_accurate=0.5)
    
    # 获取索引统计信息
    stats = vdb_core.get_indices_detail([index_name])
    fields = vdb_core.get_index_mapping(index_name)
    unique_sources = vdb_core.get_unique_sources_count(index_name)
```

## 许可证

该项目根据 MIT 许可证授权 - 详情请参阅 LICENSE 文件。 

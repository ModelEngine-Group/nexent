# Elasticsearch Vector Database

A vector search and document management service for Elasticsearch that generates embedding vectors through `EmbeddingAdapter` gateway adapters (Jina, OpenAI-compatible, DashScope, SiliconFlow, etc.).

## Environment Setup

1. Install dependencies:

```bash
pip install elasticsearch
```

2. Connection credentials are passed in through constructor parameters (the SDK never reads environment variables; the service layer reads them and passes them to the SDK):

```python
vdb_core = ElasticSearchCore(
    host="https://localhost:9200",
    api_key="your_api_key",
)
```

Embedding models are passed in as `EmbeddingAdapter` adapters from `nexent.core.gateway.modality`, for example `JinaEmbeddingAdapter`, `OpenAICompatibleEmbeddingAdapter`, etc.

## Docker Deployment Guide

### Prerequisites

1. Install Docker
   - Visit [Get Docker](https://www.docker.com/products/docker-desktop) to install Docker
   - If you use Docker Desktop, make sure to allocate at least 4GB of memory
   - You can adjust memory usage in Docker Desktop under **Settings > Resources**

2. Create a Docker network
   ```bash
   docker network create elastic
   ```

### Elasticsearch Deployment

1. Pull the Elasticsearch image
   ```bash
   docker pull docker.elastic.co/elasticsearch/elasticsearch:8.17.4
   ```

2. Start the Elasticsearch container (detached mode; allow 3-5 minutes)
   ```bash
   docker run -d --name es01 --net elastic -p 9200:9200 -m 6GB -e "xpack.ml.use_auto_machine_memory_percent=true" docker.elastic.co/elasticsearch/elasticsearch:8.17.4
   ```

3. Check the Elasticsearch logs
   ```bash
   docker logs -f es01
   ```

4. Reset the password (confirm with Yes)
   ```bash
   docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic
   ```

5. Save important information
   - The `elastic` user password and the Kibana enrollment token are displayed when the container starts
   - It is recommended to save the password as an environment variable:
     ```bash
     export ELASTIC_PASSWORD="your_password"
     ```

6. Copy the SSL certificate
   ```bash
   docker cp es01:/usr/share/elasticsearch/config/certs/http_ca.crt .
   ```

7. Verify the deployment
   ```bash
   curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD https://localhost:9200 -k
   ```

8. Obtain an API key
    ```bash
    curl --cacert http_ca.crt \
      -u elastic:$ELASTIC_PASSWORD \
      --request POST \
      --url https://localhost:9200/_security/api_key \
      --header 'Content-Type: application/json' \
      --data '{
          "name": "pick-a-name"
        }'
    ```

9. Verify the key works
    ```bash
   curl --request GET \
    --url https://XXX.XX.XXX.XX:9200/_cluster/health \
    --header 'Authorization: ApiKey API-KEY'
   ```

### Kibana Deployment (Optional)

1. Pull the Kibana image
   ```bash
   docker pull docker.elastic.co/kibana/kibana:8.17.4
   ```

2. Start the Kibana container
   ```bash
   docker run -d --name kib01 --net elastic -p 5601:5601 docker.elastic.co/kibana/kibana:8.17.4
   ```

3. Check the Kibana logs
   ```bash
   docker logs -f kib01
   ```

4. Configure Kibana
   - Generate an enrollment token by running:
     ```bash
     docker exec -it es01 /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s kibana
     ```
   - In your browser, visit http://localhost:5601 and enter the generated enrollment token
   - You may need `docker logs -f kib01` to see the verification code

5. Log in to Kibana with the `elastic` user and the password generated earlier

### Common Management Commands

```bash
# Stop containers
docker stop es01
docker stop kib01

# Remove containers
docker rm es01
docker rm kib01

# Remove network
docker network rm elastic
```

### Production Considerations

1. Data persistence
   - You must bind a data volume to `/usr/share/elasticsearch/data`
   - Example start command:
     ```bash
     docker run -d --name es01 --net elastic -p 9200:9200 -m 6GB -v es_data:/usr/share/elasticsearch/data docker.elastic.co/elasticsearch/elasticsearch:8.17.4
     ```

2. Memory configuration
   - Adjust the container memory limit according to actual needs
   - At least 6GB of memory is recommended

3. Troubleshooting
   - Insufficient memory: check the Docker Desktop memory settings
   - Port conflicts: make sure port 9200 is not already in use
   - Certificate issues: make sure the SSL certificate was copied correctly
   - Ascend server vm.max_map_count issue:
     ```bash
     # Error message
     # node validation exception: bootstrap checks failed
     # max virtual memory areas vm.max_map_count [65530] is too low, increase to at least [262144]
     
     # Solution (run on the host machine):
     sudo sysctl -w vm.max_map_count=262144
     
     # To make it persistent, edit /etc/sysctl.conf and add:
     vm.max_map_count=262144
     
     # Then run:
     sudo sysctl -p
     ```

### Remote Deployment Troubleshooting Guide

When Elasticsearch is deployed on a remote server, you may run into network access issues. Common problems and their solutions:

1. Remote access denied
   - Symptom: curl requests return "Connection reset by peer"
   - Solution:
     ```bash
     # Use an SSH tunnel for port forwarding
     ssh -L 9200:localhost:9200 user@remote_server
     
     # Access via the local port in a new terminal
     curl -H "Authorization: ApiKey your_api_key" https://localhost:9200/_cluster/health\?pretty -k
     ```

2. Network configuration checklist
   - Make sure the remote server's firewall allows access to port 9200
     ```bash
     # For systems using iptables
     sudo iptables -A INPUT -p tcp --dport 9200 -j ACCEPT
     sudo service iptables save
     ```
   
   - Check the Elasticsearch network configuration
     ```yaml
     # Example elasticsearch.yml configuration
     network.host: 0.0.0.0
     http.cors.enabled: true
     http.cors.allow-origin: "*"
     ```

3. Security configuration recommendations
   - In production environments, it is recommended to:
     - Restrict the CORS `allow-origin` to specific domains
     - Use a reverse proxy (e.g., Nginx) to manage SSL termination
     - Configure appropriate network security group rules
     - Use SSL certificates instead of self-signed certificates

4. Using environment variables
   - Configure the remote connection in a `.env` file:
     ```
     ELASTICSEARCH_HOST=https://remote_server:9200
     ELASTICSEARCH_API_KEY=your_api_key
     ```
   
   - If you use an SSH tunnel, you can keep using localhost:
     ```
     ELASTICSEARCH_HOST=https://localhost:9200
     ```

5. Troubleshooting commands
   ```bash
   # Check the port listening status
   netstat -tulpn | grep 9200
   
   # Check the ES logs
   docker logs es01
   
   # Test the SSL connection
   openssl s_client -connect remote_server:9200
   ```

## Core Components

- `elasticsearch_core.py`: the main class `ElasticSearchCore`, containing all Elasticsearch operations
- `base.py`: the abstract base class `VectorDatabaseCore`, which defines a unified vector store interface (making it easy to extend to other backends)
- `datamate_core.py`: `DataMateCore`, the DataMate vector store implementation (exported by default from `nexent.vector_database`)
- `utils.py`: utility functions for data formatting and query building

Embedding vectors are generated by `EmbeddingAdapter` adapters from `nexent.core.gateway.modality` (e.g., `JinaEmbeddingAdapter`, `OpenAICompatibleEmbeddingAdapter`, `DashScopeEmbeddingAdapter`, `SiliconflowEmbeddingAdapter`).

## Usage Examples

### Basic Initialization

```python
from nexent.vector_database.elasticsearch_core import ElasticSearchCore

# Specify credentials directly (host and api_key are required parameters)
vdb_core = ElasticSearchCore(
    host="https://localhost:9200",
    api_key="your_api_key",
    verify_certs=False,
    ssl_show_warn=False,
)
```

### Index Management

```python
# Create a new vector index (embedding_dim is optional; the embedding model's dimension is used when not specified)
vdb_core.create_index("my_documents")

# List all user indices
indices = vdb_core.get_user_indices()
print(indices)

# Check whether an index exists
exists = vdb_core.check_index_exists("my_documents")
print(exists)

# Delete an index
vdb_core.delete_index("my_documents")
```

### Document Operations

```python
from nexent.core.gateway.model_context import EmbeddingContext
from nexent.core.gateway.modality import OpenAICompatibleEmbeddingAdapter

# Build the embedding model adapter
embedding_model = OpenAICompatibleEmbeddingAdapter(EmbeddingContext(
    model_name="your-embedding-model",
    base_url="https://your-embedding-api/v1/embeddings",
    api_key="your_api_key",
    modality="embedding",
    factory="openai",
    embedding_dim=1024,
))

# Index documents (embedding vectors are generated automatically; batch_size defaults to 64)
documents = [
    {
        "id": "doc1",
        "title": "Document 1",
        "file": "file1.txt",
        "path_or_url": "https://example.com/doc1",
        "content": "This is the content of document 1",
        "process_source": "Web",
        "embedding_model_name": "your-embedding-model",  # specify the embedding model
        "file_size": 1024,  # file size in bytes
        "create_time": "2023-06-01T10:30:00"  # file creation time
    },
    {
        "id": "doc2",
        "title": "Document 2",
        "file": "file2.txt",
        "path_or_url": "https://example.com/doc2",
        "content": "This is the content of document 2",
        "process_source": "Web"
        # default values are used when other fields are not provided
    }
]
total_indexed = vdb_core.vectorize_documents(
    "my_documents", embedding_model, documents, batch_size=64
)
print(f"Successfully indexed {total_indexed} documents")

# Delete documents by URL or path
deleted_count = vdb_core.delete_documents("my_documents", "https://example.com/doc1")
print(f"Deleted {deleted_count} documents")
```

### Search

```python
# Accurate text search (index_names is a list of index names; multiple indices are supported)
results = vdb_core.accurate_search(["my_documents"], "sample query", top_k=5)
for result in results:
    print(f"Score: {result['score']}, Document: {result['document']['title']}")

# Semantic vector search (an embedding model must be passed in)
results = vdb_core.semantic_search(["my_documents"], "sample query", embedding_model, top_k=5)
for result in results:
    print(f"Score: {result['score']}, Document: {result['document']['title']}")

# Hybrid search (weight_accurate is optional; inferred automatically by default: queries containing digits favor accurate search with 0.7, otherwise 0.3)
results = vdb_core.hybrid_search(
    ["my_documents"],
    "sample query",
    embedding_model,
    top_k=5,
    weight_accurate=0.3  # accurate search weight is 0.3, vector search weight is 0.7
)
for result in results:
    print(f"Score: {result['score']}, Document: {result['document']['title']}")
```

### Statistics and Monitoring

```python
# Get index statistics
stats = vdb_core.get_indices_detail(["my_documents"])
print(stats)

# Get the file list with details
file_details = vdb_core.get_documents_detail("my_documents")
print(file_details)

# Count the documents in an index
doc_count = vdb_core.count_documents("my_documents")
print(doc_count)

# Fetch text chunks from an index with pagination
chunks = vdb_core.get_index_chunks("my_documents", page=1, page_size=10)
print(chunks)
```

## ElasticSearchCore Main Features

The ElasticSearchCore class provides the following main features:

- **Index management**: create and delete indices, check whether an index exists, and list user indices
- **Document operations**: batch-index documents with embedding vectors, delete specified documents, and single-chunk CRUD (`create_chunk` / `update_chunk` / `delete_chunk`)
- **Search operations**: accurate text search, semantic vector search, and hybrid search (with optional ES filter support)
- **Statistics and monitoring**: index statistics (`get_indices_detail`), file list details (`get_documents_detail`), and document counts (`count_documents`)

### Advanced Feature Examples

```python
# Get the file list with details (returned fields: path_or_url, filename, file_size, create_time)
files = vdb_core.get_documents_detail("my_documents")
for file in files:
    print(f"File path: {file['path_or_url']}")
    print(f"Filename: {file['filename']}")
    print(f"File size: {file['file_size']} bytes")
    print(f"Created at: {file['create_time']}")
    print("---")

# Get aggregated statistics for all indices
all_stats = vdb_core.get_indices_detail(["my_documents", "other_index"])
for index_name, stats in all_stats.items():
    print(f"Index: {index_name}")
    print(f"Document count: {stats['base_info']['doc_count']}")
    print(f"Embedding model: {stats['base_info'].get('embedding_model')}")
    print("---")
```

## REST API

The SDK itself does not ship a REST service. In the current repository, knowledge-base REST APIs are provided by the backend service (e.g., `backend/apps/northbound_knowledge_app.py`), including:

- **POST** `/indices/{index_name}`: create an index
- **DELETE** `/indices/{index_name}`: delete an index
- **POST** `/indices/search/hybrid`: hybrid search
- **DELETE** `/indices/{index_name}/documents?path_or_url=...&scope=...`: delete documents
  - `scope=source_only`: delete only the MinIO source file while keeping the chunks and vectors in ES (search still works, preview does not)
  - `scope=full`: delete the ES documents and the MinIO source file, and clean up related Redis task records
- **GET** `/indices/{index_name}/files`: get the index file list

For the exact request/response formats, refer to the route definitions in `backend/apps/northbound_knowledge_app.py`.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

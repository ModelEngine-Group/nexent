# Vector Database

This document describes the vector database functionality in the Nexent SDK.

## Overview

The vector database module provides efficient storage and retrieval of high-dimensional vector embeddings with support for:

- Vector similarity search
- Metadata filtering
- Batch operations
- Multiple backend support

## Supported Backends

### Elasticsearch
High-performance distributed search and analytics engine.

### Qdrant
Vector similarity search engine optimized for performance.

### FAISS
Library for efficient similarity search and clustering of dense vectors.

## Usage

```python
from nexent.vector_database import VectorDB

# Initialize vector database
vector_db = VectorDB(
    backend="elasticsearch",
    host="localhost",
    port=9200
)

# Insert vectors
vector_db.insert(
    vectors=embeddings,
    metadata={"source": "document.pdf"}
)

# Search similar vectors
results = vector_db.search(
    query_vector=query_embedding,
    top_k=10
)
```

## Configuration

The vector database can be configured through:
- Connection parameters
- Index settings
- Search parameters

For detailed configuration options, see the SDK documentation.
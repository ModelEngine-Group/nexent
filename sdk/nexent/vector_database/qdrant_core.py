import base64
import logging
import time
import uuid
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from qdrant_client import QdrantClient, models

from ..core.models.embedding_model import BaseEmbedding
from .base import VectorDatabaseCore


logger = logging.getLogger("qdrant_core")

DEFAULT_SCROLL_SIZE = 1000
TEXT_VECTOR_NAME = "embedding"
IMAGE_VECTOR_NAME = "multi_embedding"
FULL_TEXT_FIELDS = ("content", "title", "filename", "path_or_url")
KEYWORD_FIELDS = ("id", "path_or_url", "filename", "process_source", "embedding_model_name")


class QdrantCore(VectorDatabaseCore):
    """Qdrant-backed VectorDatabaseCore."""

    def __init__(
        self,
        url: Optional[str],
        api_key: Optional[str] = None,
        timeout: float = 20,
    ):
        if not url:
            raise ValueError("QDRANT_URL is not configured")
        self.url = url
        self.api_key = api_key
        self.client = QdrantClient(
            url=url,
            api_key=api_key or None,
            timeout=timeout,
        )

    def create_index(self, index_name: str, embedding_dim: Optional[int] = None) -> bool:
        try:
            if self.check_index_exists(index_name):
                logger.info("Qdrant collection %s already exists", index_name)
                return True

            vector_size = embedding_dim or 1024
            self.client.create_collection(
                collection_name=index_name,
                vectors_config={
                    TEXT_VECTOR_NAME: models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                    IMAGE_VECTOR_NAME: models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                },
            )
            self._ensure_payload_indexes(index_name)
            return True
        except Exception as exc:
            logger.error("Error creating Qdrant collection %s: %s", index_name, exc)
            return False

    def delete_index(self, index_name: str) -> bool:
        try:
            if not self.check_index_exists(index_name):
                return False
            self.client.delete_collection(collection_name=index_name)
            return True
        except Exception as exc:
            logger.error("Error deleting Qdrant collection %s: %s", index_name, exc)
            return False

    def get_user_indices(self, index_pattern: str = "*") -> List[str]:
        try:
            collections = self.client.get_collections()
            collection_items = getattr(collections, "collections", collections)
            names = [
                getattr(item, "name", None) if not isinstance(item, dict) else item.get("name")
                for item in collection_items
            ]
            return [name for name in names if name and not name.startswith(".") and fnmatch(name, index_pattern)]
        except Exception as exc:
            logger.error("Error listing Qdrant collections: %s", exc)
            return []

    def check_index_exists(self, index_name: str) -> bool:
        try:
            if hasattr(self.client, "collection_exists"):
                return bool(self.client.collection_exists(collection_name=index_name))
            self.client.get_collection(collection_name=index_name)
            return True
        except Exception:
            return False

    def vectorize_documents(
        self,
        index_name: str,
        embedding_model: BaseEmbedding,
        documents: List[Dict[str, Any]],
        batch_size: int = 64,
        content_field: str = "content",
        embedding_batch_size: int = 10,
        large_mode: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        _ = large_mode
        if not documents:
            return 0

        processed_docs = self._preprocess_documents(documents, content_field)
        if getattr(embedding_model, "model_type", None) != "multimodal":
            processed_docs = [
                doc for doc in processed_docs
                if doc.get("process_source") != "UniversalImageExtractor"
            ]

        total = len(processed_docs)
        if total == 0:
            return 0

        point_buffer: List[Any] = []
        indexed_count = 0
        vectorized_count = 0

        for start in range(0, total, embedding_batch_size):
            sub_batch = processed_docs[start:start + embedding_batch_size]
            docs_for_embeddings, embeddings = self._embed_documents(
                sub_batch,
                content_field,
                embedding_model,
            )
            vectorized_count += len(docs_for_embeddings)
            if progress_callback:
                progress_callback(vectorized_count, total)

            for doc, embedding in zip(docs_for_embeddings, embeddings):
                point_buffer.append(self._build_point(index_name, doc, embedding, embedding_model))

            if len(point_buffer) >= batch_size:
                indexed_count += self._upsert_points(index_name, point_buffer)
                point_buffer = []

        if point_buffer:
            indexed_count += self._upsert_points(index_name, point_buffer)

        return indexed_count

    def delete_documents(self, index_name: str, path_or_url: str) -> int:
        try:
            filter_condition = self._field_filter("path_or_url", path_or_url)
            deleted_count = self._count(index_name, filter_condition)
            self.client.delete(
                collection_name=index_name,
                points_selector=models.FilterSelector(filter=filter_condition),
                wait=True,
            )
            return deleted_count
        except Exception as exc:
            logger.error("Error deleting Qdrant documents: %s", exc)
            return 0

    def get_index_chunks(
        self,
        index_name: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        path_or_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        query_filter = self._field_filter("path_or_url", path_or_url) if path_or_url else None
        total = self._count(index_name, query_filter)
        paginate = page is not None and page_size is not None
        limit = max(page_size or DEFAULT_SCROLL_SIZE, 1) if paginate else DEFAULT_SCROLL_SIZE
        offset = None
        skip = (max(page or 1, 1) - 1) * limit if paginate else 0
        chunks: List[Dict[str, Any]] = []

        while True:
            points, offset = self._scroll(index_name, limit=limit, offset=offset, query_filter=query_filter)
            if skip:
                if len(points) <= skip:
                    skip -= len(points)
                    if offset is None:
                        break
                    continue
                points = points[skip:]
                skip = 0

            for point in points:
                chunks.append(self._payload_from_point(point))
                if paginate and len(chunks) >= limit:
                    break

            if paginate and len(chunks) >= limit:
                break
            if offset is None:
                break

        return {
            "chunks": chunks,
            "total": total,
            "page": page if paginate else None,
            "page_size": page_size if paginate else None,
        }

    def create_chunk(self, index_name: str, chunk: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._payload_without_vectors(chunk)
        chunk_id = payload.get("id") or str(uuid.uuid4())
        payload["id"] = chunk_id
        point = self._point_from_payload(index_name, payload, chunk)
        self.client.upsert(collection_name=index_name, points=[point], wait=True)
        return {"id": chunk_id, "result": "created"}

    def update_chunk(self, index_name: str, chunk_id: str, chunk_updates: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._get_point_by_chunk_id(index_name, chunk_id, with_vectors=True)
        if existing is None:
            raise ValueError(f"Chunk {chunk_id} not found in index {index_name}")

        payload = self._payload_from_point(existing)
        payload.update(self._payload_without_vectors(chunk_updates))
        payload["id"] = chunk_id

        vectors = self._vectors_from_point(existing)
        if TEXT_VECTOR_NAME in chunk_updates:
            vectors[TEXT_VECTOR_NAME] = chunk_updates[TEXT_VECTOR_NAME]
        if IMAGE_VECTOR_NAME in chunk_updates:
            vectors[IMAGE_VECTOR_NAME] = chunk_updates[IMAGE_VECTOR_NAME]

        point = models.PointStruct(
            id=self._point_id(index_name, chunk_id),
            vector=vectors,
            payload=payload,
        )
        self.client.upsert(collection_name=index_name, points=[point], wait=True)
        return {"id": chunk_id, "result": "updated"}

    def delete_chunk(self, index_name: str, chunk_id: str) -> bool:
        if self._get_point_by_chunk_id(index_name, chunk_id) is None:
            return False
        self.client.delete(
            collection_name=index_name,
            points_selector=models.PointIdsList(points=[self._point_id(index_name, chunk_id)]),
            wait=True,
        )
        return True

    def count_documents(self, index_name: str) -> int:
        return self._count(index_name, None)

    def search(self, index_name: str, query: Dict[str, Any]) -> Dict[str, Any]:
        size = int(query.get("size", 10))
        query_filter = self._filter_from_es_query(query)
        points, _ = self._scroll(index_name, limit=size, offset=None, query_filter=query_filter)
        hits = [
            {
                "_id": str(getattr(point, "id", "")),
                "_score": 1.0,
                "_source": self._payload_from_point(point),
                "_index": index_name,
            }
            for point in points
        ]
        return {"hits": {"hits": hits, "total": {"value": self._count(index_name, query_filter)}}}

    def multi_search(self, body: List[Dict[str, Any]], index_name: str) -> Dict[str, Any]:
        responses = []
        for i in range(0, len(body), 2):
            query = body[i + 1] if i + 1 < len(body) else {}
            limit = int(query.get("size", 10))
            query_filter = self._filter_from_es_query(query)
            points, _ = self._scroll(index_name, limit=limit, offset=None, query_filter=query_filter)
            responses.append({
                "hits": {
                    "hits": [
                        {
                            "_id": str(getattr(point, "id", "")),
                            "_score": 1.0,
                            "_source": self._payload_from_point(point),
                            "_index": index_name,
                        }
                        for point in points
                    ]
                }
            })
        return {"responses": responses}

    def accurate_search(self, index_names: List[str], query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        query_terms = [term.lower() for term in query_text.split() if term.strip()]
        if not query_terms:
            return []

        text_filter = self._full_text_filter(query_text)
        for index_name in index_names:
            offset = None
            while True:
                points, offset = self._scroll(
                    index_name,
                    limit=DEFAULT_SCROLL_SIZE,
                    offset=offset,
                    query_filter=text_filter,
                )
                for point in points:
                    payload = self._payload_from_point(point)
                    haystack = " ".join(
                        str(payload.get(field, ""))
                        for field in FULL_TEXT_FIELDS
                    ).lower()
                    score = sum(haystack.count(term) for term in query_terms)
                    if score > 0:
                        results.append({"score": float(score), "document": payload, "index": index_name})
                if offset is None:
                    break

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    def semantic_search(
        self,
        index_names: List[str],
        query_text: str,
        embedding_model: BaseEmbedding,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        query_embedding = embedding_model.get_embeddings(query_text)[0]
        vector_names = [TEXT_VECTOR_NAME]
        if getattr(embedding_model, "model_type", None) == "multimodal":
            vector_names.append(IMAGE_VECTOR_NAME)

        results: List[Dict[str, Any]] = []
        for index_name in index_names:
            for vector_name in vector_names:
                for point in self._query_points(index_name, vector_name, query_embedding, top_k):
                    payload = self._payload_from_point(point)
                    results.append({
                        "score": float(getattr(point, "score", 0.0) or 0.0),
                        "document": payload,
                        "index": index_name,
                    })

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    def hybrid_search(
        self,
        index_names: List[str],
        query_text: str,
        embedding_model: BaseEmbedding,
        top_k: int = 5,
        weight_accurate: float = 0.3,
    ) -> List[Dict[str, Any]]:
        accurate_results = self.accurate_search(index_names, query_text, top_k=top_k)
        semantic_results = self.semantic_search(index_names, query_text, embedding_model, top_k=top_k)
        combined: Dict[str, Dict[str, Any]] = {}

        for result in accurate_results:
            doc_id = result.get("document", {}).get("id")
            if not doc_id:
                continue
            combined[doc_id] = {
                "document": result["document"],
                "accurate_score": result.get("score", 0.0),
                "semantic_score": 0.0,
                "index": result["index"],
            }

        for result in semantic_results:
            doc_id = result.get("document", {}).get("id")
            if not doc_id:
                continue
            item = combined.setdefault(
                doc_id,
                {
                    "document": result["document"],
                    "accurate_score": 0.0,
                    "semantic_score": 0.0,
                    "index": result["index"],
                },
            )
            item["semantic_score"] = max(item["semantic_score"], result.get("score", 0.0))

        max_accurate = max((item["accurate_score"] for item in combined.values()), default=1.0) or 1.0
        max_semantic = max((item["semantic_score"] for item in combined.values()), default=1.0) or 1.0
        results = []
        for item in combined.values():
            normalized_accurate = item["accurate_score"] / max_accurate
            normalized_semantic = item["semantic_score"] / max_semantic
            score = weight_accurate * normalized_accurate + (1 - weight_accurate) * normalized_semantic
            results.append({
                "score": score,
                "document": item["document"],
                "index": item["index"],
                "scores": {"accurate": normalized_accurate, "semantic": normalized_semantic},
            })

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    def get_documents_detail(self, index_name: str) -> List[Dict[str, Any]]:
        documents: Dict[str, Dict[str, Any]] = {}
        offset = None
        while True:
            points, offset = self._scroll(index_name, limit=DEFAULT_SCROLL_SIZE, offset=offset, query_filter=None)
            for point in points:
                payload = self._payload_from_point(point)
                source = payload.get("path_or_url", "")
                if not source:
                    continue
                current = documents.setdefault(
                    source,
                    {
                        "path_or_url": source,
                        "filename": payload.get("filename", ""),
                        "file_size": payload.get("file_size", 0),
                        "create_time": payload.get("create_time"),
                        "chunk_count": 0,
                    },
                )
                current["chunk_count"] += 1
            if offset is None:
                break
        return list(documents.values())

    def get_indices_detail(
        self,
        index_names: List[str],
        embedding_dim: Optional[int] = None,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        details = {}
        for index_name in index_names:
            try:
                collection_info = self.client.get_collection(collection_name=index_name)
                points_count = int(getattr(collection_info, "points_count", 0) or 0)
                documents = self.get_documents_detail(index_name)
                process_source, embedding_model = self._first_payload_values(
                    index_name,
                    ("process_source", "embedding_model_name"),
                )
                details[index_name] = {
                    "base_info": {
                        "doc_count": len(documents),
                        "chunk_count": points_count,
                        "store_size": "0B",
                        "process_source": process_source or "",
                        "embedding_model": embedding_model or "",
                        "embedding_dim": embedding_dim or self._vector_size(index_name, TEXT_VECTOR_NAME),
                        "creation_date": 0,
                        "update_date": 0,
                    },
                    "search_performance": {
                        "total_search_count": 0,
                        "hit_count": 0,
                    },
                }
            except Exception as exc:
                logger.error("Error getting Qdrant stats for %s: %s", index_name, exc)
                details[index_name] = {"error": str(exc)}
        return details

    def _ensure_payload_indexes(self, index_name: str) -> None:
        for field_name in KEYWORD_FIELDS:
            try:
                self.client.create_payload_index(
                    collection_name=index_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:
                logger.debug("Skipping Qdrant payload index %s.%s: %s", index_name, field_name, exc)

        for field_name in FULL_TEXT_FIELDS:
            try:
                self.client.create_payload_index(
                    collection_name=index_name,
                    field_name=field_name,
                    field_schema=models.TextIndexParams(
                        type=models.TextIndexType.TEXT,
                        tokenizer=models.TokenizerType.WORD,
                        lowercase=True,
                    ),
                )
            except Exception as exc:
                logger.debug("Skipping Qdrant text index %s.%s: %s", index_name, field_name, exc)

    def _full_text_filter(self, query_text: str) -> Any:
        match_type = getattr(models, "MatchTextAny", None)
        if match_type is None:
            match_type = models.MatchText
            match_kwargs = {"text": query_text}
        else:
            match_kwargs = {"text_any": query_text}

        return models.Filter(
            should=[
                models.FieldCondition(
                    key=field_name,
                    match=match_type(**match_kwargs),
                )
                for field_name in FULL_TEXT_FIELDS
            ]
        )

    @staticmethod
    def _point_id(index_name: str, chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexent:{index_name}:{chunk_id}"))

    def _preprocess_documents(self, documents: List[Dict[str, Any]], content_field: str) -> List[Dict[str, Any]]:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        processed = []
        for doc in documents:
            item = doc.copy()
            item.setdefault("create_time", current_time)
            item.setdefault("date", current_date)
            item.setdefault("file_size", 0)
            item.setdefault("process_source", "Unstructured")
            if not item.get("id"):
                item["id"] = f"{int(time.time())}_{hash(item.get(content_field, ''))}"[:20]
            processed.append(item)
        return processed

    def _embed_documents(
        self,
        documents: List[Dict[str, Any]],
        content_field: str,
        embedding_model: BaseEmbedding,
    ) -> Tuple[List[Dict[str, Any]], List[Any]]:
        if getattr(embedding_model, "model_type", None) == "multimodal":
            inputs = []
            docs_for_embeddings = []
            for doc in documents:
                if doc.get("process_source") == "UniversalImageExtractor":
                    image_bytes = doc.pop("image_bytes", b"")
                    if image_bytes:
                        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                        inputs.append({"image": f"data:image/jpeg;base64,{image_base64}"})
                        docs_for_embeddings.append(doc)
                else:
                    inputs.append({"text": doc.get(content_field, "")})
                    docs_for_embeddings.append(doc)
            return docs_for_embeddings, embedding_model.get_multimodal_embeddings(inputs)

        inputs = [doc.get(content_field, "") for doc in documents]
        return documents, embedding_model.get_embeddings(inputs)

    def _build_point(
        self,
        index_name: str,
        doc: Dict[str, Any],
        embedding: Sequence[float],
        embedding_model: BaseEmbedding,
    ) -> Any:
        payload = self._payload_without_vectors(doc)
        if "embedding_model_name" not in payload:
            payload["embedding_model_name"] = getattr(embedding_model, "embedding_model_name", "unknown")
        vector_name = (
            IMAGE_VECTOR_NAME
            if payload.get("process_source") == "UniversalImageExtractor"
            else TEXT_VECTOR_NAME
        )
        return models.PointStruct(
            id=self._point_id(index_name, payload["id"]),
            vector={vector_name: list(embedding)},
            payload=payload,
        )

    def _point_from_payload(self, index_name: str, payload: Dict[str, Any], source: Dict[str, Any]) -> Any:
        vectors = {}
        if TEXT_VECTOR_NAME in source:
            vectors[TEXT_VECTOR_NAME] = source[TEXT_VECTOR_NAME]
        if IMAGE_VECTOR_NAME in source:
            vectors[IMAGE_VECTOR_NAME] = source[IMAGE_VECTOR_NAME]
        return models.PointStruct(
            id=self._point_id(index_name, payload["id"]),
            vector=vectors,
            payload=payload,
        )

    @staticmethod
    def _payload_without_vectors(document: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in document.items()
            if key not in {TEXT_VECTOR_NAME, IMAGE_VECTOR_NAME, "image_bytes"}
        }

    def _upsert_points(self, index_name: str, points: List[Any]) -> int:
        self.client.upsert(collection_name=index_name, points=points, wait=True)
        return len(points)

    @staticmethod
    def _field_filter(field_name: str, value: Any) -> Any:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=field_name,
                    match=models.MatchValue(value=value),
                )
            ]
        )

    def _filter_from_es_query(self, query: Dict[str, Any]) -> Optional[Any]:
        query_body = query.get("query", {})
        if "function_score" in query_body:
            query_body = query_body.get("function_score", {}).get("query", {})
        term = query_body.get("term", {})
        if not term:
            return None
        for field_name, raw_value in term.items():
            value = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
            if value is not None:
                return self._field_filter(field_name, value)
        return None

    def _count(self, index_name: str, query_filter: Optional[Any]) -> int:
        result = self.client.count(
            collection_name=index_name,
            count_filter=query_filter,
            exact=True,
        )
        fallback_count = result.get("count", 0) if isinstance(result, dict) else 0
        return int(getattr(result, "count", fallback_count) or 0)

    def _scroll(
        self,
        index_name: str,
        limit: int,
        offset: Optional[Any],
        query_filter: Optional[Any],
        with_vectors: bool = False,
    ) -> Tuple[List[Any], Optional[Any]]:
        result = self.client.scroll(
            collection_name=index_name,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=with_vectors,
        )
        if isinstance(result, tuple):
            return list(result[0]), result[1]
        return list(getattr(result, "points", [])), getattr(result, "next_page_offset", None)

    def _query_points(
        self,
        index_name: str,
        vector_name: str,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> List[Any]:
        try:
            result = self.client.query_points(
                collection_name=index_name,
                query=list(query_embedding),
                using=vector_name,
                limit=top_k,
                with_payload=True,
            )
            return list(getattr(result, "points", result))
        except AttributeError:
            return list(self.client.search(
                collection_name=index_name,
                query_vector=(vector_name, list(query_embedding)),
                limit=top_k,
                with_payload=True,
            ))

    def _get_point_by_chunk_id(self, index_name: str, chunk_id: str, with_vectors: bool = False) -> Optional[Any]:
        points, _ = self._scroll(
            index_name,
            limit=1,
            offset=None,
            query_filter=self._field_filter("id", chunk_id),
            with_vectors=with_vectors,
        )
        return points[0] if points else None

    @staticmethod
    def _payload_from_point(point: Any) -> Dict[str, Any]:
        payload = getattr(point, "payload", None)
        if payload is None and isinstance(point, dict):
            payload = point.get("payload")
        payload = dict(payload or {})
        if "id" not in payload:
            point_id = getattr(point, "id", None)
            if point_id is not None:
                payload["id"] = str(point_id)
        return payload

    @staticmethod
    def _vectors_from_point(point: Any) -> Dict[str, Any]:
        vector = getattr(point, "vector", None)
        if vector is None and isinstance(point, dict):
            vector = point.get("vector")
        if isinstance(vector, dict):
            return dict(vector)
        if vector:
            return {TEXT_VECTOR_NAME: vector}
        return {}

    def _vector_size(self, index_name: str, vector_name: str) -> int:
        try:
            info = self.client.get_collection(collection_name=index_name)
            vectors = getattr(getattr(info, "config", None), "params", None)
            vectors = getattr(vectors, "vectors", None)
            if isinstance(vectors, dict):
                vector_params = vectors.get(vector_name) or next(iter(vectors.values()))
                return int(getattr(vector_params, "size", 1024))
            return int(getattr(vectors, "size", 1024))
        except Exception:
            return 1024

    def _first_payload_values(self, index_name: str, fields: Iterable[str]) -> Tuple[Any, ...]:
        points, _ = self._scroll(index_name, limit=1, offset=None, query_filter=None)
        payload = self._payload_from_point(points[0]) if points else {}
        return tuple(payload.get(field) for field in fields)

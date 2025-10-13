"""
Async Knowledge Summary Utilities
Provides async pipeline for knowledge base summarization with clustering and integration
"""

import asyncio
import logging
import time
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
from jinja2 import Template
from openai import AsyncOpenAI
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from backend.database.model_management_db import get_model_by_model_id
from utils.config_utils import get_model_name_from_config, tenant_config_manager
from utils.prompt_template_utils import get_async_knowledge_summary_prompt_template
from consts.const import MODEL_CONFIG_MAPPING, LANGUAGE

logger = logging.getLogger(__name__)


class AsyncLLMClient:
    """Async LLM client using OpenAI-compatible API"""
    
    def __init__(self, model_config: Dict, language: str = LANGUAGE["ZH"]):
        """
        Initialize async LLM client
        
        Args:
            model_config: Model configuration dict with api_key, base_url, model_name
            language: Language code ('zh' or 'en')
        """
        self.model_config = model_config
        self.client = AsyncOpenAI(
            api_key=model_config.get('api_key', ''),
            base_url=model_config.get('base_url', '')
        )
        self.model_name = get_model_name_from_config(model_config)
        self.semaphore = asyncio.Semaphore(3)  # Max 3 concurrent LLM calls
        self.language = language
        
        # Load prompt templates
        self.prompts = get_async_knowledge_summary_prompt_template(language)
        logger.info(f"Loaded async knowledge summary prompts for language: {language}")
    
    async def chat_async(
        self, 
        messages: List[Dict], 
        max_tokens: int = 500, 
        temperature: float = 0.3
    ) -> Optional[str]:
        """
        Async LLM chat completion
        
        Args:
            messages: List of message dicts with role and content
            max_tokens: Max tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated text or None on error
        """
        async with self.semaphore:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=0.8
                )
                
                if response and response.choices:
                    return response.choices[0].message.content.strip()
                else:
                    logger.error("LLM response format error")
                    return None
                    
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return None
    
    async def batch_generate_cards_async(self, cards_data: List[Dict]) -> List[Dict]:
        """
        Batch async generate knowledge cards
        
        Args:
            cards_data: List of card data dicts
            
        Returns:
            List of generated knowledge cards
        """
        logger.info(f"Starting batch async generation of {len(cards_data)} knowledge cards")
        
        tasks = [self._generate_single_card_async(card_data) for card_data in cards_data]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        generated_cards = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Card {i} generation failed: {result}")
                fallback_card = self._create_fallback_card(cards_data[i])
                generated_cards.append(fallback_card)
            elif result:
                generated_cards.append(result)
        
        logger.info(f"Batch async generation completed, {len(generated_cards)} cards generated")
        return generated_cards
    
    async def _generate_single_card_async(self, card_data: Dict) -> Optional[Dict]:
        """Generate single knowledge card"""
        chunk_cluster = card_data['chunk_cluster']
        parent_cluster_id = card_data['parent_cluster_id']
        
        # Merge chunk texts
        merged_text = self._merge_chunks(chunk_cluster['chunks'])
        
        if not merged_text or len(merged_text.strip()) < 50:
            logger.warning("Merged text too short, skipping card generation")
            return None
        
        # Parallel generation of summary and keywords
        summary_task = self._generate_summary_async(merged_text)
        keywords_task = self._extract_keywords_async(merged_text)
        
        summary, keywords = await asyncio.gather(summary_task, keywords_task)
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence(chunk_cluster)
        
        card = {
            'card_id': f"cluster_{parent_cluster_id}_card_{chunk_cluster.get('cluster_id', 0)}",
            'parent_cluster': parent_cluster_id,
            'summary': summary,
            'keywords': keywords,
            'source_chunks': [
                {
                    'chunk_id': chunk.get('chunk_id', f"{chunk.get('_id', 'unknown')}"),
                    'source_doc': chunk.get('filename', 'unknown'),
                    'length': len(chunk.get('content', ''))
                }
                for chunk in chunk_cluster['chunks']
            ],
            'chunk_count': chunk_cluster['size'],
            'avg_similarity': chunk_cluster.get('avg_similarity', 0.0),
            'confidence_score': confidence_score
        }
        
        return card
    
    async def _generate_summary_async(self, text: str, max_length: int = 200) -> str:
        """Async generate summary"""
        if len(text) > 2000:
            text = text[:2000] + "..."
        
        # Use template from YAML
        template = Template(self.prompts['SUMMARY_GENERATION_PROMPT'])
        prompt = template.render(text=text, max_length=max_length)
        
        messages = [{"role": "user", "content": prompt}]
        
        response = await self.chat_async(
            messages=messages,
            max_tokens=max_length,  # 减少token数量，强制简洁
            temperature=0.3
        )
        
        if response:
            # 清理可能的markdown格式符号
            cleaned_response = self._clean_markdown_symbols(response)
            # 确保长度控制
            if len(cleaned_response) > max_length:
                cleaned_response = cleaned_response[:max_length] + "..."
            return cleaned_response
        else:
            logger.warning("LLM summary generation failed, using fallback strategy")
            return text[:max_length] + "..."
    
    async def _extract_keywords_async(self, text: str, max_keywords: int = 10) -> List[str]:
        """Async extract keywords"""
        if len(text) > 2000:
            text = text[:2000] + "..."
        
        # Use template from YAML
        template = Template(self.prompts['KEYWORD_EXTRACTION_PROMPT'])
        prompt = template.render(text=text, max_keywords=max_keywords)
        
        messages = [{"role": "user", "content": prompt}]
        
        response = await self.chat_async(
            messages=messages,
            max_tokens=200,
            temperature=0.3
        )
        
        if response:
            keywords = [kw.strip() for kw in response.replace('，', ',').split(',')]
            keywords = [kw for kw in keywords if kw]
            return keywords[:max_keywords]
        else:
            logger.warning("LLM keyword extraction failed, using fallback strategy")
            return self._fallback_keyword_extraction(text)
    
    def _merge_chunks(self, chunks: List[dict]) -> str:
        """Merge chunk texts"""
        if not chunks:
            return ""
        
        texts = [chunk.get('content', '') for chunk in chunks]
        return ' '.join(texts)
    
    def _calculate_confidence(self, chunk_cluster: Dict) -> float:
        """Calculate confidence score"""
        size_score = min(chunk_cluster['size'] / 10.0, 1.0)
        similarity_score = chunk_cluster.get('avg_similarity', 0.0)
        confidence = 0.4 * size_score + 0.6 * similarity_score
        return round(confidence, 3)
    
    def _create_fallback_card(self, card_data: Dict) -> Dict:
        """Create fallback card"""
        chunk_cluster = card_data['chunk_cluster']
        parent_cluster_id = card_data['parent_cluster_id']
        
        merged_text = self._merge_chunks(chunk_cluster['chunks'])
        
        return {
            'card_id': f"cluster_{parent_cluster_id}_card_{chunk_cluster.get('cluster_id', 0)}",
            'parent_cluster': parent_cluster_id,
            'summary': merged_text[:200] + "..." if len(merged_text) > 200 else merged_text,
            'keywords': self._fallback_keyword_extraction(merged_text),
            'source_chunks': [
                {
                    'chunk_id': chunk.get('chunk_id', f"{chunk.get('_id', 'unknown')}"),
                    'source_doc': chunk.get('filename', 'unknown'),
                    'length': len(chunk.get('content', ''))
                }
                for chunk in chunk_cluster['chunks']
            ],
            'chunk_count': chunk_cluster['size'],
            'avg_similarity': chunk_cluster.get('avg_similarity', 0.0),
            'confidence_score': 0.5
        }
    
    def _fallback_keyword_extraction(self, text: str) -> List[str]:
        """Fallback keyword extraction"""
        import re
        
        words = re.findall(r'[\u4e00-\u9fa5]+', text)
        stop_words = {'的', '了', '和', '是', '在', '有', '个', '等', '与', '及'}
        words = [w for w in words if len(w) >= 2 and w not in stop_words]
        
        word_counts = Counter(words)
        top_words = [word for word, count in word_counts.most_common(10)]
        
        return top_words
    
    def _clean_markdown_symbols(self, text: str) -> str:
        """Clean markdown symbols from text"""
        import re
        
        # Remove markdown headers
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        # Remove markdown bold/italic
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
        # Remove markdown lists
        text = re.sub(r'^[\s]*[-*+]\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s*', '', text, flags=re.MULTILINE)
        # Remove horizontal rules
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        # Remove extra whitespace
        text = re.sub(r'\n\s*\n', '\n', text)
        text = text.strip()
        
        return text


class DocumentClusterer:
    """Document clusterer using K-means"""
    
    def __init__(self, max_clusters: int = 10):
        """Initialize clusterer"""
        self.max_clusters = max_clusters
        self.scaler = StandardScaler()
    
    def cluster_documents(self, vectors: np.ndarray) -> Dict:
        """
        Cluster documents
        
        Args:
            vectors: Document vectors
            
        Returns:
            Clustering result dict
        """
        # Handle single document case
        if len(vectors) == 1:
            logger.info("Single document detected: returning single cluster")
            return {
                'cluster_labels': np.array([0]),
                'n_clusters': 1,
                'silhouette_score': 1.0
            }
        
        try:
            vectors_scaled = self.scaler.fit_transform(vectors)
            optimal_k = self._find_optimal_k(vectors_scaled)
            
            kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(vectors_scaled)
            
            silhouette_avg = silhouette_score(vectors_scaled, cluster_labels)
            
            logger.info(f"K-means clustering completed: {optimal_k} clusters, silhouette score: {silhouette_avg:.3f}")
            
            return {
                'cluster_labels': cluster_labels,
                'n_clusters': optimal_k,
                'silhouette_score': silhouette_avg
            }
            
        except Exception as e:
            logger.error(f"Clustering failed: {e}")
            return None
    
    def _find_optimal_k(self, vectors: np.ndarray) -> int:
        """Find optimal K value"""
        max_k = min(self.max_clusters, len(vectors) - 1)
        
        if max_k < 2:
            return 1
        
        # Check document similarity
        if len(vectors) > 1:
            similarity_matrix = cosine_similarity(vectors)
            mask = ~np.eye(similarity_matrix.shape[0], dtype=bool)
            avg_similarity = np.mean(similarity_matrix[mask])
            
            if avg_similarity > 0.95:
                logger.warning(f"Documents too similar (avg similarity: {avg_similarity:.3f}), using single cluster")
                return 1
        
        best_k = 2
        best_score = -1
        
        for k in range(2, max_k + 1):
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
                cluster_labels = kmeans.fit_predict(vectors)
                
                if len(set(cluster_labels)) > 1:
                    score = silhouette_score(vectors, cluster_labels)
                    if score > best_score:
                        best_score = score
                        best_k = k
                        
            except Exception as e:
                logger.warning(f"K={k} clustering failed: {e}")
                continue
        
        logger.info(f"Optimal K value: {best_k}")
        return best_k


class ChunkDivider:
    """Chunk divider with sliding window"""
    
    def __init__(self, window_size: int = 512, overlap_ratio: float = 0.2):
        """
        Initialize chunk divider
        
        Args:
            window_size: Window size in characters
            overlap_ratio: Overlap ratio (0-1)
        """
        self.window_size = window_size
        self.overlap_ratio = overlap_ratio
        self.min_chunk_length = 50
    
    def divide_documents(self, documents: List[dict]) -> List[dict]:
        """
        Divide documents into chunks
        
        Args:
            documents: List of document dicts from Elasticsearch
            
        Returns:
            List of chunk dicts
        """
        all_chunks = []
        
        for doc in documents:
            text = doc.get('content', '')
            if not text or len(text.strip()) < self.min_chunk_length:
                continue
                
            chunks = self._sliding_window_chunk(text, doc)
            all_chunks.extend(chunks)
        
        logger.info(f"Divided {len(all_chunks)} chunks from {len(documents)} documents")
        return all_chunks
    
    def _sliding_window_chunk(self, text: str, doc: dict) -> List[dict]:
        """Sliding window chunking"""
        chunks = []
        sentences = self._split_sentences(text)
        
        current_chunk = []
        current_length = 0
        chunk_start_pos = 0
        
        for sent in sentences:
            sent_length = len(sent)
            
            if current_length + sent_length > self.window_size and current_chunk:
                chunk_text = ''.join(current_chunk)
                if len(chunk_text.strip()) >= self.min_chunk_length:
                    chunks.append({
                        'content': chunk_text,
                        'filename': doc.get('filename', 'unknown'),
                        '_id': doc.get('_id', 'unknown'),
                        'title': doc.get('title', ''),
                        'chunk_id': f"{doc.get('_id', 'unknown')}_chunk_{len(chunks)}",
                        'start_pos': chunk_start_pos,
                        'end_pos': chunk_start_pos + len(chunk_text),
                        'length': len(chunk_text)
                    })
                
                overlap_count = int(len(current_chunk) * self.overlap_ratio)
                if overlap_count > 0:
                    overlap_text = ''.join(current_chunk[-overlap_count:])
                    chunk_start_pos += len(chunk_text) - len(overlap_text)
                    current_chunk = current_chunk[-overlap_count:]
                    current_length = len(overlap_text)
                else:
                    chunk_start_pos += len(chunk_text)
                    current_chunk = []
                    current_length = 0
            
            current_chunk.append(sent)
            current_length += sent_length
        
        if current_chunk:
            chunk_text = ''.join(current_chunk)
            if len(chunk_text.strip()) >= self.min_chunk_length:
                chunks.append({
                    'content': chunk_text,
                    'filename': doc.get('filename', 'unknown'),
                    '_id': doc.get('_id', 'unknown'),
                    'title': doc.get('title', ''),
                    'chunk_id': f"{doc.get('_id', 'unknown')}_chunk_{len(chunks)}",
                    'start_pos': chunk_start_pos,
                    'end_pos': chunk_start_pos + len(chunk_text),
                    'length': len(chunk_text)
                })
        
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """Simple sentence splitting"""
        import re
        
        if len(text) < self.min_chunk_length:
            return [text] if text.strip() else []
        
        sentences = re.split(r'([。！？\n]+)', text)
        
        result = []
        for i in range(0, len(sentences), 2):
            if i + 1 < len(sentences):
                sent = sentences[i] + sentences[i + 1]
            else:
                sent = sentences[i]
            
            if sent.strip():
                result.append(sent)
        
        if not result:
            result = [text]
        
        return result


class ChunkClusterer:
    """Chunk clusterer based on similarity threshold"""
    
    def __init__(self, similarity_threshold: float = 0.70, min_cluster_size: int = 1):
        """
        Initialize chunk clusterer
        
        Args:
            similarity_threshold: Similarity threshold (0-1)
            min_cluster_size: Minimum cluster size
        """
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size
    
    def cluster_chunks(self, vectors: np.ndarray, chunks: List[dict]) -> Dict:
        """
        Cluster chunks with document-first approach
        
        Args:
            vectors: Chunk vectors
            chunks: Chunk dicts
            
        Returns:
            Clustering result
        """
        if len(chunks) == 0:
            return {'chunk_clusters': [], 'n_clusters': 0}
        
        # First: Group chunks by document source
        document_groups = self._group_chunks_by_document(chunks, vectors)
        
        # Second: Within each document, perform semantic clustering
        all_clusters = []
        cluster_counter = 0
        
        for doc_id, (doc_chunks, doc_vectors) in document_groups.items():
            if len(doc_chunks) == 1:
                # Single chunk document - create single cluster
                cluster = {
                    'cluster_id': cluster_counter,
                    'chunks': doc_chunks,
                    'size': 1,
                    'avg_similarity': 1.0,
                    'document_id': doc_id
                }
                all_clusters.append(cluster)
                cluster_counter += 1
            else:
                # Multiple chunks document - semantic clustering within document
                doc_similarity_matrix = cosine_similarity(doc_vectors)
                doc_cluster_labels = self._threshold_clustering(doc_similarity_matrix)
                
                # Organize clusters within this document
                doc_clusters = self._organize_clusters(doc_chunks, doc_cluster_labels, doc_similarity_matrix)
                
                # Assign cluster IDs and add document info
                for cluster in doc_clusters['chunk_clusters']:
                    cluster['cluster_id'] = cluster_counter
                    cluster['document_id'] = doc_id
                    all_clusters.append(cluster)
                    cluster_counter += 1
        
        result = {
            'chunk_clusters': all_clusters,
            'noise_chunks': [],
            'n_clusters': len(all_clusters),
            'n_noise': 0
        }
        
        logger.info(f"Document-first clustering completed: {result['n_clusters']} clusters from {len(document_groups)} documents")
        return result
    
    def _group_chunks_by_document(self, chunks: List[dict], vectors: np.ndarray) -> Dict[str, tuple]:
        """Group chunks by their source document"""
        document_groups = {}
        
        for i, chunk in enumerate(chunks):
            # Use filename as document identifier
            doc_id = chunk.get('filename', chunk.get('source_doc', f'doc_{i}'))
            
            if doc_id not in document_groups:
                document_groups[doc_id] = ([], [])
            
            document_groups[doc_id][0].append(chunk)  # chunks
            document_groups[doc_id][1].append(vectors[i])  # vectors
        
        # Convert lists to numpy arrays
        for doc_id in document_groups:
            chunks_list, vectors_list = document_groups[doc_id]
            vectors_array = np.array(vectors_list)
            document_groups[doc_id] = (chunks_list, vectors_array)
        
        return document_groups
    
    def cluster_chunks_with_document_clusters(self, vectors: np.ndarray, chunks: List[dict], chunks_by_doc_cluster: Dict[int, List[dict]]) -> Dict:
        """
        Cluster chunks with awareness of document clusters
        
        Args:
            vectors: Chunk vectors
            chunks: Chunk dicts
            chunks_by_doc_cluster: Chunks organized by document clusters
            
        Returns:
            Clustering result with document cluster awareness
        """
        if len(chunks) == 0:
            return {'chunk_clusters': [], 'n_clusters': 0}
        
        all_clusters = []
        cluster_counter = 0
        
        # Process each document cluster separately
        for doc_cluster_id, doc_cluster_chunks in chunks_by_doc_cluster.items():
            if not doc_cluster_chunks:
                continue
                
            # Get vectors for this document cluster
            doc_cluster_indices = []
            for chunk in doc_cluster_chunks:
                for i, orig_chunk in enumerate(chunks):
                    if chunk == orig_chunk:
                        doc_cluster_indices.append(i)
                        break
            
            if not doc_cluster_indices:
                continue
                
            doc_cluster_vectors = vectors[doc_cluster_indices]
            
            # Smart chunk clustering decision based on token limit
            estimated_tokens = self._estimate_tokens_for_chunks(doc_cluster_chunks)
            max_tokens_per_cluster = 4000  # Conservative token limit for LLM processing
            
            if estimated_tokens <= max_tokens_per_cluster:
                # Few chunks or low token count: merge all chunks into one cluster
                cluster = {
                    'cluster_id': cluster_counter,
                    'chunks': doc_cluster_chunks,
                    'size': len(doc_cluster_chunks),
                    'avg_similarity': 0.9,  # High similarity for same document cluster
                    'document_cluster_id': doc_cluster_id
                }
                all_clusters.append(cluster)
                cluster_counter += 1
                logger.info(f"Document cluster {doc_cluster_id}: merged {len(doc_cluster_chunks)} chunks into 1 cluster (tokens: {estimated_tokens})")
            else:
                # Many chunks or high token count: apply semantic clustering
                doc_similarity_matrix = cosine_similarity(doc_cluster_vectors)
                doc_cluster_labels = self._threshold_clustering(doc_similarity_matrix)
                
                # Organize clusters within this document cluster
                doc_clusters = self._organize_clusters(doc_cluster_chunks, doc_cluster_labels, doc_similarity_matrix)
                
                # Assign cluster IDs and add document cluster info
                for cluster in doc_clusters['chunk_clusters']:
                    cluster['cluster_id'] = cluster_counter
                    cluster['document_cluster_id'] = doc_cluster_id
                    all_clusters.append(cluster)
                    cluster_counter += 1
                
                logger.info(f"Document cluster {doc_cluster_id}: {len(doc_cluster_chunks)} chunks clustered into {len(doc_clusters['chunk_clusters'])} sub-clusters (tokens: {estimated_tokens})")
        
        result = {
            'chunk_clusters': all_clusters,
            'noise_chunks': [],
            'n_clusters': len(all_clusters),
            'n_noise': 0
        }
        
        logger.info(f"Document-cluster-aware chunk clustering completed: {result['n_clusters']} clusters from {len(chunks_by_doc_cluster)} document clusters")
        return result
    
    def _estimate_tokens_for_chunks(self, chunks: List[dict]) -> int:
        """Estimate token count for a list of chunks"""
        total_text = ""
        for chunk in chunks:
            content = chunk.get('content', '')
            total_text += content + " "
        
        # Rough estimation: 1 token ≈ 4 characters for Chinese text
        estimated_tokens = len(total_text.strip()) // 4
        return estimated_tokens
    
    def _threshold_clustering(self, similarity_matrix: np.ndarray) -> np.ndarray:
        """Threshold-based clustering"""
        n_chunks = len(similarity_matrix)
        cluster_labels = np.full(n_chunks, -1, dtype=int)
        current_cluster = 0
        
        for i in range(n_chunks):
            if cluster_labels[i] != -1:
                continue
            
            similar_indices = np.where(similarity_matrix[i] >= self.similarity_threshold)[0]
            
            if len(similar_indices) >= self.min_cluster_size:
                for idx in similar_indices:
                    if cluster_labels[idx] == -1:
                        cluster_labels[idx] = current_cluster
                current_cluster += 1
            else:
                cluster_labels[i] = -1
        
        return cluster_labels
    
    def _organize_clusters(
        self, 
        chunks: List[dict], 
        cluster_labels: np.ndarray, 
        similarity_matrix: np.ndarray
    ) -> Dict:
        """Organize clustering results"""
        chunk_clusters = {}
        noise_chunks = []
        
        for i, (chunk, label) in enumerate(zip(chunks, cluster_labels)):
            if label == -1:
                noise_chunks.append(chunk)
            else:
                if label not in chunk_clusters:
                    chunk_clusters[label] = {
                        'cluster_id': int(label),
                        'chunks': [],
                        'size': 0,
                        'avg_similarity': 0.0
                    }
                chunk_clusters[label]['chunks'].append(chunk)
                chunk_clusters[label]['size'] += 1
        
        for cluster_id, cluster_info in chunk_clusters.items():
            chunk_indices = [i for i, label in enumerate(cluster_labels) if label == cluster_id]
            if len(chunk_indices) > 1:
                cluster_sim_matrix = similarity_matrix[np.ix_(chunk_indices, chunk_indices)]
                mask = ~np.eye(cluster_sim_matrix.shape[0], dtype=bool)
                avg_sim = np.mean(cluster_sim_matrix[mask])
                cluster_info['avg_similarity'] = float(avg_sim)
            else:
                cluster_info['avg_similarity'] = 1.0
        
        return {
            'chunk_clusters': list(chunk_clusters.values()),
            'noise_chunks': noise_chunks,
            'n_clusters': len(chunk_clusters),
            'n_noise': len(noise_chunks)
        }


class KnowledgeIntegrator:
    """Knowledge integrator for cluster and global integration"""
    
    def __init__(self, llm_client: AsyncLLMClient):
        """
        Initialize knowledge integrator
        
        Args:
            llm_client: Async LLM client
        """
        self.llm_client = llm_client
    
    async def integrate_cluster_cards(self, cards: List[Dict], cluster_id: int) -> Dict:
        """
        Integrate knowledge cards within a cluster
        
        Args:
            cards: Knowledge cards
            cluster_id: Cluster ID
            
        Returns:
            Cluster integration result
        """
        if not cards:
            return None
        
        if len(cards) == 1:
            card = cards[0]
            return {
                'cluster_id': cluster_id,
                'integrated_summary': card['summary'],
                'integrated_keywords': card['keywords'],
                'card_count': 1,
                'source_cards': [card['card_id']],
                'confidence_score': card['confidence_score']
            }
        
        logger.info(f"Integrating {len(cards)} knowledge cards in cluster {cluster_id}...")
        
        card_summaries = []
        all_keywords = []
        
        for i, card in enumerate(cards):
            card_summaries.append(f"Card{i+1}: {card['summary']}")
            all_keywords.extend(card['keywords'])
        
        integrated_summary = await self._generate_cluster_summary_async(card_summaries, cluster_id)
        integrated_keywords = self._integrate_keywords(all_keywords)
        
        avg_confidence = sum(card['confidence_score'] for card in cards) / len(cards)
        
        return {
            'cluster_id': cluster_id,
            'integrated_summary': integrated_summary,
            'integrated_keywords': integrated_keywords,
            'card_count': len(cards),
            'source_cards': [card['card_id'] for card in cards],
            'confidence_score': round(avg_confidence, 3),
            'detailed_cards': cards
        }
    
    async def integrate_all_clusters(self, cluster_integrations: List[Dict]) -> Dict:
        """
        Integrate all cluster summaries
        
        Args:
            cluster_integrations: List of cluster integration results
            
        Returns:
            Global integration result
        """
        if not cluster_integrations:
            return None
        
        logger.info(f"Integrating {len(cluster_integrations)} cluster summaries...")
        
        cluster_summaries = []
        all_keywords = []
        
        for i, cluster in enumerate(cluster_integrations):
            cluster_summaries.append(f"Cluster{i+1}: {cluster['integrated_summary']}")
            all_keywords.extend(cluster['integrated_keywords'])
        
        global_summary = await self._generate_global_summary_async(cluster_summaries)
        global_keywords = self._integrate_keywords(all_keywords)
        
        total_cards = sum(cluster['card_count'] for cluster in cluster_integrations)
        avg_confidence = sum(cluster['confidence_score'] for cluster in cluster_integrations) / len(cluster_integrations)
        
        return {
            'global_summary': global_summary,
            'global_keywords': global_keywords,
            'cluster_count': len(cluster_integrations),
            'total_cards': total_cards,
            'avg_confidence': round(avg_confidence, 3),
            'cluster_details': cluster_integrations
        }
    
    async def _generate_cluster_summary_async(self, card_summaries: List[str], cluster_id: int) -> str:
        """Generate cluster-level integrated summary"""
        summaries_text = '\n'.join(card_summaries)
        
        # Use template from YAML
        template = Template(self.llm_client.prompts['CLUSTER_INTEGRATION_PROMPT'])
        prompt = template.render(summaries_text=summaries_text)
        
        messages = [{"role": "user", "content": prompt}]
        
        response = await self.llm_client.chat_async(
            messages=messages,
            max_tokens=300,  # 减少token数量
            temperature=0.3
        )
        
        if response:
            # 清理markdown符号
            cleaned_response = self._clean_markdown_symbols(response)
            return cleaned_response
        else:
            logger.warning("LLM cluster integration failed, using fallback strategy")
            return "；".join(card_summaries)
    
    async def _generate_global_summary_async(self, cluster_summaries: List[str]) -> str:
        """Generate global integrated summary with dynamic point structure"""
        summaries_text = '\n\n'.join(cluster_summaries)
        cluster_count = len(cluster_summaries)
        
        # Use template from YAML
        template = Template(self.llm_client.prompts['GLOBAL_INTEGRATION_PROMPT'])
        prompt = template.render(summaries_text=summaries_text, cluster_count=cluster_count)
        
        messages = [{"role": "user", "content": prompt}]
        
        response = await self.llm_client.chat_async(
            messages=messages,
            max_tokens=2000,  # 增加token限制以支持结构化长文本
            temperature=0.3
        )
        
        if response:
            # 直接返回大模型输出，无需额外格式化
            return response
        else:
            logger.warning("LLM global integration failed, using fallback strategy")
            return "\n\n".join(cluster_summaries)
    
    def _clean_markdown_symbols(self, text: str) -> str:
        """Clean markdown symbols from text"""
        import re
        
        # Remove markdown headers
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        # Remove markdown bold/italic
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
        # Remove markdown lists
        text = re.sub(r'^[\s]*[-*+]\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s]*\d+\.\s*', '', text, flags=re.MULTILINE)
        # Remove horizontal rules
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        # Remove extra whitespace
        text = re.sub(r'\n\s*\n', '\n', text)
        text = text.strip()
        
        return text
    
    def _format_final_summary(self, text: str) -> str:
        """Format final summary for better readability with dynamic numbered points"""
        import re
        
        # Split into lines and clean
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Format numbered points dynamically
        formatted_lines = []
        point_counter = 0
        
        for line in lines:
            if line:
                # Check if line already has Chinese numbering
                if re.match(r'^[一二三四五六七八九十百千万]+、', line):
                    formatted_lines.append(line)
                    point_counter += 1
                else:
                    # Add dynamic numbering
                    point_counter += 1
                    chinese_num = self._convert_to_chinese_number(point_counter)
                    line = f'{chinese_num}、{line}'
                    formatted_lines.append(line)
        
        # Add proper spacing between numbered points
        formatted_text = '\n\n'.join(formatted_lines)
        
        # Ensure each point has proper spacing and clear structure
        import re
        # Clean up any extra spaces and ensure consistent formatting
        formatted_text = re.sub(r'\n\s*\n\s*\n', '\n\n', formatted_text)  # Remove excessive line breaks
        formatted_text = re.sub(r'([一二三四五六七八九十]+、[^一-十\n]+)(?=\n|$)', r'\1', formatted_text)  # Ensure proper ending
        
        # Ensure each numbered point is followed by proper spacing
        lines = formatted_text.split('\n')
        formatted_lines = []
        for i, line in enumerate(lines):
            formatted_lines.append(line)
            # Add spacing after numbered points
            if re.match(r'^[一二三四五六七八九十]+、', line.strip()) and i < len(lines) - 1:
                if not lines[i + 1].strip():  # If next line is empty, keep it
                    continue
                else:  # If next line has content, add spacing
                    formatted_lines.append('')
        
        return '\n'.join(formatted_lines)
    
    def _convert_to_chinese_number(self, num: int) -> str:
        """Convert Arabic number to Chinese number"""
        if num <= 10:
            num_map = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九', 10: '十'}
            return num_map[num]
        elif num <= 99:
            # For numbers 11-99, use combination
            if num == 10:
                return '十'
            elif num < 20:
                return f'十{self._convert_to_chinese_number(num % 10)}'
            else:
                tens = num // 10
                ones = num % 10
                if ones == 0:
                    return f'{self._convert_to_chinese_number(tens)}十'
                else:
                    return f'{self._convert_to_chinese_number(tens)}十{self._convert_to_chinese_number(ones)}'
        else:
            # For numbers >= 100, use Arabic number as fallback
            return str(num)
    
    def _integrate_keywords(self, keywords_list: List[str], max_keywords: int = 20) -> List[str]:
        """Integrate keyword list"""
        keyword_counts = Counter(keywords_list)
        top_keywords = [kw for kw, count in keyword_counts.most_common(max_keywords)]
        return top_keywords


async def async_vectorize_batch(
    texts: List[str],
    embedding_model,
    batch_size: int = 20
) -> np.ndarray:
    """
    Async batch vectorization using embedding model
    
    Args:
        texts: List of texts to vectorize
        embedding_model: Embedding model instance
        batch_size: Batch size
        
    Returns:
        Vector matrix
    """
    logger.info(f"Starting async vectorization of {len(texts)} texts, batch size: {batch_size}")
    
    batches = [texts[i:i+batch_size] for i in range(0, len(texts), batch_size)]
    logger.info(f"Divided into {len(batches)} batches")
    
    async def vectorize_batch(batch_texts: List[str]) -> np.ndarray:
        """Vectorize a single batch"""
        try:
            # Use embedding model's get_embeddings method in thread pool
            loop = asyncio.get_event_loop()
            vectors = await loop.run_in_executor(
                None,
                lambda: embedding_model.get_embeddings(batch_texts)
            )
            return np.array(vectors)
        except Exception as e:
            logger.error(f"Batch vectorization failed: {e}", exc_info=True)
            # Return zero vectors as fallback
            return np.zeros((len(batch_texts), embedding_model.embedding_dim))
    
    # Concurrent processing of all batches
    tasks = [vectorize_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Merge results
    all_vectors = []
    for i, result in enumerate(batch_results):
        if isinstance(result, Exception):
            logger.error(f"Batch {i} processing failed: {result}")
            batch_size_actual = len(batches[i])
            zero_vector = np.zeros((batch_size_actual, embedding_model.embedding_dim))
            all_vectors.append(zero_vector)
        else:
            all_vectors.append(result)
    
    if all_vectors:
        vectors = np.vstack(all_vectors)
        logger.info(f"Async vectorization completed, vector shape: {vectors.shape}")
        return vectors
    else:
        logger.error("All batches failed")
        return np.zeros((len(texts), embedding_model.embedding_dim))


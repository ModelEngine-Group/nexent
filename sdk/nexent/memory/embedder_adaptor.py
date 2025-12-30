from typing import Literal, Optional, Union
from mem0.embeddings.base import EmbeddingBase
from nexent.core.models.embedding_model import OpenAICompatibleEmbedding
from mem0.configs.embeddings.base import BaseEmbedderConfig


class EmbedderAdaptor(EmbeddingBase):
    """
    EmbedderAdaptor is a class that adapts the OpenAICompatibleEmbedding to Mem0 embedders.
    """

    def __init__(self, config: Optional[Union[BaseEmbedderConfig, dict]] = None):
        if isinstance(config, dict):
            config = BaseEmbedderConfig(**config)

        super().__init__(config)

        self._embedder = OpenAICompatibleEmbedding(
            model_name=self.config.model,
            base_url=self.config.openai_base_url,
            api_key=self.config.api_key,
            embedding_dim=self.config.embedding_dims,
            ssl_verify=getattr(self.config, "ssl_verify", True),
        )

    def embed(
        self,
        text: str | list[str],
        memory_action: Optional[Literal["add", "search", "update"]] = None,
    ) -> list[float] | list[list[float]]:
        """生成文本或批量文本的向量表示。

        Parameters
        ----------
        text : str | List[str]
            待向量化的文本；当传入批量文本 List[str] 时，将返回同样长度的向量列表。
        memory_action : Literal["add", "search", "update"], optional
            仅为兼容 mem0 接口，当前实现不会区分不同动作。

        Returns
        -------
        List[float] | List[List[float]]
            单文本时返回一个向量，批量文本时返回向量列表。
        """
        if isinstance(text, str):
            # follow mem0 logic
            cleaned_text = text.replace("\n", " ")
            vectors = self._embedder.get_embeddings(cleaned_text)
            return vectors[0]
        elif isinstance(text, list):
            # follow mem0 logic
            cleaned_batch = [t.replace("\n", " ") for t in text]
            vectors = self._embedder.get_embeddings(cleaned_batch)
            return vectors


import logging
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

from ..utils.observer import MessageObserver
from .openai_llm import OpenAIModel
from .restful_llm import RestfulLLMModel

logger = logging.getLogger("model_factory")


class BaseModelFactory(ABC):
    """Base model factory class""" 
    
    @abstractmethod
    def create_model(self, 
                    observer: MessageObserver,
                    model_config: Dict[str, Any],
                    **kwargs) -> Any:
        """
        Create model instance
        
        Args:
            observer: Message observer
            model_config: Model configuration information
            **kwargs: Other parameters
            
        Returns:
            Model instance
        """
        pass


class OpenAIModelFactory(BaseModelFactory):
    """OpenAI compatible model factory"""
    
    def create_model(self, 
                    observer: MessageObserver,
                    model_config: Dict[str, Any],
                    **kwargs) -> OpenAIModel:
        """
        Create OpenAI compatible model instance
        
        Args:
            observer: Message observer
            model_config: Model configuration information
            **kwargs: Other parameters
            
        Returns:
            OpenAIModel instance
        """
        return OpenAIModel(
            observer=observer,
            model_id=model_config.get("model_name", ""),
            api_key=model_config.get("api_key", ""),
            api_base=model_config.get("base_url", ""),
            temperature=model_config.get("temperature", 0.2),
            top_p=model_config.get("top_p", 0.95),
            **kwargs
        )


class RestfulLLMModelFactory(BaseModelFactory):
    """RESTful LLM model factory"""
    
    def create_model(self, 
                    observer: MessageObserver,
                    model_config: Dict[str, Any],
                    **kwargs) -> RestfulLLMModel:
        """
        Create RESTful LLM model instance
        
        Args:
            observer: Message observer
            model_config: Model configuration information
            **kwargs: Other parameters
            
        Returns:
            RestfulLLMModel instance
        """
        return RestfulLLMModel(
            observer=observer,
            base_url=model_config.get("base_url", ""),
            api_key=model_config.get("api_key", ""),
            model_name=model_config.get("model_name", "qwen"),
            temperature=model_config.get("temperature", 0.2),
            top_p=model_config.get("top_p", 0.95),
            timeout=model_config.get("timeout", 60),
            **kwargs
        )


class ModelFactoryManager:
    """Model factory manager"""
    def __init__(self):
        self._factories = {
            "openai": OpenAIModelFactory(),
            "restful": RestfulLLMModelFactory(),
        }
    
    def register_factory(self, factory_name: str, factory: BaseModelFactory):
        self._factories[factory_name] = factory
        logger.info(f"Registered model factory: {factory_name}")
    
    def create_model(self, observer: MessageObserver, model_config: Dict[str, Any], **kwargs) -> Any:
        """
        Create model instance according to configuration
        
        Args:
            observer: Message observer
            model_config: Model configuration information
            **kwargs: Other parameters
            
        Returns:
            Model instance
            
        Raises:
            ValueError: When unsupported model factory type
        """
        factory_name = model_config.get("model_factory", "openai")
        
        if factory_name not in self._factories:
            raise ValueError(f"Unsupported model factory: {factory_name}. "
                           f"Supported factories: {list(self._factories.keys())}")
        
        factory = self._factories[factory_name]
        return factory.create_model(observer, model_config, **kwargs)
    
    def get_supported_factories(self):
        return list(self._factories.keys())

# Global model factory manager instance
model_factory_manager = ModelFactoryManager()

def create_model_from_config(observer: MessageObserver, model_config: Dict[str, Any], **kwargs) -> Any:
    return model_factory_manager.create_model(observer, model_config, **kwargs)

def register_custom_factory(factory_name: str, factory: BaseModelFactory):
    model_factory_manager.register_factory(factory_name, factory) 
import logging
import threading
import json
import requests
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

from smolagents import Tool
from smolagents.models import ChatMessage

from ..utils.observer import MessageObserver, ProcessType

logger = logging.getLogger("restful_llm")

class RestfulLLMModel:
    def __init__(self, 
                 observer: MessageObserver, 
                 base_url: str,
                 api_key: str,
                 model_name: str = "qwen",
                 temperature: float = 0.2, 
                 top_p: float = 0.95,
                 timeout: int = 60,
                 *args, **kwargs):
        """
        初始化RESTful LLM模型
        
        Args:
            observer: 消息观察者，用于处理流式输出
            base_url: API基础URL
            api_key: API密钥，将作为Bearer Token使用
            model_name: 模型名称
            temperature: 温度参数
            top_p: top_p参数
            timeout: 请求超时时间
        """
        self.observer = observer
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.stop_event = threading.Event()
        
        # 设置请求头
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def __call__(self, 
                 messages: List[Dict[str, Any]], 
                 stop_sequences: Optional[List[str]] = None,
                 grammar: Optional[str] = None, 
                 tools_to_call_from: Optional[List[Tool]] = None, 
                 **kwargs) -> ChatMessage:
        """
        调用RESTful LLM模型
        
        Args:
            messages: 消息列表
            stop_sequences: 停止序列
            grammar: 语法规则
            tools_to_call_from: 可用工具列表
            **kwargs: 其他参数
            
        Returns:
            ChatMessage: 模型响应消息
        """
        try:
            # 准备请求体
            request_body = {
                "model": self.model_name,
                "stream": True,
                "messages": messages,
                "temperature": self.temperature,
                "top_p": self.top_p,
                **kwargs
            }
            
            # 添加停止序列（如果支持）
            if stop_sequences:
                request_body["stop"] = stop_sequences
            
            # 发送流式请求
            response = requests.post(
                urljoin(self.base_url, "/chat/completions"),
                headers=self.headers,
                json=request_body,
                stream=True,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                raise Exception(f"API请求失败: {response.status_code} - {response.text}")
            
            chunk_list = []
            token_join = []
            role = None
            
            # 重置输出模式
            self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING
            
            # 处理流式响应
            for line in response.iter_lines():
                if self.stop_event.is_set():
                    raise RuntimeError("Model is interrupted by stop event")
                
                if line:
                    # 移除 "data: " 前缀（如果存在）
                    line_str = line.decode('utf-8')
                    if line_str.startswith("data: "):
                        line_str = line_str[6:]
                    
                    # 跳过 [DONE] 标记
                    if line_str.strip() == "[DONE]":
                        break
                    
                    try:
                        chunk_data = json.loads(line_str)
                        if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                            choice = chunk_data["choices"][0]
                            
                            # 处理增量内容
                            if "delta" in choice:
                                delta = choice["delta"]
                                if "content" in delta and delta["content"]:
                                    new_token = delta["content"]
                                    self.observer.add_model_new_token(new_token)
                                    token_join.append(new_token)
                                
                                if "role" in delta and delta["role"]:
                                    role = delta["role"]
                            
                            chunk_list.append(chunk_data)
                    except json.JSONDecodeError:
                        logger.warning(f"无法解析JSON响应: {line_str}")
                        continue
            
            # 发送结束标记
            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)
            
            # 创建响应消息
            message = ChatMessage(
                role=role if role else "assistant",
                content=model_output
            )
            
            message.raw = chunk_list
            return message
            
        except Exception as e:
            if "context_length_exceeded" in str(e) or "token" in str(e).lower():
                raise ValueError(f"Token limit exceeded: {str(e)}")
            raise e

    def check_connectivity(self) -> bool:
        """
        测试与RESTful LLM服务的连接是否正常
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        try:
            # 构造简单的测试消息
            test_message = [{"role": "user", "content": "Hello"}]
            
            # 发送非流式请求进行连接测试
            request_body = {
                "model": self.model_name,
                "stream": False,
                "messages": test_message,
                "max_tokens": 5
            }
            
            response = requests.post(
                urljoin(self.base_url, "/chat/completions"),
                headers=self.headers,
                json=request_body,
                timeout=10
            )
            
            if response.status_code == 200:
                return True
            else:
                logger.error(f"连接测试失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"连接测试失败: {str(e)}")
            return False

    def stop(self):
        """
        停止模型运行
        """
        self.stop_event.set() 
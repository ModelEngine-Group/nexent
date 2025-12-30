from smolagents.models import ChatMessage
import tiktoken
import logging

from ..models import OpenAIModel
from ..utils.observer import MessageObserver

logger = logging.getLogger("openai_long_context_model")


class OpenAILongContextModel(OpenAIModel):
    """
    Long context model class, used to process large text files
    Support automatic truncation of content exceeding context limits
    """
    
    def __init__(self, observer: MessageObserver, temperature=0.5, top_p=0.95,
                 max_context_tokens=128000, truncation_strategy="start", ssl_verify: bool = True, *args, **kwargs):
        """
        Initialize the long context model
        
        Args:
            observer: Message observer
            temperature: Temperature parameter
            top_p: top_p parameter
            max_context_tokens: Maximum context token number, default is 128k
            truncation_strategy: Truncation strategy
                - "start": Only keep the beginning part
                - "middle": Keep the beginning and end parts
                - "end": Only keep the end part
            *args, **kwargs: Other parameters
        """
        super().__init__(observer=observer, temperature=temperature, top_p=top_p, ssl_verify=ssl_verify, *args, **kwargs)
        self.max_context_tokens = max_context_tokens
        if truncation_strategy not in ["start", "middle", "end"]:
            raise ValueError("truncation_strategy must be 'start', 'middle' or 'end'")
        self.truncation_strategy = truncation_strategy
        self._tokenizer = None
    
    def _get_tokenizer(self):
        """Get tokenizer, used to calculate token number"""
        if self._tokenizer is None:
            try:
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                # If there is no tiktoken, use simple character count estimation
                self._tokenizer = None
        return self._tokenizer
    
    def count_tokens(self, text: str) -> int:
        """
        Calculate the token number of the text
        
        Args:
            text: The text to calculate
            
        Returns:
            int: token number
        """
        tokenizer = self._get_tokenizer()
        if tokenizer:
            token_count = len(tokenizer.encode(text))
            logger.debug(f"Token count using tiktoken: {token_count} tokens for text length {len(text)}")
            return token_count
        else:
            # Simple character count estimation (approximately 4 characters = 1 token)
            estimated_tokens = len(text) // 4
            logger.debug(f"Token count using estimation: {estimated_tokens} tokens for text length {len(text)} (4 chars ≈ 1 token)")
            return estimated_tokens
    
    def truncate_text(self, text: str, max_tokens: int) -> str:
        """
        Truncate the text to the specified token number
        
        Args:
            text: The text to truncate
            max_tokens: Maximum token number
            
        Returns:
            str: Truncated text
        """
        original_tokens = self.count_tokens(text)
        logger.info(f"Starting text truncation: original_tokens={original_tokens}, max_tokens={max_tokens}, strategy={self.truncation_strategy}, text_length={len(text)}")
        
        if original_tokens <= max_tokens:
            return text

        tokenizer = self._get_tokenizer()
        
        if tokenizer:
            logger.debug("Using tiktoken tokenizer for precise truncation")
            # Use tiktoken for precise truncation
            tokens = tokenizer.encode(text)
            if len(tokens) <= max_tokens:
                logger.debug(f"Token count within limit after encoding: {len(tokens)} <= {max_tokens}")
                return text
            
            if self.truncation_strategy == "start":
                # Only keep the beginning part
                logger.info(f"Truncating with 'start' strategy: keeping first {max_tokens} tokens")
                truncated_tokens = tokens[:max_tokens]
                truncated_text = tokenizer.decode(truncated_tokens)
            elif self.truncation_strategy == "middle":
                # Keep the beginning and end,
                half_tokens = max_tokens // 2
                start_tokens = tokens[:half_tokens]
                end_tokens = tokens[-(max_tokens - half_tokens):]
                truncated_tokens = start_tokens + end_tokens
                truncated_text = tokenizer.decode(truncated_tokens)
            else:
                # Only keep the end part
                logger.info(f"Truncating with 'end' strategy: keeping last {max_tokens} tokens")
                truncated_tokens = tokens[-max_tokens:]
                truncated_text = tokenizer.decode(truncated_tokens)
        else:
            logger.warning("tiktoken not available, using character count estimation for truncation")
            # Use character count for estimation truncation
            estimated_chars = max_tokens * 4
            if len(text) <= estimated_chars:
                logger.debug(f"Text length within estimated limit: {len(text)} <= {estimated_chars} chars")
                return text
            
            if self.truncation_strategy == "start":
                # Only keep the beginning part
                truncated_text = text[:estimated_chars]
            elif self.truncation_strategy == "middle":
                # Keep the beginning and end
                half_chars = estimated_chars // 2
                start_text = text[:half_chars]
                end_text = text[-(estimated_chars - half_chars):]
                truncated_text = start_text + "\n\n[Content truncated...]\n\n" + end_text
            else:  # end
                # Only keep the end part
                truncated_text = text[-estimated_chars:]

        # Calculate retention percentage (integer only)
        retention_percentage = int((len(truncated_text) / len(text)) * 100)
        logger.info(f"Truncation completed: {len(text)} -> {len(truncated_text)} characters, retained {retention_percentage}% of original content")
        return truncated_text
    
    def prepare_long_text_message(self, text_content: str, system_prompt: str, user_prompt: str):
        """
        Prepare the message format containing long text, automatically handle truncation
        
        Args:
            text_content: Text content
            system_prompt: System prompt
            user_prompt: User prompt
            
        Returns:
            tuple[List[Dict[str, Any]], str]: Prepared message list and truncation percentage string
        """
        logger.info("Preparing long text message with automatic truncation")
        
        # Calculate the token number of the system prompt and user prompt
        system_tokens = self.count_tokens(system_prompt)
        user_prompt_tokens = self.count_tokens(user_prompt)
        content_tokens = self.count_tokens(text_content)
        
        logger.info(f"Token breakdown: system={system_tokens}, user_prompt={user_prompt_tokens}, content={content_tokens}, max_context={self.max_context_tokens}")
        logger.debug(f"Text lengths: system={len(system_prompt)}, user_prompt={len(user_prompt)}, content={len(text_content)}")
        
        # Reserve tokens for text content
        available_tokens = self.max_context_tokens - system_tokens - user_prompt_tokens - 100  # Reserve 100 tokens as buffer
        
        # Check if there are sufficient tokens available
        if available_tokens <= 0:
            error_msg = f"Insufficient tokens available. Required: {system_tokens + user_prompt_tokens + 100}, Available: {self.max_context_tokens}, Shortage: {abs(available_tokens)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Truncate the text content
        truncated_text = self.truncate_text(text_content, available_tokens)
        final_content_tokens = self.count_tokens(truncated_text)
        logger.info(f"Content truncation result: {content_tokens} -> {final_content_tokens} tokens")
        
        # Calculate truncation percentage
        truncation_percentage = int((final_content_tokens / content_tokens) * 100) if content_tokens > 0 else 100
        
        # Build messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_prompt}\n\n{truncated_text}"}
        ]
        
        total_message_tokens = system_tokens + user_prompt_tokens + final_content_tokens
        logger.info(f"Message preparation completed: total_tokens={total_message_tokens}, messages_count={len(messages)}, truncation_percentage={truncation_percentage}%")
        
        return messages, str(truncation_percentage)

    def analyze_long_text(self, text_content: str, system_prompt: str, user_prompt: str) -> tuple[ChatMessage, str]:
        """
        Analyze the long text content

        Args:
            text_content: Text content
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            tuple[ChatMessage, str]: Model returned message and truncation percentage string
        """
        logger.info("Starting long text analysis")
        logger.debug(f"Input parameters: content_length={len(text_content)}, system_prompt_length={len(system_prompt)}, user_prompt_length={len(user_prompt)}")
        
        try:
            messages, truncation_percentage = self.prepare_long_text_message(text_content, system_prompt, user_prompt)
            logger.info("Messages prepared successfully, calling model for analysis")
            
            result = self(messages=messages)
            logger.info("Long text analysis completed successfully")
            return result, truncation_percentage
            
        except Exception as e:
            logger.error(f"Error during long text analysis: {str(e)}")
            raise

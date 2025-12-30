import base64
import os
from typing import List, Dict, Any, Union, BinaryIO

from smolagents.models import ChatMessage

from ..models import OpenAIModel
from ..utils.observer import MessageObserver


class OpenAIVLModel(OpenAIModel):
    def __init__(
        self,
        observer: MessageObserver,
        temperature: float = 0.7,
        top_p: float = 0.7,
        frequency_penalty: float = 0.5,
        max_tokens: int = 512,
        ssl_verify: bool = True,
        *args,
        **kwargs,
    ):
        """
        Initialize VLM model. Accepts `ssl_verify` and forwards it to parent.
        """
        super().__init__(observer=observer, ssl_verify=ssl_verify, *args, **kwargs)
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.max_tokens = max_tokens
        self._current_request = None  # Used to store the current request

    async def check_connectivity(self) -> bool:
        """
        Check the connectivity of the VLM model.

        Returns:
            bool: Returns True if the model can respond normally, otherwise returns False.
        """
        try:
            # Directly reuse the parent class's check_connectivity method
            return await super().check_connectivity()
        except Exception as e:
            import logging
            logging.error(f"VLM connectivity check failed: {str(e)}")
            return False

    def encode_image(self, image_input: Union[str, BinaryIO]) -> str:
        """
        Encode an image file or file stream into a base64 string.

        Args:
            image_input: Image file path or file stream object.

        Returns:
            str: Base64 encoded image data.
        """
        if isinstance(image_input, str):
            with open(image_input, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        else:
            # For file stream objects, read directly
            return base64.b64encode(image_input.read()).decode('utf-8')

    def prepare_image_message(self, image_input: Union[str, BinaryIO], system_prompt: str = "Describe this picture.") -> \
    List[Dict[str, Any]]:
        """
        Prepare a message format containing an image.

        Args:
            image_input: Image file path or file stream object.
            system_prompt: System prompt.

        Returns:
            List[Dict[str, Any]]: Prepared message list.
        """
        base64_image = self.encode_image(image_input)

        # Detect image format
        image_format = "jpeg"  # Default format
        if isinstance(image_input, str) and os.path.exists(image_input):
            _, ext = os.path.splitext(image_input)
            if ext.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                image_format = ext.lower()[1:]  # Remove the dot
                if image_format == 'jpg':
                    image_format = 'jpeg'

        messages = [{"role": "system", "content": [{"text": system_prompt, "type": "text"}]}, {"role": "user",
            "content": [{"type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "auto"}}]}]

        return messages

    def analyze_image(self, image_input: Union[str, BinaryIO],
            system_prompt: str = "Please describe this picture concisely and carefully, within 200 words.", stream: bool = True,
            **kwargs) -> ChatMessage:
        """
        Analyze image content.

        Args:
            image_input: Image file path or file stream object.
            system_prompt: System prompt.
            stream: Whether to output in streaming mode.
            **kwargs: Other parameters.

        Returns:
            ChatMessage: Message returned by the model.
        """
        messages = self.prepare_image_message(image_input, system_prompt)
        return self(messages=messages, **kwargs)

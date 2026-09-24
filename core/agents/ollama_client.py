# core/agents/ollama_client.py

import requests
from typing import Any


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        think: bool = False,
        timeout: int = 300
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.think = think
        self.timeout = timeout

    def chat(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        num_ctx: int = 8192,
        num_predict: int | None = None,
        format_schema: dict[str, Any] | None = None,
        seed: int | None = None,
        num_gpu: int | None = None,
        num_thread: int | None = None,
    ) -> str:

        messages = []

        if system:
            messages.append({
                "role": "system",
                "content": system
            })

        messages.append({
            "role": "user",
            "content": prompt
        })

        options = {
            "temperature": temperature,
            "num_ctx": num_ctx,
        }
        if num_predict is not None:
            options["num_predict"] = num_predict
        if seed is not None:
            options["seed"] = seed
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        if num_thread is not None:
            options["num_thread"] = num_thread

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "keep_alive": "30m",
            "options": options,
        }
        if format_schema is not None:
            payload["format"] = format_schema

        response = requests.post(
            f"{self.host}/api/chat",
            json=payload,
            timeout=self.timeout
        )

        response.raise_for_status()

        data = response.json()

        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama retornou uma resposta vazia.")
        return content.strip()

    def is_alive(self) -> bool:
        try:
            response = requests.get(
                f"{self.host}/api/tags",
                timeout=5
            )

            return response.ok

        except requests.RequestException:
            return False

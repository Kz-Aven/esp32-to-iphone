"""Minimal client for any OpenAI-compatible chat endpoint (vision models)."""

import base64
import json
import os

import httpx

TOKEN_PARAMS = ("max_tokens", "max_completion_tokens")


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str = "", extra: dict | None = None,
                 token_param: str = "auto"):
        self.model, self.extra = model, extra or {}
        # "auto": send max_tokens; switch for good if the server asks for max_completion_tokens (newer OpenAI models)
        self.token_param, self._auto = (token_param, False) if token_param in TOKEN_PARAMS else ("max_tokens", True)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=120)

    @classmethod
    def from_env(cls, role: str) -> "LLM":
        """ROLE_* variables (e.g. ACTOR_MODEL) override the shared LLM_* ones."""
        def env(key, default=""):
            return os.environ.get(f"{role}_{key}") or os.environ.get(f"LLM_{key}", default)
        return cls(env("BASE_URL", "http://localhost:8000/v1"), env("MODEL"),
                   env("API_KEY"), json.loads(env("EXTRA_BODY", "{}")), env("TOKEN_PARAM", "auto"))

    async def chat(self, system: str, text: str, image: bytes | None = None,
                   max_tokens: int = 600, temperature: float = 0) -> str:
        content = [{"type": "text", "text": text}]
        if image:
            url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
            content.insert(0, {"type": "image_url", "image_url": {"url": url}})
        body = {"model": self.model, "temperature": temperature, **self.extra,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        r = await self._http.post("/chat/completions", json={self.token_param: max_tokens, **body})
        if r.status_code == 400 and self._auto and "max_completion_tokens" in r.text:
            self.token_param, self._auto = "max_completion_tokens", False
            r = await self._http.post("/chat/completions", json={self.token_param: max_tokens, **body})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

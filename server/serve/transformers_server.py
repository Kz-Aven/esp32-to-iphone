"""Minimal OpenAI-compatible server for a Hugging Face vision-language model (e.g. DiffusionGemma).

Only what the agent needs: POST /v1/chat/completions with text and base64 image_url parts, GET /v1/models.
Env: MODEL_ID (repo id or path), MODEL_NAME (id reported to clients), PORT (8000),
     IMAGE_TOKENS (visual token budget; DiffusionGemma supports 70/140/280/560/1120).
"""

import asyncio
import base64
import io
import os
import re
import time

import torch
import transformers
import uvicorn
from fastapi import FastAPI
from PIL import Image

MODEL_ID = os.environ.get("MODEL_ID", "google/diffusiongemma-26B-A4B-it")
MODEL_NAME = os.environ.get("MODEL_NAME", MODEL_ID.rsplit("/", 1)[-1])
IMAGE_TOKENS = int(os.environ.get("IMAGE_TOKENS", "280"))

processor = transformers.AutoProcessor.from_pretrained(MODEL_ID)
if IMAGE_TOKENS and hasattr(processor, "image_processor"):
    processor.image_processor.max_soft_tokens = processor.image_processor.image_seq_length = IMAGE_TOKENS
    processor.image_seq_length = IMAGE_TOKENS
config = transformers.AutoConfig.from_pretrained(MODEL_ID)
model_class = getattr(transformers, config.architectures[0], transformers.AutoModelForImageTextToText)
model = model_class.from_pretrained(MODEL_ID, dtype="auto", device_map="auto").eval()

app = FastAPI()
lock = asyncio.Lock()  # one generation at a time


def to_parts(content) -> list[dict]:
    """OpenAI message content -> transformers chat parts (images first, as the model prefers)."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    parts = []
    for p in content:
        if p["type"] == "text":
            parts.append({"type": "text", "text": p["text"]})
        elif p["type"] == "image_url":
            data = base64.b64decode(p["image_url"]["url"].split(",", 1)[1])
            parts.insert(0, {"type": "image", "image": Image.open(io.BytesIO(data)).convert("RGB")})
    return parts


def generate(messages: list[dict], max_tokens: int) -> str:
    chat = [{"role": m["role"], "content": to_parts(m["content"])} for m in messages]
    inputs = processor.apply_chat_template(chat, tokenize=True, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt").to(model.device)
    prompt = inputs["input_ids"][0]
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_tokens)[0]
    out = out.reshape(-1)
    if len(out) > len(prompt) and torch.equal(out[:len(prompt)], prompt):  # the output echoes the prompt
        out = out[len(prompt):]
    text = processor.decode(out).rsplit("<channel|>", 1)[-1]  # drop an (empty) thinking channel
    return re.sub(r"<\|?[a-z_]+\|?>", "", text).strip()  # and special tokens such as <turn|> <eos> <pad>


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
async def chat(body: dict):
    async with lock:
        text = await asyncio.to_thread(generate, body["messages"], int(body.get("max_tokens") or 512))
    return {"id": f"chatcmpl-{time.time_ns()}", "object": "chat.completion", "created": int(time.time()),
            "model": MODEL_NAME, "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": text}}]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))

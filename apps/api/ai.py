import json
import re

import httpx

from config import settings


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return text


async def chat(prompt: str, system: str | None = None) -> str:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={"model": settings.ollama_model, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def chat_json(prompt: str, system: str | None = None) -> dict:
    base_system = system or "You are a precise analyst. Output valid JSON only."
    json_system = f"{base_system}\nRespond with valid JSON only. No markdown fences, no prose outside JSON."

    last_error: json.JSONDecodeError | None = None
    for attempt in range(2):
        attempt_system = json_system
        if attempt == 1:
            attempt_system += "\nYour previous response was not valid JSON. Return ONLY a JSON object."

        messages: list[dict[str, str]] = [
            {"role": "system", "content": attempt_system},
            {"role": "user", "content": prompt},
        ]

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            raw = response.json()["message"]["content"]

        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError as exc:
            last_error = exc

    raise ValueError(f"Model did not return valid JSON: {last_error}")

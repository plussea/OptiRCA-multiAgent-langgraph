"""Smoke test: verify the project's .env can talk to DeepSeek.

Replicates the wiring used in src/optirc/core/llm_client.py:
- pydantic_settings loads .env
- AsyncOpenAI client pointed at settings.llm_base_url with settings.openrouter_api_key
- Two probes: plain text, and JSON-shaped response (DeepSeek has no
  response_format:json_object, so we parse manually — same as llm_client.py)
"""

import asyncio
import json
import os
import sys

# Load .env via pydantic_settings (same way src/optirc/core/config.py does)
from pydantic_settings import BaseSettings, SettingsConfigDict


class S(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    openrouter_api_key: str = ""
    llm_backup_model: str = ""
    llm_backup_base_url: str = ""
    llm_backup_api_key: str = ""


s = S()
print("=== Loaded .env ===")
print(" provider =", s.llm_provider)
print(" model    =", s.llm_model)
print(" base_url =", s.llm_base_url)
print(" key set  =", bool(s.openrouter_api_key), f"(len={len(s.openrouter_api_key)})")
print(" backup_model =", s.llm_backup_model)
print(" backup_base  =", s.llm_backup_base_url)
print(" backup_key   =", bool(s.llm_backup_api_key))
print()

from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url=s.llm_base_url,
    api_key=s.openrouter_api_key,
    timeout=30.0,
)


async def probe_text():
    print("=== Probe 1: generate_text ===")
    try:
        r = await client.chat.completions.create(
            model=s.llm_model,
            messages=[
                {"role": "system", "content": "Reply in one short sentence."},
                {"role": "user", "content": "用中文说你好，并告诉我 2+2 等于几。"},
            ],
            temperature=0.0,
        )
        print("OK  content =", repr(r.choices[0].message.content))
        return True
    except Exception as e:
        print("FAIL", type(e).__name__, "-", e)
        return False


async def probe_json():
    print()
    print("=== Probe 2: generate_json (manual parse path) ===")
    try:
        r = await client.chat.completions.create(
            model=s.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. "
                        "IMPORTANT: You must respond with valid JSON only. "
                        "No markdown, no explanations, just raw JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": 'Return a JSON object: {"answer": "<capital of France>", "number": 42}',
                },
            ],
            temperature=0.0,
        )
        content = (r.choices[0].message.content or "").strip()
        # Strip markdown fence if DeepSeek wrapped it
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        parsed = json.loads(content)
        print("OK  parsed  =", parsed)
        return True
    except Exception as e:
        print("FAIL", type(e).__name__, "-", e)
        return False


async def main():
    ok1 = await probe_text()
    ok2 = await probe_json()
    print()
    print("=== Summary ===")
    print(" text :", "PASS" if ok1 else "FAIL")
    print(" json :", "PASS" if ok2 else "FAIL")
    sys.exit(0 if (ok1 and ok2) else 1)


asyncio.run(main())

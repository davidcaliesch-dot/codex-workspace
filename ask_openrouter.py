#!/usr/bin/env python3
"""Send a text prompt and explicitly named text files to OpenRouter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_FILE_BYTES = 1_000_000
DEFAULT_ALIASES = {
    "gpt": "openai/gpt-5.6-sol",
    "claude": "anthropic/claude-sonnet-5",
    "gemini": "google/gemini-3.5-flash-lite",
    "grok": "x-ai/grok-4.1-fast",
    "deepseek": "deepseek/deepseek-v3.2",
    "cheap": "google/gemini-3.5-flash-lite",
}


def aliases() -> dict[str, str]:
    return {
        name: os.environ.get(f"ASK_MODEL_{name.upper()}", model)
        for name, model in DEFAULT_ALIASES.items()
    }


def read_text_file(raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes: {path}")
    data = path.read_bytes()
    if b"\x00" in data:
        raise ValueError(f"binary file is not supported: {path}")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not UTF-8 text: {path}") from exc
    return f"\n\n--- FILE: {path.name} ---\n{content}\n--- END FILE ---"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", help="alias or OpenRouter model slug")
    parser.add_argument("--prompt", help="question for the external model")
    parser.add_argument("--file", action="append", default=[], help="UTF-8 text file; repeatable")
    parser.add_argument("--system", default="Answer the user's request directly and critically.")
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--list-aliases", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_aliases = aliases()
    if args.list_aliases:
        print(json.dumps(model_aliases, indent=2, sort_keys=True))
        return 0
    if not args.model or not args.prompt:
        print("error: MODEL and --prompt are required", file=sys.stderr)
        return 2
    if not 1 <= args.max_tokens <= 16000:
        print("error: --max-tokens must be between 1 and 16000", file=sys.stderr)
        return 2
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("error: OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    model = model_aliases.get(args.model.lower(), args.model)
    try:
        content = args.prompt + "".join(read_text_file(path) for path in args.file)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": content},
        ],
        "max_tokens": args.max_tokens,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://chatgpt.com/",
            "X-Title": "ChatGPT Ask Skill",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        print(f"OpenRouter HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"OpenRouter request failed: {exc}", file=sys.stderr)
        return 1
    try:
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("error: unexpected OpenRouter response", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

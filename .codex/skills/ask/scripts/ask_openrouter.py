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


class ResponseError(ValueError):
    """An OpenRouter response did not contain a usable answer."""


def _error_summary(error: object) -> str | None:
    """Return a safe, compact summary without serializing arbitrary metadata."""
    if isinstance(error, str) and error.strip():
        return error.strip()
    if not isinstance(error, dict):
        return None

    details = []
    code = error.get("code")
    message = error.get("message")
    if isinstance(code, (str, int)):
        details.append(f"code={code}")
    if isinstance(message, str) and message.strip():
        details.append(f"message={message.strip()}")
    return ", ".join(details) or None


def _message_text(content: object) -> str | None:
    """Extract text from either string or structured message content."""
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None

    parts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            parts.append(text)
    answer = "".join(parts)
    return answer if answer.strip() else None


def extract_answer(result: object) -> str:
    """Validate a chat completion and return its non-empty text answer."""
    if not isinstance(result, dict):
        raise ResponseError("response body is not a JSON object")

    top_error = _error_summary(result.get("error"))
    if top_error:
        raise ResponseError(f"OpenRouter error: {top_error}")

    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ResponseError("response has no choices")

    diagnostics = []
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            diagnostics.append(f"choice {index}: invalid object")
            continue

        choice_error = _error_summary(choice.get("error"))
        finish_reason = choice.get("finish_reason")
        native_reason = choice.get("native_finish_reason")
        reason = finish_reason if isinstance(finish_reason, str) else "missing"
        if isinstance(native_reason, str) and native_reason != finish_reason:
            reason += f" (native: {native_reason})"

        message = choice.get("message")
        if isinstance(message, dict):
            answer = _message_text(message.get("content"))
            if answer is not None:
                return answer
            message_error = _error_summary(message.get("error"))
        else:
            message_error = None

        error = choice_error or message_error
        detail = f"choice {index}: empty message.content; finish_reason={reason}"
        if error:
            detail += f"; error={error}"
        diagnostics.append(detail)

    raise ResponseError("; ".join(diagnostics))


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
        answer = extract_answer(result)
    except ResponseError as exc:
        print(f"error: unexpected OpenRouter response: {exc}", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

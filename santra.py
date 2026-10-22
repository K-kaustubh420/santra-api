#!/usr/bin/env python3
"""
Santra – single-file browser-automation API for ChatGPT / Claude / Grok / Gemini.
Accepts text + files, drives a real browser session, scrapes the reply, returns it.
Optional official-API fallback when scraping fails.

Usage:
  pip install fastapi uvicorn playwright python-dotenv httpx python-multipart
  playwright install chromium
  python santra.py

API:
  POST /v1/chat          – main endpoint (JSON or multipart)
  GET  /health
  GET  /providers
  POST /v1/login/{provider} – open headed browser so you can log in once
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from playwright.async_api import (
    BrowserContext,
    Page,
    async_playwright,
    TimeoutError as PlaywrightTimeout,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = os.getenv("SANTRA_HOST", "0.0.0.0")
PORT = int(os.getenv("SANTRA_PORT", "8765"))
HEADLESS = os.getenv("SANTRA_HEADLESS", "false").lower() in ("1", "true", "yes")
PROFILE_ROOT = Path(os.getenv("SANTRA_BROWSER_PROFILE_DIR", "./santra_profiles")).resolve()
DEFAULT_PROVIDER = os.getenv("SANTRA_DEFAULT_PROVIDER", "chatgpt").lower()
RESPONSE_TIMEOUT = int(os.getenv("SANTRA_RESPONSE_TIMEOUT", "180"))
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "false").lower() in ("1", "true", "yes")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("santra")

# ---------------------------------------------------------------------------
# Provider definitions (selectors are intentionally multi-fallback)
# Update these when a site redesigns; they are the only fragile part.
# ---------------------------------------------------------------------------
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "chatgpt": {
        "url": "https://chatgpt.com/",
        "new_chat_url": "https://chatgpt.com/",
        "input": [
            '#prompt-textarea',
            '[data-testid="prompt-textarea"]',
            'textarea[name="prompt-textarea"]',
            '[contenteditable="true"][data-lexical-editor="true"]',
            '[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"].ProseMirror',
        ],
        "send": [
            '[data-testid="send-button"]',
            'button[data-testid="send-button"]',
            'button[aria-label*="Send" i]',
            'button[type="submit"]',
        ],
        "stop": [
            '[data-testid="stop-button"]',
            'button[aria-label*="Stop" i]',
            'button[data-testid*="stop" i]',
        ],
        "assistant": [
            '[data-message-author-role="assistant"]',
            '[data-testid*="conversation-turn"][data-message-author-role="assistant"]',
            'article[data-testid^="conversation-turn"] .markdown',
            '[data-assistant-markdown]',
        ],
        "assistant_strict": [
            '[data-message-author-role="assistant"]',
            '[data-assistant-markdown]',
        ],
        "file_input": 'input[type="file"]',
        "file_button": [
            'button[aria-label*="Attach" i]',
            'button[aria-label*="Upload" i]',
            '[data-testid="file-upload-button"]',
        ],
    },
    "claude": {
        "url": "https://claude.ai/new",
        "new_chat_url": "https://claude.ai/new",
        "input": [
            'div[contenteditable="true"][role="textbox"]',
            'div.ProseMirror[contenteditable="true"]',
            '[data-testid="chat-input"]',
            'fieldset div[contenteditable="true"]',
        ],
        "send": [
            'button[aria-label*="Send" i]',
            'button[type="submit"]',
            'button:has(svg)',
        ],
        "stop": [
            'button[aria-label*="Stop" i]',
            'button[aria-label*="Cancel" i]',
        ],
        "assistant": [
            '[data-testid="assistant-message"]',
            'div[data-is-streaming]',
            '.font-claude-message',
            'div[class*="assistant"]',
        ],
        "assistant_strict": [
            '[data-testid="assistant-message"]',
            '.font-claude-message',
        ],
        "file_input": 'input[type="file"]',
        "file_button": [
            'button[aria-label*="Attach" i]',
            'button[aria-label*="Upload" i]',
        ],
    },
    "grok": {
        "url": "https://grok.com/",
        "new_chat_url": "https://grok.com/",
        "input": [
            'textarea[placeholder*="Ask" i]',
            'textarea[aria-label*="Ask" i]',
            'div[contenteditable="true"][role="textbox"]',
            'textarea',
        ],
        "send": [
            'button[aria-label*="Send" i]',
            'button[type="submit"]',
            'button:has(svg)',
        ],
        "stop": [
            'button[aria-label*="Stop" i]',
        ],
        "assistant": [
            '[data-testid*="message"]',
            'div[class*="message"]',
            'div[class*="response"]',
        ],
        "assistant_strict": [
            '[data-message-author-role="assistant"]',
            '[data-testid*="assistant" i]',
        ],
        "file_input": 'input[type="file"]',
        "file_button": [
            'button[aria-label*="Attach" i]',
            'button[aria-label*="Upload" i]',
        ],
    },
    "gemini": {
        "url": "https://gemini.google.com/app",
        "new_chat_url": "https://gemini.google.com/app",
        "input": [
            'div[contenteditable="true"][role="textbox"]',
            'rich-textarea div[contenteditable="true"]',
            'div.ql-editor[contenteditable="true"]',
            'textarea',
        ],
        "send": [
            'button[aria-label*="Send" i]',
            'button[aria-label*="Submit" i]',
            'button[mattooltip*="Send" i]',
        ],
        "stop": [
            'button[aria-label*="Stop" i]',
        ],
        "assistant": [
            'model-response',
            'div[class*="response"]',
            'message-content',
            'div[data-message-author-role="model"]',
        ],
        "assistant_strict": [
            'model-response',
            'div[data-message-author-role="model"]',
        ],
        "file_input": 'input[type="file"]',
        "file_button": [
            'button[aria-label*="Upload" i]',
            'button[aria-label*="Attach" i]',
        ],
    },
}

# ---------------------------------------------------------------------------
# Browser manager (one persistent context per provider)
# ---------------------------------------------------------------------------
class BrowserManager:
    def __init__(self) -> None:
        self._playwright = None
        self._contexts: Dict[str, BrowserContext] = {}
        self._pages: Dict[str, Page] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        log.info("Playwright started. Profiles at %s", PROFILE_ROOT)

    async def stop(self) -> None:
        for name, ctx in list(self._contexts.items()):
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        self._pages.clear()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        log.info("Playwright stopped")

    async def get_page(self, provider: str, force_new: bool = False) -> Page:
        async with self._lock:
            if provider not in PROVIDERS:
                raise ValueError(f"Unknown provider: {provider}")

            if provider in self._pages and not force_new:
                page = self._pages[provider]
                if not page.is_closed():
                    return page

            profile_dir = PROFILE_ROOT / provider
            profile_dir.mkdir(parents=True, exist_ok=True)

            ctx = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=HEADLESS,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                ignore_default_args=["--enable-automation"],
            )
            self._contexts[provider] = ctx

            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            self._pages[provider] = page
            return page

    async def close_provider(self, provider: str) -> None:
        async with self._lock:
            if provider in self._pages:
                try:
                    await self._pages[provider].close()
                except Exception:
                    pass
                del self._pages[provider]
            if provider in self._contexts:
                try:
                    await self._contexts[provider].close()
                except Exception:
                    pass
                del self._contexts[provider]

browser_mgr = BrowserManager()

# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------
async def find_first(page: Page, selectors: List[str], timeout: float = 8.0):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception as e:
                last_err = e
        await asyncio.sleep(0.25)
    raise PlaywrightTimeout(f"None of the selectors matched: {selectors} ({last_err})")

async def fill_prompt(page: Page, selectors: List[str], text: str) -> None:
    loc = await find_first(page, selectors, timeout=15)
    await loc.click()
    # Prefer fill for textarea; for contenteditable we set text via JS + events
    tag = await loc.evaluate("el => el.tagName.toLowerCase()")
    if tag in ("textarea", "input"):
        await loc.fill(text)
    else:
        await loc.evaluate(
            """(el, value) => {
                el.focus();
                el.innerText = value;
                el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            text,
        )

async def attach_files(page: Page, cfg: dict, file_paths: List[str]) -> None:
    if not file_paths:
        return
    # Try hidden file input first
    try:
        inp = page.locator(cfg["file_input"]).first
        if await inp.count() > 0:
            await inp.set_input_files(file_paths)
            await asyncio.sleep(1.0)
            return
    except Exception:
        pass
    # Click attach button then set files
    for sel in cfg.get("file_button", []):
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                async with page.expect_file_chooser() as fc_info:
                    await btn.click()
                chooser = await fc_info.value
                await chooser.set_files(file_paths)
                await asyncio.sleep(1.0)
                return
        except Exception:
            continue
    log.warning("Could not attach files – no suitable file control found")

async def click_send(page: Page, cfg: dict) -> None:
    loc = await find_first(page, cfg["send"], timeout=10)
    await loc.click()

async def wait_for_generation(page: Page, cfg: dict, timeout: float) -> None:
    """Wait until the stop button appears then disappears (or timeout)."""
    stop_sels = cfg.get("stop") or []
    # Give the stop button a chance to appear
    appeared = False
    end = time.time() + min(15, timeout)
    while time.time() < end:
        for sel in stop_sels:
            try:
                if await page.locator(sel).first.is_visible():
                    appeared = True
                    break
            except Exception:
                pass
        if appeared:
            break
        await asyncio.sleep(0.3)

    if not appeared:
        # Some UIs never show a stop button; fall back to stability check later
        await asyncio.sleep(2)
        return

    # Wait for stop to disappear
    deadline = time.time() + timeout
    while time.time() < deadline:
        still = False
        for sel in stop_sels:
            try:
                if await page.locator(sel).first.is_visible():
                    still = True
                    break
            except Exception:
                pass
        if not still:
            await asyncio.sleep(0.8)  # let final tokens render
            return
        await asyncio.sleep(0.4)
    log.warning("Generation wait timed out after %.0fs", timeout)

def clean_response_text(text: str) -> str:
    """Extract the latest labeled assistant reply and remove common UI noise."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    assistant_marker = re.compile(
        r"^\s*(?:chatgpt|claude|grok|gemini|assistant)(?:\s+said)?\s*:\s*",
        re.IGNORECASE,
    )
    for index in range(len(lines) - 1, -1, -1):
        match = assistant_marker.match(lines[index])
        if match:
            lines = [lines[index][match.end():], *lines[index + 1:]]
            break

    chrome_lines = {
        "skip to content",
        "open sidebar",
        "close sidebar",
        "chatgpt",
        "claude",
        "grok",
        "gemini",
        "new chat",
        "scheduled",
        "search",
        "library",
        "plugins",
        "explore gpts",
        "settings",
        "upgrade plan",
        "share",
        "go",
        "today",
        "yesterday",
        "previous 7 days",
        "previous 30 days",
    }
    footer_lines = {
        "latest response",
        "think",
        "is this conversation helpful so far?",
    }
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.casefold() in footer_lines:
            break
        if line.casefold() in chrome_lines:
            continue
        footer_match = re.search(
            r"chatgpt can make mistakes|claude can make mistakes|"
            r"gemini may display inaccurate info",
            line,
            flags=re.IGNORECASE,
        )
        if footer_match:
            line = line[:footer_match.start()].strip()
            if line:
                cleaned_lines.append(line)
            break
        line = re.sub(
            r"^(?:you said|chatgpt said|you|assistant)\s*:\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


async def scrape_last_assistant_details(page: Page, cfg: dict) -> tuple[str, str]:
    async def latest_text(selectors: List[str]) -> str:
        for sel in selectors:
            try:
                locs = page.locator(sel)
                n = await locs.count()
                for i in range(n - 1, -1, -1):
                    el = locs.nth(i)
                    if await el.is_visible():
                        text = (await el.inner_text()).strip()
                        if text:
                            return text
            except Exception:
                continue
        return ""

    # Prefer selectors that identify assistant-only message containers.
    raw_text = await latest_text(cfg.get("assistant_strict", []))
    if raw_text and clean_response_text(raw_text):
        return clean_response_text(raw_text), raw_text

    # Retain the original broader selectors for sites that redesign their DOM.
    raw_text = await latest_text(cfg["assistant"])
    if raw_text:
        cleaned = clean_response_text(raw_text)
        if cleaned:
            return cleaned, raw_text

    # Last-resort: grab the largest visible text block near the bottom.
    try:
        raw_text = await page.evaluate(
            """() => {
                const candidates = Array.from(document.querySelectorAll('div, article, section, p'))
                    .filter(el => el.offsetParent !== null && el.innerText && el.innerText.length > 40);
                candidates.sort((a,b) => b.innerText.length - a.innerText.length);
                return candidates[0] ? candidates[0].innerText.trim() : '';
            }"""
        )
        raw_text = raw_text or ""
        return clean_response_text(raw_text) or raw_text, raw_text
    except Exception:
        return "", ""


async def scrape_last_assistant(page: Page, cfg: dict) -> str:
    cleaned, _ = await scrape_last_assistant_details(page, cfg)
    return cleaned


async def _browser_chat(
    provider: str,
    prompt: str,
    file_paths: Optional[List[str]] = None,
    new_chat: bool = True,
) -> tuple[str, str]:
    cfg = PROVIDERS[provider]
    page = await browser_mgr.get_page(provider)

    if new_chat:
        await page.goto(cfg["new_chat_url"], wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(1.5)
    else:
        # Ensure we are on the right origin
        if cfg["url"].split("/")[2] not in (page.url or ""):
            await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(1.5)

    if file_paths:
        await attach_files(page, cfg, file_paths)

    await fill_prompt(page, cfg["input"], prompt)
    await asyncio.sleep(0.3)
    await click_send(page, cfg)

    await wait_for_generation(page, cfg, RESPONSE_TIMEOUT)

    last_cleaned = ""
    last_raw = ""
    stable = 0
    for _ in range(40):
        cleaned, raw = await scrape_last_assistant_details(page, cfg)
        if cleaned == last_cleaned and cleaned:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            last_cleaned = cleaned
            last_raw = raw
        await asyncio.sleep(0.6)

    return last_cleaned.strip(), last_raw.strip()


async def browser_chat(
    provider: str,
    prompt: str,
    file_paths: Optional[List[str]] = None,
    new_chat: bool = True,
) -> str:
    response, _ = await _browser_chat(provider, prompt, file_paths, new_chat)
    return response


async def browser_chat_with_raw(
    provider: str,
    prompt: str,
    file_paths: Optional[List[str]] = None,
    new_chat: bool = True,
) -> tuple[str, str]:
    return await _browser_chat(provider, prompt, file_paths, new_chat)

# ---------------------------------------------------------------------------
# Optional API fallback
# ---------------------------------------------------------------------------
async def fallback_chat(provider: str, prompt: str) -> str:
    if not FALLBACK_ENABLED:
        raise RuntimeError("Fallback disabled")

    async with httpx.AsyncClient(timeout=120) as client:
        if provider in ("chatgpt", "openai") and os.getenv("OPENAI_API_KEY"):
            r = await client.post(
                f"{os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        if provider == "claude" and os.getenv("ANTHROPIC_API_KEY"):
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

        if provider == "gemini" and os.getenv("GOOGLE_API_KEY"):
            model = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={os.getenv('GOOGLE_API_KEY')}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

        if provider == "grok" and os.getenv("XAI_API_KEY"):
            r = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"},
                json={
                    "model": os.getenv("XAI_MODEL", "grok-3"),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    raise RuntimeError(f"No fallback credentials configured for provider '{provider}'")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await browser_mgr.start()
    yield
    await browser_mgr.stop()

app = FastAPI(
    title="Santra",
    description="Browser-automation API for ChatGPT / Claude / Grok / Gemini",
    version="1.0.0",
    lifespan=lifespan,
)

class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    provider: Optional[str] = None
    new_chat: bool = True
    use_fallback: bool = True

class ChatResponse(BaseModel):
    provider: str
    response: str
    source: str  # "browser" | "fallback"
    elapsed_ms: int
    raw_response: Optional[str] = None

class ChatCompletionMessage(BaseModel):
    model_config = {"extra": "ignore"}

    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Union[str, List[Any], None] = ""

class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "ignore"}

    model: str = Field(..., min_length=1)
    messages: List[ChatCompletionMessage] = Field(..., min_length=1)
    stream: bool = False

class OpenAIChatCompletionMessage(BaseModel):
    role: Literal["assistant"]
    content: str

class OpenAIChatCompletionChoice(BaseModel):
    index: int
    message: OpenAIChatCompletionMessage
    finish_reason: Literal["stop"]

class OpenAIChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class OpenAIChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: List[OpenAIChatCompletionChoice]
    usage: OpenAIChatCompletionUsage

MODEL_PROVIDER_ALIASES = {
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "gpt": "chatgpt",
    "gpt-4": "chatgpt",
    "gpt-4o": "chatgpt",
    "gpt-4o-mini": "chatgpt",
    "claude": "claude",
    "anthropic": "claude",
    "grok": "grok",
    "xai": "grok",
    "gemini": "gemini",
    "google": "gemini",
}

def provider_for_model(model: str) -> str:
    normalized = model.strip().lower()
    model_name = normalized.rsplit("/", 1)[-1]
    provider = MODEL_PROVIDER_ALIASES.get(normalized) or MODEL_PROVIDER_ALIASES.get(model_name)
    if provider is None:
        for prefix, mapped_provider in (
            ("gpt-", "chatgpt"),
            ("claude-", "claude"),
            ("grok-", "grok"),
            ("gemini-", "gemini"),
        ):
            if model_name.startswith(prefix):
                provider = mapped_provider
                break
    if provider not in PROVIDERS:
        raise HTTPException(
            400,
            f"Unknown model '{model}'. Choose a Santra provider model: {list(PROVIDERS)}",
        )
    return provider

def message_content_text(content: Union[str, List[Any], None]) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts = []
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return "\n".join(text_parts)

def prompt_from_messages(messages: List[ChatCompletionMessage]) -> str:
    last_user_index = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].role == "user"),
        None,
    )
    if last_user_index is None:
        raise HTTPException(400, "messages must include at least one user message")

    last_user_message = message_content_text(messages[last_user_index].content)
    prior_messages = [
        message
        for message in messages[:last_user_index]
        if message.role in ("system", "user", "assistant")
        and message_content_text(message.content).strip()
    ]
    context_messages = prior_messages[-4:]
    if not context_messages:
        return last_user_message

    role_labels = {"system": "System", "user": "User", "assistant": "Assistant"}
    context = "\n\n".join(
        f"{role_labels[message.role]}:\n{message_content_text(message.content)[:1200]}"
        for message in context_messages
    )
    return f"Conversation context:\n{context}\n\nLatest user message:\n{last_user_message}"

@app.get("/health")
async def health():
    return {"status": "ok", "providers": list(PROVIDERS.keys())}

@app.get("/v1/models")
async def list_openai_models():
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": 0, "owned_by": "santra"}
            for name in PROVIDERS
        ],
    }

@app.post("/v1/chat/completions", response_model=OpenAIChatCompletionResponse)
async def openai_chat_completions(req: ChatCompletionRequest):
    provider = provider_for_model(req.model)
    result = await execute_chat(
        prompt_from_messages(req.messages),
        provider,
        True,
        True,
        [],
        allow_empty_response=True,
    )
    completion_id = f"chatcmpl-santra-{uuid.uuid4().hex}"
    created = int(time.time())
    content = result.response if isinstance(result.response, str) else ""

    if req.stream:
        chunks = [
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        sse_body = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n"
        return StreamingResponse(
            iter([sse_body]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

@app.get("/providers")
async def list_providers():
    return {
        name: {"url": cfg["url"], "has_profile": (PROFILE_ROOT / name).exists()}
        for name, cfg in PROVIDERS.items()
    }

@app.post("/v1/login/{provider}")
async def login(provider: str):
    """Open a headed browser window so the user can log in once.
    The persistent profile is kept for subsequent automation."""
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider. Choose from: {list(PROVIDERS)}")
    # Force headed for login
    global HEADLESS
    old = HEADLESS
    HEADLESS = False
    try:
        page = await browser_mgr.get_page(provider, force_new=True)
        await page.goto(PROVIDERS[provider]["url"], wait_until="domcontentloaded")
        return {
            "message": f"Browser opened for {provider}. Log in manually, then close the window or just leave it. Profile is saved at {PROFILE_ROOT / provider}",
            "profile": str(PROFILE_ROOT / provider),
        }
    finally:
        HEADLESS = old

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    prompt: Optional[str] = Form(None),
    provider: Optional[str] = Form(None),
    new_chat: bool = Form(True),
    use_fallback: bool = Form(True),
    files: List[UploadFile] = File(default=[]),
):
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = ChatRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            detail = exc.errors() if isinstance(exc, ValidationError) else str(exc)
            raise HTTPException(422, detail=detail) from exc
        prompt = body.prompt
        provider = body.provider
        new_chat = body.new_chat
        use_fallback = body.use_fallback
        files = []

    return await execute_chat(prompt, provider, new_chat, use_fallback, files)


async def execute_chat(
    prompt: Optional[str],
    provider: Optional[str],
    new_chat: bool,
    use_fallback: bool,
    files: List[UploadFile],
    allow_empty_response: bool = False,
) -> ChatResponse:
    if not prompt:
        raise HTTPException(400, "prompt is required")

    provider = (provider or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}'. Available: {list(PROVIDERS)}")

    tmp_paths: List[str] = []
    start = time.time()
    source = "browser"
    response_text = ""
    raw_response = ""

    try:
        # Save uploaded files to temp
        for uf in files or []:
            suffix = Path(uf.filename or "file").suffix
            fd, path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with open(path, "wb") as f:
                f.write(await uf.read())
            tmp_paths.append(path)

        try:
            response_text, raw_response = await browser_chat_with_raw(
                provider=provider,
                prompt=prompt,
                file_paths=tmp_paths or None,
                new_chat=new_chat,
            )
            if not allow_empty_response and (not response_text or len(response_text) < 5):
                raise RuntimeError("Scraped response empty or too short")
        except Exception as browser_err:
            log.warning("Browser path failed: %s", browser_err)
            if use_fallback and FALLBACK_ENABLED:
                log.info("Trying official API fallback for %s", provider)
                response_text = await fallback_chat(provider, prompt)
                raw_response = response_text
                source = "fallback"
            else:
                raise HTTPException(
                    502,
                    detail={
                        "error": "browser_automation_failed",
                        "message": str(browser_err),
                        "hint": "Log in via POST /v1/login/{provider} first, or enable FALLBACK_ENABLED + API keys",
                    },
                )

        elapsed = int((time.time() - start) * 1000)
        return ChatResponse(
            provider=provider,
            response=response_text,
            source=source,
            elapsed_ms=elapsed,
            raw_response=raw_response,
        )
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except Exception:
                pass

@app.post("/v1/chat/json", response_model=ChatResponse)
async def chat_json(req: ChatRequest):
    """Convenience pure-JSON endpoint (no file upload)."""
    return await execute_chat(
        req.prompt,
        req.provider,
        req.new_chat,
        req.use_fallback,
        [],
    )

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    log.info("Starting Santra on http://%s:%s  (default provider=%s, headless=%s)", HOST, PORT, DEFAULT_PROVIDER, HEADLESS)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
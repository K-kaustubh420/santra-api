"""Streamlit UI for the Santra FastAPI service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import streamlit as st
from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
PROVIDERS = ("chatgpt", "claude", "grok", "gemini")
PROVIDER_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "grok": "Grok",
    "gemini": "Gemini",
}
API_BASE = os.getenv("SANTRA_API_URL", "http://127.0.0.1:8765").rstrip("/")
KEY_SETTINGS = {
    "OPENAI_API_KEY": "OpenAI API key",
    "ANTHROPIC_API_KEY": "Anthropic API key",
    "GOOGLE_API_KEY": "Google API key",
    "XAI_API_KEY": "xAI API key",
}

st.set_page_config(page_title="Santra", page_icon="✳", layout="wide")


def read_settings() -> dict[str, str]:
    """Read .env-backed settings without exposing secret values to the UI."""
    return {key: value or "" for key, value in dotenv_values(ENV_FILE).items()}


def save_settings(values: dict[str, str]) -> None:
    ENV_FILE.touch(exist_ok=True)
    for key, value in values.items():
        set_key(str(ENV_FILE), key, value, quote_mode="auto")


def backend_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    return httpx.request(method, f"{API_BASE}{path}", timeout=30, **kwargs)


settings = read_settings()
default_provider = settings.get("SANTRA_DEFAULT_PROVIDER", "chatgpt").lower()
if default_provider not in PROVIDERS:
    default_provider = "chatgpt"
fallback_enabled = settings.get("FALLBACK_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}

st.title("✳ Santra")
st.caption("One prompt, four providers — powered by your existing browser profiles.")

with st.sidebar:
    st.subheader("Connection")
    api_base = st.text_input("API URL", value=API_BASE, help="Base URL of the Santra FastAPI server.")
    API_BASE = api_base.rstrip("/")
    st.caption(f"Server base URL: {API_BASE}")
    try:
        health_response = backend_request("GET", "/health")
        health_response.raise_for_status()
        st.success(f"API running at {API_BASE}")
    except httpx.HTTPError as exc:
        st.error(f"API unavailable: {exc}")

    st.divider()
    st.subheader("Provider login")
    login_provider = st.selectbox(
        "Open login window for",
        PROVIDERS,
        format_func=lambda name: PROVIDER_LABELS[name],
        key="login_provider",
    )
    if st.button("Open login window", width="stretch"):
        try:
            response = backend_request("POST", f"/v1/login/{login_provider}")
            response.raise_for_status()
            st.success(response.json().get("message", "Login window opened."))
        except httpx.HTTPError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            st.error(f"Could not open login window: {detail}")

    st.divider()
    with st.expander("Settings", expanded=False):
        with st.form("settings_form"):
            configured_default = st.selectbox(
                "Default provider",
                PROVIDERS,
                index=PROVIDERS.index(default_provider),
                format_func=lambda name: PROVIDER_LABELS[name],
            )
            headless = st.checkbox(
                "Run browser headless",
                value=settings.get("SANTRA_HEADLESS", "false").lower()
                in {"1", "true", "yes"},
            )
            timeout = st.number_input(
                "Response timeout (seconds)",
                min_value=10,
                max_value=900,
                value=int(settings.get("SANTRA_RESPONSE_TIMEOUT", "180")),
                step=10,
            )
            profile_dir = st.text_input(
                "Browser profile directory",
                value=settings.get("SANTRA_BROWSER_PROFILE_DIR", "./santra_profiles"),
            )
            configured_fallback = st.checkbox(
                "Enable API fallback",
                value=fallback_enabled,
                help="Also enable “Use fallback” on a chat request to permit fallback for that request.",
            )
            st.caption("Leave a key blank to keep its current value.")
            api_keys = {
                key: st.text_input(
                    label,
                    type="password",
                    value="",
                    placeholder="Configured — leave blank to keep" if settings.get(key) else "Not configured",
                )
                for key, label in KEY_SETTINGS.items()
            }
            save_config = st.form_submit_button("Save settings", width="stretch")
            if save_config:
                updates = {
                    "SANTRA_DEFAULT_PROVIDER": configured_default,
                    "SANTRA_HEADLESS": str(headless).lower(),
                    "SANTRA_RESPONSE_TIMEOUT": str(int(timeout)),
                    "SANTRA_BROWSER_PROFILE_DIR": profile_dir,
                    "FALLBACK_ENABLED": str(configured_fallback).lower(),
                }
                updates.update({key: value for key, value in api_keys.items() if value})
                save_settings(updates)
                st.success("Settings saved to .env. Restart the API server to apply them.")

st.subheader("Connect to an IDE or OpenAI-compatible tool")
with st.expander("OpenAI-compatible connection details", expanded=True):
    ide_base_url = f"{API_BASE}/v1"
    ide_api_key = "santra-local"
    selected_model = st.selectbox("Model", PROVIDERS, key="ide_model")
    st.caption("Copy these values into a tool configured for an OpenAI-compatible API.")
    st.markdown("**API base URL**")
    st.code(ide_base_url, language=None)
    st.markdown("**API key**")
    st.code(ide_api_key, language=None)
    st.markdown("**Model names**")
    st.code(", ".join(PROVIDERS), language=None)
    st.markdown("**Selected model**")
    st.code(selected_model, language=None)

    continue_config = {
        "models": [
            {
                "title": f"Santra ({selected_model})",
                "provider": "openai",
                "model": selected_model,
                "apiBase": ide_base_url,
                "apiKey": ide_api_key,
            }
        ]
    }
    st.markdown("**Example client configuration**")
    st.code(json.dumps(continue_config, indent=2), language="json")
    st.markdown("**How to add Santra in VS Code**")
    st.markdown(
        "1. Start the Santra API and sign in to the provider once using the login button.\n"
        "2. Open **Language Models** in VS Code and add a model using an OpenAI-compatible provider.\n"
        f"3. Set the API base URL to `{ide_base_url}`, API key to `{ide_api_key}`, "
        f"and model to `{selected_model}`.\n"
        "4. Save the model and select it in chat. The API key is a dummy local value; "
        "Santra accepts any bearer token."
    )
    st.markdown("**Sample request**")
    st.code(
        f'curl {API_BASE}/v1/chat/completions -H "Content-Type: application/json" '
        f'-d \'{{"model":"{selected_model}","messages":[{{"role":"user","content":"Hello"}}]}}\'',
        language="bash",
    )

st.subheader("Ask a provider")
with st.form("chat_form", clear_on_submit=False):
    provider = st.selectbox(
        "Provider",
        PROVIDERS,
        index=PROVIDERS.index(default_provider),
        format_func=lambda name: PROVIDER_LABELS[name],
    )
    prompt = st.text_area("Prompt", height=180, placeholder="What would you like to ask?")
    uploads = st.file_uploader(
        "Attach files",
        accept_multiple_files=True,
        help="Files are uploaded to the selected provider through the Santra API.",
    )
    new_chat_col, fallback_col = st.columns(2)
    with new_chat_col:
        new_chat = st.checkbox("Start a new chat", value=True)
    with fallback_col:
        use_fallback = st.checkbox(
            "Use fallback",
            value=False,
            disabled=not fallback_enabled,
            help="Enable API fallback in Settings first.",
        )
    submitted = st.form_submit_button("Send prompt", type="primary", width="stretch")

if submitted:
    if not prompt.strip():
        st.warning("Enter a prompt before sending.")
    else:
        data = {
            "prompt": prompt,
            "provider": provider,
            "new_chat": str(new_chat).lower(),
            "use_fallback": str(use_fallback).lower(),
        }
        files = [
            ("files", (upload.name, upload.getvalue(), upload.type or "application/octet-stream"))
            for upload in uploads
        ] if uploads else []
        try:
            with st.spinner(f"Waiting for {PROVIDER_LABELS[provider]}…"):
                response = httpx.post(
                    f"{API_BASE}/v1/chat",
                    data=data,
                    files=files or None,
                    timeout=float(settings.get("SANTRA_RESPONSE_TIMEOUT", "180")) + 60,
                )
            response.raise_for_status()
            result = response.json()
            st.session_state["latest_result"] = result
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except ValueError:
                detail = exc.response.text
            st.error(f"Request failed ({exc.response.status_code}): {detail}")
        except httpx.HTTPError as exc:
            st.error(f"Could not reach the Santra API: {exc}")

result = st.session_state.get("latest_result")
if result:
    st.divider()
    st.subheader(f"{PROVIDER_LABELS.get(result.get('provider'), result.get('provider', 'Provider'))} response")
    st.caption(f"Source: {result.get('source', 'unknown')} · {result.get('elapsed_ms', 0)} ms")
    st.markdown(result.get("response") or "_No response text returned._")
    if st.checkbox("Show raw scrape for debugging", key="show_raw_scrape"):
        raw_label = "Raw scraped text" if result.get("source") == "browser" else "Raw response text"
        with st.expander(raw_label, expanded=True):
            raw_text = result.get("raw_response")
            st.text(raw_text if raw_text else "No raw browser text was returned (the response may use API fallback).")

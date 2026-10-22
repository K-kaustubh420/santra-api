# Santra

Santra automates ChatGPT, Claude, Grok, and Gemini in persistent Playwright browser profiles and exposes the workflow through a FastAPI endpoint. A separate Streamlit app provides a browser-based interface while continuing to use that same API.

## Install

From PowerShell in the project directory:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
playwright install chromium
```

Configure `.env` as needed. Use the API's login endpoint or the Streamlit sidebar to open a provider login window and sign in to its persistent browser profile.

## Run the API and UI

Start the API in one terminal:

```powershell
python santra.py
```

Start the Streamlit UI in a second terminal:

```powershell
streamlit run app.py
```

The UI connects to `http://127.0.0.1:8765` by default; set `SANTRA_API_URL` to use a different API URL. Existing endpoints remain available at `/v1/chat`, `/v1/chat/json`, `/health`, `/providers`, and `/v1/login/{provider}`.

## IDE and OpenAI-compatible clients

Santra also exposes `POST /v1/chat/completions` and `GET /v1/models` using an OpenAI-compatible shape. The completion endpoint reuses the existing browser chat flow and returns the cleaned assistant response. It accepts agent-style `tool` and `function` messages, text content-part lists, and extra OpenAI request fields; tool/function messages are skipped when building browser prompts. Requests with `"stream": true` receive an OpenAI-compatible server-sent event response after the browser reply is ready; tokens are not streamed incrementally.

Use these values in VS Code Language Models, Continue, or another client configured for an OpenAI-compatible API:

- **API base URL:** `http://127.0.0.1:8765/v1`
- **API key:** `santra-local` (any bearer token/dummy key is accepted; it is not used for authentication)
- **Model:** `chatgpt`, `claude`, `grok`, or `gemini`

Start the API and log into a provider once using the Streamlit sidebar login button (or `POST /v1/login/{provider}`). In VS Code, add a model using an OpenAI-compatible provider, enter the base URL, API key, and model above, then select that model in chat. The Streamlit app's **Connect to an IDE or OpenAI-compatible tool** panel shows the current base URL and copyable values/configuration.

Quick test:

```bash
curl http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"chatgpt","messages":[{"role":"user","content":"Hello"}]}'
```

Model discovery is available at `GET http://127.0.0.1:8765/v1/models`.

Settings edited in the UI are saved to `.env`. Restart the API for changes to browser startup options, timeout, default provider, fallback enablement, API keys, or profile directory to take effect.

## Response extraction

Santra prefers provider-specific assistant-message selectors, then tries the broader provider selectors and a last-resort page scrape. When a provider reply label is present (for example, `ChatGPT said:`), the `response` is extracted from its last occurrence through the answer, stopping at common footers; otherwise, light UI-noise cleanup is applied to the scraped text. The original `raw_response` remains available for debugging. Existing API clients can continue reading `response` as before.

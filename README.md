# Santra

Santra is a small local service that sends prompts to ChatGPT, Claude, Grok, or Gemini using a real Chromium browser session, then returns the reply through an HTTP API. It also includes a simple web interface and an OpenAI-compatible endpoint for connecting compatible VS Code extensions and other clients.

Santra exists to make those browser-based assistants accessible through one local interface. It automates the provider websites; it is not an official API client unless you separately enable the optional API fallback.

## What it can do

- Automate **ChatGPT**, **Claude**, **Grok**, and **Gemini** using separate, persistent browser profiles.
- Open a visible browser for you to sign in, then reuse that profile on later requests.
- Accept prompts and file uploads through the API and Streamlit interface.
- Expose standard Santra chat endpoints and an OpenAI-compatible chat-completions endpoint.
- Optionally use configured OpenAI, Anthropic, Google, or xAI API credentials as a fallback when browser automation fails.
- Provide a Streamlit interface for chatting, logging in, editing settings, and viewing compatible-client connection details.

## Requirements

- Python 3.10 or newer is recommended.
- An internet connection and a supported desktop browser environment for Playwright Chromium.
- An account for each provider you want to use.
- For optional API fallback only: API credentials from the provider you enable.

The project uses Python packages listed in [`requirements.txt`](./requirements.txt). The setup below applies to Windows, macOS, and Linux.
If Python is not installed, install Python 3.10 or newer from [python.org](https://www.python.org/downloads/) first. On Windows, enable the option to add Python to `PATH`.

## Install

Open a terminal in the Santra project folder, then create and activate a virtual environment.

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS or Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

With the environment activated, install Santra and Chromium:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Run commands from the project folder so Santra can find its `.env` file and browser profiles.

## Sign in to a provider

Start the API (see [Start Santra](#start-santra)), then open a second terminal and request a login window. Replace `chatgpt` with `claude`, `grok`, or `gemini` as needed. On Windows, use `curl.exe` rather than PowerShell's `curl` alias.

```bash
curl -X POST http://127.0.0.1:8765/v1/login/chatgpt
```

Sign in to the provider in the browser window that opens. Santra saves the session under `santra_profiles/<provider>` and reuses it for later requests. Sign in separately for each provider you plan to use. Do not share or commit these profile folders.

## Start Santra

From the project folder, with the virtual environment activated:

```bash
python santra.py
```

The API defaults to port `8765`. Its default host setting binds to all network interfaces; for local-only use, set `SANTRA_HOST=127.0.0.1` in `.env` before starting the API. See [Security](#security).

To start the optional web interface, open another terminal in the project folder, activate the same virtual environment, then run:

```bash
streamlit run app.py
```

Open the address printed by Streamlit (usually `http://localhost:8501`). Its sidebar can open provider login windows and save settings to `.env`. Restart the API after changing settings that affect it.

## Test the API

Use `curl.exe` instead of `curl` in Windows PowerShell.

Check that the API is running:

```bash
curl http://127.0.0.1:8765/health
```

Send a prompt as JSON to `/v1/chat`:

```bash
curl -X POST http://127.0.0.1:8765/v1/chat -H "Content-Type: application/json" -d '{"prompt":"Reply with a short greeting.","provider":"chatgpt"}'
```

A successful response includes `provider`, `response`, `source`, and `elapsed_ms`; `raw_response` contains the scraped text before cleanup.

To upload a file, use the multipart form endpoint:

```bash
curl -X POST http://127.0.0.1:8765/v1/chat -F "prompt=Summarize this file" -F "provider=chatgpt" -F "files=@./document.pdf"
```

The provider website determines which file types it accepts. The JSON chat request does not support file uploads.

## VS Code and compatible clients

Santra exposes an OpenAI-compatible API for clients that let you configure a custom OpenAI-compatible endpoint. Start the API, sign in to a provider, then add a model in your VS Code extension/client using:

- **Base URL:** `http://127.0.0.1:8765/v1`
- **API key:** `santra-local` (a placeholder; Santra does not authenticate or validate bearer tokens)
- **Model:** `chatgpt`, `claude`, `grok`, or `gemini`

Example configuration format shown by Santra's Streamlit interface (client configuration formats vary):

```json
{
  "models": [
    {
      "title": "Santra (chatgpt)",
      "provider": "openai",
      "model": "chatgpt",
      "apiBase": "http://127.0.0.1:8765/v1",
      "apiKey": "santra-local"
    }
  ]
}
```

Select the added model in your client and send a message. The API does not require a real API key for browser-based requests.

## API reference

FastAPI also provides an interactive API page at `http://127.0.0.1:8765/docs`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check service status and list provider names. |
| `GET` | `/providers` | List provider URLs and whether a local profile directory exists. |
| `POST` | `/v1/login/{provider}` | Open a visible browser window for provider sign-in. |
| `POST` | `/v1/chat` | Chat with JSON or multipart form data; multipart requests can include files. |
| `POST` | `/v1/chat/json` | JSON-only chat request. |
| `GET` | `/v1/models` | List the four Santra model IDs for compatible clients. |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completion; accepts `stream: true`. |

For `/v1/chat` and `/v1/chat/json`, the request supports `prompt`, optional `provider`, `new_chat` (default `true`), and `use_fallback` (default `true`). The provider defaults to `SANTRA_DEFAULT_PROVIDER`, which is `chatgpt` unless configured otherwise. `source` in the response indicates `browser` or `fallback`.

The completions endpoint accepts `model` and `messages`. Its model names are the four provider IDs; common names such as `gpt-4o`, `claude-*`, `grok-*`, and `gemini-*` are also mapped to providers. It uses the latest user message and a limited text context from earlier messages. It does not implement provider-native tools or function calling.

### Streaming

`POST /v1/chat/completions` accepts `"stream": true` and responds with server-sent events (SSE), ending with `data: [DONE]`. This is **not token-by-token streaming**: Santra waits for the browser response, then sends that response in a single content chunk. Example:

```bash
curl -N http://127.0.0.1:8765/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"chatgpt","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

## Configuration

Santra loads optional settings from `.env` in the project directory. The default values are shown below:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SANTRA_HOST` | `0.0.0.0` | API bind address. Prefer `127.0.0.1` for local-only use. |
| `SANTRA_PORT` | `8765` | API port. |
| `SANTRA_HEADLESS` | `false` | Run provider browsers without a visible window. Login still opens a visible browser. |
| `SANTRA_BROWSER_PROFILE_DIR` | `./santra_profiles` | Directory for persistent provider sessions. |
| `SANTRA_DEFAULT_PROVIDER` | `chatgpt` | Provider used when a request does not specify one. |
| `SANTRA_RESPONSE_TIMEOUT` | `180` | Browser response timeout in seconds. |
| `FALLBACK_ENABLED` | `false` | Allow configured official-API fallback when browser automation fails. |

Fallback credentials are optional: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or `XAI_API_KEY`. Optional model settings are `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GOOGLE_MODEL`, and `XAI_MODEL`; OpenAI also supports `OPENAI_BASE_URL`. Fallback requires both `FALLBACK_ENABLED=true` and `use_fallback=true` on the request. The VS Code/Streamlit chat-completions route requests fallback, but it remains disabled unless the global setting is enabled.

Keep `.env` private. The Streamlit settings form writes settings and API keys to this file; leave a key field blank to keep its existing value.

## Troubleshooting

- **The browser opens but chat fails:** Sign in using `POST /v1/login/{provider}` and confirm the account is usable in that browser window.
- **Browser installation or launch errors:** Re-run `python -m playwright install chromium` from the activated environment.
- **Missing Linux browser libraries:** Install Chromium's operating-system dependencies with `python -m playwright install --with-deps chromium`.
- **The API cannot be reached:** Confirm `python santra.py` is running and the client uses the same host and port. The Streamlit interface defaults to `http://127.0.0.1:8765`; change `SANTRA_API_URL` if your API runs elsewhere.
- **A provider stops working after a website update:** Santra relies on website UI selectors, which can change. Check the browser and API logs; report the issue with the provider and steps to reproduce.
- **Fallback does not run:** Enable it in `.env`, set the corresponding provider API key, restart the API, and allow fallback for the request.
- **Settings seem unchanged:** Restart the API after editing `.env` or saving settings in Streamlit.

## Security and limitations

- The API has no authentication, authorization, or TLS. The placeholder API key is not security. Keep Santra on a trusted machine/network and bind it to `127.0.0.1` unless you add appropriate access controls and a secure network setup.
- Browser profiles contain logged-in sessions. Protect `santra_profiles` like passwords; do not commit or share it. API fallback keys are stored in `.env`, which should also remain private.
- Browser automation depends on third-party websites, account access, and fragile page selectors. Provider changes, sign-in challenges, rate limits, or service policies may interrupt it.
- Streaming is response-after-completion SSE, not incremental token streaming. OpenAI-compatible support is limited; this is not a full implementation of every OpenAI API feature.
- API fallback sends prompt text to the configured official provider API. It does not send uploaded files through the fallback path.

## Contributing and roadmap

Community contributions are welcome! Bug fixes, provider integrations, documentation improvements, and feature suggestions are all appreciated. Please open an issue to report a problem or discuss a proposal, and submit a pull request for changes. Include the operating system, provider, steps to reproduce, and relevant logs when reporting bugs; never include credentials, cookies, or browser profile data.

Potential next steps (not currently implemented):

- More reliable provider handling and automated regression checks.
- Genuine incremental streaming.
- Stronger authentication and safer deployment guidance.
- Additional provider integrations and clearer compatibility testing.

There is no `LICENSE` file in the repository at this time. Check with the project maintainers before redistributing or reusing Santra.

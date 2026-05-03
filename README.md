# PokéLab

**A visual-first MCP server for Pokémon cards — search, collect, and design directly inside your AI chat.**

PokéLab is a [FastMCP](https://github.com/jlowin/fastmcp) server that renders interactive [Prefab](https://prefab.ai) UI apps inline in Claude Desktop and VS Code Copilot Chat. Instead of returning text, its tools return live, interactive surfaces: a searchable card grid, a collection dashboard, and a full card designer — all without leaving the chat window.

**Demo:** [Watch the project walkthrough on YouTube](https://youtu.be/BYWNsr0OwuQ)

[![PokéLab demo video thumbnail](https://img.youtube.com/vi/BYWNsr0OwuQ/hqdefault.jpg)](https://youtu.be/BYWNsr0OwuQ)

---

## Features

- **Live card search** — query the Pokémon TCG API and browse results in an inline visual grid with save buttons
- **Collection dashboard** — manage your saved cards in a persistent local collection
- **Card designer** — build custom cards with a structured form UI, live preview, and one-click save
- **Raw data tools** — fetch normalized card payloads for automation, chaining, or prose answers
- **Slash command** — `/design_card_walkthrough` kicks off the full visual demo flow end-to-end

---

## How it works

```
Claude / Copilot ──MCP/stdio──► server.py ──HTTP──► Pokémon TCG API
                                    │
                                    ▼
                           sandbox/collection.json
```

`server.py` is a single-file FastMCP server. Tools decorated with `@mcp.tool(app=True)` return Prefab UI trees instead of text — that one flag is what makes cards render inside the chat rather than being described in prose. The three visual tools (`preview_real_card`, `card_lab`, `design_card`) each return a fully interactive `PrefabApp`. The three backend tools (`fetch_real_card`, `manage_collection`, `save_custom_card`) return structured data and handle persistence.

### The MCP → Prefab seam

```python
@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    ...
```

Without `app=True`, a tool returns text. With it, the tool returns a rendered, interactive Prefab page that the MCP host displays inline. That single decorator is the architectural hinge of the whole project.

### Card designer flow

```
Prefab form controls (tabs, selects, sliders, switches)
            │
            ▼
    save_custom_card({ name, hp, types, attacks, … })
            │
            ▼
        _render_card(spec)  →  Prefab card tree
            │
            ▼
    Claude Desktop / VS Code renders it inline
```

The user fills a structured Prefab UI instead of writing a long prompt. The form keeps live state, previews the card in real time, and persists the spec through the same collection pipeline used for real cards.

---

## Tools

| Tool | Surface | Purpose |
|---|---|---|
| `preview_real_card(name)` | Prefab MCP app | Live visual search grid with inline save buttons |
| `card_lab()` | Prefab MCP app | Saved collection dashboard |
| `design_card()` | Prefab MCP app | Interactive card designer with live preview |
| `fetch_real_card(name)` | Raw structured data | Single normalized card payload for automation or prose |
| `manage_collection(action, …)` | Backend tool | Add, list, remove, or clear saved cards |
| `save_custom_card(...)` | Backend tool | Persist a custom card from the designer or an agent |

**Quick selection guide**

- Browse live search results visually → `preview_real_card`
- View cards you've already saved → `card_lab`
- Build a custom card → `design_card`
- Get raw card data for code or chaining → `fetch_real_card`

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Or with `uv`:

```bash
uv pip install -r requirements.txt
```

### 2. (Optional) Configure an API key

Copy `.env.example` to `.env` and add your free [Pokémon TCG API key](https://dev.pokemontcg.io/) to raise the rate limit from 30 req/min to 1 000 req/min. The visual apps and designer work fine without a key.

```dotenv
POKEMON_TCG_API_KEY=your_api_key_here
```

### 3. Verify with the FastMCP inspector

```bash
cd pokelab
fastmcp dev inspector server.py
```

Or launch the dedicated app preview:

```bash
fastmcp dev apps server.py
```

If port `8000` is already in use, pick another pair:

```bash
fastmcp dev apps server.py --mcp-port 8001 --dev-port 8081
```

Recommended test sequence:

1. `preview_real_card` → `pikachu` → a card grid renders with save buttons
2. Click **Save to collection** on one print
3. `card_lab` → the saved card appears in the dashboard
4. `design_card` → the card studio opens
5. `fetch_real_card` → `pikachu` → inspect the raw JSON

---

## Connecting to Claude Desktop

Find and edit the Claude Desktop config file:

| OS | Path |
|---|---|
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |

Add a PokéLab entry with the absolute path to `server.py`:

```json
{
  "mcpServers": {
    "pokelab": {
      "command": "python",
      "args": ["/absolute/path/to/pokelab/server.py"]
    }
  }
}
```

Quit and relaunch Claude Desktop — it only re-reads config on startup. The hammer/plug icon in the chat input confirms the server is connected.

---

## Connecting to VS Code Copilot Chat

Create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "pokelab": {
      "type": "stdio",
      "command": "python",
      "args": ["/absolute/path/to/pokelab/server.py"]
    }
  }
}
```

Or run **MCP: Add Server** from the Command Palette, then start `pokelab` from **MCP: List Servers**. Open Copilot Chat in Agent mode — the tools and visual apps are available from the chat tool picker.

> If the UI looks stale after editing `server.py`, restart `pokelab` from **MCP: List Servers** and delete `pokelab/__pycache__`.

---

## Usage

### Visual card search

> *"Open a visual PokéLab search for Pikachu."*

`preview_real_card("pikachu")` renders a card grid inline with moves, weakness/resistance metadata, rarity labels, and save buttons.

### Collection dashboard

> *"Show me my PokéLab collection."*

After saving cards from the search UI, `card_lab()` renders the persisted collection in the same card format.

### Card studio

> *"Open the PokéLab card designer."*

`design_card()` opens a Prefab app with identity, stats, and finish tabs — selects, stage radio buttons, sliders, switches, checkboxes, flavour text, summary metrics, and a live preview. The Save button calls `save_custom_card(...)`.

### Raw lookup

> *"Fetch the Charizard card and tell me its attacks."*

`fetch_real_card("charizard")` returns structured JSON. The AI parses it and answers in prose — useful for piping data into other tools.

### Slash command

In Claude Desktop, type `/` and select `design_card_walkthrough` from the prompt menu for an end-to-end guided demo.

---

## Calling it from Python

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("server.py") as client:
        raw_card    = await client.call_tool("fetch_real_card",    {"name": "pikachu"})
        live_search = await client.call_tool("preview_real_card",  {"name": "charizard"})
        collection  = await client.call_tool("card_lab",           {})
        designer    = await client.call_tool("design_card",        {})
        saved       = await client.call_tool("manage_collection",  {"action": "list"})

asyncio.run(main())
```

---

## File structure

```
pokelab/
├── server.py            # all tools, Prefab renderers, and persistence logic
├── requirements.txt
├── sandbox/
│   └── collection.json  # saved card collection
├── .env                 # optional API key (gitignored)
└── README.md
```

The entire server lives in one file — tools, Prefab renderers, and the persistence pipeline are readable top to bottom.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named fastmcp` | `pip install -r requirements.txt` |
| `card_lab` shows empty collection | Save a card from `preview_real_card` first, or check `sandbox/collection.json` directly |
| `design_card` Save does nothing | Your MCP host must support MCP Apps tool actions |
| Stale UI after editing `server.py` | Restart the server and delete `__pycache__` |
| HTTP 429 from the TCG API | Add `POKEMON_TCG_API_KEY` to `.env` (free at [dev.pokemontcg.io](https://dev.pokemontcg.io/)) |
| Server starts but client can't see it | Use an absolute path in the config; run `python server.py` directly to check for import errors |

---

## License

MIT

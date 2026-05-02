# PokéLab

PokéLab is a FastMCP server that fetches, previews, saves, designs, and renders Pokemon cards inside Claude Desktop or VS Code Copilot Chat.

It started as an EAGv3 Session 4 exercise and has since been tightened into a visual-first MCP demo with distinct app tools for live search, saved collection browsing, and custom card design.

---

## What it does

Six tools and one built-in prompt are exposed over MCP:

| Tool | Surface | Use it when |
|---|---|---|
| `fetch_real_card(name)` | Raw structured data | You want one live card payload for automation, chaining, or prose answers |
| `preview_real_card(name)` | Prefab MCP app | You want a live visual search grid with inline save buttons |
| `manage_collection(action, …)` | Backend tool | You want to add, list, remove, or clear saved cards |
| `card_lab()` | Prefab MCP app | You want the saved collection dashboard, not a live API search |
| `design_card()` | Prefab MCP app | You want an interactive card designer with live preview |
| `save_custom_card(...)` | Backend tool | The designer or an agent wants to persist a custom card |

The server also exposes `/design_card_walkthrough`, a prompt that kicks off the visual-first demo flow end-to-end.

## Tool selection guide

- Use `preview_real_card(name)` for live Pokemon TCG search results you want to browse visually.
- Use `card_lab()` only for cards already saved in `sandbox/collection.json`.
- Use `fetch_real_card(name)` when you need one normalized card object instead of a visual app.
- Use `manage_collection(...)` and `save_custom_card(...)` as supporting persistence tools behind the UI.

## Calling it from code

If you want to invoke PokéLab from Python instead of chat, use a FastMCP client:

```python
import asyncio
from fastmcp import Client


async def main():
  async with Client("server.py") as client:
    raw_card = await client.call_tool("fetch_real_card", {"name": "pikachu"})
    live_search = await client.call_tool("preview_real_card", {"name": "charizard"})
    collection_app = await client.call_tool("card_lab", {})
    designer_app = await client.call_tool("design_card", {})
    saved_cards = await client.call_tool("manage_collection", {"action": "list"})


asyncio.run(main())
```

Useful one-liners for individual tools:

- `await client.call_tool("fetch_real_card", {"name": "pikachu"})`
- `await client.call_tool("preview_real_card", {"name": "bulbasaur"})`
- `await client.call_tool("manage_collection", {"action": "list"})`
- `await client.call_tool("manage_collection", {"action": "remove", "card_id": "base1-4"})`
- `await client.call_tool("card_lab", {})`
- `await client.call_tool("design_card", {})`
- `await client.call_tool("save_custom_card", {"name": "Embersprite", "primary_type": "Fire"})`

---

## Quick demo

In Claude Desktop with the server connected, type:

> *"Open a visual PokéLab search for Pikachu so I can inspect real cards inline and save one from the UI. Then do the same for Charizard. After that, show me my collection in the card lab and open the custom card designer."*

When each preview opens, use the inline **Save to collection** button on the print you want. The saved state flips in place, and `card_lab()` then renders the persisted collection inline when the host supports MCP Apps.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Or if you use `uv`:

```bash
uv pip install -r requirements.txt
```

### 2. Optional: configure `.env`

PokéLab does not ship an `.env.example`. Create a `.env` file in the repo root only if you want higher Pokemon TCG API rate limits:

```dotenv
POKEMON_TCG_API_KEY=your_api_key_here
```

The custom card designer and the visual search/collection apps work without any external LLM key.

### 3. Sanity check with the FastMCP inspector

Before wiring it into Claude Desktop, verify everything works in isolation:

```bash
cd pokelab
fastmcp dev inspector server.py
```

This opens the current FastMCP browser inspector. Click each tool, fill in the arguments, and watch the responses come back. For `preview_real_card`, `card_lab`, and `design_card`, the Prefab UI renders right there in the inspector — that's the same UI Claude Desktop or Copilot Chat will show you inline.

If you want the dedicated app preview UI instead, run:

```bash
cd pokelab
fastmcp dev apps server.py
```

If port `8000` is already in use on your machine, pick another pair of ports, for example:

```bash
fastmcp dev apps server.py --mcp-port 8001 --dev-port 8081
```

A good test sequence in the inspector:

1. `preview_real_card` → name: `pikachu` → a visual search renders with save buttons
2. Click **Save to collection** on one Pikachu print in the preview app
3. `card_lab` → click *Run* → the saved card renders in the collection dashboard
4. `design_card` → click *Run* → the Prefab card studio opens
5. `fetch_real_card` → name: `pikachu` → inspect the raw JSON surface if you want the non-visual automation path too

If those work, you're good. The MCP wire works, your Prefab installation works, and your file CRUD works.

---

## Connecting to Claude Desktop

Claude Desktop reads MCP server config from one JSON file. You'll add an entry pointing it at your `server.py`.

### 1. Find your Claude Desktop config file

| OS | Path |
|---|---|
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |

If the file doesn't exist yet, create it.

### 2. Add the PokéLab entry

Edit the file to look like this. Replace the path with the **absolute** path to your `server.py`:

```json
{
  "mcpServers": {
    "pokelab": {
      "command": "python",
      "args": ["C:\\Users\\Akshay\\Repos\\pokelab\\server.py"]
    }
  }
}
```

If you already have other MCP servers configured, just add the `"pokelab"` block alongside them inside `mcpServers`.

**Path notes:**
- On Windows, use double backslashes (`\\`) in the path, OR forward slashes (`/`) — both work in JSON.
- On macOS/Linux, use a normal forward-slash path.
- If `python` isn't on your PATH, use the full path to your interpreter (e.g. `"C:\\Python312\\python.exe"` or `/usr/bin/python3`).
- If you used `uv`, you can replace `"command": "python"` with `"command": "uv"` and `"args": ["run", "python", "<path>/server.py"]`.

### 3. Restart Claude Desktop

Quit completely (not just close the window) and reopen. Claude Desktop only re-reads the config on startup.

### 4. Verify the connection

Inside Claude Desktop, look for a small hammer/plug icon near the message input — that's the MCP indicator. Click it and you should see "pokelab" listed with the PokéLab tools (`fetch_real_card`, `preview_real_card`, `manage_collection`, `card_lab`, `design_card`, `save_custom_card`) and the prompt (`design_card_walkthrough`).

If the server fails to start, click the indicator to see the error message. The most common causes are:

- **Wrong path** in the JSON — copy-paste the path from your file explorer to be sure.
- **Wrong `python` command** — try the full path to the interpreter that has the dependencies installed.
- **Missing dependencies** — open a terminal and run `python <path>/server.py` directly. If it errors out about a missing module, fix that first.

---

## Connecting to VS Code Copilot Chat

VS Code supports MCP servers through `mcp.json`, and current builds also support MCP Apps rendered inline in chat when the server returns an app-enabled tool result.

### Option 1 — workspace config

Create `.vscode/mcp.json` in this workspace and add:

```json
{
  "servers": {
    "pokelab": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/Users/Akshay/Repos/pokelab/server.py"]
    }
  }
}
```

Adjust the command or path for your local Python installation if `python` is not on your PATH.

### Option 2 — command palette

Run **MCP: Add Server** from the Command Palette, choose a local stdio server, use the Python executable as the command, and pass `C:/Users/Akshay/Repos/pokelab/server.py` as the argument. Choose Workspace if you want the config stored in `.vscode/mcp.json`, or Global/User if you want it available everywhere.

After adding it, run **MCP: List Servers**, start `pokelab`, trust the server when prompted, then open Copilot Chat and use Agent mode. The tools, prompt, resources, and MCP Apps can be enabled or disabled from the chat tool picker.

If you change `server.py` and chat still renders an older PokéLab UI, restart `pokelab` from **MCP: List Servers** first. If the stale UI persists, stop any lingering `python .../pokelab/server.py` processes and remove `pokelab/__pycache__` before starting the server again so VS Code reloads the current source instead of an older runtime state.

---

## Using it in chat

Once the server shows up in Claude Desktop, you can interact with it in plain English.

### Example 1 — visual real-card search

> *"Open a visual PokéLab search for Pikachu."*

Copilot calls `preview_real_card("pikachu")`. A Prefab app opens inline, lays out multiple matching prints in a compact grid, shows both attack names plus weakness/resistance metadata, and lets you save one directly from the UI.

### Example 2 — collection dashboard after inline save

> *"Show me my PokéLab collection."*

After you save one or more cards in `preview_real_card`, Copilot calls `card_lab()`. The Prefab dashboard renders inline showing the persisted collection.

### Example 3 — the card studio

> *"Open the PokéLab custom card designer."*

Copilot calls `design_card()`. A Prefab app opens with tabs, select menus, radio buttons, sliders, switches, checkboxes, text areas, an accordion, metrics, progress, a table, and a live card preview. The Save button calls `save_custom_card(...)` behind the scenes.

### Example 4 — raw lookup for agent automation

> *"Use PokéLab to fetch the Charizard card and tell me its attacks."*

Claude calls `fetch_real_card("charizard")`, parses the result, and answers in prose. That raw lookup surface still exists for chaining with `manage_collection(...)` or other non-visual tool flows.

### Example 5 — the slash command

In Claude Desktop's input, type `/` and you should see `design_card_walkthrough` in the prompt menu. Selecting it auto-fills the multi-tool demo prompt.

---

## How it works

The architecture in one picture:

```
Claude/Copilot ──MCP/stdio──►  server.py  ──HTTP──►  Pokemon TCG API
           │
                                    ▼
                             sandbox/collection.json
```

Three layers:

1. **The MCP client** picks tools based on what you ask for.
2. **PokéLab server (`server.py`)** runs Python functions decorated with `@mcp.tool()` (or `@mcp.tool(app=True)` for the UI tools). It calls the Pokemon TCG API, persists to a JSON file, and returns either dicts/strings or Prefab UI trees. `preview_real_card`, `card_lab`, and `design_card` are the primary visual chat surfaces; `fetch_real_card`, `manage_collection`, and `save_custom_card` stay available as structured backend tools.
3. **The data plane** — JSON file for persistence and the Pokemon TCG API for real-card content.

Recent metadata tightening also makes the live-search, saved-collection, and raw-fetch tools more explicit to MCP clients, which helps reduce wrong-surface launches in chat.

### The seam between MCP and Prefab

The single most important line in the codebase:

```python
@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    ...
```

The `app=True` flag changes the meaning of the return value. Without it, an MCP tool returns text. With it, the tool returns a *rendered, interactive Prefab page* that Claude Desktop displays inline.

That one flag is what makes Pokemon cards render inside the chat instead of being described in prose.

### Why `design_card` works without prompt engineering

The trick is that the user fills a structured Prefab UI instead of writing a long prompt. The app keeps state for card fields, previews the card live, and sends the fields to `save_custom_card(...)`. Python takes that structured spec and saves it through the same collection pipeline used for real cards.

```
Prefab form controls
            │
            ▼
  save_custom_card(...)
  { name, hp, types, attacks, ... }
            │
            ▼
   _render_card(spec)
   → builds Prefab tree
            │
            ▼
  Claude Desktop or VS Code renders it inline
```

This makes the project a better Prefab showcase: the card studio uses tabs, cards, inputs, selects, radio buttons, sliders, switches, checkboxes, accordions, badges, metrics, progress, tables, buttons, actions, and state templates.

---

## File structure

```
pokelab/
├── .dev/
│   ├── DEMO_FLOW.md
│   ├── PROJECT_OVERVIEW.md
│   └── development-log.md
├── server.py            # tools, prompt, save helper, and Prefab renderers
├── requirements.txt
├── sandbox/
│   └── collection.json  # the saved card collection
├── .env                 # optional local API key file (gitignored)
└── README.md
```

One Python file contains the server logic. That's deliberate — it keeps the MCP tools, Prefab renderers, and persistence pipeline readable top to bottom.

---

## Mapping back to the lessons

If you trace the code in `server.py`, every section corresponds to a Session 4 lesson:

| Code section | Came from |
|---|---|
| `from fastmcp import FastMCP`, `mcp.run()` | Lesson 02 |
| HTTP fetch helper, sandbox folder | Lesson 01 |
| `_load_collection`/`_save_collection` (JSON) | Lesson 01 (`note_*` family, simplified) |
| `@mcp.tool(app=True)` returning `PrefabApp` | Lesson 04C |
| `with Card(): with CardHeader(): ...` DSL | Lesson 04A |
| `Badge`, `Muted`, `Row`, `Column`, `Tab`, `Slider`, `Switch`, `Table` | Lesson 04D's widget catalog |
| `CallTool`, `ShowToast`, `PrefabApp(state={...})` | Lesson 04B/04C reactive UI patterns |
| `@mcp.prompt()` slash command | Lesson 01 (`review_code` / `debug_error`) |

The interesting thing is the *combination*.

---

## Troubleshooting

### "No module named fastmcp" / prefab_ui

Install the dependencies:

```bash
pip install -r requirements.txt
```

If you have multiple Python installations, make sure you're installing into the same one your MCP client is using.

### `card_lab` shows an empty collection

You haven't saved any cards yet. The most visual path is to call `preview_real_card`, click **Save to collection** on the print you want, then reopen `card_lab`. If you want the raw tool flow instead, call `fetch_real_card` first and then `manage_collection("add", card=...)`. The dashboard reads from `sandbox/collection.json` — you can also open that file in a text editor to confirm what's there.

### `design_card` opens, but Save does not persist the card

Run the server through an MCP client that supports tool calls from Prefab actions. The Save button calls `save_custom_card(...)`, so the app host must support MCP Apps tool actions.

### The wrong PokéLab UI opens, or the UI looks stale

- Ask for the surface explicitly: say "visual live search" for `preview_real_card`, "saved collection" for `card_lab`, or "raw card data" for `fetch_real_card`.
- Restart `pokelab` from your MCP server list if the host keeps rendering an older app.
- If the stale UI persists, stop lingering `python .../pokelab/server.py` processes and remove `pokelab/__pycache__`, then relaunch the server.

### Pokemon TCG API rate-limited (HTTP 429)

You're hitting the API too often without an API key. Add `POKEMON_TCG_API_KEY` to your `.env` (free at [dev.pokemontcg.io](https://dev.pokemontcg.io/)) — that bumps the limit from 30/min to 1000/min.

### The server starts but the MCP client doesn't see it

- **Did you fully quit and relaunch Claude Desktop?** Just closing the window doesn't reload the config.
- **Is the path absolute?** Relative paths don't work in the config file.
- **Does `python server.py` work from your terminal?** If not, fix that first — the MCP client runs the same command.

---

## What's deliberately not in here

The MCP spec includes a few advanced primitives — Sampling (server asks the host's LLM), Elicitation (server asks the user mid-tool), and the `GenerativeUI` provider (LLM literally writes Prefab Python in a sandbox). FastMCP supports all of these. None of them were in the Session 4 lessons, so none of them are in this project.

The patterns in `server.py` add up to a single Python file where one tool call fetches data, another saves it, another renders the collection as a UI, and another opens a Prefab designer that saves structured custom cards.

---

## License

MIT. Built during EAGv3 Session 4 and iterated into a visual-first MCP demo.

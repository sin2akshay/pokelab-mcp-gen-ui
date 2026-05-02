# PokéLab

An MCP server that fetches, saves, designs, and renders Pokemon cards inside Claude Desktop.

Built for EAGv3 Session 4 — every pattern in this project comes from a Session 4 lesson; nothing new was introduced.

---

## What it does

Four tools, exposed over the Model Context Protocol:

| Tool | What it does |
|---|---|
| `fetch_real_card(name)` | Looks up a real Pokemon card by name from the [Pokemon TCG API](https://docs.pokemontcg.io/) |
| `manage_collection(action, …)` | CRUD over a personal card collection persisted to JSON |
| `card_lab()` | Renders the saved collection as an interactive Prefab UI inside the chat |
| `design_card(prompt)` | Asks Gemini to design a custom card from an English description, saves it, renders it |

A slash command (`/design_card_walkthrough`) is also exposed, which kicks off a full demo end-to-end.

---

## Quick demo

In Claude Desktop with the server connected, type:

> *"Fetch a Pikachu and a Charizard, save them to my collection, then show me my collection in a Prefab dashboard. Then design a custom card: a fire-fairy hybrid called Embersprite, around 80 HP, attacks themed on temple candles."*

Claude will fan out across all four tools. A live, interactive Prefab dashboard renders inline in the chat.

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

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and add your `GEMINI_API_KEY`. You only need this if you plan to use `design_card`. The other three tools work without it.

### 3. Sanity check with the FastMCP inspector

Before wiring it into Claude Desktop, verify everything works in isolation:

```bash
cd pokelab
fastmcp dev inspector server.py
```

This opens the current FastMCP browser inspector. Click each tool, fill in the arguments, and watch the responses come back. For `card_lab` and `design_card`, the Prefab UI renders right there in the inspector — that's the same UI Claude Desktop will show you in chat.

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

1. `fetch_real_card` → name: `pikachu` → see the card JSON
2. `manage_collection` → action: `add`, card: (paste the result above) → "Saved Pikachu..."
3. `card_lab` → click *Run* → a Prefab card renders below

If those three work, you're good. The MCP wire works, your Prefab installation works, and your file CRUD works.

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
      "args": ["C:\\Users\\Akshay\\Repos\\EAGv3\\Session 4\\pokelab\\server.py"]
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

Inside Claude Desktop, look for a small hammer/plug icon near the message input — that's the MCP indicator. Click it and you should see "pokelab" listed with all four tools (`fetch_real_card`, `manage_collection`, `card_lab`, `design_card`) and the prompt (`design_card_walkthrough`).

If the server fails to start, click the indicator to see the error message. The most common causes are:

- **Wrong path** in the JSON — copy-paste the path from your file explorer to be sure.
- **Wrong `python` command** — try the full path to the interpreter that has the dependencies installed.
- **Missing dependencies** — open a terminal and run `python <path>/server.py` directly. If it errors out about a missing module, fix that first.

---

## Using it in chat

Once the server shows up in Claude Desktop, you can interact with it in plain English.

### Example 1 — single-tool call

> *"Use PokéLab to fetch the Charizard card and tell me its attacks."*

Claude calls `fetch_real_card("charizard")`, parses the result, and answers in prose.

### Example 2 — multi-tool fan-out

> *"Fetch Pikachu, Bulbasaur, and Squirtle. Save all three to my collection, then show me the collection."*

Claude calls `fetch_real_card` three times, `manage_collection` three times, and finally `card_lab` once. The Prefab dashboard renders inline showing all three cards.

### Example 3 — the stretch demo

> *"Design a custom Pokemon card: a Lightning-Psychic hybrid called Voltgeist, around 110 HP, with attacks that play on the idea of memories trapped in a thunderbolt."*

Claude calls `design_card("…")`. Gemini fills in a JSON spec. Python renders it as a Pokemon card. A custom card materializes in the chat.

### Example 4 — the slash command

In Claude Desktop's input, type `/` and you should see `design_card_walkthrough` in the prompt menu. Selecting it auto-fills the multi-tool demo prompt.

---

## How it works

The architecture in one picture:

```
Claude Desktop  ──MCP/stdio──►  server.py  ──HTTP──►  Pokemon TCG API
                                    │                  Gemini
                                    ▼
                             sandbox/collection.json
```

Three layers:

1. **Claude Desktop (the MCP client)** picks tools based on what you ask for.
2. **PokéLab server (`server.py`)** runs four Python functions decorated with `@mcp.tool()` (or `@mcp.tool(app=True)` for the UI tools). It calls the Pokemon TCG API and Gemini, persists to a JSON file, and returns either dicts/strings or Prefab UI trees.
3. **The data plane** — JSON file for persistence, two HTTP APIs for content.

### The seam between MCP and Prefab

The single most important line in the codebase:

```python
@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    ...
```

The `app=True` flag changes the meaning of the return value. Without it, an MCP tool returns text. With it, the tool returns a *rendered, interactive Prefab page* that Claude Desktop displays inline.

That one flag is what makes Pokemon cards render inside the chat instead of being described in prose.

### Why `design_card` works without the LLM writing code

The trick (lifted straight from Lesson 04D's Talk-to-App) is that **Gemini never writes Prefab code**. It writes a small structured JSON object — a card spec. Python takes that spec and renders it through the same `_render_card` function used for real cards.

```
"design a fire-fairy hybrid"
            │
            ▼
   Gemini fills in JSON spec
   { name, hp, types, attacks, ... }
            │
            ▼
   _render_card(spec)
   → builds Prefab tree
            │
            ▼
   Claude Desktop renders it inline
```

LLMs are reliable at filling structured forms. They're less reliable at writing Python that imports correctly and indents correctly. By keeping Gemini at the form-filling layer and translating with deterministic Python, the system gets the best of both.

---

## File structure

```
pokelab/
├── server.py            # everything: 4 tools, 1 prompt, the Prefab renderer
├── sandbox/
│   └── collection.json  # the saved card collection
├── requirements.txt
├── .env.example
├── .env                 # your real keys (gitignored)
├── .gitignore
└── README.md
```

One Python file. That's deliberate — it mirrors `example_mcp_server.py` from Lesson 01 so you can read it top to bottom.

---

## Mapping back to the lessons

If you trace the code in `server.py`, every section corresponds to a Session 4 lesson:

| Code section | Came from |
|---|---|
| `from fastmcp import FastMCP`, `mcp.run()` | Lesson 02 |
| `requests.get(...)`, sandbox folder | Lesson 01 |
| `_load_collection`/`_save_collection` (JSON) | Lesson 01 (`note_*` family, simplified) |
| `@mcp.tool(app=True)` returning `PrefabApp` | Lesson 03 |
| `with Card(): with CardHeader(): ...` DSL | Lesson 04A |
| `Badge`, `Muted`, `Row`, `Column`, `Tab` | Lesson 04D's widget catalog |
| `client.models.generate_content(...)` | Lesson 03 (`AgenticMCPUse.py`), 04D |
| Planner prompt that returns JSON | Lesson 04D (`PLANNER_PROMPT`) |
| Defensive `_strip_fences` and try/except | Lesson 04D (the broken-output guard) |
| `@mcp.prompt()` slash command | Lesson 01 (`review_code` / `debug_error`) |

Nothing new was introduced. The interesting thing is the *combination*.

---

## Troubleshooting

### "No module named fastmcp" / prefab_ui

Install the dependencies:

```bash
pip install -r requirements.txt
```

If you have multiple Python installations, make sure you're installing into the same one Claude Desktop is using.

### `card_lab` shows an empty collection

You haven't saved any cards yet. Call `fetch_real_card` first, then `manage_collection("add", card=...)`, then `card_lab`. The dashboard reads from `sandbox/collection.json` — you can also open that file in a text editor to confirm what's there.

### `design_card` returns the "Card design failed" error card

Two common causes:

- **`GEMINI_API_KEY` not set** — check your `.env` file.
- **Gemini returned malformed JSON** — usually transient; just rephrase and try again. The error card shows you the first 200 characters of what came back, which often makes the issue obvious.

### Pokemon TCG API rate-limited (HTTP 429)

You're hitting the API too often without an API key. Add `POKEMON_TCG_API_KEY` to your `.env` (free at [dev.pokemontcg.io](https://dev.pokemontcg.io/)) — that bumps the limit from 30/min to 1000/min.

### The server starts but Claude Desktop doesn't see it

- **Did you fully quit and relaunch Claude Desktop?** Just closing the window doesn't reload the config.
- **Is the path absolute?** Relative paths don't work in the config file.
- **Does `python server.py` work from your terminal?** If not, fix that first — Claude Desktop runs the same command.

---

## What's deliberately not in here

The MCP spec includes a few advanced primitives — Sampling (server asks the host's LLM), Elicitation (server asks the user mid-tool), and the `GenerativeUI` provider (LLM literally writes Prefab Python in a sandbox). FastMCP supports all of these. None of them were in the Session 4 lessons, so none of them are in this project.

The patterns in `server.py` are all things you've already practiced. The new thing is what they add up to: a single Python file where one tool call fetches data, another saves it, a third renders it as a UI inside Claude Desktop, and a fourth designs entirely new cards from English. That combination is the project.

---

## License

MIT. Built as part of EAGv3 Session 4.

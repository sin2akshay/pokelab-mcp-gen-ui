"""
PokéLab — an MCP server that fetches, saves, designs, and renders Pokemon cards.

Stitches together every Session 4 pattern:
  Lesson 01  @mcp.tool(), file CRUD, sandbox folder, requests.get
  Lesson 02  mcp.run() entry point, stdio transport
  Lesson 03  Gemini integration (inside the server this time)
  Lesson 04A Prefab DSL, nested with-blocks
  Lesson 04B Rx + SetState reactive state
  Lesson 04C @mcp.tool(app=True) returning a PrefabApp
  Lesson 04D Talk-to-App planner — LLM emits JSON spec, Python renders it

Tools exposed:
  fetch_real_card(name)       — internet:    Pokemon TCG API (includes card image)
  manage_collection(action,…) — file CRUD:   sandbox/collection.json
  refresh_collection_images() — internet:    backfills image URLs for old saved cards
  card_lab()                  — Prefab UI:   renders collection as a styled grid
  design_card(prompt)         — stretch:     LLM designs a card; same renderer

Run:
    python server.py                    # stdio mode for Claude Desktop
    fastmcp dev inspector server.py     # MCP Inspector for tool testing
    fastmcp dev apps server.py          # browser preview for app-returning tools
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
    Grid,
    H3,
    Image,
    Muted,
    Row,
    Separator,
    Text,
)

load_dotenv()
# ---------------------------------------------------------------------------
# Sandbox — every file we touch lives in here, mirroring the safety pattern
# from example_mcp_server.py.
# ---------------------------------------------------------------------------

SANDBOX = Path(__file__).parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)
COLLECTION_FILE = SANDBOX / "collection.json"

# ---------------------------------------------------------------------------
# MCP server instance.
# ---------------------------------------------------------------------------

mcp = FastMCP("PokeLab")

# ---------------------------------------------------------------------------
# Type → visual style mapping
# ---------------------------------------------------------------------------

TYPE_STYLES = {
    "Fire":      {"bg": "bg-orange-100",  "border": "border-orange-300", "symbol": "🔥"},
    "Water":     {"bg": "bg-blue-100",    "border": "border-blue-300",   "symbol": "💧"},
    "Lightning": {"bg": "bg-yellow-100",  "border": "border-yellow-300", "symbol": "⚡"},
    "Grass":     {"bg": "bg-green-100",   "border": "border-green-300",  "symbol": "🌿"},
    "Psychic":   {"bg": "bg-purple-100",  "border": "border-purple-300", "symbol": "🔮"},
    "Fighting":  {"bg": "bg-red-100",     "border": "border-red-300",    "symbol": "👊"},
    "Darkness":  {"bg": "bg-gray-800",    "border": "border-gray-600",   "symbol": "🌑"},
    "Metal":     {"bg": "bg-slate-100",   "border": "border-slate-300",  "symbol": "⚙️"},
    "Fairy":     {"bg": "bg-pink-100",    "border": "border-pink-300",   "symbol": "✨"},
    "Dragon":    {"bg": "bg-indigo-100",  "border": "border-indigo-300", "symbol": "🐉"},
    "Colorless": {"bg": "bg-gray-50",     "border": "border-gray-200",   "symbol": "⭕"},
}

RARITY_SYMBOL = {
    "Common":    "●",
    "Uncommon":  "◆",
    "Rare":      "★",
    "Rare Holo": "★✦",
}


def _type_style(types):
    primary = (types or ["Colorless"])[0]
    return TYPE_STYLES.get(primary, TYPE_STYLES["Colorless"])


def _energy_symbols(cost):
    return "".join(
        TYPE_STYLES.get(c, TYPE_STYLES["Colorless"])["symbol"]
        for c in cost
    )


# ===========================================================================
# 1. INTERNET TOOL — Pokemon TCG API
# ===========================================================================
# Returns a normalized dict — only the fields we render.
# Trimming the response keeps tokens down when the model passes the result
# back to itself.
# ---------------------------------------------------------------------------

POKE_TCG_BASE = "https://api.pokemontcg.io/v2/cards"


@mcp.tool()
def fetch_real_card(name: str) -> dict:
    """Fetch a real Pokemon card by name from the Pokemon TCG API.

    Args:
        name: A Pokemon name like "pikachu", "charizard", "mewtwo".

    Returns:
        A dict describing the card (id, name, hp, types, attacks, etc.)
        or {"error": "..."} if the lookup failed.
    """
    headers = {}
    if api_key := os.getenv("POKEMON_TCG_API_KEY"):
        headers["X-Api-Key"] = api_key
    try:
        r = requests.get(
            POKE_TCG_BASE,
            params={"q": f"name:{name}", "pageSize": 1, "orderBy": "set.releaseDate"},
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        return {"error": f"Network error fetching {name!r}: {e}"}

    cards = r.json().get("data", [])
    if not cards:
        return {"error": f"No card found for {name!r}"}

    c = cards[0]
    return {
        "id": c["id"],
        "name": c["name"],
        "hp": c.get("hp", "?"),
        "types": c.get("types", []),
        "subtitle": (c.get("subtypes") or ["Basic"])[0],
        "attacks": [
            {"name": a["name"], "cost": a.get("cost", []),
             "damage": a.get("damage", ""), "text": a.get("text", "")}
            for a in c.get("attacks", [])
        ],
        "weakness": (
            {"type": c["weaknesses"][0].get("type", ""),
             "value": c["weaknesses"][0].get("value", "")}
            if c.get("weaknesses") else None
        ),
        "set": c.get("set", {}).get("name", ""),
        "number": c.get("number", ""),
        "rarity": c.get("rarity", ""),
        "image_url": c.get("images", {}).get("small", ""),
        "source": "pokemon_tcg_api",
    }


# ===========================================================================
# 2. FILE CRUD TOOL — collection.json
# ===========================================================================
# A single tool dispatched by an `action` argument. JSON file storage instead
# of SQLite — easier to eyeball during the demo (and easier to git diff).
# ---------------------------------------------------------------------------

def _load_collection():
    if not COLLECTION_FILE.exists():
        return []
    try:
        return json.loads(COLLECTION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_collection(cards):
    COLLECTION_FILE.write_text(json.dumps(cards, indent=2), encoding="utf-8")


@mcp.tool()
def manage_collection(action: str, card: dict | None = None, card_id: str | None = None) -> str:
    """CRUD over the saved card collection.
    action: add | list | remove | clear
    card: dict from fetch_real_card (for add)
    card_id: string id (for remove)
    """
    cards = _load_collection()
    if action == "add":
        if not card or "id" not in card:
            return "ERROR: action=add requires a card dict with an 'id' field"
        cards = [c for c in cards if c.get("id") != card["id"]]
        cards.append(card)
        _save_collection(cards)
        return f"Saved {card.get('name', 'card')} (id={card['id']}). Collection has {len(cards)} cards."
    if action == "list":
        if not cards:
            return "Collection is empty."
        return ", ".join(f"{c['name']} ({c['id']})" for c in cards)
    if action == "remove":
        if not card_id:
            return "ERROR: action=remove requires a card_id"
        cards = [c for c in cards if c.get("id") != card_id]
        _save_collection(cards)
        return f"Removed {card_id}. {len(cards)} cards remaining."
    if action == "clear":
        _save_collection([])
        return "Collection cleared."
    return f"ERROR: unknown action {action!r}. Use add | list | remove | clear."


# ===========================================================================
# 2b. REFRESH IMAGES — backfill image_url for old saved cards
# ===========================================================================

@mcp.tool()
def refresh_collection_images() -> str:
    """Re-fetch image URLs from the Pokemon TCG API for any saved card missing one.
    Run this once if your collection was saved with the old server.py.
    """
    cards = _load_collection()
    updated = 0
    skipped = 0
    headers = {}
    if api_key := os.getenv("POKEMON_TCG_API_KEY"):
        headers["X-Api-Key"] = api_key

    for card in cards:
        if card.get("image_url") or card.get("source") == "designed_by_llm":
            skipped += 1
            continue
        card_id = card.get("id", "")
        try:
            r = requests.get(f"{POKE_TCG_BASE}/{card_id}", headers=headers, timeout=10)
            if r.status_code == 200:
                img = r.json().get("data", {}).get("images", {}).get("small", "")
                if img:
                    card["image_url"] = img
                    updated += 1
            time.sleep(0.1)
        except Exception:
            pass

    _save_collection(cards)
    return f"Done. Updated {updated} cards with images. Skipped {skipped}."


# ===========================================================================
# 3. PREFAB UI — redesigned card renderer + card_lab grid
# ===========================================================================

def _render_card(card: dict) -> None:
    """Render one Pokemon card with type colours, image, attacks, and footer."""
    types    = card.get("types") or ["Colorless"]
    style    = _type_style(types)
    bg       = style["bg"]
    symbol   = style["symbol"]
    is_dark  = types[0] == "Darkness"
    text_cls = "text-white" if is_dark else ""
    name     = card.get("name", "Unknown")
    hp       = card.get("hp", "?")
    rarity   = card.get("rarity", "")
    rarity_sym = RARITY_SYMBOL.get(rarity, "")

    with Card(css_class="overflow-hidden shadow-md hover:shadow-xl transition-shadow duration-200"):

        # — Coloured header band ———————————————————————————————————————————
        with CardHeader(css_class=f"{bg} border-b {style['border']} pb-2"):
            with Row(css_class="justify-between items-start"):
                with Column(css_class="gap-0"):
                    with Row(css_class="items-center gap-1"):
                        Text(symbol, css_class="text-lg")
                        Text(name, css_class=f"text-base font-bold {text_cls}")
                    if card.get("subtitle"):
                        Muted(card["subtitle"],
                              css_class=f"text-xs {'text-gray-300' if is_dark else ''}")
                with Column(css_class="items-end gap-0"):
                    Text(f"{hp} HP",
                         css_class=f"text-xl font-extrabold {'text-white' if is_dark else 'text-gray-700'}")
                    if rarity_sym:
                        Muted(rarity_sym, css_class="text-xs text-right")

        # — Card image ———————————————————————————————————————————————————
        img_url = card.get("image_url", "")
        if img_url:
            with CardContent(css_class="p-0"):
                Image(
                    src=img_url,
                    alt=f"{name} Pokemon card",
                    width="100%",
                    height="auto",
                    css_class="object-contain bg-gray-50",
                )
        else:
            with CardContent(css_class=f"p-0 {bg} h-28 flex items-center justify-center"):
                Text(symbol, css_class="text-5xl opacity-30")

        # — Attacks ——————————————————————————————————————————————————————
        with CardContent(css_class="pt-2 pb-1 px-3"):
            attacks = card.get("attacks", [])
            if attacks:
                with Column(css_class="gap-2"):
                    for atk in attacks:
                        cost_str = _energy_symbols(atk.get("cost", []))
                        dmg = atk.get("damage", "")
                        with Column(css_class="gap-0.5"):
                            with Row(css_class="justify-between items-center"):
                                with Row(css_class="gap-1 items-center"):
                                    if cost_str:
                                        Text(cost_str, css_class="text-sm")
                                    Text(atk["name"], css_class="font-semibold text-sm")
                                if dmg:
                                    Text(dmg, css_class="font-bold text-sm")
                            if atk.get("text"):
                                Muted(atk["text"], css_class="text-xs leading-tight")
            else:
                Muted("No attacks", css_class="text-xs italic")

        # — Footer ———————————————————————————————————————————————————————
        with CardContent(css_class="pt-1 pb-2 px-3"):
            Separator(css_class="mb-2")
            with Row(css_class="justify-between items-center"):
                w = card.get("weakness")
                if w:
                    weak_sym = TYPE_STYLES.get(w.get("type", ""), TYPE_STYLES["Colorless"])["symbol"]
                    Muted(f"Weak: {weak_sym} {w.get('value', '')}", css_class="text-xs")
                else:
                    Muted("Weak: —", css_class="text-xs")
                set_name = card.get("set", "")
                number   = card.get("number", "")
                if set_name or number:
                    Muted(f"{set_name} #{number}" if number else set_name,
                          css_class="text-xs text-right")
            if card.get("source") == "designed_by_llm":
                Badge("✦ Custom", variant="secondary", css_class="text-xs mt-1")


@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    """Render my Pokémon card collection as a visual grid with card images."""
    cards = _load_collection()

    with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:
        with Card():
            with CardHeader():
                Text("✦ My Pokémon Collection",
                     css_class="text-xl font-bold")
                Muted(f"{len(cards)} card{'s' if len(cards) != 1 else ''} · sandbox/collection.json")
            with CardContent():
                if not cards:
                    with Column(css_class="items-center py-12 gap-2"):
                        Text("🃏", css_class="text-6xl opacity-30")
                        Muted("No cards yet. Call fetch_real_card then manage_collection to add some.")
                else:
                    with Grid(columns={"default": 1, "md": 2, "lg": 3}, gap=4):
                        for card in cards:
                            _render_card(card)

    return app


# ===========================================================================
# 4. DESIGN CARD — Talk-to-App stretch tool
# ===========================================================================

CARD_DESIGNER_PROMPT = """You design Pokemon Trading Card Game cards. Given the user's
description, respond with EXACTLY ONE JSON object describing one card.

Required shape:
{{
  "name": "<short evocative name, 1-2 words>",
  "hp": <integer between 30 and 220>,
  "types": [<one or two of: Fire, Water, Grass, Lightning, Psychic,
                            Fighting, Darkness, Metal, Fairy, Dragon, Colorless>],
  "subtitle": "<flavor subtitle, e.g. 'Candle Sprite Pokemon'>",
  "attacks": [
    {{"name": "<short>", "cost": [<types from same list>], "damage": "<e.g. '20' or '40+'>",
      "text": "<one short rules sentence>"}}
  ],
  "weakness": {{"type": "<type>", "value": "<e.g. '+20' or 'x2'>"}},
  "flavor": "<one-line flavor text>"
}}

Balance: Basic ~30-90 HP, Stage 2 ~100-170 HP. Cost and damage should scale together.
Respond with JSON only - no markdown fences, no prose.

User request: {prompt}
"""


def _call_gemini(prompt: str) -> str:
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def _error_card_app(message: str) -> PrefabApp:
    with PrefabApp(css_class="max-w-md mx-auto p-6") as app:
        with Card():
            with CardHeader():
                Text("Card design failed", css_class="font-bold")
            with CardContent():
                with Column(css_class="gap-2"):
                    Muted(message)
                    Muted("Try rephrasing and call design_card again.")
    return app


@mcp.tool(app=True)
def design_card(prompt: str) -> PrefabApp:
    """Design a custom Pokemon card from an English description using an LLM.
    The LLM fills in a JSON spec; Python renders it through _render_card().
    Example: 'a fire-fairy hybrid called Embersprite, 80 HP, temple flame attacks'
    """
    try:
        raw = _call_gemini(CARD_DESIGNER_PROMPT.format(prompt=prompt))
    except Exception as e:
        return _error_card_app(f"LLM call failed: {e}")

    try:
        spec = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        return _error_card_app(f"Couldn't parse LLM response as JSON ({e}). Got: {raw[:200]}")

    cards = _load_collection()
    next_id = sum(1 for c in cards if c.get("source") == "designed_by_llm") + 1
    card = {
        "id": f"custom-{next_id:03d}",
        "name": str(spec.get("name", "Unnamed")),
        "hp": str(spec.get("hp", "?")),
        "types": spec.get("types", ["Colorless"]),
        "subtitle": str(spec.get("subtitle", "Custom Pokemon")),
        "attacks": [
            {"name": str(a.get("name", "Attack")), "cost": a.get("cost", []),
             "damage": str(a.get("damage", "")), "text": str(a.get("text", ""))}
            for a in spec.get("attacks", [])
        ],
        "weakness": spec.get("weakness"),
        "set": "Custom Lab",
        "number": f"C{next_id:03d}",
        "rarity": "Custom",
        "flavor": spec.get("flavor", ""),
        "image_url": "",
        "source": "designed_by_llm",
    }

    cards.append(card)
    _save_collection(cards)

    with PrefabApp(css_class="max-w-sm mx-auto p-6") as app:
        _render_card(card)
        Muted(f"Saved as {card['id']}. Call card_lab() to see your full collection.",
              css_class="text-xs text-center mt-2")

    return app


# ===========================================================================
# 5. PROMPT — slash command
# ===========================================================================

@mcp.prompt()
def design_card_walkthrough() -> str:
    """Walk a new user through the PokéLab demo end-to-end."""
    return (
        "I want to try the PokéLab MCP server. Please:\n"
        "1. Fetch a Pikachu and a Charizard from the Pokemon TCG API.\n"
        "2. Save both to my collection.\n"
        "3. Call refresh_collection_images so all cards have their artwork.\n"
        "4. Show me my collection in a Prefab dashboard.\n"
        "5. Then design a custom card: a fire-fairy hybrid called 'Embersprite'"
        " with around 80 HP and attacks themed on temple candles.\n"
    )


if __name__ == "__main__":
    print(f"PokeLab starting -- sandbox: {SANDBOX}", file=sys.stderr)
    mcp.run()
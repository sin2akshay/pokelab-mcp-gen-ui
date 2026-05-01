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
  fetch_real_card(name)       — internet:    Pokemon TCG API
  manage_collection(action,…) — file CRUD:   sandbox/collection.json
  card_lab()                  — Prefab UI:   renders the collection in chat
  design_card(prompt)         — stretch:     LLM designs a card; same renderer

Run:
  # Production / Claude Desktop — speaks MCP over stdio:
  python server.py

  # Dev preview — opens a browser to click tools and see UIs render:
  fastmcp dev server.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from prefab_ui.actions import SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
    H1,
    H3,
    Muted,
    Row,
    Tab,
    Tabs,
    Text,
)
from prefab_ui.rx import Rx

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


# ===========================================================================
# 1. INTERNET TOOL — Pokemon TCG API
# ===========================================================================
# Same shape as `fetch_url` from example_mcp_server.py, but specialized for
# the Pokemon TCG API. Returns a normalized dict — only the fields we render.
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
            params={"q": f'name:{name}', "pageSize": 1, "orderBy": "set.releaseDate"},
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
        "subtitle": c.get("subtypes", ["Basic"])[0] if c.get("subtypes") else "Basic",
        "attacks": [
            {
                "name": a["name"],
                "cost": a.get("cost", []),
                "damage": a.get("damage", ""),
                "text": a.get("text", ""),
            }
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
        "source": "pokemon_tcg_api",
    }


# ===========================================================================
# 2. FILE CRUD TOOL — collection.json
# ===========================================================================
# Same shape as the note_* family from example_mcp_server.py: a single tool
# dispatched by an `action` argument. JSON file storage instead of SQLite —
# easier to eyeball during the demo (and easier to git diff).
# ---------------------------------------------------------------------------

def _load_collection() -> list[dict]:
    if not COLLECTION_FILE.exists():
        return []
    try:
        return json.loads(COLLECTION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_collection(cards: list[dict]) -> None:
    COLLECTION_FILE.write_text(json.dumps(cards, indent=2), encoding="utf-8")


@mcp.tool()
def manage_collection(
    action: str,
    card: dict | None = None,
    card_id: str | None = None,
) -> str:
    """CRUD over the saved card collection.

    Args:
        action: One of "add", "list", "remove", "clear".
        card:   For action="add" — the card dict from fetch_real_card or design_card.
        card_id: For action="remove" — the id of the card to remove.

    Returns:
        A human-readable status string.
    """
    cards = _load_collection()

    if action == "add":
        if not card or "id" not in card:
            return "ERROR: action=add requires a card dict with an 'id' field"
        # Replace if id already present, else append (idempotent).
        cards = [c for c in cards if c.get("id") != card["id"]]
        cards.append(card)
        _save_collection(cards)
        return f"Saved {card.get('name', 'card')} (id={card['id']}). Collection has {len(cards)} cards."

    if action == "list":
        if not cards:
            return "Collection is empty."
        names = ", ".join(f"{c['name']} ({c['id']})" for c in cards)
        return f"{len(cards)} cards: {names}"

    if action == "remove":
        if not card_id:
            return "ERROR: action=remove requires a card_id"
        before = len(cards)
        cards = [c for c in cards if c.get("id") != card_id]
        _save_collection(cards)
        return f"Removed {card_id}. {len(cards)} cards remaining (was {before})."

    if action == "clear":
        _save_collection([])
        return "Collection cleared."

    return f"ERROR: unknown action {action!r}. Use add | list | remove | clear."


# ===========================================================================
# 3. PREFAB UI — `card_lab` and the shared card renderer
# ===========================================================================
# Same shape as `counter_card` from Lesson 03: @mcp.tool(app=True) returns a
# PrefabApp. The renderer `_render_card` is also called from `design_card`
# below, so real and generated cards look identical.
# ---------------------------------------------------------------------------

# Map Pokemon TCG types to a Prefab Badge variant. Prefab only supports a few
# variants out of the box, so we use them deliberately.
TYPE_TO_VARIANT = {
    "Fire": "destructive",
    "Fighting": "destructive",
    "Water": "default",
    "Electric": "warning",
    "Lightning": "warning",
    "Grass": "success",
    "Psychic": "default",
    "Fairy": "default",
    "Dragon": "default",
    "Darkness": "default",
    "Metal": "default",
    "Colorless": "default",
}


def _render_card(card: dict) -> None:
    """Render one Pokemon card using Prefab components.

    This is the heart of the project — both real and LLM-designed cards
    pass through here, so they look the same in the UI.
    """
    types = card.get("types") or ["Colorless"]
    type_str = " / ".join(types)
    primary_variant = TYPE_TO_VARIANT.get(types[0], "default")

    with Card():
        with CardHeader():
            with Row(gap=2):
                CardTitle(card["name"])
                Badge(f"HP {card.get('hp', '?')}", variant="default")
                Badge(type_str, variant=primary_variant)
        with CardContent():
            with Column(gap=3):
                # Subtitle line: subtype + set + number
                meta_bits = []
                if card.get("subtitle"):
                    meta_bits.append(card["subtitle"])
                if card.get("set"):
                    meta_bits.append(card["set"])
                if card.get("number"):
                    meta_bits.append(f"#{card['number']}")
                if meta_bits:
                    Muted(" · ".join(meta_bits))

                # Attacks
                for atk in card.get("attacks", []):
                    cost = atk.get("cost") or []
                    cost_str = " ".join(cost) if cost else "—"
                    with Row(gap=3):
                        Text(f"⚡ {atk['name']}")
                        Muted(f"[{cost_str}]")
                        Text(str(atk.get("damage") or "—"))
                    if atk.get("text"):
                        Muted(atk["text"])

                # Weakness
                if card.get("weakness"):
                    w = card["weakness"]
                    Muted(f"Weakness: {w.get('type', '')} {w.get('value', '')}")

                # Source tag — makes it obvious in the UI which cards were generated
                if card.get("source") == "designed_by_llm":
                    Badge("Custom — designed by LLM", variant="success")


@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    """Render my Pokemon card collection as an interactive Prefab dashboard."""
    cards = _load_collection()

    with PrefabApp(css_class="max-w-2xl mx-auto p-6") as app:
        with Card():
            with CardHeader():
                CardTitle("My Pokémon Collection")
                Muted(f"{len(cards)} cards in sandbox/collection.json")
            with CardContent():
                if not cards:
                    Muted("(empty — call fetch_real_card or design_card first)")
                else:
                    with Column(gap=4):
                        for card in cards:
                            _render_card(card)

    return app


# ===========================================================================
# 4. STRETCH — `design_card` (Talk-to-App pattern from Lesson 04D)
# ===========================================================================
# The user describes a card in English. We ask Gemini to fill in a JSON
# spec — the same task-shape as PLANNER_PROMPT in prompt_to_app.py. We
# save the result to the collection and render it through the same
# `_render_card` we use for real cards.
# ---------------------------------------------------------------------------

CARD_DESIGNER_PROMPT = """You design Pokemon Trading Card Game cards. Given the user's
description, respond with EXACTLY ONE JSON object describing one card.

Required shape:
{{
  "name": "<short evocative name, 1-2 words>",
  "hp": <integer between 30 and 220>,
  "types": [<one or two of: Fire, Water, Grass, Electric, Psychic,
                            Fighting, Darkness, Metal, Fairy, Dragon, Colorless>],
  "subtitle": "<flavor subtitle, e.g. 'Candle Sprite Pokémon'>",
  "attacks": [
    {{"name": "<short>", "cost": [<types from same list>], "damage": "<e.g. '20' or '40+'>",
      "text": "<one short rules sentence>"}}
    // 1 or 2 attacks total
  ],
  "weakness": {{"type": "<type>", "value": "<e.g. '+20' or 'x2'>"}},
  "flavor": "<one-line flavor text>"
}}

Balance guidelines (keep cards reasonable):
- Basic Pokemon: 30-90 HP, attacks deal 10-40 damage with 1-2 energy cost.
- HP and damage should scale together — bigger HP = bigger attacks but more cost.
- Cost length should roughly match damage tier.

Respond with the JSON object only — no markdown fences, no prose, no commentary.

User request: {prompt}
"""


def _call_gemini(prompt: str) -> str:
    """Call Gemini and return the raw text. Lazy-imported so the server
    starts even without google-genai installed (you only need it for design_card).
    """
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env — design_card needs it")

    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()


def _strip_fences(raw: str) -> str:
    """Tolerate the LLM occasionally wrapping JSON in markdown code fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Strip ```json\n ... \n``` or ``` ... ```
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def _error_card_app(message: str) -> PrefabApp:
    """When something goes wrong, render a small explanatory card instead of crashing."""
    with PrefabApp(css_class="max-w-md mx-auto p-6") as app:
        with Card():
            with CardHeader():
                CardTitle("Card design failed")
            with CardContent():
                with Column(gap=2):
                    Muted(message)
                    Muted("Try rephrasing your request and call design_card again.")
    return app


@mcp.tool(app=True)
def design_card(prompt: str) -> PrefabApp:
    """Design a custom Pokemon card from an English description, using an LLM.

    The LLM fills in a structured card spec (NOT Prefab code). Python takes
    that spec, normalizes it, saves it to the collection, and renders it
    through the same _render_card function used for real cards.

    Args:
        prompt: An English description like "a fire-fairy hybrid called
                Embersprite, around 80 HP, attacks themed on temple flames".
    """
    try:
        raw = _call_gemini(CARD_DESIGNER_PROMPT.format(prompt=prompt))
    except Exception as e:
        return _error_card_app(f"LLM call failed: {e}")

    try:
        spec = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        return _error_card_app(
            f"Couldn't parse the LLM's response as JSON ({e}). "
            f"Got: {raw[:200]}"
        )

    # Normalize into our shared card shape so _render_card works.
    cards = _load_collection()
    next_id = sum(1 for c in cards if c.get("source") == "designed_by_llm") + 1
    card = {
        "id": f"custom-{next_id:03d}",
        "name": str(spec.get("name", "Unnamed")),
        "hp": str(spec.get("hp", "?")),
        "types": spec.get("types", ["Colorless"]),
        "subtitle": str(spec.get("subtitle", "Custom Pokémon")),
        "attacks": [
            {
                "name": str(a.get("name", "Attack")),
                "cost": a.get("cost", []),
                "damage": str(a.get("damage", "")),
                "text": str(a.get("text", "")),
            }
            for a in spec.get("attacks", [])
        ],
        "weakness": spec.get("weakness"),
        "set": "Custom Lab",
        "number": f"custom-{next_id:03d}",
        "rarity": "Custom",
        "flavor": spec.get("flavor", ""),
        "source": "designed_by_llm",
    }

    # Save to collection — the new card will appear next time card_lab is called.
    cards.append(card)
    _save_collection(cards)

    # Render this single card now.
    with PrefabApp(css_class="max-w-md mx-auto p-6") as app:
        _render_card(card)
        Muted(f"Saved as {card['id']}. Call card_lab to see your full collection.")

    return app


# ===========================================================================
# 5. PROMPT — a slash-command the host can surface to the user
# ===========================================================================
# Bonus: same shape as the @mcp.prompt() examples in example_mcp_server.py.
# This makes "/design_card_walkthrough" appear as a slash command in
# Claude Desktop's prompt menu, walking the user through the demo.
# ---------------------------------------------------------------------------

@mcp.prompt()
def design_card_walkthrough() -> str:
    """Walk a new user through the PokéLab demo end-to-end."""
    return (
        "I want to try the PokéLab MCP server. Please:\n"
        "1. Fetch a Pikachu and a Charizard from the Pokemon TCG API.\n"
        "2. Save both to my collection.\n"
        "3. Show me my collection in a Prefab dashboard.\n"
        "4. Then design a custom card: a fire-fairy hybrid called "
        "'Embersprite' with around 80 HP and attacks themed on temple candles.\n"
    )


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"PokéLab starting — sandbox: {SANDBOX}", file=sys.stderr)
    mcp.run()

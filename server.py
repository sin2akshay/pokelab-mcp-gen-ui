"""PokéLab is an MCP server for live Pokemon TCG lookups, collection storage,
and Prefab-powered visual card apps.

Session 4 patterns used:
    Lesson 01  @mcp.tool(), file CRUD, sandbox folder, HTTP fetch
    Lesson 02  mcp.run() entry point, stdio transport
    Lesson 04A Prefab DSL, nested with-blocks
    Lesson 04B Rx + SetState reactive state
    Lesson 04C @mcp.tool(app=True) returning a PrefabApp
    Lesson 04D Talk-to-App pattern — structured inputs, Python renders them

Exposed MCP tools:
    fetch_real_card(name)         — raw live Pokemon TCG lookup
    manage_collection(action, ...) — save, list, remove, or clear cards
    card_lab()                    — visual saved-collection dashboard
    preview_real_card(name)       — visual live search with inline save
    save_custom_card(...)         — persist a designed custom card
    design_card()                 — interactive Prefab card designer

Async client skeleton for the sample queries in the tool docstrings:
    from fastmcp import Client

    async with Client("server.py") as client:
        result = await client.call_tool("<tool_name>", {...})

Run locally:
    python server.py
    fastmcp dev inspector server.py
    fastmcp dev apps server.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# pokemontcg.io rejects the default Python urllib user agent with HTTP 403,
# so every outbound request shares this header set.
DEFAULT_HEADERS = {
    "User-Agent": "PokeLab/1.0 (+https://github.com/PokeLab) Python-urllib",
    "Accept": "application/json, image/*;q=0.9, */*;q=0.5",
}

from dotenv import load_dotenv
from fastmcp import FastMCP
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Accordion,
    AccordionItem,
    Badge,
    Button,
    Card,
    CardDescription,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Checkbox,
    Column,
    Grid,
    Image,
    Input,
    Metric,
    Muted,
    Radio,
    RadioGroup,
    Row,
    Separator,
    Select,
    SelectOption,
    Slider,
    Switch,
    Tab,
    Tabs,
    Text,
    Textarea,
)
from prefab_ui.components.control_flow import If

load_dotenv()
# ---------------------------------------------------------------------------
# Sandbox storage. All local writes stay under sandbox/ so the demo never
# touches arbitrary files.
# ---------------------------------------------------------------------------

SANDBOX = Path(__file__).parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)
COLLECTION_FILE = SANDBOX / "collection.json"

# ---------------------------------------------------------------------------
# MCP server root.
# ---------------------------------------------------------------------------

mcp = FastMCP("PokeLab")

# ---------------------------------------------------------------------------
# Type-to-style mappings shared across collection, search, and custom art.
# ---------------------------------------------------------------------------

TYPE_STYLES = {
    "Fire":      {"bg": "bg-gradient-to-r from-orange-300 via-amber-200 to-yellow-100", "border": "border-orange-300", "symbol": "🔥"},
    "Water":     {"bg": "bg-gradient-to-r from-sky-300 via-cyan-200 to-blue-100",       "border": "border-blue-300",   "symbol": "💧"},
    "Lightning": {"bg": "bg-gradient-to-r from-yellow-200 via-amber-100 to-orange-50",  "border": "border-yellow-300", "symbol": "⚡"},
    "Grass":     {"bg": "bg-gradient-to-r from-lime-300 via-green-200 to-emerald-100",  "border": "border-green-300",  "symbol": "🌿"},
    "Psychic":   {"bg": "bg-gradient-to-r from-fuchsia-200 via-purple-200 to-violet-100","border": "border-purple-300", "symbol": "🔮"},
    "Fighting":  {"bg": "bg-gradient-to-r from-rose-300 via-red-200 to-orange-100",      "border": "border-red-300",    "symbol": "👊"},
    "Darkness":  {"bg": "bg-gradient-to-r from-slate-800 via-slate-700 to-zinc-600",     "border": "border-slate-700",  "symbol": "🌑"},
    "Metal":     {"bg": "bg-gradient-to-r from-slate-200 via-zinc-100 to-slate-50",      "border": "border-slate-300",  "symbol": "⚙️"},
    "Fairy":     {"bg": "bg-gradient-to-r from-pink-200 via-rose-100 to-fuchsia-50",     "border": "border-pink-300",   "symbol": "✨"},
    "Dragon":    {"bg": "bg-gradient-to-r from-indigo-300 via-violet-200 to-sky-100",    "border": "border-indigo-300", "symbol": "🐉"},
    "Colorless": {"bg": "bg-gradient-to-r from-stone-200 via-slate-100 to-white",         "border": "border-gray-200",   "symbol": "⭕"},
}

TYPE_ART_STYLES = {
    "Fire":      {"start": "#fed7aa", "end": "#ffedd5", "glow": "#fb923c", "accent": "#9a3412", "text": "#431407"},
    "Water":     {"start": "#bfdbfe", "end": "#dbeafe", "glow": "#60a5fa", "accent": "#1d4ed8", "text": "#172554"},
    "Lightning": {"start": "#fde68a", "end": "#fef3c7", "glow": "#facc15", "accent": "#a16207", "text": "#713f12"},
    "Grass":     {"start": "#bbf7d0", "end": "#dcfce7", "glow": "#4ade80", "accent": "#166534", "text": "#14532d"},
    "Psychic":   {"start": "#e9d5ff", "end": "#f3e8ff", "glow": "#c084fc", "accent": "#7e22ce", "text": "#581c87"},
    "Fighting":  {"start": "#fecaca", "end": "#fee2e2", "glow": "#f87171", "accent": "#991b1b", "text": "#450a0a"},
    "Darkness":  {"start": "#374151", "end": "#111827", "glow": "#9ca3af", "accent": "#f9fafb", "text": "#f3f4f6"},
    "Metal":     {"start": "#cbd5e1", "end": "#f1f5f9", "glow": "#94a3b8", "accent": "#334155", "text": "#0f172a"},
    "Fairy":     {"start": "#fbcfe8", "end": "#fdf2f8", "glow": "#f472b6", "accent": "#9d174d", "text": "#500724"},
    "Dragon":    {"start": "#c7d2fe", "end": "#e0e7ff", "glow": "#818cf8", "accent": "#3730a3", "text": "#312e81"},
    "Colorless": {"start": "#e5e7eb", "end": "#f8fafc", "glow": "#cbd5e1", "accent": "#475569", "text": "#0f172a"},
}

RARITY_SYMBOL = {
    "Common":    "●",
    "Uncommon":  "◆",
    "Promo":     "★",
    "Rare":      "★",
    "Rare Holo": "★✦",
    "Rare Ultra": "★★",
}


def _type_style(types):
    primary = (types or ["Colorless"])[0]
    return TYPE_STYLES.get(primary, TYPE_STYLES["Colorless"])


def _energy_symbols(cost):
    return "".join(
        TYPE_STYLES.get(c, TYPE_STYLES["Colorless"])["symbol"]
        for c in cost
    )


def _rarity_symbol(rarity: str) -> str:
    normalized = rarity.strip()
    if not normalized:
        return ""
    if normalized in RARITY_SYMBOL:
        return RARITY_SYMBOL[normalized]
    if normalized.startswith("Rare Holo"):
        return "★✦"
    if normalized.startswith("Rare "):
        return "★"
    return ""


def _format_rarity_label(rarity: str, *, source: str = "") -> str:
    normalized = rarity.strip()
    if normalized:
        symbol = _rarity_symbol(normalized)
        return f"{symbol} {normalized}".strip() if symbol else normalized
    return "Custom" if source in CUSTOM_CARD_SOURCES else ""


CARD_TYPES = tuple(TYPE_STYLES.keys())
CUSTOM_RARITIES = ("Common", "Uncommon", "Rare", "Rare Holo", "Custom")
CARD_STAGES = ("Basic", "Stage 1", "Stage 2")
CUSTOM_CARD_SOURCES = {"designed_by_llm", "designed_in_prefab"}


def _type_art_style(types):
    primary = (types or ["Colorless"])[0]
    return TYPE_ART_STYLES.get(primary, TYPE_ART_STYLES["Colorless"])


def _art_text(value, default: str, limit: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default
    if len(text) > limit:
        text = f"{text[: max(0, limit - 3)].rstrip()}..."
    return escape(text, quote=True)


def _custom_card_image_data_uri(card: dict) -> str:
    """Build a styled portrait illustration for custom cards."""
    types = card.get("types") or ["Colorless"]
    art = _type_art_style(types)
    symbol = _type_style(types)["symbol"]
    name = _art_text(card.get("name"), "Unnamed", 24)
    subtitle = _art_text(card.get("subtitle"), "Custom Pokemon", 26)
    rarity = _art_text(card.get("rarity"), "Custom", 18)
    hp = _art_text(card.get("hp"), "?", 6)
    flavor = _art_text(card.get("flavor"), "Designed in PokeLab.", 56)
    primary_type = _art_text(types[0], "Colorless", 14)
    attack_name = _art_text(
        ((card.get("attacks") or [{}])[0]).get("name"),
        "Signature Move",
        24,
    )
    secondary_badge = ""
    if len(types) > 1:
        secondary_type = _art_text(types[1], "", 14)
        secondary_badge = (
            "<g transform='translate(408 126)'>"
            "<rect x='0' y='0' width='176' height='36' rx='18' fill='white' fill-opacity='0.14'/>"
            f"<text x='88' y='24' text-anchor='middle' font-family='Segoe UI, sans-serif' font-size='16' font-weight='600' fill='{art['text']}' fill-opacity='0.84'>{secondary_type}</text>"
            "</g>"
        )

    svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 900' role='img' aria-label='{name} custom card art'>
    <defs>
        <linearGradient id='bg' x1='0%' y1='0%' x2='100%' y2='100%'>
            <stop offset='0%' stop-color='{art['start']}'/>
            <stop offset='100%' stop-color='{art['end']}'/>
        </linearGradient>
        <radialGradient id='flare' cx='80%' cy='18%' r='62%'>
            <stop offset='0%' stop-color='{art['glow']}' stop-opacity='0.95'/>
            <stop offset='100%' stop-color='{art['glow']}' stop-opacity='0'/>
        </radialGradient>
    </defs>
    <rect width='640' height='900' rx='36' fill='url(#bg)'/>
    <rect x='18' y='18' width='604' height='864' rx='30' fill='none' stroke='white' stroke-opacity='0.24' stroke-width='2'/>
    <circle cx='522' cy='166' r='164' fill='url(#flare)'/>
    <path d='M0 564 C 110 500, 214 610, 326 574 S 520 476, 640 520 L 640 900 L 0 900 Z' fill='white' fill-opacity='0.16'/>
    <path d='M34 420 C 136 362, 246 430, 344 398 S 536 314, 606 358' fill='none' stroke='white' stroke-opacity='0.22' stroke-width='14' stroke-linecap='round'/>
    <g transform='translate(52 54)'>
        <rect x='0' y='0' width='184' height='38' rx='19' fill='white' fill-opacity='0.72'/>
        <text x='18' y='25' font-family='Segoe UI, sans-serif' font-size='18' font-weight='700' fill='{art['accent']}'>CUSTOM LAB</text>
        <text x='0' y='188' font-family='Segoe UI Emoji, Segoe UI Symbol, sans-serif' font-size='120'>{symbol}</text>
        <text x='0' y='288' font-family='Segoe UI, sans-serif' font-size='50' font-weight='700' fill='{art['text']}'>{name}</text>
        <text x='0' y='326' font-family='Segoe UI, sans-serif' font-size='24' fill='{art['text']}' fill-opacity='0.78'>{subtitle}</text>
    </g>
    <g transform='translate(408 78)'>
        <rect x='0' y='0' width='176' height='40' rx='20' fill='white' fill-opacity='0.24'/>
        <text x='88' y='26' text-anchor='middle' font-family='Segoe UI, sans-serif' font-size='16' font-weight='600' fill='{art['text']}'>{primary_type}</text>
    </g>
    {secondary_badge}
    <g transform='translate(48 610)'>
        <rect x='0' y='0' width='544' height='228' rx='28' fill='white' fill-opacity='0.14'/>
        <text x='28' y='44' font-family='Segoe UI, sans-serif' font-size='18' fill='{art['text']}' fill-opacity='0.72'>Signature Move</text>
        <text x='28' y='88' font-family='Segoe UI, sans-serif' font-size='32' font-weight='700' fill='{art['text']}'>{attack_name}</text>
        <text x='28' y='130' font-family='Segoe UI, sans-serif' font-size='22' fill='{art['text']}' fill-opacity='0.74'>{flavor}</text>
        <text x='28' y='188' font-family='Segoe UI, sans-serif' font-size='20' fill='{art['text']}' fill-opacity='0.74'>{rarity} • HP {hp}</text>
        <text x='28' y='212' font-family='Segoe UI, sans-serif' font-size='16' fill='{art['text']}' fill-opacity='0.62'>Designed in PokeLab</text>
    </g>
</svg>
""".strip()
    return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"


def _card_image_url(card: dict) -> str:
    image_url = card.get("image_url", "")
    if isinstance(image_url, str) and image_url:
        return image_url
    if card.get("source") in CUSTOM_CARD_SOURCES:
        return _custom_card_image_data_uri(card)
    return ""


# ===========================================================================
# 1. LIVE LOOKUP HELPERS — Pokemon TCG API
# ===========================================================================
# Normalize remote API payloads into the smaller card shape used by both the
# raw fetch tool and the visual search app.
# ---------------------------------------------------------------------------

POKE_TCG_BASE = "https://api.pokemontcg.io/v2/cards"
POKE_TCG_API_TIMEOUT = 20
POKE_TCG_API_RETRY_TIMEOUTS = (20, 35)
POKE_TCG_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
POKE_TCG_SEARCH_FALLBACK_PAGE_SIZES = (3, 1)


def _json_get(
    url: str,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = POKE_TCG_API_TIMEOUT,
) -> tuple[int, dict]:
    if params:
        url = f"{url}?{urlencode(params)}"

    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    request = Request(url, headers=merged_headers)
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
        return response.status, json.loads(payload)


def _json_get_with_retry(
    url: str,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    retry_timeouts: tuple[float, ...] = POKE_TCG_API_RETRY_TIMEOUTS,
) -> tuple[int, dict]:
    last_error: Exception | None = None

    for timeout in retry_timeouts:
        try:
            return _json_get(url, params=params, headers=headers, timeout=timeout)
        except HTTPError as error:
            last_error = error
            if error.code not in POKE_TCG_RETRYABLE_STATUS_CODES or timeout == retry_timeouts[-1]:
                raise
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if timeout == retry_timeouts[-1]:
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Pokemon TCG fetch failed without an exception")


def _fetch_image_data_uri(url: str, *, timeout: float = 10) -> str:
    """Download an image and return it as a base64 ``data:`` URI.

    Embedding bytes inline avoids CSP / mixed-origin restrictions in MCP host
    iframes that block ``https://images.pokemontcg.io`` directly. On any
    failure we fall back to the original URL so the collection at least keeps
    a clickable link instead of crashing the renderer.
    """
    if not url:
        return ""
    try:
        request = Request(url, headers=DEFAULT_HEADERS)
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "image/png")
        if not data:
            return url
        return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return url
    except Exception:
        return url


def _pokemon_tcg_headers() -> dict[str, str]:
    headers = {}
    if api_key := os.getenv("POKEMON_TCG_API_KEY"):
        headers["X-Api-Key"] = api_key
    return headers


def _first_modifier(modifiers: list[dict] | None) -> dict | None:
    if not modifiers:
        return None
    modifier = modifiers[0] or {}
    modifier_type = str(modifier.get("type", "")).strip()
    modifier_value = str(modifier.get("value", "")).strip()
    if not modifier_type and not modifier_value:
        return None
    return {
        "type": modifier_type,
        "value": modifier_value or "—",
    }


def _normalize_real_card(card: dict, default_name: str) -> dict:
    remote_image = card.get("images", {}).get("small", "")
    return {
        "id": card.get("id", ""),
        "name": card.get("name", default_name),
        "hp": card.get("hp", "?"),
        "types": card.get("types", []) or [],
        "subtitle": (card.get("subtypes") or ["Basic"])[0],
        "attacks": [
            {
                "name": attack.get("name", ""),
                "cost": attack.get("cost", []) or [],
                "damage": attack.get("damage", ""),
                "text": attack.get("text", ""),
            }
            for attack in (card.get("attacks") or [])
        ],
        "weakness": _first_modifier(card.get("weaknesses")),
        "resistance": _first_modifier(card.get("resistances")),
        "set": (card.get("set") or {}).get("name", ""),
        "number": card.get("number", ""),
        "rarity": card.get("rarity", ""),
        "image_url": _fetch_image_data_uri(remote_image),
        "source": "pokemon_tcg_api",
    }


def _lookup_real_cards(name: str, *, page_size: int = 1) -> list[dict] | dict:
    query = name.strip()
    if not query:
        return {"error": "Pokemon name is required."}

    payload: dict | None = None
    fallback_page_sizes = [page_size]
    if page_size > 1:
        fallback_page_sizes.extend(
            size for size in POKE_TCG_SEARCH_FALLBACK_PAGE_SIZES
            if size < page_size and size not in fallback_page_sizes
        )

    try:
        for candidate_page_size in fallback_page_sizes:
            try:
                _, payload = _json_get_with_retry(
                    POKE_TCG_BASE,
                    params={"q": f"name:{query}", "pageSize": candidate_page_size, "orderBy": "set.releaseDate"},
                    headers=_pokemon_tcg_headers(),
                )
                break
            except (URLError, TimeoutError, OSError):
                if candidate_page_size == fallback_page_sizes[-1]:
                    raise
    except HTTPError as e:
        return {"error": f"Pokemon TCG API returned HTTP {e.code} for {query!r}: {e.reason}"}
    except (URLError, TimeoutError, OSError) as e:
        return {"error": f"Network error fetching {query!r}: {e}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from Pokemon TCG API for {query!r}: {e}"}
    except Exception as e:  # pragma: no cover - defensive
        return {"error": f"Unexpected error fetching {query!r}: {e}"}

    if payload is None:
        return {"error": f"No response returned for {query!r}"}

    if not isinstance(payload, dict):
        return {"error": f"Unexpected response shape for {query!r}"}

    cards = payload.get("data", []) or []
    if not cards:
        return {"error": f"No card found for {query!r}"}

    default_name = query.title()
    return [_normalize_real_card(card, default_name) for card in cards]


@mcp.tool(
    description="Fetch one live Pokemon TCG card as structured data. Use this for raw data or automation flows, not for opening the visual search UI or viewing the saved collection.",
    annotations={
        "title": "Fetch One Live Card",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
def fetch_real_card(
    name: Annotated[str, "Pokemon name to look up against the live Pokemon TCG API, such as 'charizard' or 'pikachu'."]
) -> dict:
    """Fetch one live Pokemon card as structured data.

    Sample query:
        await client.call_tool("fetch_real_card", {"name": "pikachu"})

    Args:
        name: A Pokemon name like "pikachu", "charizard", "mewtwo".

    Returns:
        A dict describing the card (id, name, hp, types, attacks, etc.)
        or {"error": "..."} if the lookup failed.
    """
    cards = _lookup_real_cards(name, page_size=1)
    if isinstance(cards, dict):
        return cards
    return cards[0]


# ===========================================================================
# 2. COLLECTION HELPERS — sandbox/collection.json
# ===========================================================================
# The collection is stored as JSON so it stays easy to inspect during demos and
# easy to diff while iterating on the server.
# ---------------------------------------------------------------------------

def _load_collection():
    if not COLLECTION_FILE.exists():
        return []
    try:
        return json.loads(COLLECTION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"PokeLab: failed to load collection ({e}); starting empty.", file=sys.stderr)
        return []


def _save_collection(cards) -> bool:
    try:
        COLLECTION_FILE.write_text(json.dumps(cards, indent=2), encoding="utf-8")
        return True
    except (OSError, TypeError) as e:
        print(f"PokeLab: failed to save collection ({e}).", file=sys.stderr)
        return False


def _collection_has_card(card_id: str, cards: list[dict] | None = None) -> bool:
    if not card_id:
        return False
    existing_cards = cards if cards is not None else _load_collection()
    return any(str(card.get("id", "")) == card_id for card in existing_cards)


def _saved_state_key(card_id: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in card_id.strip())
    if not normalized:
        normalized = "card"
    if normalized[0].isdigit():
        normalized = f"card_{normalized}"
    return f"saved_{normalized}"


@mcp.tool()
def manage_collection(action: str, card: dict | None = None, card_id: str | None = None) -> str:
    """Manage cards stored in sandbox/collection.json.

    Sample queries:
        await client.call_tool("manage_collection", {"action": "list"})
        await client.call_tool("manage_collection", {"action": "remove", "card_id": "base1-4"})
        await client.call_tool("manage_collection", {"action": "add", "card": card_payload})

    Args:
        action: One of add, list, remove, or clear.
        card: Card payload to save when action is add.
        card_id: Card id to remove when action is remove.
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
# 3. PREFAB UI HELPERS — shared renderers for collection, search, and studio
# ===========================================================================

def _save_fetched_card_action(card: dict, saved_state_key: str | None = None) -> CallTool:
    card_name = str(card.get("name", "Card")).strip() or "Card"
    on_success = [ShowToast(
        "Card saved",
        description=f"{card_name} is now in sandbox/collection.json.",
        variant="success",
    )]
    if saved_state_key:
        on_success.insert(0, SetState(saved_state_key, True))
    return CallTool(
        "manage_collection",
        arguments={"action": "add", "card": card},
        on_success=on_success,
        on_error=ShowToast("Save failed", description="{{ $error }}", variant="error"),
    )


def _attack_slots(attacks: list[dict], *, limit: int = 2) -> list[dict | None]:
    visible = list(attacks[:limit])
    return visible + [None] * max(0, limit - len(visible))


def _is_dark_type(types) -> bool:
    primary = (types or ["Colorless"])[0]
    return primary == "Darkness"


def _modifier_summary(label: str, modifier: dict | None) -> str:
    modifier_type = str((modifier or {}).get("type", "")).strip()
    modifier_value = str((modifier or {}).get("value", "")).strip() or "—"
    if not modifier_type:
        return f"{label}: —"
    symbol = TYPE_STYLES.get(modifier_type, TYPE_STYLES["Colorless"])["symbol"]
    return f"{label}: {symbol} {modifier_value}"


def _render_card_banner(
    name: str,
    subtitle: str,
    *,
    types: list[str],
    hp: str | int,
    rarity_label: str,
    bg: str,
    border_cls: str,
    compact: bool = False,
) -> None:
    style = _type_style(types)
    is_dark = _is_dark_type(types)
    type_symbols = _energy_symbols(types) or style["symbol"]
    title_cls = "text-white drop-shadow-sm" if is_dark else "text-slate-950"
    subtitle_cls = "text-white/80" if is_dark else "text-slate-700"
    ribbon_cls = (
        "rounded-full border border-white/15 bg-black/10 px-3 py-1.5 shadow-sm"
        if is_dark else
        "rounded-full border border-white/80 bg-white/80 px-3 py-1.5 shadow-sm"
    )
    rarity_cls = (
        "rounded-full border border-white/15 bg-black/10 px-3 py-1.5 text-[11px] font-semibold text-white/90 shadow-sm"
        if is_dark else
        "rounded-full border border-white/80 bg-white/80 px-3 py-1.5 text-[11px] font-semibold text-slate-700 shadow-sm"
    )
    metric_cls = (
        "rounded-2xl border border-white/15 bg-black/10 px-3 py-2 shadow-sm"
        if is_dark else
        "rounded-2xl border border-white/80 bg-white/85 px-3 py-2 shadow-sm"
    )
    type_label = (types or ["Colorless"])[0] if compact else " / ".join((types or ["Colorless"])[:2])

    with CardHeader(css_class=f"{bg} border-b {border_cls} px-4 {'pt-4 pb-3' if compact else 'pt-5 pb-4'}"):
        with Column(gap=3):
            with Row(justify="between", align="center", css_class="gap-3"):
                with Row(gap=2, align="center", css_class=ribbon_cls):
                    Text(type_symbols, css_class="text-sm")
                    Text(type_label, css_class=f"text-[11px] font-semibold uppercase tracking-[0.18em] {subtitle_cls}")
                if rarity_label:
                    Text(rarity_label, css_class=rarity_cls)

            with Row(justify="between", align="start", css_class="gap-3"):
                with Column(gap=1):
                    CardTitle(name, css_class=f"{'text-base' if compact else 'text-xl'} font-bold tracking-tight leading-none {title_cls}")
                    if subtitle:
                        CardDescription(
                            subtitle,
                            css_class=f"{'text-[13px]' if compact else 'text-sm'} font-medium {subtitle_cls}",
                        )
                with Column(gap=0, align="end", css_class=metric_cls):
                    Text(f"{hp} HP", css_class=f"{'text-base' if compact else 'text-xl'} font-black leading-none {title_cls}")
                    Text("Hit points", css_class=f"text-[10px] font-semibold uppercase tracking-[0.18em] {subtitle_cls}")


def _render_art_stage(
    img_url: str,
    *,
    name: str,
    bg: str,
    symbol: str,
    compact: bool = False,
) -> None:
    with Column(gap=0, css_class="rounded-3xl border border-amber-100 bg-gradient-to-b from-stone-200/80 via-stone-100 to-white p-3 shadow-inner"):
        if img_url:
            Image(
                src=img_url,
                alt=f"{name} Pokemon card",
                width="100%",
                height="240px" if compact else "auto",
                css_class=f"w-full rounded-2xl bg-white object-contain {'p-2' if compact else 'p-3'}",
            )
        else:
            with Column(
                align="center",
                justify="center",
                css_class=f"{bg} {'min-h-60' if compact else 'min-h-40'} rounded-2xl border border-white/50",
            ):
                Text(symbol, css_class="text-5xl opacity-30")


def _render_bound_energy_pill(field_name: str) -> None:
    for energy_type, style in TYPE_STYLES.items():
        with If(f"{field_name} == '{energy_type}'"):
            Text(
                style["symbol"],
                css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-sm shadow-sm",
            )


def _render_attack_stage(attacks: list[dict], *, compact: bool = False) -> None:
    visible_attacks = _attack_slots(attacks, limit=2) if compact else list(attacks)

    with Column(gap=3, css_class="rounded-3xl border border-amber-100 bg-white/85 px-4 py-4 shadow-sm"):
        Text(
            "Moves",
            css_class="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500",
        )

        if compact:
            for attack in visible_attacks:
                with Row(
                    justify="between",
                    align="center",
                    css_class="min-h-11 rounded-2xl border border-stone-200 bg-stone-50/90 px-3 py-2 shadow-sm",
                ):
                    if attack:
                        cost_str = _energy_symbols(attack.get("cost", []))
                        with Row(gap=2, align="center"):
                            if cost_str:
                                Text(
                                    cost_str,
                                    css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs shadow-sm",
                                )
                            Text(attack.get("name", "Move"), css_class="text-sm font-semibold text-slate-900")
                        if attack.get("damage"):
                            Text(
                                attack["damage"],
                                css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-900 shadow-sm",
                            )
                    else:
                        Muted("No second move listed", css_class="text-xs italic text-stone-500")
        elif visible_attacks:
            with Column(gap=2):
                for atk in visible_attacks:
                    cost_str = _energy_symbols(atk.get("cost", []))
                    dmg = atk.get("damage", "")

                    with Column(gap=2, css_class="rounded-2xl border border-stone-200 bg-stone-50/90 px-3 py-3 shadow-sm"):
                        with Row(justify="between", align="center", css_class="gap-2"):
                            with Row(gap=2, align="center"):
                                if cost_str:
                                    Text(
                                        cost_str,
                                        css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs shadow-sm",
                                    )
                                Text(atk["name"], css_class="text-sm font-semibold text-slate-900")
                            if dmg:
                                Text(
                                    dmg,
                                    css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-900 shadow-sm",
                                )
                        if atk.get("text"):
                            Muted(atk["text"], css_class="text-xs leading-relaxed text-slate-600")
        else:
            Muted("No moves listed for this card.", css_class="text-xs italic text-stone-500")


def _render_search_result_card(
    card: dict,
    *,
    save_action: CallTool | None = None,
    saved_state_key: str | None = None,
) -> None:
    """Render a compact card tile for the live-search grid."""
    types = card.get("types") or ["Colorless"]
    style = _type_style(types)
    symbol = style["symbol"]
    bg = style["bg"]
    name = card.get("name", "Unknown")
    hp = card.get("hp", "?")
    rarity = card.get("rarity", "") or "Unknown"
    rarity_label = _format_rarity_label(rarity, source=str(card.get("source", "")))
    subtitle = card.get("subtitle", "")
    set_name = card.get("set", "")
    number = card.get("number", "")
    img_url = _card_image_url(card)
    attacks = card.get("attacks") or []
    weakness = card.get("weakness")
    resistance = card.get("resistance")
    subtitle_text = f"{subtitle} · {set_name}" if subtitle and set_name else subtitle or set_name

    with Card(css_class="flex h-full flex-col overflow-hidden rounded-3xl border border-amber-100/80 bg-gradient-to-b from-white via-amber-50/70 to-stone-100/80 shadow-lg ring-1 ring-black/5 hover:-translate-y-1 hover:shadow-2xl transition-all duration-200"):
        _render_card_banner(
            name,
            subtitle_text,
            types=types,
            hp=hp,
            rarity_label=rarity_label,
            bg=bg,
            border_cls=style["border"],
            compact=True,
        )

        with CardContent(css_class="flex-1"):
            with Column(gap=3):
                _render_art_stage(img_url, name=name, bg=bg, symbol=symbol, compact=True)
                _render_attack_stage(attacks, compact=True)

        with CardFooter(css_class="border-t border-stone-200 bg-stone-50/85"):
            with Column(gap=2, css_class="w-full"):
                with Row(justify="between", align="start", css_class="gap-2"):
                    with Column(gap=1):
                        Muted(_modifier_summary("Weak", weakness), css_class="text-xs text-stone-600")
                        Muted(_modifier_summary("Resist", resistance), css_class="text-xs text-stone-600")
                    if set_name or number:
                        Muted(
                            f"{set_name} #{number}" if number else set_name,
                            css_class="text-xs text-right text-stone-600",
                        )
                if saved_state_key:
                    with Row(justify="between", align="center", css_class="gap-3"):
                        with If(saved_state_key):
                            Badge("Saved to collection", variant="secondary", css_class="text-xs")
                        with If(f"!{saved_state_key}"):
                            Muted("Archive this print in your collection.", css_class="text-xs text-stone-600")
                        if save_action is not None:
                            with If(f"!{saved_state_key}"):
                                Button("Save print", icon="save", variant="success", on_click=save_action)


def _render_app_shell_header(
    title: str,
    description: str,
    meta_items: list[str] | None = None,
    *,
    icon: str = "✦",
) -> None:
    with Row(justify="between", align="start", css_class="gap-4"):
        with Column(gap=1):
            with Row(gap=2, align="center"):
                Text(icon, css_class="text-lg text-amber-300")
                CardTitle(title, css_class="text-xl tracking-tight text-white")
            CardDescription(description, css_class="text-sm text-slate-300")

        if meta_items:
            with Row(gap=2, css_class="flex-wrap justify-end"):
                for item in meta_items:
                    Text(
                        item,
                        css_class="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200",
                    )


def _render_card(
    card: dict,
    *,
    save_action: CallTool | None = None,
    saved_state_key: str | None = None,
) -> None:
    """Render one full-size collection card with shared card chrome."""
    types    = card.get("types") or ["Colorless"]
    style    = _type_style(types)
    bg       = style["bg"]
    symbol   = style["symbol"]
    name     = card.get("name", "Unknown")
    hp       = card.get("hp", "?")
    rarity   = card.get("rarity", "")
    rarity_label = _format_rarity_label(rarity, source=str(card.get("source", "")))
    subtitle = card.get("subtitle", "")
    set_name = card.get("set", "")
    number = card.get("number", "")
    img_url = _card_image_url(card)

    with Card(css_class="flex h-full flex-col overflow-hidden rounded-3xl border border-amber-100/80 bg-gradient-to-b from-white via-amber-50/70 to-stone-100/80 shadow-lg ring-1 ring-black/5 hover:-translate-y-1 hover:shadow-2xl transition-all duration-200"):
        _render_card_banner(
            name,
            subtitle,
            types=types,
            hp=hp,
            rarity_label=rarity_label,
            bg=bg,
            border_cls=style["border"],
        )

        with CardContent(css_class="flex-1"):
            with Column(gap=4):
                _render_art_stage(img_url, name=name, bg=bg, symbol=symbol)
                _render_attack_stage(card.get("attacks", []))

        with CardFooter(css_class="border-t border-stone-200 bg-stone-50/85"):
            with Column(gap=2, css_class="w-full"):
                with Row(justify="between", align="start", css_class="gap-3"):
                    with Column(gap=1):
                        Muted(_modifier_summary("Weak", card.get("weakness")), css_class="text-xs text-stone-600")
                        Muted(_modifier_summary("Resist", card.get("resistance")), css_class="text-xs text-stone-600")
                    if set_name or number:
                        Muted(
                            f"{set_name} #{number}" if number else set_name,
                            css_class="text-xs text-right text-stone-600",
                        )
                if card.get("source") in CUSTOM_CARD_SOURCES:
                    Muted("✦ Custom", css_class="text-xs text-stone-600")
                if card.get("flavor"):
                    Muted(card["flavor"], css_class="text-xs italic leading-relaxed text-stone-600")
                if saved_state_key:
                    with Row(justify="between", align="center", css_class="gap-3"):
                        with If(saved_state_key):
                            Badge("Saved to collection", variant="secondary", css_class="text-xs")
                        with If(f"!{saved_state_key}"):
                            Muted("Archive this card in your collection.", css_class="text-xs text-stone-600")
                        if save_action is not None:
                            with If(f"!{saved_state_key}"):
                                Button("Save to collection", icon="save", variant="success", on_click=save_action)


@mcp.tool(
    app=True,
    description="Open the saved Pokelab collection dashboard from sandbox/collection.json. Use only for cards already saved in the collection; do not use this tool for live Pokemon TCG search or preview.",
    annotations={
        "title": "View Saved Collection",
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def card_lab() -> PrefabApp:
    """Open the saved-card collection dashboard.

    Sample query:
        await client.call_tool("card_lab", {})
    """
    cards = _load_collection()
    count_label = f"{len(cards)} card{'s' if len(cards) != 1 else ''}"

    with PrefabApp() as app:
        with Column(gap=4, css_class="max-w-5xl mx-auto p-6"):
            with Card():
                with CardHeader():
                    _render_app_shell_header(
                        "My Pokemon Collection",
                        f"{count_label} stored in sandbox/collection.json.",
                        ["Collection lab", "Prefab UI"],
                    )
                with CardContent():
                    if not cards:
                        with Column(gap=2, align="center", css_class="py-12"):
                            Text("🃏", css_class="text-6xl opacity-30")
                            Muted("No cards yet. Call fetch_real_card then manage_collection to add some.")
                    else:
                        with Grid(columns=1, gap=4, css_class="md:grid-cols-2 lg:grid-cols-3"):
                            for card in cards:
                                _render_card(card)

    return app


@mcp.tool(
    app=True,
    description="Search the live Pokemon TCG API for cards matching a Pokemon name and open the visual results grid with inline save buttons. Use this for preview, search, browse, or inspect requests; do not use it to show the existing saved collection.",
    annotations={
        "title": "Search Live TCG Cards",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)
def preview_real_card(
    name: Annotated[str, "Pokemon name to search for in the live Pokemon TCG API, such as 'charizard' or 'pikachu'."]
) -> PrefabApp:
    """Open the live Pokemon TCG search UI with inline save controls.

    Sample query:
        await client.call_tool("preview_real_card", {"name": "charizard"})
    """
    cards_or_error = _lookup_real_cards(name, page_size=6)
    cards: list[dict] = []
    error_message = ""
    initial_state: dict[str, bool] = {}

    if isinstance(cards_or_error, dict):
        error_message = cards_or_error["error"]
    else:
        cards = cards_or_error
        collection = _load_collection()
        initial_state = {
            _saved_state_key(str(card.get("id", ""))): _collection_has_card(str(card.get("id", "")), collection)
            for card in cards
        }

    with PrefabApp(state=initial_state) as app:
        with Column(gap=4, css_class="max-w-6xl mx-auto p-6"):
            with Card():
                with CardHeader():
                    if cards:
                        _render_app_shell_header(
                            "Pokemon TCG search",
                            f"Showing {len(cards)} live match{'es' if len(cards) != 1 else ''} for {name.strip()!r}. Save any print directly from this view.",
                            ["Live TCG API", "Inline save"],
                            icon="◈",
                        )
                    else:
                        _render_app_shell_header(
                            "Pokemon TCG search",
                            "Fetched live from the Pokemon TCG API. Save any card only if you want to keep it.",
                            ["Live TCG API", "Inline save"],
                            icon="◈",
                        )

                with CardContent():
                    if error_message:
                        with Card(css_class="border border-red-200 shadow-sm"):
                            with CardHeader():
                                CardTitle("Could not fetch card", css_class="text-lg text-red-700")
                            with CardContent():
                                Muted(error_message, css_class="text-sm text-red-700")
                    else:
                        with Grid(columns=1, gap=4, css_class="sm:grid-cols-2 xl:grid-cols-3"):
                            for card in cards:
                                state_key = _saved_state_key(str(card.get("id", "")))
                                _render_search_result_card(
                                    card,
                                    save_action=_save_fetched_card_action(card, state_key),
                                    saved_state_key=state_key,
                                )

    return app


# ===========================================================================
# 4. CARD STUDIO HELPERS — deterministic custom-card generation and UI
# ===========================================================================

def _coerce_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _choice(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def _boolish(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _custom_attack(name: str, cost: str, damage: str, text: str) -> dict | None:
    if not any((name, damage, text)):
        return None
    energy_type = _choice(cost, CARD_TYPES, "Colorless")
    return {
        "name": name.strip() or "Tackle",
        "cost": [energy_type],
        "damage": damage.strip(),
        "text": text.strip(),
    }


def _next_custom_id(cards: list[dict]) -> str:
    existing_ids = []
    for card in cards:
        card_id = str(card.get("id", ""))
        if card_id.startswith("custom-"):
            try:
                existing_ids.append(int(card_id.removeprefix("custom-")))
            except ValueError:
                pass
    next_id = max(existing_ids, default=0) + 1
    return f"custom-{next_id:03d}"


def _build_custom_card(
    *,
    card_id: str,
    name: str,
    hp,
    primary_type: str,
    secondary_type: str = "",
    stage: str = "Basic",
    rarity: str = "Rare",
    attack_1_name: str = "",
    attack_1_cost: str = "Colorless",
    attack_1_damage: str = "",
    attack_1_text: str = "",
    attack_2_name: str = "",
    attack_2_cost: str = "Colorless",
    attack_2_damage: str = "",
    attack_2_text: str = "",
    weakness_type: str = "Water",
    weakness_value: str = "x2",
    resistance_type: str = "",
    resistance_value: str = "-30",
    flavor: str = "",
    illustrator: str = "PokeLab",
    holo=False,
    first_edition=False,
    notes: str = "",
) -> dict:
    primary = _choice(primary_type, CARD_TYPES, "Colorless")
    secondary = secondary_type if secondary_type in CARD_TYPES and secondary_type != primary else ""
    attacks = [
        attack for attack in (
            _custom_attack(attack_1_name, attack_1_cost, attack_1_damage, attack_1_text),
            _custom_attack(attack_2_name, attack_2_cost, attack_2_damage, attack_2_text),
        ) if attack
    ]

    card = {
        "id": card_id,
        "name": name.strip() or "Unnamed",
        "hp": str(_coerce_int(hp, default=80, minimum=30, maximum=220)),
        "types": [primary, *([secondary] if secondary else [])],
        "subtitle": stage if stage in CARD_STAGES else "Basic",
        "attacks": attacks,
        "weakness": {
            "type": _choice(weakness_type, CARD_TYPES, "Colorless"),
            "value": weakness_value.strip() or "x2",
        },
        "resistance": (
            {
                "type": resistance_type,
                "value": resistance_value.strip() or "-30",
            }
            if resistance_type in CARD_TYPES else None
        ),
        "set": "Custom Lab",
        "number": card_id.replace("custom-", "C"),
        "rarity": _choice(rarity, CUSTOM_RARITIES, "Custom"),
        "flavor": flavor.strip(),
        "illustrator": illustrator.strip() or "PokeLab",
        "holo": _boolish(holo),
        "first_edition": _boolish(first_edition),
        "notes": notes.strip(),
        "image_url": "",
        "source": "designed_in_prefab",
    }
    card["image_url"] = _custom_card_image_data_uri(card)
    return card


@mcp.tool()
def save_custom_card(
    name: str,
    hp: int | str = 80,
    primary_type: str = "Fire",
    secondary_type: str = "Fairy",
    stage: str = "Basic",
    rarity: str = "Rare",
    attack_1_name: str = "Temple Wick",
    attack_1_cost: str = "Fire",
    attack_1_damage: str = "30",
    attack_1_text: str = "Heal 10 damage from this Pokemon.",
    attack_2_name: str = "Fairy Flare",
    attack_2_cost: str = "Fairy",
    attack_2_damage: str = "60+",
    attack_2_text: str = "If this Pokemon has a status condition, this attack does 30 more damage.",
    weakness_type: str = "Water",
    weakness_value: str = "x2",
    resistance_type: str = "",
    resistance_value: str = "-30",
    flavor: str = "Small temple flames gather around it when wishes are spoken.",
    illustrator: str = "PokeLab",
    holo: bool | str = True,
    first_edition: bool | str = False,
    notes: str = "",
) -> dict:
    """Save a custom card submitted from the Prefab designer UI.

    Sample query:
        await client.call_tool("save_custom_card", {"name": "Embersprite", "primary_type": "Fire"})
    """
    cards = _load_collection()
    card = _build_custom_card(
        card_id=_next_custom_id(cards),
        name=name,
        hp=hp,
        primary_type=primary_type,
        secondary_type=secondary_type,
        stage=stage,
        rarity=rarity,
        attack_1_name=attack_1_name,
        attack_1_cost=attack_1_cost,
        attack_1_damage=attack_1_damage,
        attack_1_text=attack_1_text,
        attack_2_name=attack_2_name,
        attack_2_cost=attack_2_cost,
        attack_2_damage=attack_2_damage,
        attack_2_text=attack_2_text,
        weakness_type=weakness_type,
        weakness_value=weakness_value,
        resistance_type=resistance_type,
        resistance_value=resistance_value,
        flavor=flavor,
        illustrator=illustrator,
        holo=holo,
        first_edition=first_edition,
        notes=notes,
    )
    cards.append(card)
    _save_collection(cards)
    return {"message": f"Saved {card['name']} as {card['id']}", "card": card}


def _select_options(options: tuple[str, ...]) -> None:
    for option in options:
        SelectOption(option, value=option)


def _save_card_action() -> CallTool:
    return CallTool(
        "save_custom_card",
        arguments={
            "name": "{{ name }}",
            "hp": "{{ hp }}",
            "primary_type": "{{ primary_type }}",
            "secondary_type": "{{ secondary_type }}",
            "stage": "{{ stage }}",
            "rarity": "{{ rarity }}",
            "attack_1_name": "{{ attack_1_name }}",
            "attack_1_cost": "{{ attack_1_cost }}",
            "attack_1_damage": "{{ attack_1_damage }}",
            "attack_1_text": "{{ attack_1_text }}",
            "attack_2_name": "{{ attack_2_name }}",
            "attack_2_cost": "{{ attack_2_cost }}",
            "attack_2_damage": "{{ attack_2_damage }}",
            "attack_2_text": "{{ attack_2_text }}",
            "weakness_type": "{{ weakness_type }}",
            "weakness_value": "{{ weakness_value }}",
            "resistance_type": "{{ resistance_type }}",
            "resistance_value": "{{ resistance_value }}",
            "flavor": "{{ flavor }}",
            "illustrator": "{{ illustrator }}",
            "holo": "{{ holo }}",
            "first_edition": "{{ first_edition }}",
            "notes": "{{ notes }}",
        },
        on_success=ShowToast(
            "Card saved",
            description="{{ name }} is now in sandbox/collection.json.",
            variant="success",
        ),
        on_error=ShowToast("Save failed", description="{{ $error }}", variant="error"),
    )


def _render_live_card_preview() -> None:
    with Card(css_class="flex flex-col overflow-hidden rounded-3xl border border-amber-100/80 bg-gradient-to-b from-white via-amber-50/70 to-stone-100/80 shadow-lg ring-1 ring-black/5"):
        with CardHeader(css_class="bg-gradient-to-r from-amber-200 via-orange-100 to-yellow-50 border-b border-amber-300 px-4 pt-5 pb-4"):
            with Column(gap=3):
                with Row(justify="between", align="center", css_class="gap-3"):
                    with Row(gap=2, align="center", css_class="rounded-full border border-white/80 bg-white/80 px-3 py-1.5 shadow-sm"):
                        Text("{{ primary_type }}", css_class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-700")
                    Text("{{ rarity }}", css_class="rounded-full border border-white/80 bg-white/80 px-3 py-1.5 text-[11px] font-semibold text-slate-700 shadow-sm")
                with Row(justify="between", align="start", css_class="gap-3"):
                    with Column(gap=1):
                        CardTitle("{{ name }}", css_class="text-xl font-bold tracking-tight text-slate-950")
                        CardDescription(
                            "{{ secondary_type ? stage + ' · ' + primary_type + ' / ' + secondary_type : stage + ' · ' + primary_type }}",
                            css_class="text-sm font-medium text-slate-700",
                        )
                    with Column(gap=0, align="end", css_class="rounded-2xl border border-white/80 bg-white/85 px-3 py-2 shadow-sm"):
                        Text("{{ hp }} HP", css_class="text-xl font-black text-slate-900")
                        Text("Hit points", css_class="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-600")
        with CardContent(css_class="flex-1"):
            with Column(gap=4):
                with Column(gap=1, css_class="rounded-3xl border border-amber-100 bg-gradient-to-b from-stone-200/80 via-stone-100 to-white px-4 py-5 shadow-inner"):
                    Text("Card concept", css_class="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500")
                    Muted("{{ notes }}", css_class="text-xs leading-relaxed text-slate-600")
                with Row(justify="between", align="center", css_class="flex-wrap gap-2 rounded-full border border-stone-200 bg-stone-100/80 px-3 py-2"):
                    with Row(gap=2, css_class="flex-wrap"):
                        Text("{{ primary_type }}", css_class="rounded-full border border-white bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-slate-700 shadow-sm")
                        Text("{{ holo ? 'Holo' : 'Matte' }}", css_class="rounded-full border border-white bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-slate-700 shadow-sm")
                    Text("{{ first_edition ? '1st Edition' : 'Standard print' }}", css_class="text-[11px] font-semibold uppercase tracking-[0.16em] text-stone-600")
                with Column(gap=3, css_class="rounded-3xl border border-amber-100 bg-white/85 px-4 py-4 shadow-sm"):
                    Text("Moves", css_class="text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500")
                    with Column(gap=2, css_class="rounded-2xl border border-stone-200 bg-stone-50/90 px-3 py-3 shadow-sm"):
                        with Row(justify="between", align="center", css_class="gap-2"):
                            with Row(gap=2, align="center"):
                                _render_bound_energy_pill("attack_1_cost")
                                Text("{{ attack_1_name }}", css_class="text-sm font-semibold text-slate-900")
                            Text("{{ attack_1_damage }}", css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-900 shadow-sm")
                        Muted("{{ attack_1_text }}", css_class="text-xs leading-relaxed text-slate-600")
                    with Column(gap=2, css_class="rounded-2xl border border-stone-200 bg-stone-50/90 px-3 py-3 shadow-sm"):
                        with Row(justify="between", align="center", css_class="gap-2"):
                            with Row(gap=2, align="center"):
                                _render_bound_energy_pill("attack_2_cost")
                                Text("{{ attack_2_name }}", css_class="text-sm font-semibold text-slate-900")
                            Text("{{ attack_2_damage }}", css_class="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-900 shadow-sm")
                        Muted("{{ attack_2_text }}", css_class="text-xs leading-relaxed text-slate-600")
        with CardFooter(css_class="border-t border-stone-200 bg-stone-50/85"):
            with Column(gap=2, css_class="w-full"):
                with Row(justify="between", align="start", css_class="gap-3"):
                    with Column(gap=1):
                        Muted(
                            "{{ weakness_type ? 'Weak: ' + weakness_type + ' ' + weakness_value : 'Weak: —' }}",
                            css_class="text-xs text-stone-600",
                        )
                        Muted(
                            "{{ resistance_type ? 'Resist: ' + resistance_type + ' ' + resistance_value : 'Resist: —' }}",
                            css_class="text-xs text-stone-600",
                        )
                    Muted("{{ illustrator }}", css_class="text-xs text-right text-stone-600")
                Muted("{{ flavor }}", css_class="text-xs italic leading-relaxed text-stone-600")


@mcp.tool(app=True)
def design_card() -> PrefabApp:
    """Open the interactive Prefab card designer.

    Sample query:
        await client.call_tool("design_card", {})
    """
    initial_state = {
        "name": "Embersprite",
        "hp": 80,
        "primary_type": "Fire",
        "secondary_type": "Fairy",
        "stage": "Basic",
        "rarity": "Rare Holo",
        "attack_1_name": "Temple Wick",
        "attack_1_cost": "Fire",
        "attack_1_damage": "30",
        "attack_1_text": "Heal 10 damage from this Pokemon.",
        "attack_2_name": "Fairy Flare",
        "attack_2_cost": "Fairy",
        "attack_2_damage": "60+",
        "attack_2_text": "If this Pokemon has a status condition, this attack does 30 more damage.",
        "weakness_type": "Water",
        "weakness_value": "x2",
        "resistance_type": "",
        "resistance_value": "-30",
        "flavor": "Small temple flames gather around it when wishes are spoken.",
        "illustrator": "PokeLab",
        "holo": True,
        "first_edition": False,
        "notes": "Balanced for a fast Basic card with a light sustain hook.",
    }

    with PrefabApp(state=initial_state) as app:
        with Column(gap=5, css_class="max-w-6xl mx-auto p-6"):
            with Row(justify="between", align="center"):
                with Column(gap=1):
                    Text("PokéLab Card Studio", css_class="text-2xl font-bold")
                    Muted("Build a custom card with Prefab controls, preview it live, then save it to the collection.")
                Button("Save card", icon="save", variant="success", on_click=_save_card_action())

            with Grid(columns=[2, 1], gap=4):
                with Tabs(value="identity", variant="line"):
                    with Tab("Identity", value="identity"):
                        with Card():
                            with CardHeader():
                                CardTitle("Card identity")
                                CardDescription("Names, types, rarity, and collection metadata.")
                            with CardContent():
                                with Grid(columns=2, gap=4):
                                    with Column(gap=2):
                                        Text("Name", css_class="text-sm font-medium")
                                        Input(name="name", placeholder="Embersprite", required=True)
                                    with Column(gap=2):
                                        Text("Stage", css_class="text-sm font-medium")
                                        with RadioGroup(name="stage"):
                                            with Row(gap=3):
                                                for stage in CARD_STAGES:
                                                    Radio(option=stage, label=stage)
                                    with Column(gap=2):
                                        Text("Primary type", css_class="text-sm font-medium")
                                        with Select(name="primary_type", placeholder="Choose a type"):
                                            _select_options(CARD_TYPES)
                                    with Column(gap=2):
                                        Text("Secondary type", css_class="text-sm font-medium")
                                        with Select(name="secondary_type", placeholder="Optional"):
                                            SelectOption("None", value="")
                                            _select_options(CARD_TYPES)
                                    with Column(gap=2):
                                        Text("Rarity", css_class="text-sm font-medium")
                                        with Select(name="rarity", placeholder="Choose rarity"):
                                            _select_options(CUSTOM_RARITIES)
                                    with Column(gap=2):
                                        Text("Illustrator", css_class="text-sm font-medium")
                                        Input(name="illustrator", placeholder="PokeLab")

                    with Tab("Stats", value="stats"):
                        with Card():
                            with CardHeader():
                                CardTitle("Battle stats")
                                CardDescription("Tune HP, attacks, weakness, resistance, and battle flavor.")
                            with CardContent():
                                with Column(gap=4):
                                    with Grid(columns=3, gap=4):
                                        Metric(label="HP", value="{{ hp }}", description="30 to 220")
                                        Metric(label="Primary", value="{{ primary_type }}", description="Main energy")
                                        Metric(label="Rarity", value="{{ rarity }}", description="Print style")
                                    with Column(gap=2):
                                        with Row(justify="between", align="center"):
                                            Text("HP", css_class="text-sm font-medium")
                                            Badge("{{ hp }}", variant="warning")
                                        # Slider state already binds through `name`. Passing
                                        # `value="{{ hp }}"` here would send a templated string
                                        # and fail the Prefab slider prop validator.
                                        Slider(name="hp", min=30, max=220, step=10)
                                    Separator()
                                    with Grid(columns=2, gap=4):
                                        with Column(gap=2):
                                            Text("Attack 1", css_class="text-sm font-medium")
                                            Input(name="attack_1_name", placeholder="Attack name")
                                            with Select(name="attack_1_cost", placeholder="Energy cost"):
                                                _select_options(CARD_TYPES)
                                            Input(name="attack_1_damage", placeholder="30", input_type="text")
                                            Textarea(name="attack_1_text", rows=3, placeholder="One short rules sentence")
                                        with Column(gap=2):
                                            Text("Attack 2", css_class="text-sm font-medium")
                                            Input(name="attack_2_name", placeholder="Attack name")
                                            with Select(name="attack_2_cost", placeholder="Energy cost"):
                                                _select_options(CARD_TYPES)
                                            Input(name="attack_2_damage", placeholder="60+", input_type="text")
                                            Textarea(name="attack_2_text", rows=3, placeholder="One short rules sentence")

                    with Tab("Finish", value="finish"):
                        with Card():
                            with CardHeader():
                                CardTitle("Finishing touches")
                                CardDescription("Use optional controls to make the card feel collectible.")
                            with CardContent():
                                with Column(gap=4):
                                    with Grid(columns=2, gap=4):
                                        with Column(gap=2):
                                            Text("Weakness type", css_class="text-sm font-medium")
                                            with Select(name="weakness_type", placeholder="Choose weakness"):
                                                _select_options(CARD_TYPES)
                                        with Column(gap=2):
                                            Text("Weakness value", css_class="text-sm font-medium")
                                            Input(name="weakness_value", placeholder="x2")
                                        with Column(gap=2):
                                            Text("Resistance type", css_class="text-sm font-medium")
                                            with Select(name="resistance_type", placeholder="Optional"):
                                                SelectOption("None", value="")
                                                _select_options(CARD_TYPES)
                                        with Column(gap=2):
                                            Text("Resistance value", css_class="text-sm font-medium")
                                            Input(name="resistance_value", placeholder="-30")
                                    with Row(gap=4, align="center"):
                                        # Boolean controls also bind through `name`. Passing a
                                        # templated `value` like `"{{ holo }}"` would turn the
                                        # prop into a string and break validation.
                                        Switch(name="holo", label="Holographic finish")
                                        Checkbox(name="first_edition", label="First edition stamp")
                                    Textarea(name="flavor", rows=3, placeholder="Flavor text")
                                    with Accordion(default_open_items=0):
                                        with AccordionItem("Designer notes", value="notes"):
                                            Textarea(name="notes", rows=4, placeholder="Private balancing notes")
                                    with Row(gap=2):
                                        Button("Save card", icon="save", variant="success", on_click=_save_card_action())
                                        Button(
                                            "Open collection next",
                                            icon="layout-grid",
                                            variant="secondary",
                                            on_click=ShowToast(
                                                "After saving, call card_lab() to view the collection.",
                                                variant="info",
                                            ),
                                        )

                with Column(gap=4):
                    _render_live_card_preview()

    return app


# ===========================================================================
# 5. MCP PROMPT — guided demo shortcut
# ===========================================================================

@mcp.prompt()
def design_card_walkthrough() -> str:
    """Walk a new user through the PokéLab demo end-to-end."""
    return (
        "I want to try the PokéLab MCP server. Please:\n"
        "1. Prefer the visual PokéLab app tools over raw JSON tools whenever possible.\n"
        "2. Open a visual real-card search for Pikachu so I can inspect and save a print inline.\n"
        "3. Then open a visual real-card search for Charizard.\n"
        "4. Show me my saved collection in the Prefab card lab.\n"
        "5. Then open design_card so I can create a custom card in the Prefab UI.\n"
    )


if __name__ == "__main__":
    print(f"PokeLab starting -- sandbox: {SANDBOX}", file=sys.stderr)
    mcp.run()
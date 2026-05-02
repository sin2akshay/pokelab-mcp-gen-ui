"""
PokéLab — an MCP server that fetches, saves, designs, and renders Pokemon cards.

Stitches together every Session 4 pattern:
    Lesson 01  @mcp.tool(), file CRUD, sandbox folder, HTTP fetch
  Lesson 02  mcp.run() entry point, stdio transport
  Lesson 04A Prefab DSL, nested with-blocks
  Lesson 04B Rx + SetState reactive state
  Lesson 04C @mcp.tool(app=True) returning a PrefabApp
    Lesson 04D Talk-to-App pattern — structured inputs, Python renders them

Tools exposed:
  fetch_real_card(name)       — internet:    Pokemon TCG API (includes card image)
    preview_real_card(name)     — Prefab UI:   visual real-card search with inline save
  manage_collection(action,…) — file CRUD:   sandbox/collection.json
  refresh_collection_images() — internet:    backfills image URLs for old saved cards
  card_lab()                  — Prefab UI:   renders collection as a styled grid
    design_card()               — Prefab UI:   form-driven custom card designer
    save_custom_card(...)       — file CRUD:   saves a designed card from the UI

Run:
    python server.py                    # stdio mode for Claude Desktop
    fastmcp dev inspector server.py     # MCP Inspector for tool testing
    fastmcp dev apps server.py          # browser preview for app-returning tools
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# Default User-Agent — pokemontcg.io / its CDN reject the default
# `Python-urllib/3.x` UA with HTTP 403, so every outbound request goes through
# this header set.
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
    Progress,
    Radio,
    RadioGroup,
    Row,
    Separator,
    Select,
    SelectOption,
    Slider,
    Switch,
    Tab,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    Text,
    Textarea,
)
from prefab_ui.components.control_flow import If

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
# 1. INTERNET TOOL — Pokemon TCG API
# ===========================================================================
# Returns normalized card dicts — only the fields we render.
# Trimming the response keeps tokens down when the model passes the result
# back to itself or when a visual search renders multiple matches.
# ---------------------------------------------------------------------------

POKE_TCG_BASE = "https://api.pokemontcg.io/v2/cards"


def _json_get(
    url: str,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> tuple[int, dict]:
    if params:
        url = f"{url}?{urlencode(params)}"

    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    request = Request(url, headers=merged_headers)
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
        return response.status, json.loads(payload)


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
        "image_remote_url": remote_image,
        "source": "pokemon_tcg_api",
    }


def _lookup_real_cards(name: str, *, page_size: int = 1) -> list[dict] | dict:
    query = name.strip()
    if not query:
        return {"error": "Pokemon name is required."}

    try:
        _, payload = _json_get(
            POKE_TCG_BASE,
            params={"q": f"name:{query}", "pageSize": page_size, "orderBy": "set.releaseDate"},
            headers=_pokemon_tcg_headers(),
            timeout=10,
        )
    except HTTPError as e:
        return {"error": f"Pokemon TCG API returned HTTP {e.code} for {query!r}: {e.reason}"}
    except (URLError, TimeoutError) as e:
        return {"error": f"Network error fetching {query!r}: {e}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from Pokemon TCG API for {query!r}: {e}"}
    except Exception as e:  # pragma: no cover - defensive
        return {"error": f"Unexpected error fetching {query!r}: {e}"}

    if not isinstance(payload, dict):
        return {"error": f"Unexpected response shape for {query!r}"}

    cards = payload.get("data", []) or []
    if not cards:
        return {"error": f"No card found for {query!r}"}

    default_name = query.title()
    return [_normalize_real_card(card, default_name) for card in cards]


@mcp.tool()
def fetch_real_card(name: str) -> dict:
    """Fetch a real Pokemon card by name from the Pokemon TCG API.

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
    failed = 0
    headers = {}
    if api_key := os.getenv("POKEMON_TCG_API_KEY"):
        headers["X-Api-Key"] = api_key

    for card in cards:
        existing = card.get("image_url", "")
        is_custom = card.get("source") in CUSTOM_CARD_SOURCES
        is_data_uri = isinstance(existing, str) and existing.startswith("data:")
        if is_custom:
            if is_data_uri:
                skipped += 1
            else:
                card["image_url"] = _custom_card_image_data_uri(card)
                updated += 1
            continue
        if is_data_uri:
            skipped += 1
            continue
        card_id = card.get("id", "")
        if not card_id:
            failed += 1
            continue
        try:
            status, payload = _json_get(
                f"{POKE_TCG_BASE}/{card_id}",
                headers=headers,
                timeout=10,
            )
            if status == 200 and isinstance(payload, dict):
                img = (payload.get("data") or {}).get("images", {}).get("small", "")
                if img:
                    card["image_remote_url"] = img
                    card["image_url"] = _fetch_image_data_uri(img)
                    updated += 1
                else:
                    failed += 1
            elif existing:
                # Already had a remote URL — re-embed as data URI so the host
                # iframe can render it without external network access.
                card["image_remote_url"] = existing if not existing.startswith("data:") else card.get("image_remote_url", "")
                card["image_url"] = _fetch_image_data_uri(card.get("image_remote_url") or existing)
                updated += 1
            else:
                failed += 1
            time.sleep(0.1)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            print(f"PokeLab: refresh failed for {card_id}: {e}", file=sys.stderr)
            failed += 1
        except Exception as e:  # pragma: no cover - defensive
            print(f"PokeLab: unexpected error refreshing {card_id}: {e}", file=sys.stderr)
            failed += 1

    saved = _save_collection(cards)
    suffix = "" if saved else " (WARNING: could not persist collection.json)"
    return (
        f"Done. Updated {updated} cards with embedded images, skipped {skipped}, "
        f"failed {failed}.{suffix}"
    )


# ===========================================================================
# 3. PREFAB UI — redesigned card renderer + card_lab grid
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


def _render_modifier_panel(label: str, modifier: dict | None, *, compact: bool = False) -> None:
    modifier_type = str((modifier or {}).get("type", "")).strip()
    modifier_value = str((modifier or {}).get("value", "")).strip() or "—"
    symbol = TYPE_STYLES.get(modifier_type, TYPE_STYLES["Colorless"])["symbol"] if modifier_type else "—"
    value_text = f"{symbol} {modifier_value}" if modifier_type else "—"
    width_cls = "min-w-24" if compact else "min-w-28"
    padding_cls = "px-2.5 py-1.5" if compact else "px-3 py-2"

    with Column(gap=0, css_class=f"{width_cls} rounded-xl border border-slate-200/80 bg-white/80 {padding_cls} shadow-sm"):
        Text(label, css_class="text-xs font-semibold uppercase tracking-widest text-slate-500")
        Text(value_text, css_class="text-sm font-semibold text-slate-900")
        if not compact:
            Muted(modifier_type or "Not listed", css_class="text-xs")


def _render_search_result_card(
    card: dict,
    *,
    save_action: CallTool | None = None,
    saved_state_key: str | None = None,
) -> None:
    """Render a compact card tile for the live TCG search grid."""
    types = card.get("types") or ["Colorless"]
    style = _type_style(types)
    symbol = style["symbol"]
    bg = style["bg"]
    name = card.get("name", "Unknown")
    hp = card.get("hp", "?")
    rarity = card.get("rarity", "") or "Unknown"
    subtitle = card.get("subtitle", "")
    set_name = card.get("set", "")
    number = card.get("number", "")
    img_url = _card_image_url(card)
    attacks = card.get("attacks") or []
    attack_slots = _attack_slots(attacks, limit=2)
    weakness = card.get("weakness")
    resistance = card.get("resistance")

    with Card(css_class="h-full overflow-hidden border border-slate-200/90 bg-gradient-to-b from-white via-slate-50 to-slate-100 shadow-md hover:-translate-y-0.5 hover:shadow-xl transition-all duration-200"):
        with CardHeader(css_class=f"{bg} border-b {style['border']} px-3 py-3"):
            with Row(justify="between", align="start", css_class="gap-3"):
                with Column(gap=2, css_class="flex-1 rounded-2xl border border-white/75 bg-white/82 px-3 py-2 shadow-sm"):
                    with Row(gap=2, align="center"):
                        with Row(gap=1, align="center", css_class="rounded-full border border-slate-200 bg-white px-2 py-1 shadow-sm"):
                            Text(_energy_symbols(types) or symbol, css_class="text-sm")
                        CardTitle(name, css_class="text-base font-black tracking-tight leading-none text-slate-950")
                    if subtitle or set_name:
                        CardDescription(
                            f"{subtitle} · {set_name}" if subtitle and set_name else subtitle or set_name,
                            css_class="text-sm font-medium text-slate-700",
                        )
                with Column(gap=1, align="end", css_class="min-w-20 rounded-2xl border border-white/80 bg-amber-50/90 px-3 py-2 shadow-sm"):
                    Text("HP", css_class="text-xs font-semibold uppercase tracking-widest text-amber-700")
                    Text(f"{hp}", css_class="text-lg font-black leading-none text-slate-950")
                    Text(rarity, css_class="text-xs font-medium text-slate-700 text-right")

        if img_url:
            with CardContent():
                Image(
                    src=img_url,
                    alt=f"{name} Pokemon card",
                    width="100%",
                    height="240px",
                    css_class="w-full rounded-2xl bg-white/90 object-contain p-2 shadow-sm",
                )
        else:
            with CardContent():
                with Column(align="center", justify="center", css_class=f"{bg} min-h-60 rounded-2xl"):
                    Text(symbol, css_class="text-5xl opacity-30")

        with CardContent():
            with Row(gap=2, css_class="flex-wrap"):
                for type_name in types[:2]:
                    Badge(type_name, variant="secondary", css_class="text-xs")
                Badge(rarity, variant="info", css_class="text-xs")

            with Column(gap=2, css_class="mt-3 min-h-24"):
                for attack in attack_slots:
                    with Row(justify="between", align="center", css_class="min-h-10 rounded-xl border border-slate-200/80 bg-white/78 px-3 py-2 shadow-sm"):
                        if attack:
                            cost_str = _energy_symbols(attack.get("cost", []))
                            with Row(gap=2, align="center"):
                                if cost_str:
                                    Text(cost_str, css_class="text-xs")
                                Text(attack.get("name", "Attack"), css_class="text-sm font-semibold text-slate-900")
                            if attack.get("damage"):
                                Text(attack["damage"], css_class="text-sm font-bold text-slate-900")
                        else:
                            Muted("—", css_class="text-sm italic")

        with CardFooter(css_class="border-t border-slate-200/80 bg-slate-50/85"):
            with Column(gap=2, css_class="w-full"):
                with Row(justify="between", align="start", css_class="gap-2"):
                    with Row(gap=2, css_class="flex-wrap"):
                        _render_modifier_panel("Weakness", weakness, compact=True)
                        _render_modifier_panel("Resistance", resistance, compact=True)
                    with Column(gap=0, align="end", css_class="rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2 shadow-sm"):
                        Text(set_name or "Set", css_class="text-xs font-semibold uppercase tracking-widest text-slate-500")
                        Text(f"#{number}" if number else "—", css_class="text-sm font-semibold text-slate-900")

                if saved_state_key:
                    with Row(justify="between", align="center"):
                        with If(saved_state_key):
                            Badge("Saved to collection", variant="secondary", css_class="text-xs")
                        with If(f"!{saved_state_key}"):
                            Muted("Save this print", css_class="text-xs")
                        if save_action is not None:
                            with If(f"!{saved_state_key}"):
                                Button("Save print", icon="save", variant="success", on_click=save_action)


def _render_card(
    card: dict,
    *,
    save_action: CallTool | None = None,
    saved_state_key: str | None = None,
) -> None:
    """Render one Pokemon card with type colours, image, attacks, and footer."""
    types    = card.get("types") or ["Colorless"]
    style    = _type_style(types)
    bg       = style["bg"]
    symbol   = style["symbol"]
    type_symbols = _energy_symbols(types) or symbol
    name     = card.get("name", "Unknown")
    hp       = card.get("hp", "?")
    rarity   = card.get("rarity", "")
    rarity_sym = RARITY_SYMBOL.get(rarity, "")
    rarity_label = rarity_sym or rarity or ("Custom" if card.get("source") in CUSTOM_CARD_SOURCES else "")

    with Card(css_class="overflow-hidden border border-slate-200/90 bg-gradient-to-b from-white via-slate-50 to-slate-100 shadow-md hover:-translate-y-0.5 hover:shadow-xl transition-all duration-200"):

        # — Coloured header band ———————————————————————————————————————————
        with CardHeader(css_class=f"{bg} border-b {style['border']} px-4 py-4"):
            with Row(justify="between", align="start", css_class="gap-3"):
                with Column(gap=2, css_class="flex-1 rounded-3xl border border-white/75 bg-white/82 px-4 py-3 shadow-sm"):
                    with Row(gap=2, align="center"):
                        with Row(gap=1, align="center", css_class="rounded-full border border-slate-200 bg-white px-2 py-1 shadow-sm"):
                            Text(type_symbols, css_class="text-sm")
                        CardTitle(name, css_class="text-xl font-black tracking-tight leading-none text-slate-950")
                    if card.get("subtitle"):
                        CardDescription(
                            card["subtitle"],
                            css_class="text-sm font-medium text-slate-700",
                        )
                with Column(gap=1, align="end", css_class="min-w-24 rounded-2xl border border-white/80 bg-amber-50/90 px-3 py-2 shadow-sm"):
                    Text("HP", css_class="text-xs font-semibold uppercase tracking-widest text-amber-700")
                    Text(f"{hp}", css_class="text-2xl font-black leading-none text-slate-950")
                    if rarity_label:
                        Text(rarity_label, css_class="text-xs font-medium text-slate-700 text-right")

        # — Card image ———————————————————————————————————————————————————
        img_url = _card_image_url(card)
        if img_url:
            with CardContent():
                Image(
                    src=img_url,
                    alt=f"{name} Pokemon card",
                    width="100%",
                    height="auto",
                    css_class="w-full rounded-2xl bg-white/90 object-contain p-3 shadow-sm",
                )
        else:
            with CardContent():
                with Column(align="center", justify="center", css_class=f"{bg} min-h-32 rounded-2xl"):
                    Text(symbol, css_class="text-5xl opacity-30")

        # — Attacks ——————————————————————————————————————————————————————
        with CardContent():
            attacks = card.get("attacks", [])
            if attacks:
                with Column(gap=2):
                    for atk in attacks:
                        cost_str = _energy_symbols(atk.get("cost", []))
                        dmg = atk.get("damage", "")
                        with Column(gap=1, css_class="rounded-2xl border border-slate-200/80 bg-white/78 px-3 py-2 shadow-sm"):
                            with Row(justify="between", align="center"):
                                with Row(gap=1, align="center"):
                                    if cost_str:
                                        Text(cost_str, css_class="text-sm")
                                    Text(atk["name"], css_class="font-semibold text-sm text-slate-900")
                                if dmg:
                                    Text(dmg, css_class="font-bold text-sm text-slate-900")
                            if atk.get("text"):
                                Muted(atk["text"], css_class="text-xs leading-tight")
            else:
                Muted("No attacks", css_class="text-xs italic")

        # — Footer ———————————————————————————————————————————————————————
        with CardFooter(css_class="border-t border-slate-200/80 bg-slate-50/85"):
            with Column(gap=2, css_class="w-full"):
                with Row(justify="between", align="start", css_class="gap-3"):
                    with Row(gap=2, css_class="flex-wrap"):
                        _render_modifier_panel("Weakness", card.get("weakness"))
                        _render_modifier_panel("Resistance", card.get("resistance"))
                    set_name = card.get("set", "")
                    number = card.get("number", "")
                    with Column(gap=0, align="end", css_class="rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2 shadow-sm"):
                        Text(set_name or "Set", css_class="text-xs font-semibold uppercase tracking-widest text-slate-500")
                        Text(f"#{number}" if number else "—", css_class="text-sm font-semibold text-slate-900")
                if card.get("flavor"):
                    Muted(card["flavor"], css_class="text-xs italic")
                if card.get("source") in CUSTOM_CARD_SOURCES:
                    Badge("✦ Custom", variant="secondary", css_class="text-xs")
                if saved_state_key:
                    with Row(justify="between", align="center"):
                        with If(saved_state_key):
                            Badge("Saved to collection", variant="secondary", css_class="text-xs")
                        with If(f"!{saved_state_key}"):
                            Muted("Not in collection yet.", css_class="text-xs")
                        if save_action is not None:
                            with If(f"!{saved_state_key}"):
                                Button("Save to collection", icon="save", variant="success", on_click=save_action)


@mcp.tool(app=True)
def card_lab() -> PrefabApp:
    """Render my Pokémon card collection as a visual grid with card images."""
    cards = _load_collection()

    with PrefabApp() as app:
        with Column(gap=4, css_class="max-w-5xl mx-auto p-6"):
            with Card():
                with CardHeader():
                    CardTitle("✦ My Pokémon Collection", css_class="text-xl")
                    CardDescription(
                        f"{len(cards)} card{'s' if len(cards) != 1 else ''} · sandbox/collection.json"
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


@mcp.tool(app=True)
def preview_real_card(name: str) -> PrefabApp:
    """Show a visual real-card search with inline save controls."""
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
            with Column(gap=1):
                Text("Pokemon TCG search", css_class="text-2xl font-bold")
                if cards:
                    Muted(
                        f"Showing {len(cards)} live match{'es' if len(cards) != 1 else ''} for {name.strip()!r}. Save any print directly from this view."
                    )
                else:
                    Muted("Fetched live from the Pokemon TCG API. Save any card only if you want to keep it.")

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
# 4. DESIGN CARD — Prefab form + deterministic renderer
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
    """Save a custom card submitted from the Prefab card designer UI."""
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
    with Card(css_class="overflow-hidden border border-slate-200/90 bg-gradient-to-b from-white via-slate-50 to-slate-100 shadow-lg"):
        with CardHeader(css_class="bg-gradient-to-r from-amber-200 via-orange-100 to-yellow-50 border-b border-amber-300"):
            with Row(justify="between", align="start", css_class="gap-3"):
                with Column(gap=2, css_class="flex-1 rounded-3xl border border-white/80 bg-white/85 px-4 py-3 shadow-sm"):
                    with Row(gap=2, align="center"):
                        Badge("{{ primary_type }}", variant="secondary")
                        CardTitle("{{ name }}", css_class="text-base font-black tracking-tight")
                    CardDescription("{{ stage }} · {{ primary_type }} / {{ secondary_type }}", css_class="text-sm font-medium text-slate-700")
                with Column(gap=1, align="end", css_class="rounded-2xl border border-white/80 bg-amber-50/90 px-3 py-2 shadow-sm"):
                    Text("HP", css_class="text-xs font-semibold uppercase tracking-widest text-amber-700")
                    Text("{{ hp }}", css_class="text-xl font-black text-slate-900")
        with CardContent():
            with Column(gap=3):
                with Row(gap=2):
                    Badge("{{ rarity }}", variant="info")
                    Badge("{{ holo ? 'Holo' : 'Matte' }}", variant="success")
                Progress(value="{{ hp }}", max=220, target=120, variant="warning", gradient=True)
                Separator()
                with Column(gap=2):
                    with Row(justify="between", align="center"):
                        Text("{{ attack_1_cost }} {{ attack_1_name }}", css_class="font-semibold text-sm")
                        Text("{{ attack_1_damage }}", css_class="font-bold text-sm")
                    Muted("{{ attack_1_text }}", css_class="text-xs leading-tight")
                    with Row(justify="between", align="center"):
                        Text("{{ attack_2_cost }} {{ attack_2_name }}", css_class="font-semibold text-sm")
                        Text("{{ attack_2_damage }}", css_class="font-bold text-sm")
                    Muted("{{ attack_2_text }}", css_class="text-xs leading-tight")
                Separator()
                with Row(gap=2, css_class="flex-wrap"):
                    Badge("Weak {{ weakness_type }} {{ weakness_value }}", variant="warning")
                    Badge("{{ resistance_type ? 'Resistance ' + resistance_type + ' ' + resistance_value : 'Resistance —' }}", variant="secondary")
                Muted("{{ flavor }}", css_class="text-xs italic")


@mcp.tool(app=True)
def design_card() -> PrefabApp:
    """Open an interactive Prefab card designer instead of asking for a long prompt."""
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
                                        with RadioGroup(name="stage", value="Basic"):
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
                                        # `name="hp"` binds reactively to state.hp (seeded as 80);
                                        # passing a templated `value="{{ hp }}"` here makes the
                                        # JS Slider validator reject the prop as non-numeric.
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
                                        # Switch / Checkbox bind reactively via `name`. Passing a
                                        # templated string for `value` (e.g. "{{ holo }}") fails
                                        # the JS prop validator because these expect bool only.
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
                    with Card():
                        with CardHeader():
                            CardTitle("Card sheet")
                            CardDescription("A compact table preview of the saved fields.")
                        with CardContent():
                            with Table():
                                with TableHeader():
                                    with TableRow():
                                        TableHead("Field")
                                        TableHead("Value")
                                with TableBody():
                                    for field, value in (
                                        ("Name", "{{ name }}"),
                                        ("Types", "{{ primary_type }} / {{ secondary_type }}"),
                                        ("Weakness", "{{ weakness_type }} {{ weakness_value }}"),
                                        ("Resistance", "{{ resistance_type ? resistance_type + ' ' + resistance_value : '—' }}"),
                                        ("Illustrator", "{{ illustrator }}"),
                                    ):
                                        with TableRow():
                                            TableCell(field)
                                            TableCell(value)

    return app


# ===========================================================================
# 5. PROMPT — slash command
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
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

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from fastmcp import FastMCP
from prefab_ui.actions import ShowToast
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


CARD_TYPES = tuple(TYPE_STYLES.keys())
CUSTOM_RARITIES = ("Common", "Uncommon", "Rare", "Rare Holo", "Custom")
CARD_STAGES = ("Basic", "Stage 1", "Stage 2")
CUSTOM_CARD_SOURCES = {"designed_by_llm", "designed_in_prefab"}


# ===========================================================================
# 1. INTERNET TOOL — Pokemon TCG API
# ===========================================================================
# Returns a normalized dict — only the fields we render.
# Trimming the response keeps tokens down when the model passes the result
# back to itself.
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

    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
        return response.status, json.loads(payload)


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
        _, payload = _json_get(
            POKE_TCG_BASE,
            params={"q": f"name:{name}", "pageSize": 1, "orderBy": "set.releaseDate"},
            headers=headers,
            timeout=10,
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"error": f"Network error fetching {name!r}: {e}"}

    cards = payload.get("data", [])
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
        if card.get("image_url") or card.get("source") in CUSTOM_CARD_SOURCES:
            skipped += 1
            continue
        card_id = card.get("id", "")
        try:
            status, payload = _json_get(
                f"{POKE_TCG_BASE}/{card_id}",
                headers=headers,
                timeout=10,
            )
            if status == 200:
                img = payload.get("data", {}).get("images", {}).get("small", "")
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
        with CardHeader(css_class=f"{bg} border-b {style['border']}"):
            with Row(justify="between", align="start"):
                with Column(gap=0):
                    with Row(gap=1, align="center"):
                        Text(symbol, css_class="text-lg")
                        CardTitle(name, css_class=f"text-base {text_cls}")
                    if card.get("subtitle"):
                        CardDescription(
                            card["subtitle"],
                            css_class=f"text-xs {'text-gray-300' if is_dark else ''}",
                        )
                with Column(gap=0, align="end"):
                    Text(f"{hp} HP",
                         css_class=f"text-xl font-extrabold {'text-white' if is_dark else 'text-gray-700'}")
                    if rarity_sym:
                        Muted(rarity_sym, css_class="text-xs text-right")

        # — Card image ———————————————————————————————————————————————————
        img_url = card.get("image_url", "")
        if img_url:
            with CardContent():
                Image(
                    src=img_url,
                    alt=f"{name} Pokemon card",
                    width="100%",
                    height="auto",
                    css_class="w-full object-contain bg-gray-50",
                )
        else:
            with CardContent():
                with Column(align="center", justify="center", css_class=f"{bg} min-h-28"):
                    Text(symbol, css_class="text-5xl opacity-30")

        # — Attacks ——————————————————————————————————————————————————————
        with CardContent():
            attacks = card.get("attacks", [])
            if attacks:
                with Column(gap=2):
                    for atk in attacks:
                        cost_str = _energy_symbols(atk.get("cost", []))
                        dmg = atk.get("damage", "")
                        with Column(gap=1):
                            with Row(justify="between", align="center"):
                                with Row(gap=1, align="center"):
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
        with CardContent():
            Separator(css_class="mb-2")
            with Row(justify="between", align="center"):
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
            if card.get("flavor"):
                Muted(card["flavor"], css_class="text-xs italic mt-2 block")
            if card.get("source") in CUSTOM_CARD_SOURCES:
                Badge("✦ Custom", variant="secondary", css_class="text-xs mt-1")


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

    return {
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
    with Card(css_class="overflow-hidden shadow-lg"):
        with CardHeader(css_class="bg-amber-100 border-b border-amber-300"):
            with Row(justify="between", align="start"):
                with Column(gap=1):
                    with Row(gap=1, align="center"):
                        Text("✦", css_class="text-lg")
                        CardTitle("{{ name }}", css_class="text-base")
                    CardDescription("{{ stage }} · {{ primary_type }} / {{ secondary_type }}")
                Text("{{ hp }} HP", css_class="text-xl font-extrabold text-gray-700")
        with CardContent():
            with Column(gap=3):
                with Row(gap=2):
                    Badge("{{ primary_type }}", variant="secondary")
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
                                CardDescription("Tune HP, attacks, weakness, and battle flavor.")
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
                                        Slider(name="hp", value="{{ hp }}", min=30, max=220, step=10, gradient=True)
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
                                    with Row(gap=4, align="center"):
                                        Switch(name="holo", label="Holographic finish", value="{{ holo }}")
                                        Checkbox(name="first_edition", label="First edition stamp", value="{{ first_edition }}")
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
        "1. Fetch a Pikachu and a Charizard from the Pokemon TCG API.\n"
        "2. Save both to my collection.\n"
        "3. Call refresh_collection_images so all cards have their artwork.\n"
        "4. Show me my collection in a Prefab dashboard.\n"
        "5. Then open design_card so I can create a custom card in the Prefab UI.\n"
    )


if __name__ == "__main__":
    print(f"PokeLab starting -- sandbox: {SANDBOX}", file=sys.stderr)
    mcp.run()
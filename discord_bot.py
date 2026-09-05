"""Discord slash-command bot sharing the Drift Radar remote state."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from cloud_store import read_remote
from discord_notify import LOCAL_TZ, format_upcoming_digest
from main import load_sources

LOGGER = logging.getLogger("drift.discord")


def _observations() -> list[tuple[dict[str, Any], Any]]:
    sources = {source["id"]: source for source in load_sources() if source.get("enabled", True)}
    result: list[tuple[dict[str, Any], Any]] = []
    for state_name, max_age in (("youtube", timedelta(minutes=20)), ("calendar", timedelta(hours=30))):
        state = read_remote(state_name)
        health = state.get("source_health", {})
        for source_id, value in state.get("sources", {}).items():
            source = sources.get(source_id)
            checked_at = health.get(source_id, {}).get("checked_at")
            if not source or not checked_at or not health.get(source_id, {}).get("ok"):
                continue
            try:
                stamp = datetime.fromisoformat(checked_at).astimezone(LOCAL_TZ)
            except (TypeError, ValueError):
                continue
            if datetime.now(LOCAL_TZ) - stamp <= max_age:
                result.append((source, value))
    return result


def _filter_for_day(observations: list[tuple[dict[str, Any], Any]], target: date) -> list[tuple[dict[str, Any], Any]]:
    filtered: list[tuple[dict[str, Any], Any]] = []
    for source, value in observations:
        if isinstance(value, list):
            items = []
            for video in value:
                scheduled = video.get("scheduled_start") if isinstance(video, dict) else None
                if not scheduled:
                    continue
                try:
                    local_day = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).astimezone(LOCAL_TZ).date()
                except ValueError:
                    continue
                if local_day == target:
                    items.append(video)
            if items:
                filtered.append((source, items))
        elif isinstance(value, dict):
            items = []
            for event in value.get("events", []):
                try:
                    start = date.fromisoformat(event["start"])
                    end = date.fromisoformat(event["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if start <= target <= end:
                    items.append(event)
            if items:
                filtered.append((source, {**value, "events": items}))
    return filtered


def _filter_for_series(observations: list[tuple[dict[str, Any], Any]], query: str) -> list[tuple[dict[str, Any], Any]]:
    query = query.casefold().strip()
    return [
        (source, value)
        for source, value in observations
        if query in source.get("name", source.get("id", "")).casefold()
    ]


def _embed_payload(payload: dict[str, Any]) -> tuple[str, discord.Embed, discord.ui.View | None]:
    embed = discord.Embed.from_dict(payload["embeds"][0])
    view: discord.ui.View | None = None
    buttons = [button for row in payload.get("components", []) for button in row.get("components", [])]
    if buttons:
        view = discord.ui.View(timeout=900)
        for button in buttons[:5]:
            view.add_item(discord.ui.Button(label=button["label"], style=discord.ButtonStyle.link, url=button["url"]))
    return payload.get("content", ""), embed, view


class DriftRadarBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        super().__init__(command_prefix=[], intents=intents)
        self._guild_sync_done: set[int] = set()

    async def setup_hook(self) -> None:
        guild_id = os.environ.get("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synced %d Drift Radar commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            LOGGER.info("Synced %d global Drift Radar commands", len(synced))

    async def on_ready(self) -> None:
        LOGGER.info("Discord bot connected as %s", self.user)
        # Global commands can take a while to propagate. Guild sync makes the
        # commands appear immediately in every server where this bot is installed.
        for guild in self.guilds:
            if guild.id in self._guild_sync_done:
                continue
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                self._guild_sync_done.add(guild.id)
                LOGGER.info("Synced %d commands to guild %s (%s)", len(synced), guild.name, guild.id)
            except Exception:
                LOGGER.exception("Guild command sync failed for %s (%s)", guild.name, guild.id)


bot = DriftRadarBot()


async def _send(interaction: discord.Interaction, observations: list[tuple[dict[str, Any], Any]], empty: str) -> None:
    if not observations:
        await interaction.followup.send(empty, ephemeral=True)
        return
    content, embed, view = _embed_payload(format_upcoming_digest(observations))
    await interaction.followup.send(content=content, embed=embed, view=view)


@bot.tree.command(name="next", description="Pokaż najbliższe potwierdzone wydarzenia driftingowe")
async def next_events(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        await _send(interaction, await asyncio.to_thread(_observations), "Brak świeżych, potwierdzonych danych.")
    except Exception:
        LOGGER.exception("/next failed")
        await interaction.followup.send("Nie udało się pobrać danych. Spróbuj ponownie za chwilę.", ephemeral=True)


@bot.tree.command(name="today", description="Pokaż wydarzenia i transmisje na dziś")
async def today_events(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        observations = await asyncio.to_thread(_observations)
        today = datetime.now(LOCAL_TZ).date()
        await _send(
            interaction,
            _filter_for_day(observations, today),
            "Dziś nie ma potwierdzonych wydarzeń ani transmisji.",
        )
    except Exception:
        LOGGER.exception("/today failed")
        await interaction.followup.send("Nie udało się pobrać danych. Spróbuj ponownie za chwilę.", ephemeral=True)


@bot.tree.command(name="series", description="Pokaż najbliższe terminy wybranej serii")
@app_commands.describe(nazwa="Nazwa serii lub jej fragment, np. D1GP albo Drift Masters")
async def series_events(interaction: discord.Interaction, nazwa: str) -> None:
    await interaction.response.defer()
    try:
        observations = await asyncio.to_thread(_observations)
        matches = _filter_for_series(observations, nazwa)
        await _send(interaction, matches, f"Nie znalazłem świeżych danych dla serii „{nazwa}”.")
    except Exception:
        LOGGER.exception("/series failed")
        await interaction.followup.send("Nie udało się pobrać danych. Spróbuj ponownie za chwilę.", ephemeral=True)


@bot.tree.command(name="help", description="Pokaż pomoc i wszystkie komendy Drift Radar")
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="🏁 DRIFT RADAR · Centrum dowodzenia",
        description=(
            "Twój osobisty radar driftingu.\n"
            "Wybierz komendę poniżej, a dostaniesz wyłącznie potwierdzone dane "
            "z kalendarzy i oficjalnych transmisji."
        ),
        color=0x8B5CF6,
    )
    embed.add_field(
        name="📡 /next",
        value="Najbliższe rundy i zaplanowane transmisje — z godziną w Polsce i linkiem do oglądania.",
        inline=False,
    )
    embed.add_field(
        name="🔥 /today",
        value="Wszystko, co dzieje się dzisiaj, w tym nocne transmisje oznaczone jako 🌙.",
        inline=False,
    )
    embed.add_field(
        name="🏆 /series",
        value="Wpisz nazwę lub fragment serii, np. `/series D1GP` albo `/series Drift Masters`.",
        inline=False,
    )
    embed.add_field(
        name="🔔 Automatyczne alerty",
        value="Bot sam powiadamia o nowych terminach oraz transmisjach startujących za około 10 minut.",
        inline=False,
    )
    embed.set_footer(text="Drift Radar · Europe/Warsaw · dane z oficjalnych źródeł")
    await interaction.response.send_message(embed=embed)


def start_bot() -> threading.Thread | None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        LOGGER.info("Discord bot disabled: DISCORD_BOT_TOKEN is not configured")
        return None

    def runner() -> None:
        try:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            bot.run(token)
        except Exception:
            LOGGER.exception("Discord bot stopped")

    thread = threading.Thread(target=runner, name="drift-discord-bot", daemon=True)
    thread.start()
    return thread

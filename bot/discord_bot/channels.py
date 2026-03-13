import discord
import logging
from datetime import datetime

from bot.config import DISCORD_APPROVALS_CHANNEL_ID, DISCORD_LOG_CHANNEL_ID
from bot.discord_bot.approval_view import ApprovalView
from bot.twitter.rate_limiter import budget_remaining

log = logging.getLogger(__name__)


async def send_draft_for_approval(
    bot: discord.Client,
    draft_id: int,
    tweet_text: str,
    event_type: str,
    event_description: str,
    on_approve,
    on_reject,
    on_revise=None,
) -> discord.Message | None:
    channel = bot.get_channel(DISCORD_APPROVALS_CHANNEL_ID)
    if not channel:
        log.error("Approvals channel %d not found", DISCORD_APPROVALS_CHANNEL_ID)
        return None

    budget = await budget_remaining()

    embed = discord.Embed(
        title=f"Tweet Draft #{draft_id}",
        description=tweet_text,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Event Type", value=event_type, inline=True)
    embed.add_field(name="Chars", value=f"{len(tweet_text)}/280", inline=True)
    embed.add_field(
        name="Budget",
        value=f"{budget['daily_remaining']}/{budget['daily_limit']} today | {budget['monthly_remaining']}/{budget['monthly_limit']} month",
        inline=False,
    )
    embed.add_field(name="Event", value=event_description[:200], inline=False)

    view = ApprovalView(draft_id, tweet_text, on_approve, on_reject, on_revise=on_revise)
    msg = await channel.send(embed=embed, view=view)
    return msg


async def send_log(bot: discord.Client, message: str, color: discord.Color = discord.Color.blue()):
    channel = bot.get_channel(DISCORD_LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(description=message, color=color, timestamp=datetime.utcnow())
    await channel.send(embed=embed)


async def update_approval_message(message: discord.Message, tweet_url: str):
    embed = message.embeds[0] if message.embeds else discord.Embed()
    embed.color = discord.Color.green()
    embed.add_field(name="Status", value=f"POSTED: {tweet_url}", inline=False)
    await message.edit(embed=embed, view=None)


async def mark_rejected(message: discord.Message, reason: str = "Rejected"):
    embed = message.embeds[0] if message.embeds else discord.Embed()
    embed.color = discord.Color.red()
    embed.add_field(name="Status", value=reason, inline=False)
    await message.edit(embed=embed, view=None)


async def mark_revised(message: discord.Message):
    embed = message.embeds[0] if message.embeds else discord.Embed()
    embed.color = discord.Color.light_grey()
    embed.add_field(name="Status", value="Revised — new draft below", inline=False)
    await message.edit(embed=embed, view=None)

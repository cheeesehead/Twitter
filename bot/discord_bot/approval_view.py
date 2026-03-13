import discord
import logging

log = logging.getLogger(__name__)


class EditModal(discord.ui.Modal, title="Edit Tweet"):
    tweet_text = discord.ui.TextInput(
        label="Tweet Text",
        style=discord.TextStyle.paragraph,
        max_length=280,
        placeholder="Edit the tweet (max 280 characters)...",
    )

    def __init__(self, current_text: str, draft_id: int, on_approve):
        super().__init__()
        self.tweet_text.default = current_text
        self.draft_id = draft_id
        self.on_approve = on_approve

    async def on_submit(self, interaction: discord.Interaction):
        edited = self.tweet_text.value.strip()
        if len(edited) > 280:
            await interaction.response.send_message(
                f"Tweet is {len(edited)} chars — must be 280 or less.", ephemeral=True
            )
            return
        await interaction.response.defer()
        await self.on_approve(self.draft_id, edited, interaction)


class FeedbackModal(discord.ui.Modal, title="Revise Tweet"):
    feedback = discord.ui.TextInput(
        label="What's wrong with this tweet?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        placeholder='e.g. "too aggressive", "make it funnier", "shorter"...',
    )

    def __init__(self, draft_id: int, tweet_text: str, on_revise):
        super().__init__()
        self.draft_id = draft_id
        self.tweet_text = tweet_text
        self.on_revise = on_revise

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.on_revise(
            self.draft_id, self.tweet_text, self.feedback.value.strip(), interaction
        )


class ApprovalView(discord.ui.View):
    def __init__(self, draft_id: int, tweet_text: str, on_approve, on_reject,
                 on_revise=None, meme_id: str | None = None,
                 article_url: str | None = None):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.draft_id = draft_id
        self.tweet_text = tweet_text
        self.on_approve = on_approve
        self.on_reject = on_reject
        self.on_revise = on_revise
        self.meme_id = meme_id
        self.article_url = article_url

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="\u2705")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()
        await self.on_approve(self.draft_id, self.tweet_text, interaction)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="\u274c")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stop()
        await self.on_reject(self.draft_id, interaction)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.blurple, emoji="\u270f\ufe0f")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditModal(self.tweet_text, self.draft_id, self.on_approve)
        await interaction.response.send_modal(modal)
        self.stop()

    @discord.ui.button(label="Revise", style=discord.ButtonStyle.blurple, emoji="\U0001f504")
    async def revise(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.on_revise:
            await interaction.response.send_message(
                "Revise not available.", ephemeral=True
            )
            return
        modal = FeedbackModal(self.draft_id, self.tweet_text, self.on_revise)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        log.info("Draft %d approval timed out", self.draft_id)
        await self.on_reject(self.draft_id, None)

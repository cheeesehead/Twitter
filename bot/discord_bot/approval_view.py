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
        super().__init__(timeout=None)  # Persistent — survives restarts
        self.draft_id = draft_id
        self.tweet_text = tweet_text
        self.on_approve = on_approve
        self.on_reject = on_reject
        self.on_revise = on_revise
        self.meme_id = meme_id
        self.article_url = article_url

        # Build buttons with stable custom_id so discord.py can route
        # interactions back to us after a restart.
        approve_btn = discord.ui.Button(
            label="Approve", style=discord.ButtonStyle.green,
            emoji="\u2705", custom_id=f"approve:{draft_id}",
        )
        approve_btn.callback = self._approve_callback
        self.add_item(approve_btn)

        reject_btn = discord.ui.Button(
            label="Reject", style=discord.ButtonStyle.red,
            emoji="\u274c", custom_id=f"reject:{draft_id}",
        )
        reject_btn.callback = self._reject_callback
        self.add_item(reject_btn)

        edit_btn = discord.ui.Button(
            label="Edit", style=discord.ButtonStyle.blurple,
            emoji="\u270f\ufe0f", custom_id=f"edit:{draft_id}",
        )
        edit_btn.callback = self._edit_callback
        self.add_item(edit_btn)

        revise_btn = discord.ui.Button(
            label="Revise", style=discord.ButtonStyle.blurple,
            emoji="\U0001f504", custom_id=f"revise:{draft_id}",
        )
        revise_btn.callback = self._revise_callback
        self.add_item(revise_btn)

    async def _approve_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()
        await self.on_approve(self.draft_id, self.tweet_text, interaction)

    async def _reject_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()
        await self.on_reject(self.draft_id, interaction)

    async def _edit_callback(self, interaction: discord.Interaction):
        modal = EditModal(self.tweet_text, self.draft_id, self.on_approve)
        await interaction.response.send_modal(modal)
        self.stop()

    async def _revise_callback(self, interaction: discord.Interaction):
        if not self.on_revise:
            await interaction.response.send_message(
                "Revise not available.", ephemeral=True
            )
            return
        modal = FeedbackModal(self.draft_id, self.tweet_text, self.on_revise)
        await interaction.response.send_modal(modal)

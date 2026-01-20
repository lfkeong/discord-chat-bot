import os
import ssl
import time
from dataclasses import dataclass
from typing import Dict, Optional

import aiohttp
import certifi
import discord
from discord import app_commands
from dotenv import load_dotenv

# Fix SSL certificate issues on macOS
os.environ['SSL_CERT_FILE'] = certifi.where()

# Patch aiohttp's default connector to use certifi certificates
_original_tcp_connector_init = aiohttp.TCPConnector.__init__

def _patched_tcp_connector_init(self, *args, **kwargs):
    if 'ssl' not in kwargs or kwargs.get('ssl') is True:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        kwargs['ssl'] = ssl_context
    return _original_tcp_connector_init(self, *args, **kwargs)

aiohttp.TCPConnector.__init__ = _patched_tcp_connector_init

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# ---- Simple in-memory store (OK for testing; use DB for production) ----
# Keyed by the message id of the "locked" message.
SECRET_STORE: Dict[int, str] = {}


@dataclass
class UnlockConfig:
    # Optional role restriction: set to a role ID string/int to require it.
    allowed_role_id: Optional[int] = None


CONFIG = UnlockConfig(
    allowed_role_id=None  # e.g. 123456789012345678 to restrict
)


class UnlockView(discord.ui.View):
    def __init__(self, locked_message_id: int, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.locked_message_id = locked_message_id

    @discord.ui.button(
        label="Unlock Content",
        style=discord.ButtonStyle.primary,
        emoji="🔒",
        custom_id="unlock_content_btn"
    )
    async def unlock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # --- Optional role gate ---
        if CONFIG.allowed_role_id is not None:
            member = interaction.user
            if isinstance(member, discord.Member):
                has_role = any(r.id == CONFIG.allowed_role_id for r in member.roles)
            else:
                has_role = False

            if not has_role:
                return await interaction.response.send_message(
                    "❌ You don’t have permission to unlock this content.",
                    ephemeral=True
                )

        secret = SECRET_STORE.get(self.locked_message_id)
        if not secret:
            return await interaction.response.send_message(
                "⚠️ Sorry, I can't find the content for this message (it may have expired).",
                ephemeral=True
            )

        # Check if this is a trade_ephemeral type (dictionary) or plain text
        if isinstance(secret, dict) and secret.get("type") == "trade_ephemeral":
            # Recreate the same format as the original ephemeral message
            trade_data = secret
            
            # Get user mention
            user_id = trade_data.get("user")
            user_mention = f"<@{user_id}>" if user_id else ""
            
            # Build embed description (same as original)
            description_parts = []
            
            # Add emoji if provided
            emoji = trade_data.get("emoji")
            symbol = trade_data.get("symbol", "")
            if emoji:
                if ':' in emoji:
                    parts = emoji.split(':')
                    if len(parts) == 2:
                        emoji_str = f"<:{parts[0]}:{parts[1]}>"
                    else:
                        emoji_str = emoji
                else:
                    try:
                        emoji_id = int(emoji)
                        emoji_str = f"<:{symbol}:{emoji_id}>"
                    except:
                        emoji_str = emoji
                description_parts.append(emoji_str)
                description_parts.append(" ")
            
            # Add symbol and prices
            entry = trade_data.get("entry", "")
            sl = trade_data.get("sl", "")
            percentage_text = trade_data.get("percentage_text", "")
            
            description_parts.append(f"**{symbol.upper()}**")
            description_parts.append(" | ")
            description_parts.append(f"**Entry:** {entry} | ")
            description_parts.append(f"**SL:** {sl} {percentage_text}")
            
            description = "".join(description_parts)
            
            # Create embed (same format as original)
            embed = discord.Embed(
                description=description,
                color=discord.Color.from_rgb(59, 165, 92),
                timestamp=discord.utils.utcnow()
            )
            
            # Add disclaimer
            disclaimer = "⚠️ **Disclaimer**\nChallenge trades may involve higher risks. Only risk what you can afford to lose and be prepared for the possibility of significant losses. Always trade responsibly."
            embed.add_field(name="", value=disclaimer, inline=False)
            
            # Add footer with status
            status_text = trade_data.get("status", "Active")
            timestamp = discord.utils.format_dt(discord.utils.utcnow(), style='f')
            footer_text = f"Status: 🛑 {status_text} • {timestamp}"
            embed.set_footer(text=footer_text)
            
            # Set image if provided
            image_url = trade_data.get("image_url")
            if image_url:
                embed.set_image(url=image_url)
            
            # Send ephemeral message with same format
            await interaction.response.send_message(
                content=user_mention,
                embed=embed,
                ephemeral=True
            )
        else:
            # Plain text format (for backward compatibility with other commands)
            embed = discord.Embed(
                title="Unlocked Content",
                description=secret,
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"Unlocked by {interaction.user}")

            await interaction.response.send_message(embed=embed, ephemeral=True)


class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        # Sync commands to a specific guild for fast update (recommended for dev)
        # if GUILD_ID:
        #     guild = discord.Object(id=GUILD_ID)
        #     self.tree.copy_global_to(guild=guild)
        #     await self.tree.sync(guild=guild)
        # else:
        #     await self.tree.sync()


bot = MyBot()


# Trade ephemeral message command
@bot.tree.command(name="trade_ephemeral", description="Send an ephemeral trade message with embed, image, unlock button, and mention.")
@app_commands.describe(
    user="User to mention",
    symbol="Trading symbol (e.g., XMR, BTC)",
    entry="Entry price",
    sl="Stop loss price",
    image_url="Image URL (optional)",
    status="Status text (e.g., 'Stopped', 'Active')",
    order_type='Order type: "BUY" or "SELL" (controls emoji: :Long: or :Short:)'
)
async def trade_ephemeral_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    symbol: str,
    entry: str,
    sl: str,
    image_url: Optional[str] = None,
    status: Optional[str] = None,
    order_type: str = "BUY",
):
    # Calculate percentage (assuming it's based on entry and SL)
    try:
        entry_float = float(entry.replace(',', ''))
        sl_float = float(sl.replace(',', ''))
        percentage = abs((sl_float - entry_float) / entry_float * 100)
        percentage_text = f"(≤ {percentage:.2f}%)"
    except:
        percentage_text = ""
    
    # Normalize and validate order type
    order_type_normalized = order_type.upper()
    if order_type_normalized not in ("BUY", "SELL"):
        await interaction.response.send_message(
            'Invalid order type. Please use "BUY" or "SELL".',
            ephemeral=True
        )
        return

    # Map order type to emoji label
    # Assumes your Discord server has emojis named :Long: and :Short:
    emoji = ":Long:" if order_type_normalized == "BUY" else ":Short:"

    # Build embed description
    description_parts = []

    # Add emoji representing order type
    description_parts.append(emoji)
    description_parts.append(" ")
    
    # Add symbol and prices
    description_parts.append(f"**{symbol.upper()}**")
    description_parts.append(" | ")
    description_parts.append(f"**Entry:** ")
    # Add invisible characters for formatting (like in the HTML)
    description_parts.append(entry)
    description_parts.append(" | ")
    description_parts.append(f"**SL:** {sl} {percentage_text}")
    
    description = "".join(description_parts)
    
    # Create embed
    embed = discord.Embed(
        description=description,
        color=discord.Color.from_rgb(59, 165, 92),  # Similar to the blue-green color in the HTML
        timestamp=discord.utils.utcnow()
    )
    
    # Add disclaimer (formatted to look like a blockquote)
    # Discord embeds don't support true blockquotes, but we format it nicely
    disclaimer = "⚠️ **Disclaimer**\nChallenge trades may involve higher risks. Only risk what you can afford to lose and be prepared for the possibility of significant losses. Always trade responsibly."
    embed.add_field(name="", value=disclaimer, inline=False)
    
    # Add footer with status
    status_text = status if status else "Active"
    # Format timestamp - Discord will show it as "Today at X:XX AM/PM" format
    timestamp = discord.utils.format_dt(discord.utils.utcnow(), style='f')
    footer_text = f"Status: 🛑 {status_text} • {timestamp}"
    embed.set_footer(text=footer_text)
    
    # Set image if provided
    if image_url:
        embed.set_image(url=image_url)
    
    # Build message content with mention
    content = f"{user.mention}"
    
    # Prepare secret content for unlock button
    # Store full trade data so we can recreate the same format when unlocked
    trade_data = {
        "type": "trade_ephemeral",
        "user": user.id,
        "symbol": symbol,
        "entry": entry,
        "sl": sl,
        "percentage_text": percentage_text,
        "emoji": emoji,
        "image_url": image_url,
        "status": status_text,
        "order_type": order_type_normalized,
    }
    
    # Use interaction ID as unique identifier for ephemeral messages
    # (since we can't get message ID from ephemeral responses)
    unique_id = interaction.id
    
    # Store the trade data
    SECRET_STORE[unique_id] = trade_data
    
    # Create unlock view with button
    view = UnlockView(locked_message_id=unique_id, timeout=None)
    
    # Send ephemeral message with unlock button (only visible to the user who ran the command)
    await interaction.response.send_message(
        content=content,
        embed=embed,
        view=view,
        ephemeral=True
    )


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in environment/.env")

bot.run(TOKEN)

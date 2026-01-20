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
            
            # Add custom secret content if provided
            custom_content = trade_data.get("secret_content")
            if custom_content:
                embed.add_field(name="", value=f"\n{custom_content}", inline=False)
            
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
        intents.message_content = True  # Required to read message content
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Sync commands to a specific guild for fast update (recommended for dev)
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    # Example: Respond to regular messages (not slash commands)
    async def on_message(self, message: discord.Message):
        # Ignore messages from bots to prevent loops
        if message.author.bot:
            return
        
        # Example: Echo messages that start with "!echo"
        if message.content.startswith("!echo "):
            text = message.content[6:]  # Remove "!echo " prefix
            await message.channel.send(f"Echo: {text}")
        
        # Example: Reply to a message
        if message.content.startswith("!reply"):
            await message.reply("This is a reply to your message!")
        
        # Example: Send a message in the same channel
        if message.content.startswith("!hello"):
            await message.channel.send(f"Hello, {message.author.mention}!")


bot = MyBot()


@bot.tree.command(name="lock", description="Post an unlock button that reveals content ephemerally.")
@app_commands.describe(secret="The content to reveal when the button is pressed")
async def lock_cmd(interaction: discord.Interaction, secret: str):
    # 1) Send the locked message with the button view
    # We need the message id, so we respond first, then fetch the sent message.
    await interaction.response.send_message(
        "Press the button to unlock the content...",
        ephemeral=False
    )

    locked_message = await interaction.original_response()

    # 2) Store the secret keyed by the locked message id
    SECRET_STORE[locked_message.id] = secret

    # 3) Edit the message to add the button view, now that we know message id
    view = UnlockView(locked_message_id=locked_message.id, timeout=None)
    await locked_message.edit(view=view)


@bot.tree.command(name="lock_embed", description="Lock a trade-style embed with unlock button.")
@app_commands.describe(
    symbol="e.g. BTC",
    entry="e.g. 93022",
    sl="e.g. 93280",
    note="Optional note"
)
async def lock_embed_cmd(interaction: discord.Interaction, symbol: str, entry: str, sl: str, note: Optional[str] = None):
    # Build a nice “locked” embed preview (public), but hide the real content in secret store
    preview = discord.Embed(
        title="🔒 Locked Trade",
        description=f"**{symbol.upper()}** | **Entry:** {entry} | **SL:** {sl}\n\nPress the button to unlock the content…",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )
    if note:
        preview.add_field(name="Note", value=note, inline=False)

    await interaction.response.send_message(embed=preview)
    locked_message = await interaction.original_response()

    # Secret content that only the clicker sees (ephemeral)
    secret = (
        f"**{symbol.upper()}**\n"
        f"• Entry: {entry}\n"
        f"• SL: {sl}\n"
        f"{('• ' + note) if note else ''}\n\n"
        f"⚠️ Disclaimer: Trade responsibly."
    )
    SECRET_STORE[locked_message.id] = secret

    view = UnlockView(locked_message_id=locked_message.id, timeout=None)
    await locked_message.edit(view=view)


# Example: Simple text message
@bot.tree.command(name="say", description="Send a simple text message.")
@app_commands.describe(text="The message to send")
async def say_cmd(interaction: discord.Interaction, text: str):
    await interaction.response.send_message(text)


# Example: Message with embed
@bot.tree.command(name="embed", description="Send a message with an embed.")
@app_commands.describe(title="Embed title", description="Embed description", color="Color name (red, green, blue, etc.)")
async def embed_cmd(interaction: discord.Interaction, title: str, description: str, color: Optional[str] = None):
    # Map color names to Discord colors
    color_map = {
        "red": discord.Color.red(),
        "green": discord.Color.green(),
        "blue": discord.Color.blue(),
        "yellow": discord.Color.gold(),
        "purple": discord.Color.purple(),
        "orange": discord.Color.orange(),
    }
    embed_color = color_map.get(color.lower() if color else None, discord.Color.blurple())
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=embed_color,
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)


# Example: Send message to a specific channel
@bot.tree.command(name="send_to_channel", description="Send a message to a specific channel.")
@app_commands.describe(channel="The channel to send to", message="The message to send")
async def send_to_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    # Send message to the specified channel
    await channel.send(message)
    # Confirm to the user
    await interaction.response.send_message(f"✅ Message sent to {channel.mention}!", ephemeral=True)


# Trade ephemeral message command (matches the HTML structure you provided)
@bot.tree.command(name="trade_ephemeral", description="Send an ephemeral trade message with embed, image, unlock button, and mention.")
@app_commands.describe(
    user="User to mention",
    symbol="Trading symbol (e.g., XMR, BTC)",
    entry="Entry price",
    sl="Stop loss price",
    secret_content="Additional content to reveal when unlock button is clicked (optional)",
    emoji="Custom emoji (optional, can be emoji name or ID)",
    image_url="Image URL (optional)",
    status="Status text (e.g., 'Stopped', 'Active')",
    reply_to_message="Message ID to reply to (optional)"
)
async def trade_ephemeral_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    symbol: str,
    entry: str,
    sl: str,
    secret_content: Optional[str] = None,
    emoji: Optional[str] = None,
    image_url: Optional[str] = None,
    status: Optional[str] = None,
    reply_to_message: Optional[str] = None
):
    # Calculate percentage (assuming it's based on entry and SL)
    try:
        entry_float = float(entry.replace(',', ''))
        sl_float = float(sl.replace(',', ''))
        percentage = abs((sl_float - entry_float) / entry_float * 100)
        percentage_text = f"(≤ {percentage:.2f}%)"
    except:
        percentage_text = ""
    
    # Build embed description
    description_parts = []
    
    # Add emoji if provided
    if emoji:
        # Try to parse as custom emoji (format: name:id or just id)
        if ':' in emoji:
            # Format: emoji_name:emoji_id
            parts = emoji.split(':')
            if len(parts) == 2:
                emoji_str = f"<:{parts[0]}:{parts[1]}>"
            else:
                emoji_str = emoji
        else:
            # Try as emoji ID or use as Unicode emoji
            try:
                emoji_id = int(emoji)
                # For custom emoji, we need the name too - use symbol as fallback
                emoji_str = f"<:{symbol}:{emoji_id}>"
            except:
                # Use as Unicode emoji or emoji name
                emoji_str = emoji
        description_parts.append(emoji_str)
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
    
    # Note: For ephemeral messages, we can't directly reply to another message
    # But if reply_to_message is provided, we can add a reference in the embed
    if reply_to_message:
        try:
            message_id = int(reply_to_message)
            # Add a note about replying (though ephemeral messages are private)
            embed.insert_field_at(0, name="", value=f"*Reference: Message {reply_to_message}*", inline=False)
        except:
            pass
    
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
        "secret_content": secret_content  # Optional custom content
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

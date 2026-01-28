import os
import ssl
import time
from dataclasses import dataclass
from typing import Dict, Optional, List

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
SECRET_STORE = {}  # type: Dict[int, str]


@dataclass
class UnlockConfig:
    # Optional role restriction: set to a role ID string/int to require it.
    allowed_role_id: Optional[int] = None


CONFIG = UnlockConfig(
    allowed_role_id=None  # e.g. 123456789012345678 to restrict
)


# ---- Data Models for Enhanced Trade Display ----

@dataclass
class PositionMetrics:
    """Represents calculated position metrics for a trader or user"""
    balance: float          # Account balance
    position_size: float    # Total position value (balance * leverage)
    quantity: float         # Number of units/contracts
    risk_amount: float      # Dollar amount at risk
    risk_percentage: float  # Percentage of balance at risk


@dataclass
class TradeSignal:
    """Represents the core trade signal information"""
    symbol: str
    entry: float
    stop_loss: float
    status: str
    risk_percentage: float  # Calculated from entry and stop_loss


# ---- Position Calculator ----

class PositionCalculator:
    """Calculates position metrics based on balance and risk parameters"""
    
    @staticmethod
    def calculate_risk_percentage_from_prices(entry: float, stop_loss: float) -> float:
        """Calculate risk percentage between entry and stop loss prices"""
        if entry <= 0:
            raise ValueError("Entry price must be greater than zero")
        return abs(entry - stop_loss) / entry * 100
    
    @staticmethod
    def calculate_position(
        balance: float,
        entry_price: float,
        stop_loss: float,
        risk_percentage: float,
        leverage: float,
        quantity: Optional[float] = None
    ) -> PositionMetrics:
        """Calculate complete position metrics"""
        # Validate inputs
        if balance <= 0:
            raise ValueError("Balance must be greater than zero")
        if entry_price <= 0:
            raise ValueError("Entry price must be greater than zero")
        if stop_loss <= 0:
            raise ValueError("Stop loss must be greater than zero")
        if entry_price == stop_loss:
            raise ValueError("Entry and stop loss must be different")
        if leverage <= 0:
            raise ValueError("Leverage must be greater than zero")
        if risk_percentage < 0 or risk_percentage > 100:
            raise ValueError("Risk percentage must be between 0 and 100")
        if quantity is not None and quantity <= 0:
            raise ValueError("Quantity must be greater than zero")
        
        # Calculate position size
        position_size = balance * leverage
        
        # Calculate risk percentage from prices
        price_risk_percentage = abs(entry_price - stop_loss) / entry_price
        
        # Calculate risk amount
        risk_amount = position_size * price_risk_percentage
        
        # Calculate or use provided quantity
        if quantity is None:
            calculated_quantity = position_size / entry_price
        else:
            calculated_quantity = quantity
        
        return PositionMetrics(
            balance=balance,
            position_size=position_size,
            quantity=calculated_quantity,
            risk_amount=risk_amount,
            risk_percentage=(risk_amount / balance) * 100
        )


# ---- Formatting Utilities ----

def format_currency(value: float) -> str:
    """Format monetary value with $ and 2 decimal places"""
    if value >= 1000:
        return f"${value:,.1f}"
    return f"${value:.2f}"


def format_percentage(value: float) -> str:
    """Format percentage with % and 1 decimal place"""
    return f"{value:.1f}%"


def format_quantity(value: float) -> str:
    """Format quantity with appropriate precision"""
    if value >= 1000:
        return f"{value/1000:.2f}K"
    elif value >= 1:
        return f"{value:.2f}"
    else:
        return f"{value:.4f}"


def format_blockquote(text: str) -> str:
    """Format text as Discord blockquote"""
    return "\n".join(f"> {line}" for line in text.split("\n"))


# ---- Embed Builder ----

class EmbedBuilder:
    """Creates formatted Discord embeds for trade details and position overview"""
    
    @staticmethod
    def build_trade_details_embed(
        symbol: str,
        entry: float,
        stop_loss: float,
        status: str,
        risk_percentage: float,
        order_type: str
    ) -> discord.Embed:
        """Build the trade details embed"""
        # Determine emoji based on order type
        emoji = ":Long:" if order_type.upper() == "BUY" else ":Short:"
        
        # Build description
        description = f"{emoji} **{symbol.upper()}** | **Entry:** {entry} | **SL:** {stop_loss} (≤ {format_percentage(risk_percentage)})"
        
        # Determine color based on order type
        if order_type.upper() == "BUY":
            color = discord.Color.from_rgb(59, 165, 92)  # Green for long
        else:
            color = discord.Color.from_rgb(88, 101, 242)  # Blue for short
        
        # Create embed
        embed = discord.Embed(
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        
        # Add disclaimer as blockquote
        disclaimer = "> ⚠️ **Disclaimer**\n> Challenge trades may involve higher risks. Only risk what you can afford to lose and be prepared for the possibility of significant losses. Always trade responsibly."
        embed.add_field(name="", value=disclaimer, inline=False)
        
        # Add footer with status
        footer_text = f"Status: ❌ {status}"
        embed.set_footer(text=footer_text)
        
        return embed
    
    @staticmethod
    def build_image_embed(image_url: str) -> discord.Embed:
        """Build a separate image embed"""
        embed = discord.Embed()
        embed.set_image(url=image_url)
        return embed
    
    @staticmethod
    def build_position_overview_embed(
        trader_metrics: Optional[PositionMetrics],
        user_metrics: Optional[PositionMetrics]
    ) -> Optional[discord.Embed]:
        """Build the position overview embed"""
        # Only create embed if at least one position is provided
        if trader_metrics is None and user_metrics is None:
            return None
        
        # Create embed with title
        embed = discord.Embed(
            title="<:peepo_wg:1462143740352266408> Challenge - Position Overview",
            color=discord.Color.from_rgb(252, 194, 0)  # Gold/yellow color
        )
        
        # Add trader position field
        if trader_metrics:
            trader_text = (
                f"• **Balance:** `{format_currency(trader_metrics.balance)}`\n"
                f"• **Position:** `{format_currency(trader_metrics.position_size)}`\n"
                f"• **Quantity:** `{format_quantity(trader_metrics.quantity)}`\n"
                f"• **Risk:** `{format_currency(trader_metrics.risk_amount)} ({format_percentage(trader_metrics.risk_percentage)})`"
            )
            embed.add_field(name="Trader Position", value=trader_text, inline=True)
        
        # Add user position field
        if user_metrics:
            user_text = (
                f"• **Balance:** `{format_currency(user_metrics.balance)}`\n"
                f"• **Position:** `{format_currency(user_metrics.position_size)}`\n"
                f"• **Quantity:** `{format_quantity(user_metrics.quantity)}`\n"
                f"• **Risk:** `{format_currency(user_metrics.risk_amount)} ({format_percentage(user_metrics.risk_percentage)})`"
            )
            embed.add_field(name="Your Position", value=user_text, inline=True)
        
        # Add footer
        embed.set_footer(text="⚠️ Beta — balance may not be updated yet. Use as guidance only.")
        
        return embed


# ---- UI Component Builder ----

class UIComponentBuilder:
    """Creates non-functional button components for display"""
    
    @staticmethod
    def build_button_row() -> discord.ui.View:
        """Build a view with non-functional buttons"""
        view = discord.ui.View(timeout=None)
        
        # Add "Set My Balance..." button
        balance_button = discord.ui.Button(
            label="Set My Balance...",
            emoji="💰",
            style=discord.ButtonStyle.primary,
            disabled=True
        )
        view.add_item(balance_button)
        
        # Add "Override Risk (%)..." button
        risk_button = discord.ui.Button(
            label="Override Risk (%)...",
            emoji="🎯",
            style=discord.ButtonStyle.secondary,
            disabled=True
        )
        view.add_item(risk_button)
        
        return view


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

        # Check if this is an enhanced trade_ephemeral type
        if isinstance(secret, dict) and secret.get("type") == "trade_ephemeral_enhanced":
            # Enhanced trade data with full embeds
            trade_data = secret
            
            # Get user mention
            user_id = trade_data.get("user_id")
            user_mention = f"<@{user_id}>" if user_id else ""
            
            # Build trade details embed (without image)
            trade_embed = EmbedBuilder.build_trade_details_embed(
                symbol=trade_data.get("symbol"),
                entry=trade_data.get("entry"),
                stop_loss=trade_data.get("sl"),
                status=trade_data.get("status"),
                risk_percentage=trade_data.get("price_risk_percentage"),
                order_type=trade_data.get("order_type")
            )
            
            # Build position overview embed
            position_embed = EmbedBuilder.build_position_overview_embed(
                trader_metrics=trade_data.get("trader_metrics"),
                user_metrics=trade_data.get("user_metrics")
            )
            
            # Collect embeds
            embeds = [trade_embed]
            if position_embed:
                embeds.append(position_embed)
            
            # Add image embed if image URL provided (as 3rd embed)
            image_url = trade_data.get("image_url")
            if image_url:
                image_embed = EmbedBuilder.build_image_embed(image_url)
                embeds.append(image_embed)
            
            # Build button row
            button_view = UIComponentBuilder.build_button_row()
            
            # Send ephemeral message with full content
            await interaction.response.send_message(
                content=user_mention,
                embeds=embeds,
                view=button_view,
                ephemeral=True
            )
        
        # Check if this is a legacy trade_ephemeral type (dictionary) or plain text
        elif isinstance(secret, dict) and secret.get("type") == "trade_ephemeral":
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
        # Sync commands to a specific guild for fast update (recommended for dev)
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            print("Commands synced globally")


bot = MyBot()


# Enhanced Trade ephemeral message command
@bot.tree.command(name="trade_ephemeral", description="Send an enhanced ephemeral trade message with position calculations.")
@app_commands.describe(
    user="User to mention",
    symbol="Trading symbol (e.g., XMR, BTC)",
    entry="Entry price",
    sl="Stop loss price",
    order_type='Order type: "BUY" or "SELL" (controls emoji: :Long: or :Short:)',
    status="Status text (e.g., 'Limit order cancelled', 'Active')",
    trader_balance="Trader's account balance (optional)",
    risk_percentage="Risk percentage (default: 25%)",
    leverage="Leverage multiplier (default: 5x)",
    quantity="Explicit quantity override (optional)",
    image_url="Image URL (optional)"
)
async def trade_ephemeral_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    symbol: str,
    entry: float,
    sl: float,
    order_type: str = "BUY",
    status: Optional[str] = None,
    trader_balance: Optional[float] = None,
    risk_percentage: float = 25.0,
    leverage: float = 5.0,
    quantity: Optional[float] = None,
    image_url: Optional[str] = None,
):
    """Enhanced trade ephemeral command with position calculations"""
    
    # Validate parameters
    try:
        if entry <= 0:
            await interaction.response.send_message(
                "❌ Entry price must be greater than zero.",
                ephemeral=True
            )
            return
        
        if sl <= 0:
            await interaction.response.send_message(
                "❌ Stop loss must be greater than zero.",
                ephemeral=True
            )
            return
        
        if entry == sl:
            await interaction.response.send_message(
                "❌ Entry and stop loss must be different.",
                ephemeral=True
            )
            return
        
        if trader_balance is not None and trader_balance <= 0:
            await interaction.response.send_message(
                "❌ Trader balance must be greater than zero.",
                ephemeral=True
            )
            return
        
        if risk_percentage < 0 or risk_percentage > 100:
            await interaction.response.send_message(
                "❌ Risk percentage must be between 0 and 100.",
                ephemeral=True
            )
            return
        
        if leverage <= 0:
            await interaction.response.send_message(
                "❌ Leverage must be greater than zero.",
                ephemeral=True
            )
            return
        
        if quantity is not None and quantity <= 0:
            await interaction.response.send_message(
                "❌ Quantity must be greater than zero.",
                ephemeral=True
            )
            return
        
        # Normalize order type
        order_type_normalized = order_type.upper()
        if order_type_normalized not in ("BUY", "SELL"):
            await interaction.response.send_message(
                '❌ Invalid order type. Please use "BUY" or "SELL".',
                ephemeral=True
            )
            return
        
        # Calculate risk percentage from prices
        price_risk_percentage = PositionCalculator.calculate_risk_percentage_from_prices(entry, sl)
        
        # User balance defaults to trader balance
        user_balance = trader_balance
        
        # Calculate trader position if balance provided
        trader_metrics = None
        if trader_balance is not None:
            trader_metrics = PositionCalculator.calculate_position(
                balance=trader_balance,
                entry_price=entry,
                stop_loss=sl,
                risk_percentage=risk_percentage,
                leverage=leverage,
                quantity=quantity
            )
        
        # Calculate user position (same as trader)
        user_metrics = trader_metrics
        
        # Store trade data for unlock button
        status_text = status if status else "Active"
        
        trade_data = {
            "type": "trade_ephemeral_enhanced",
            "user_id": user.id,
            "symbol": symbol,
            "entry": entry,
            "sl": sl,
            "order_type": order_type_normalized,
            "status": status_text,
            "price_risk_percentage": price_risk_percentage,
            "trader_metrics": trader_metrics,
            "user_metrics": user_metrics,
            "image_url": image_url,
        }
        
        # Use interaction ID as unique identifier
        unique_id = interaction.id
        SECRET_STORE[unique_id] = trade_data
        
        # Create unlock view
        unlock_view = UnlockView(locked_message_id=unique_id, timeout=None)
        
        # Send initial message with unlock button
        await interaction.response.send_message(
            content=f"{user.mention} Press the button to unlock the content...",
            view=unlock_view,
            ephemeral=True
        )
        
    except ValueError as e:
        await interaction.response.send_message(
            f"❌ Error: {str(e)}",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ An unexpected error occurred: {str(e)}",
            ephemeral=True
        )


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in environment/.env")

bot.run(TOKEN)

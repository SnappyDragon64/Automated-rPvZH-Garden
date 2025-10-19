import asyncio
import dataclasses
import io
import json
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional, List

import discord
from redbot.core import Config, commands, data_manager

from .decorators import is_cog_ready, is_not_locked
from .helpers import (
    TimeHelper,
    PlantHelper,
    SalesHelper,
    LockHelper,
    LoggingHelper,
    DataHelper,
    ImageHelper,
    GardenHelper,
    FusionHelper,
    TradeHelper,
    ShopHelper,
    BackgroundHelper,
    GameStateHelper,
    PIL_AVAILABLE,
)
from .models import PlantedSeedling, PlantedPlant, ShopItemDefinition


class ARG(commands.Cog):
    """Penny's Zen Garden Interface - Assist users in managing their Zen Gardens."""

    CURRENCY_EMOJI = "<:Sun:286219730296242186>"
    DISCORD_LOG_CHANNEL_ID = 1386642972539621487
    # 1379054870312779917
    _DISPLAY_TEXT_GARDEN_IN_PROFILE: bool = False

    def __init__(self, bot: commands.Bot):
        self._initialized = False

        self.bot = bot
        self.config = Config.get_conf(self, identifier=291154617134223360)
        self.config.register_global(game_state={})

        self.cog_data_path = data_manager.bundled_data_path(self)
        self.lock_helper = LockHelper()
        self.logger = LoggingHelper(bot, self.DISCORD_LOG_CHANNEL_ID)
        self.data_loader = DataHelper(self.cog_data_path, self.logger)
        self.data_loader.load_all_data()

        self.game_state_helper = GameStateHelper(self.config, self.logger)

        self.image_helper: Optional[ImageHelper] = None
        self.sales_helper: Optional[SalesHelper] = None
        self.plant_helper: Optional[PlantHelper] = None
        self.fusion_helper: Optional[FusionHelper] = None
        self.background_helper: Optional[BackgroundHelper] = None
        self.trade_helper: Optional[TradeHelper] = None
        self.garden_helper: Optional[GardenHelper] = None
        self.shop_helper: Optional[ShopHelper] = None

        self.growth_task = self.bot.loop.create_task(self.startup_and_growth_loop())

    def cog_unload(self):
        """Cog cleanup method."""

        if self.growth_task:
            self.growth_task.cancel()

        self.lock_helper.clear_all_locks()
        self.logger.init_log("Zen Garden cog systems are now offline.", "INFO")

    async def _load_and_initialize_helpers(self):
        await self.game_state_helper.load_game_state()

        self.image_helper = ImageHelper(self.cog_data_path, self.logger)
        self.sales_helper = SalesHelper(self.data_loader.sales_prices, self.CURRENCY_EMOJI)
        self.plant_helper = PlantHelper(self.data_loader.base_plants, self.data_loader.seedlings_data)
        self.fusion_helper = FusionHelper(self.data_loader.fusion_plants, self.data_loader.materials_data,
                                          self.plant_helper)
        self.background_helper = BackgroundHelper(self.data_loader.backgrounds_data)
        self.trade_helper = TradeHelper(self.lock_helper)

        self.garden_helper = GardenHelper(self.game_state_helper)
        self.shop_helper = ShopHelper(
            self.game_state_helper,
            self.plant_helper,
            self.data_loader.penny_shop_data,
            self.data_loader.rux_shop_data,
            self.data_loader.dave_shop_data,
            self.data_loader.materials_data
        )

        self.image_helper.load_assets()

    async def startup_and_growth_loop(self):
        """The main background task for the cog."""

        await self.bot.wait_until_ready()
        await self.logger.flush_init_log_queue()
        await self.logger.log_to_discord("Growth Loop: System Online.", "INFO")

        await self._load_and_initialize_helpers()

        await self.shop_helper.refresh_penny_shop_if_needed(self.logger)
        await self.shop_helper.refresh_dave_shop_if_needed(self.logger)

        self._initialized = True

        await self.logger.log_to_discord("Growth Loop: Startup complete. Entering main simulation cycle.", "INFO")
        loop_counter = 0
        while not self.bot.is_closed():
            try:
                loop_start_time = time.monotonic()

                growth_duration = self.game_state_helper.get_global_state("plant_growth_duration_minutes", 240)
                base_progress = 100.0 / (growth_duration if growth_duration > 0 else 240)

                all_user_ids = self.garden_helper.get_all_user_ids()

                for user_id_int in all_user_ids:
                    profile = self.garden_helper.get_user_profile_view(user_id_int)

                    time_mastery_bonus = 1 + (profile.time_mastery * 0.1)

                    for i, slot_content in enumerate(profile.garden):
                        if isinstance(slot_content, PlantedSeedling):
                            growth_multiplier = 1.0
                            seedling_id = slot_content.id
                            if seedling_def := self.plant_helper.get_seedling_by_id(seedling_id):
                                growth_multiplier = seedling_def.growth_multiplier

                            final_progress = base_progress * time_mastery_bonus * growth_multiplier

                            self.garden_helper.update_seedling_progress(user_id_int, i, final_progress)

                            updated_profile = self.garden_helper.get_user_profile_view(user_id_int)
                            updated_slot = updated_profile.garden[i]

                            if isinstance(updated_slot, PlantedSeedling) and updated_slot.progress >= 100.0:
                                await self._mature_plant(user_id_int, i, updated_slot)

                await self.shop_helper.refresh_penny_shop_if_needed(self.logger)
                await self.shop_helper.refresh_dave_shop_if_needed(self.logger)

                await self.game_state_helper.commit_to_disk()

                loop_duration = time.monotonic() - loop_start_time
                await self.logger.log_to_discord(
                    f"Growth Loop: Cycle {loop_counter} completed in {loop_duration:.2f}s. Data saved.",
                    "INFO")
            except Exception as e:
                await self.logger.log_to_discord(
                    f"Growth Loop: CRITICAL Anomaly in cycle {loop_counter}: {e}\n{traceback.format_exc()}", "CRITICAL")

            loop_counter += 1
            now = datetime.now()
            next_minute_start = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            target_time = next_minute_start + timedelta(seconds=1)
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(max(0.1, wait_seconds))

    async def _mature_plant(self, user_id: int, plot_index: int, seedling_obj: PlantedSeedling):
        """Handles the logic for when a seedling reaches 100% growth."""

        seedling_id = seedling_obj.id

        plant_category = "vanilla"

        if seedling_def := self.plant_helper.get_seedling_by_id(seedling_id):
            plant_category = seedling_def.category

        grown_plant_def = self.plant_helper.get_random_plant_by_category(plant_category)

        if grown_plant_def is None:
            await self.logger.log_to_discord(
                f"CRITICAL: Failed to get a plant for category '{plant_category}' for user {user_id}. Maturation "
                f"aborted.",
                "CRITICAL")
            return

        newly_matured_plant = PlantedPlant(
            id=grown_plant_def.id,
            name=grown_plant_def.name,
            type=grown_plant_def.type
        )
        self.garden_helper.set_garden_plot(user_id, plot_index, newly_matured_plant)

        discord_user = self.bot.get_user(user_id)
        if not discord_user:
            return

        embed = discord.Embed(
            title="🌱 Plant Maturation Complete",
            description=f"Alert, {discord_user.mention}: Your **{seedling_obj.name}** in plot "
                        f"{plot_index + 1} has matured into a **{newly_matured_plant.name}**.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny System Monitoring")

        image_file_to_send = self.image_helper.get_image_file_for_plant(newly_matured_plant.id)
        if image_file_to_send:
            embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        notification_channel_id = seedling_obj.notification_channel_id
        target_channel = self.bot.get_channel(notification_channel_id) if notification_channel_id else None

        sent_to_channel = False
        if discord.TextChannel:
            try:
                await target_channel.send(content=discord_user.mention, embed=embed, file=image_file_to_send,
                                          allowed_mentions=discord.AllowedMentions(users=True))
                sent_to_channel = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        if not sent_to_channel:
            try:
                dm_image_file = self.image_helper.get_image_file_for_plant(newly_matured_plant.id)

                if dm_image_file:
                    embed.set_image(url=f"attachment://{dm_image_file.filename}")
                else:
                    embed.set_image(url=None)

                await discord_user.send(embed=embed, file=dm_image_file)
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.command(name="profile")
    @is_cog_ready()
    async def profile_command(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        target_user = user or ctx.author

        if user and target_user.id != ctx.author.id:
            if self.lock_helper.get_user_lock(target_user.id):
                profile_lock_embed = discord.Embed(
                    title="⚠️ Target Profile Advisory",
                    description=(f"User {target_user.mention} is currently engaged in a pending action.\n"
                                 f"Their profile data may be subject to imminent change."),
                    color=discord.Color.orange()
                )
                await ctx.send(embed=profile_lock_embed)

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        rank = self.garden_helper.get_user_rank(target_user.id)
        rank_str = str(rank) if rank is not None else "N/A"

        garden_image_file: Optional[discord.File] = None
        display_text_garden = self._DISPLAY_TEXT_GARDEN_IN_PROFILE

        if not PIL_AVAILABLE:
            display_text_garden = True
        else:
            try:
                active_bg_id = profile.active_background
                bg_def = self.background_helper.get_background_by_id(active_bg_id)
                bg_filename = f"{bg_def.image_file}.png" if bg_def else "garden.png"

                unlocked_slots = {i + 1 for i in range(12) if self.garden_helper.is_slot_unlocked(profile, i + 1)}
                garden_image_file = await self.image_helper.generate_garden_image(profile, unlocked_slots,
                                                                                  background_filename=bg_filename)
            except Exception as e:
                await self.logger.log_to_discord(
                    f"Profile image generation failed for {target_user.id}: {e}\n{traceback.format_exc()}", "ERROR")
                await ctx.send("An error occurred while generating the garden image; displaying text fallback.",
                               delete_after=10)
                display_text_garden = True

        embed = discord.Embed(color=discord.Color.blue())
        embed.set_author(name=f"{target_user.display_name}: Zen Garden Dossier",
                         icon_url=target_user.display_avatar.url)

        sun_mastery = profile.sun_mastery
        time_mastery = profile.time_mastery

        sun_mastery_display = f"\n**Sun Mastery:** {sun_mastery} ({1 + (0.1 * sun_mastery):.2f}x sell boost)" \
            if sun_mastery > 0 else ""
        time_mastery_display = f"\n**Time Mastery:** {time_mastery} ({1 + (0.1 * time_mastery):.2f}x growth boost)" \
            if time_mastery > 0 else ""

        embed.add_field(
            name="📈 Core Metrics",
            value=f"**Solar Energy Balance:** {profile.balance:,} {self.CURRENCY_EMOJI}\n"
                  f"**Garden User Rank:** #{rank_str}{sun_mastery_display}{time_mastery_display}",
            inline=False
        )

        if display_text_garden:
            col1, col2 = self.garden_helper.get_text_garden_display(profile)
            embed.add_field(name="🌳 Garden Plots", value=col1, inline=True)
            embed.add_field(name="🌳 Garden Plots", value=col2, inline=True)

        inventory_items = profile.inventory
        inventory_field_value = "No assets acquired."

        if inventory_items:
            all_item_defs = self.shop_helper.get_all_item_definitions()
            inventory_display = []

            for item_id, count in sorted(inventory_items.items()):
                item_info = all_item_defs.get(item_id)

                if isinstance(item_info, ShopItemDefinition) and item_info.category == "upgrade":
                    continue

                item_name = ""
                if isinstance(item_info, ShopItemDefinition):
                    item_name = item_info.name
                elif isinstance(item_info, dict):
                    item_name = item_info.get("name", item_id)

                item_name = item_name or item_id
                inventory_display.append(f"**{item_name}** (`{item_id}`)" + (f" x{count}" if count > 1 else ""))

            if inventory_display:
                inventory_field_value = ", ".join(inventory_display)

        embed.add_field(name="🎒 Acquired Assets", value=inventory_field_value, inline=False)

        if garden_image_file:
            embed.set_image(url=f"attachment://{garden_image_file.filename}")

        embed.set_footer(text="Penny - Data Systems & User Profiling")
        await ctx.send(embed=embed, file=garden_image_file)

    @commands.command(name="daily")
    @is_cog_ready()
    @is_not_locked()
    async def daily_command(self, ctx: commands.Context):
        """Collect your daily solar energy stipend."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        current_date_est = TimeHelper.get_est_date()

        if profile.last_daily == current_date_est:
            now_est = datetime.now(TimeHelper.EST)
            next_reset_est = (now_est + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            unix_ts = int(next_reset_est.timestamp())
            embed = discord.Embed(
                title="❌ Daily Stipend Already Dispensed",
                description=f"User {ctx.author.mention}, system records indicate your daily solar energy stipend of "
                            f"1000 {self.CURRENCY_EMOJI} has already been collected for {current_date_est}.\n "
                            f"Next available collection cycle begins: <t:{unix_ts}:R>.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Financial Systems Interface")
            await ctx.send(embed=embed)
            return

        self.garden_helper.add_balance(ctx.author.id, 1000)
        self.garden_helper.set_last_daily(ctx.author.id, current_date_est)
        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        embed = discord.Embed(
            title=f"☀️ Daily Solar Energy Collected",
            description=f"User {ctx.author.mention}, your daily stipend of **1000** {self.CURRENCY_EMOJI} has been "
                        f"successfully credited to your account.\n "
                        f"Your current solar balance is now **{profile.balance:,}** {self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Financial Systems Interface")
        await ctx.send(embed=embed)

    @commands.command(name="plant")
    @is_cog_ready()
    @is_not_locked()
    async def plant_command(self, ctx: commands.Context, *slots_to_plant_in: int):
        """Initiate seedling cultivation in specified garden plots."""

        if not slots_to_plant_in:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Cultivation",
                                  description=f"User {ctx.author.mention}, please specify target plot numbers for "
                                              f"seedling cultivation.\nSyntax: `{ctx.prefix}plant <plot_num_1> ["
                                              f"plot_num_2] ...`\nExample: `{ctx.prefix}plant 1 2 3`",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        garden = profile.garden
        cost_per_seedling = 100

        valid_slots_to_plant = []
        error_messages = []

        for slot_num_1based in set(slots_to_plant_in):
            if not (1 <= slot_num_1based <= 12):
                error_messages.append(f"Plot {slot_num_1based}: Invalid designation.")
            elif not self.garden_helper.is_slot_unlocked(profile, slot_num_1based):
                error_messages.append(f"Plot {slot_num_1based}: Access restricted (Locked).")
            elif garden[slot_num_1based - 1] is not None:
                error_messages.append(f"Plot {slot_num_1based}: Currently occupied.")
            else:
                valid_slots_to_plant.append(slot_num_1based)

        if not valid_slots_to_plant:
            desc = "Cultivation protocol aborted:\n\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Cultivation Protocol Error", description=desc, color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        actual_cost = len(valid_slots_to_plant) * cost_per_seedling

        if profile.balance < actual_cost:
            embed = discord.Embed(title="❌ Insufficient Solar Energy Reserves",
                                  description=f"Cultivation cost for {len(valid_slots_to_plant)} plot(s): "
                                              f"**{actual_cost:,}** {self.CURRENCY_EMOJI}.\n"
                                              f"Your available balance: "
                                              f"**{profile.balance:,}** {self.CURRENCY_EMOJI}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        self.garden_helper.remove_balance(ctx.author.id, actual_cost)

        for slot_num_1based in valid_slots_to_plant:
            self.garden_helper.plant_seedling(
                ctx.author.id, slot_num_1based - 1, "Seedling", ctx.channel.id
            )

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        planted_slots_str = ", ".join(map(str, sorted(valid_slots_to_plant)))
        desc = f"Seedling cultivation initiated in plot(s): **{planted_slots_str}**.\n"
        desc += f"Solar energy expended: **{actual_cost:,}** {self.CURRENCY_EMOJI}.\n"
        desc += f"Remaining solar balance: **{profile.balance:,}** {self.CURRENCY_EMOJI}."

        if error_messages:
            desc += "\n\n**Advisory:** Some plots were not processed:\n" + "\n".join(
                [f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="🌱 Seedling Cultivation Initiated", description=desc, color=discord.Color.green())
        await ctx.send(embed=embed)

    @commands.command(name="sell")
    @is_cog_ready()
    @is_not_locked()
    async def sell_command(self, ctx: commands.Context, *slots_to_sell_from: int):
        """Liquidate mature botanical assets from specified plots."""

        if not slots_to_sell_from:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Liquidation",
                                  description=f"User {ctx.author.mention}, please designate which botanical assets are "
                                              f"to be "f"liquidated from your garden plots.\n"
                                              f"Syntax: `{ctx.prefix}sell <plot_num_1> [plot_num_2] ...`\n"
                                              f"Example: `{ctx.prefix}sell 1 2 3`",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        sale_results = self.sales_helper.process_sales(profile, slots_to_sell_from)

        total_earnings = sale_results["total_earnings"]
        sold_plants_details = sale_results["sold_plants_details"]
        error_messages = sale_results["error_messages"]
        mastery_gained = sale_results["mastery_gained"]
        time_mastery_gained = sale_results["time_mastery_gained"]
        plots_to_clear = sale_results["plots_to_clear"]

        if not sold_plants_details and not mastery_gained and not time_mastery_gained:
            desc = "The asset liquidation process yielded no successful transactions.\n\n"
            if error_messages:
                desc += "Analysis of encountered issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Liquidation Process Inconclusive", description=desc,
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Financial Operations Interface")
            await ctx.send(embed=embed)
            return

        if total_earnings > 0:
            self.garden_helper.add_balance(ctx.author.id, total_earnings)

        if mastery_gained > 0:
            self.garden_helper.increment_mastery(ctx.author.id, mastery_gained)

        if time_mastery_gained > 0:
            self.garden_helper.increment_time_mastery(ctx.author.id, time_mastery_gained)

        for plot_idx_0based in plots_to_clear:
            self.garden_helper.set_garden_plot(ctx.author.id, plot_idx_0based, None)

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        desc = f"User {ctx.author.mention}, asset liquidation protocol executed successfully.\n\n"

        if sold_plants_details:
            desc += "**Liquidated Assets & Yields:**\n" + "\n".join([f"• {detail}" for detail in sold_plants_details])

        if mastery_gained > 0:
            desc += f"\n\n**Your Sun Mastery has increased by {mastery_gained} to a new level of" \
                    f"{profile.sun_mastery}!**"

        if time_mastery_gained > 0:
            desc += f"\n\n**Your Time Mastery has increased by {time_mastery_gained} to a new level of" \
                    f"{profile.time_mastery}!**"

        if total_earnings > 0:
            desc += f"\n\n**Total Solar Energy Acquired from Transaction:** {total_earnings:,} {self.CURRENCY_EMOJI}"

        desc += f"\n**Updated Solar Balance:** {profile.balance:,} {self.CURRENCY_EMOJI}"

        if error_messages:
            desc += "\n\n**System Advisory:** Note that some assets could not be liquidated due to the following" \
                    "issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="💰 Asset Liquidation Complete", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Financial Operations Interface")
        await ctx.send(embed=embed)

    @commands.command(name="shovel")
    @is_cog_ready()
    @is_not_locked()
    async def shovel_command(self, ctx: commands.Context, *slots_to_clear: int):
        """Clear plots of immature seedlings. No sun is awarded. This command cannot remove mature plants."""

        if not slots_to_clear:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Plot Clearing",
                description=f"User {ctx.author.mention}, please specify target plot numbers for clearing.\nSyntax: "
                            f"`{ctx.prefix}shovel <plot_num_1> [plot_num_2] ...`\nExample: `{ctx.prefix}shovel 1 2 3`",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        cleared_slots_details = []
        error_messages = []
        plots_to_actually_clear = []

        for slot_num_1based in set(slots_to_clear):
            plot_idx_0based = slot_num_1based - 1

            if not (0 <= plot_idx_0based < 12):
                error_messages.append(f"Plot {slot_num_1based}: Invalid designation.")
            elif not self.garden_helper.is_slot_unlocked(profile, slot_num_1based):
                error_messages.append(f"Plot {slot_num_1based}: Access restricted (Locked).")
            else:
                occupant = profile.garden[plot_idx_0based]

                if occupant is None:
                    error_messages.append(f"Plot {slot_num_1based}: Already unoccupied.")
                elif isinstance(occupant, PlantedPlant):
                    error_messages.append(
                        f"Plot {slot_num_1based}: Contains a mature plant (**{occupant.name}**). Use `{ctx.prefix}sell` "
                        f"instead.")
                elif isinstance(occupant, PlantedSeedling):
                    cleared_slots_details.append(f"Plot {slot_num_1based} (previously contained **{occupant.name}**)")
                    plots_to_actually_clear.append(plot_idx_0based)
                else:
                    error_messages.append(
                        f"Plot {slot_num_1based}: Contains an unknown entity that cannot be shoveled.")

        if not cleared_slots_details:
            desc = "The plot clearing operation yielded no changes.\n\n"
            if error_messages:
                desc += "Analysis of encountered issues:\n" + "\n".join([f"• {msg}" for msg in error_messages])
            embed = discord.Embed(title="❌ Plot Clearing Operation Inconclusive", description=desc,
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Garden Maintenance Subroutine")
            await ctx.send(embed=embed)
            return

        for plot_idx in plots_to_actually_clear:
            self.garden_helper.set_garden_plot(ctx.author.id, plot_idx, None)

        desc = f"User {ctx.author.mention}, plot clearing operation has been successfully executed.\n\n"
        desc += "**Plots Cleared of Occupants:**\n" + "\n".join([f"• {detail}" for detail in cleared_slots_details])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plots could not be cleared:\n" + "\n".join(
                [f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="🛠️ Plot Clearing Operation Complete", description=desc, color=discord.Color.blue())
        embed.set_footer(text="Penny - Garden Maintenance Subroutine")
        await ctx.send(embed=embed)

    @commands.command(name="reorder")
    @is_cog_ready()
    @is_not_locked()
    async def reorder_command(self, ctx: commands.Context, *new_order_str: str):
        """Reconfigure the physical arrangement of plants within unlocked garden plots."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        garden = profile.garden
        num_garden_slots = len(garden)

        if not new_order_str:
            embed = discord.Embed(title="⚠️ Insufficient Parameters for Garden Reconfiguration",
                                  description=(
                                      f"User {ctx.author.mention}, to reconfigure your garden, please provide the "
                                      f"desired new sequence of your current plot occupants. Specify the *current* plot"
                                      f"numbers (1-12) in the new order you want them for your **unlocked** plots.\n\n "
                                      f"**Syntax:** `{ctx.prefix}reorder <current_plot_num_for_new_pos1> "
                                      f"<current_plot_num_for_new_pos2> ...`\n "
                                      f"**Example (if plots 1-6 are unlocked):** To swap plants in plot 1 and 2, and "
                                      f"keep 3-6 the same: `{ctx.prefix}reorder 2 1 3 4 5 6`"),
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Command Syntax Adherence Module")
            await ctx.send(embed=embed)
            return

        try:
            new_order_original_slots_1_indexed = [int(slot) for slot in new_order_str]
        except ValueError:
            embed = discord.Embed(title="❌ Invalid Plot Designators for Reconfiguration",
                                  description=f"User {ctx.author.mention}, plot designators must be numerical values "
                                              f"corresponding to your current garden plots (e.g., 1, 2, 3...).",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Input Validation Error")
            await ctx.send(embed=embed)
            return

        unlocked_slot_indices_0based = sorted(
            [i for i in range(num_garden_slots) if self.garden_helper.is_slot_unlocked(profile, i + 1)])
        num_unlocked_slots = len(unlocked_slot_indices_0based)

        if len(new_order_original_slots_1_indexed) != num_unlocked_slots:
            embed = discord.Embed(title="❌ Plot Sequence Count Mismatch for Reconfiguration",
                                  description=(
                                      f"User {ctx.author.mention}, the number of plot designators provided"
                                      f"({len(new_order_original_slots_1_indexed)}) "
                                      f"does not match your current number of unlocked plots ({num_unlocked_slots}).\n"
                                      f"Please list the current plot numbers of items from your **{num_unlocked_slots}"
                                      f"unlocked plots only**, in the new sequence."),
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Input Validation Error")
            await ctx.send(embed=embed)
            return

        errors: List[str] = []
        source_slots_for_new_order_0_indexed: List[int] = []
        seen_original_slots_0_indexed_in_input: set[int] = set()

        for original_slot_1_indexed in new_order_original_slots_1_indexed:
            original_slot_0_indexed = original_slot_1_indexed - 1

            if not (0 <= original_slot_0_indexed < num_garden_slots):
                errors.append(
                    f"Specified original plot `{original_slot_1_indexed}` is out of range (1-{num_garden_slots}).")
            elif original_slot_0_indexed not in unlocked_slot_indices_0based:
                errors.append(
                    f"Specified original plot `{original_slot_1_indexed}` is locked. Only contents of unlocked plots "
                    f"can be reordered.")
            elif original_slot_0_indexed in seen_original_slots_0_indexed_in_input:
                errors.append(
                    f"Original plot `{original_slot_1_indexed}` specified multiple times. Each unlocked plot's "
                    f"content must be sourced once.")
            else:
                seen_original_slots_0_indexed_in_input.add(original_slot_0_indexed)
                source_slots_for_new_order_0_indexed.append(original_slot_0_indexed)

        for unlocked_idx_0based in unlocked_slot_indices_0based:
            if unlocked_idx_0based not in seen_original_slots_0_indexed_in_input:
                errors.append(
                    f"The content of your unlocked plot `{unlocked_idx_0based + 1}` was not included in your reorder "
                    f"sequence.")

        if errors:
            error_list_str = "\n".join([f"• {e}" for e in errors])
            embed = discord.Embed(title="❌ Reconfiguration Logic Error Detected",
                                  description=(f"User {ctx.author.mention}, garden reconfiguration failed:\n\n"
                                               f"{error_list_str}"),
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Spatial Arrangement Subroutine Error")
            await ctx.send(embed=embed)
            return

        temp_new_garden_unlocked_contents = [garden[src_idx] for src_idx in source_slots_for_new_order_0_indexed]
        new_full_garden_state = list(garden)

        for i, dest_idx_0based in enumerate(unlocked_slot_indices_0based):
            new_full_garden_state[dest_idx_0based] = temp_new_garden_unlocked_contents[i]

        self.garden_helper.set_full_garden(ctx.author.id, new_full_garden_state)

        embed = discord.Embed(title="✅ Garden Matrix Reconfigured Successfully",
                              description=f"User {ctx.author.mention}, your Zen Garden plot arrangement has been "
                                          f"updated. Verify with `{ctx.prefix}profile`.",
                              color=discord.Color.green())
        embed.set_footer(text="Penny - Spatial Arrangement Subroutine")
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard")
    @is_cog_ready()
    async def leaderboard_command(self, ctx: commands.Context, page: int = 1):
        """Display rankings of Zen Garden users by solar energy reserves."""

        sorted_users = self.garden_helper.get_sorted_leaderboard()

        if not sorted_users:
            await ctx.send("There is no user data to display on the leaderboard yet.")
            return

        items_per_page = 10
        total_pages = max(1, (len(sorted_users) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * items_per_page

        page_entries = sorted_users[start_index: start_index + items_per_page]

        if not page_entries:
            await ctx.send(f"There are no entries on page {page}.")
            return

        lb_lines = []
        medals = ["🥇", "🥈", "🥉"]

        for i, user_entry in enumerate(page_entries):
            rank = start_index + i + 1
            user_id = int(user_entry["user_id"])
            user_obj = self.bot.get_user(user_id)
            display_name = user_obj.display_name if user_obj else f"User {user_id}"
            escaped_name = discord.utils.escape_markdown(display_name)

            medal = medals[rank - 1] if rank <= 3 and page == 1 else "▫️"
            lb_lines.append(f"{medal} **#{rank}** {escaped_name}: {user_entry['balance']:,} {self.CURRENCY_EMOJI}")

        embed = discord.Embed(
            title=f"📊 Zen Garden User Rankings (Page {page}/{total_pages})",
            description="\n".join(lb_lines),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Use {ctx.prefix}leaderboard [page_num] to navigate.")
        await ctx.send(embed=embed)

    @commands.command(name="gardenhelp")
    @is_cog_ready()
    async def gardenhelp_command(self, ctx: commands.Context):
        """Display Penny's Zen Garden command manifest."""

        prefix = ctx.prefix
        embed = discord.Embed(title="⚙️ Penny's Zen Garden - Command Manifest",
                              description=f"Greetings, User {ctx.author.mention}! Welcome to the Zen Garden "
                                          f"interface. Below is a list of available commands.",
                              color=discord.Color.teal())

        if bot_avatar_url := getattr(self.bot.user, 'display_avatar', None):
            embed.set_thumbnail(url=bot_avatar_url.url)

        embed.add_field(name="🌱 Core Garden Operations", inline=False, value=(
            f"▫️ `{prefix}daily` - Collect your daily stipend of 1000 {self.CURRENCY_EMOJI}.\n"
            f"▫️ `{prefix}plant <plot...>` - Plant seedlings in specified plots.\n"
            f"▫️ `{prefix}sell <plot...>` - Liquidate mature plants from specified plots.\n"
            f"▫️ `{prefix}shovel <plot...>` - Clear plots of any occupants (no {self.CURRENCY_EMOJI} awarded).\n"
            f"▫️ `{prefix}profile [@user]` - View your Zen Garden profile or another's.\n"
            f"▫️ `{prefix}reorder <order...>` - Rearrange plants within your unlocked plots."
        ))
        embed.add_field(name="🔬 Fusion & Discovery", inline=False, value=(
            f"▫️ `{prefix}fuse <plot/item...>` - Fuse plants and/or materials to create advanced specimens.\n"
            f"▫️ `{prefix}almanac` - View your list of discovered fusions.\n"
            f"▫️ `{prefix}almanac info <name>` - Get detailed info for a discovered fusion.\n"
            f"▫️ `{prefix}almanac available [filters]` - Check for fusions you can make right now.\n"
            f"▫️ `{prefix}almanac discover [filters]` - See potential undiscovered recipes.\n"
        ))
        embed.add_field(name="🛒 Shops", inline=False, value=(
            f"▫️ `{prefix}ruxshop` - Browse Rux's Bazaar for upgrades and rare goods.\n"
            f"▫️ `{prefix}ruxbuy <item_id>` - Purchase an item from Rux's Bazaar.\n"
            f"▫️ `{prefix}pennyshop` - View Penny's exclusive, rotating collection of materials.\n"
            f"▫️ `{prefix}pennybuy <item_id>` - Purchase a material from Penny's Treasures.\n"
            f"▫️ `{prefix}daveshop` - Browse Crazy Dave's selection of plants and goods.\n"
            f"▫️ `{prefix}davebuy <item_id>` - Purchase an item from Crazy Dave."
        ))
        embed.add_field(name="🤝 Asset Exchange", inline=False, value=(
            f"▫️ `{prefix}trade @user <sun> <plot...>` - Propose a trade for another user's plants.\n"
            f"▫️ `{prefix}tradeitem @user <sun> <item...>` - Propose to buy one or more of a user's materials.\n"
            f"▫️ `{prefix}accept <id>` - Accept a pending asset exchange proposal.\n"
            f"▫️ `{prefix}decline <id>` - Decline a proposal or cancel one you initiated."
        ))
        embed.add_field(name="📦 Storage Shed Operations", inline=False, value=(
            f"▫️ `{prefix}storage [@user]` - View your storage shed.\n"
            f"▫️ `{prefix}store <plot...>` - Move mature plants from garden plots to storage.\n"
            f"▫️ `{prefix}unstore <slot...>` - Move plants from storage back to your garden."
        ))
        embed.add_field(name="📊 System & Information", inline=False, value=(
            f"▫️ `{prefix}leaderboard [page]` - View user rankings by solar energy.\n"
            f"▫️ `{prefix}background [set] <name>` - View and set your unlocked garden backgrounds.\n"
            f"▫️ `{prefix}gardenhelp` - Display this command manifest."
        ))

        current_growth_duration = self.game_state_helper.get_global_state("plant_growth_duration_minutes")
        hours, minutes = divmod(current_growth_duration, 60)
        duration_str = f"{hours} hour{'s' if hours != 1 else ''}" if hours > 0 else ""
        if minutes > 0:
            duration_str += f"{' and ' if hours > 0 else ''}{minutes} minute{'s' if minutes != 1 else ''}"

        embed.set_footer(text=f"Seedling maturation cycle is {duration_str if duration_str else '4 hours'}.")
        await ctx.send(embed=embed)

    @commands.command(name="ruxshop")
    @is_cog_ready()
    async def ruxshop_command(self, ctx: commands.Context, page: int = 1):
        """Access Rux's Bazaar for upgrades and rare goods."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        user_inventory = profile.inventory

        if not self.data_loader.rux_shop_data:
            embed = discord.Embed(title="🛒 Rux's Bazaar",
                                  description="The Bazaar is... empty. Rux must be on a supply run. Try again later, "
                                              "buddy.",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Inventory Systems Offline")
            await ctx.send(embed=embed)
            return

        eligible_items_for_display = []
        sorted_shop_items = sorted(self.data_loader.rux_shop_data.items(),
                                   key=lambda item: (item[1].category or "zzz", item[1].cost or 0))

        for item_id, item_details in sorted_shop_items:
            if not isinstance(item_details, ShopItemDefinition):
                continue

            is_limited = item_details.category == "limited"
            is_owned = item_id in user_inventory

            if is_owned and not is_limited:
                continue

            if any(req not in user_inventory for req in item_details.requirements):
                continue

            stock = self.game_state_helper.get_rux_stock(item_id)

            if is_limited and stock <= 0 and not is_owned:
                continue

            eligible_items_for_display.append((item_id, item_details))

        if not eligible_items_for_display:
            shop_content = "Looks like you've bought everything I've got for sale, pal. Or maybe you're not ready " \
                           "for my best stuff yet. Come back later! "
        else:
            items_per_page = 5
            total_pages = max(1, (len(eligible_items_for_display) + items_per_page - 1) // items_per_page)
            page = max(1, min(page, total_pages))
            start_index = (page - 1) * items_per_page
            page_items = eligible_items_for_display[start_index: start_index + items_per_page]

            shop_content_parts = []
            for item_id, details in page_items:
                name = details.name or item_id
                cost = details.cost or 0
                description = details.description or "No description available."

                item_entry = f"**{name}** (`{item_id}`)\nCost: **{cost:,}** {self.CURRENCY_EMOJI}"

                if details.category == "limited":
                    stock = self.game_state_helper.get_rux_stock(item_id)

                    if item_id in user_inventory:
                        item_entry += " (**Acquired** - Max 1)"
                    else:
                        item_entry += f" (Stock: **{stock}**)"
                item_entry += f"\n-# {description}"
                shop_content_parts.append(item_entry)

            shop_content = "\n\n".join(shop_content_parts)

        embed = discord.Embed(
            title="🛒 Rux's Bazaar",
            description=f"Hey, {ctx.author.mention}.\n\n"
                        f"**Your Current Solar Energy Balance:** {profile.balance:,} "
                        f"{self.CURRENCY_EMOJI}\n\n"
                        f"**Available Items for Procurement:**\n{shop_content}",
            color=discord.Color.teal()
        )
        footer_text = f"To procure an item: {ctx.prefix}ruxbuy <item_id>"
        if len(eligible_items_for_display) > 5:
            footer_text += f"  •  Use {ctx.prefix}ruxshop [page_num] to navigate."
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="ruxbuy")
    @is_cog_ready()
    @is_not_locked()
    async def ruxbuy_command(self, ctx: commands.Context, item_id_to_buy: str):
        """Procure an item from Rux's Bazaar."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        item_id_lower = item_id_to_buy.lower()
        actual_item_key = next((k for k in self.data_loader.rux_shop_data if k.lower() == item_id_lower), None)
        item_details = self.data_loader.rux_shop_data.get(actual_item_key)

        if not actual_item_key or not item_details:
            embed = discord.Embed(title="❌ Item Not in Bazaar",
                                  description=f"Rux says: '{item_id_to_buy}'? Never heard of it. Check your spelling "
                                              f"or use `{ctx.prefix}ruxshop` to see what I've got.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        item_name = item_details.name
        if item_details.category != "limited" and actual_item_key in profile.inventory:
            embed = discord.Embed(title="❌ Already Acquired",
                                  description=f"Rux says: You've already got the **{item_name}**. I don't do returns "
                                              f"or duplicates!",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        cost = item_details.cost
        if profile.balance < cost:
            embed = discord.Embed(title="❌ Insufficient Solar Energy",
                                  description=f"Rux says: To get the **{item_name}**, you need **{cost:,}** "
                                              f"{self.CURRENCY_EMOJI}. You only have **{profile.balance:,}** "
                                              f"{self.CURRENCY_EMOJI}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        missing_reqs = [req for req in item_details.requirements if req not in profile.inventory]
        if missing_reqs:
            missing_reqs_names = [f"`{req}`" for req in missing_reqs]

            embed = discord.Embed(title="❌ Prerequisites Not Met",
                                  description=f"Rux says: You can't buy the **{item_name}** yet. You need to get these "
                                              f"first: {', '.join(missing_reqs_names)}.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if item_details.category == "limited":
            if self.game_state_helper.get_rux_stock(actual_item_key) <= 0:
                embed = discord.Embed(title="❌ Item Out of Stock",
                                      description=f"Rux says: The **{item_name}** is all sold out! Should've been "
                                                  f"quicker, pal.",
                                      color=discord.Color.red())
                await ctx.send(embed=embed)
                return

        self.garden_helper.remove_balance(ctx.author.id, cost)
        self.garden_helper.add_item_to_inventory(ctx.author.id, actual_item_key)

        success_desc = f"Rux says: A deal's a deal! The **{item_name}** is all yours, pal.\n\n"
        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        success_desc += f"Sun debited: **{cost:,}** {self.CURRENCY_EMOJI}.\n"
        success_desc += f"New balance: **{profile.balance:,}** {self.CURRENCY_EMOJI}."

        if item_details.category == "limited":
            new_stock = max(self.game_state_helper.get_rux_stock(actual_item_key) - 1, 0)
            self.game_state_helper.set_rux_stock(actual_item_key, new_stock)
            success_desc += f"\nThis was a limited item. Stock remaining: **{new_stock}**."

        embed = discord.Embed(title="🛒 Deal's a Deal!", description=success_desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Procurement Division")
        await ctx.send(embed=embed)

    @commands.command(name="pennyshop")
    @is_cog_ready()
    async def pennyshop_command(self, ctx: commands.Context):
        """Displays the current stock of Penny's exclusive treasures."""

        current_stock = self.game_state_helper.get_global_state("treasure_shop_stock")
        next_refresh = self.shop_helper.get_next_penny_refresh_time(datetime.now(TimeHelper.EST))

        embed = discord.Embed(
            title="💎 Penny's Treasures 💎",
            description=f"A curated collection of rare and invaluable artifacts. Stock is limited and rotates "
                        f"periodically.\nNext refresh: <t:{int(next_refresh.timestamp())}:R>",
            color=discord.Color.purple()
        )

        if not current_stock:
            embed.description += "\n\nPenny is currently restocking her treasures. Please check back later!"
        else:
            display_items = []
            for item in current_stock:
                if item.get("stock", 0) > 0:
                    display_items.append(
                        f"**{item.get('name', 'N/A')}** (`{item.get('id', 'N/A')}`)\n"
                        f"Price: **{item.get('price', 0):,}** {self.CURRENCY_EMOJI} • Stock: **1**"
                    )

            if not display_items:
                embed.add_field(name="Current Wares", value="All treasures for this rotation have been procured!",
                                inline=False)
            else:
                midpoint = (len(display_items) + 1) // 2
                embed.add_field(name="Current Wares", value="\n\n".join(display_items[:midpoint]), inline=True)
                embed.add_field(name="\u200b", value="\n\n".join(display_items[midpoint:]), inline=True)

        embed.set_footer(text=f"Use {ctx.prefix}pennybuy <item_id> to purchase")
        await ctx.send(embed=embed)

    @commands.command(name="pennybuy")
    @is_cog_ready()
    @is_not_locked()
    async def pennybuy_command(self, ctx: commands.Context, *, item_id: str):
        """Purchase an item from Penny's Treasures."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        shop_stock = self.game_state_helper.get_global_state("treasure_shop_stock")

        item_to_buy, item_index = None, -1

        for i, item in enumerate(shop_stock):
            if item.get("id", "").lower() == item_id.lower() and item.get("stock", 0) > 0:
                item_to_buy, item_index = item, i
                break

        if not item_to_buy:
            embed = discord.Embed(title="❌ Item Not Available",
                                  description=f"The item `{item_id}` is not currently available in Penny's Treasures.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        price = item_to_buy.get("price", 9999999)
        if profile.balance < price:
            embed = discord.Embed(title="❌ Insufficient Solar Energy",
                                  description=f"You require **{price:,}** {self.CURRENCY_EMOJI} to procure this "
                                              f"treasure, but your available balance is only "
                                              f"**{profile.balance:,}**.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        self.garden_helper.remove_balance(ctx.author.id, price)
        self.garden_helper.add_item_to_inventory(ctx.author.id, item_to_buy["id"])

        current_penny_stock = self.game_state_helper.get_global_state("treasure_shop_stock", [])

        if item_index < len(current_penny_stock):
            current_penny_stock[item_index]["stock"] = 0

        self.game_state_helper.set_global_state("treasure_shop_stock", current_penny_stock)

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        embed = discord.Embed(
            title="✅ Treasure Procured!",
            description=f"You have successfully acquired the **{item_to_buy.get('name')}** for **{price:,}** "
                        f"{self.CURRENCY_EMOJI}.\nYour new balance is **{profile.balance:,}** "
                        f"{self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="daveshop")
    @is_cog_ready()
    async def daveshop_command(self, ctx: commands.Context):
        """Displays Crazy Dave's Twiddydinkies."""

        stock = self.game_state_helper.get_global_state("dave_shop_stock")
        last_refresh_ts = self.game_state_helper.get_global_state("last_dave_shop_refresh")
        next_refresh = (datetime.fromtimestamp(last_refresh_ts, tz=TimeHelper.EST) + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0)

        embed = discord.Embed(
            title="🌱 Crazy Dave's Twiddydinkies",
            description=f"WAABBI WABBO WOO! I'M CRAAAAZY DAVE! But you can call me Crazy Dave. Here's some stuff I "
                        f"found in my car!\nNext restock: <t:{int(next_refresh.timestamp())}:R>",
            color=discord.Color.from_rgb(139, 69, 19)
        )

        if not stock:
            embed.description += "\n\nI'm all out of twiddydinkies! Come back later, neighbor!"
        else:
            display_items = []
            for item in stock:
                if item.get("stock", 0) > 0:
                    display_items.append(
                        f"**{item.get('name')}** (`{item.get('id')}`)\n"
                        f"Price: **{item.get('price', 0):,}** {self.CURRENCY_EMOJI} • Stock: **{item.get('stock')}**"
                    )

            if display_items:
                midpoint = (len(display_items) + 1) // 2
                embed.add_field(name="Wares", value="\n\n".join(display_items[:midpoint]), inline=True)
                embed.add_field(name="\u200b", value="\n\n".join(display_items[midpoint:]), inline=True)
            else:
                embed.add_field(name="Wares", value="Looks like you bought everything! Because I'm CRAAAAZY!",
                                inline=False)

        embed.set_footer(text=f"Use {ctx.prefix}davebuy <item_id> to purchase")
        await ctx.send(embed=embed)

    @commands.command(name="davebuy")
    @is_cog_ready()
    @is_not_locked()
    async def davebuy_command(self, ctx: commands.Context, *, item_id: str):
        """Purchase an item from Crazy Dave's Twiddydinkies."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        shop_stock = self.game_state_helper.get_global_state("dave_shop_stock")

        item_to_buy = None
        item_index = -1
        for i, item in enumerate(shop_stock):
            if item.get("id", "").lower() == item_id.lower():
                item_to_buy = item
                item_index = i
                break

        if not item_to_buy:
            await ctx.send(embed=discord.Embed(title="❌ Item Not Found",
                                               description=f"Dave says: I don't have any `{item_id}`! Are you sure "
                                                           f"that's not a taco?",
                                               color=discord.Color.red()))
            return

        if item_to_buy.get("stock", 0) <= 0:
            await ctx.send(embed=discord.Embed(title="❌ Out of Stock",
                                               description=f"Dave says: All the **{item_to_buy.get('name')}** are "
                                                           f"gone! You gotta be quicker than that, neighbor!",
                                               color=discord.Color.red()))
            return

        price = item_to_buy.get("price", 9999999)

        if profile.balance < price:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Funds",
                                               description=f"You need **{price:,}** {self.CURRENCY_EMOJI} for this "
                                                           f"twiddydinky! You only have {profile.balance:,}.",
                                               color=discord.Color.red()))
            return

        item_type = item_to_buy.get("type")

        if item_type in ["plant", "seedling"]:
            first_empty_slot = next((i for i, s in enumerate(profile.garden) if
                                     self.garden_helper.is_slot_unlocked(profile, i + 1) and s is None), -1)

            if first_empty_slot == -1:
                await ctx.send(embed=discord.Embed(title="❌ Garden Full",
                                                   description="Dave says: Your garden is full, neighbor! You need to make some space first!",
                                                   color=discord.Color.red()))
                return
            
            if item_type == "plant":
                plant_def = self.plant_helper.get_base_plant_by_id(item_to_buy["id"])
                if not plant_def:
                    await ctx.send(embed=discord.Embed(title="❌ Plant Definition Missing",
                                                       description=f"Dave says: I found the item, but my almanac is missing the page for **{item_to_buy['name']}**! This is a bug.",
                                                       color=discord.Color.red()))
                    return 
                
                self.garden_helper.remove_balance(ctx.author.id, price)
                plant_to_add = PlantedPlant(id=plant_def.id, name=plant_def.name, type=plant_def.type)
                self.garden_helper.set_garden_plot(ctx.author.id, first_empty_slot, plant_to_add)

            elif item_type == "seedling":
                seedling_def = self.plant_helper.get_seedling_by_id(item_to_buy["id"])
                if not seedling_def:
                    await ctx.send(embed=discord.Embed(title="❌ Seedling Definition Missing",
                                                       description=f"Dave says: I found the item, but I forgot what kind of seed it is! This is a bug.",
                                                       color=discord.Color.red()))
                    return
                
                self.garden_helper.remove_balance(ctx.author.id, price)
                self.garden_helper.plant_seedling(ctx.author.id, first_empty_slot, item_to_buy["id"], ctx.channel.id)

        elif item_type == "material":
            if item_to_buy["id"] not in self.data_loader.materials_data:
                await ctx.send(embed=discord.Embed(title="❌ Material Definition Missing",
                                                   description=f"Dave says: I found something shiny, but I don't know what it is! This is a bug.",
                                                   color=discord.Color.red()))
                return
            
            self.garden_helper.remove_balance(ctx.author.id, price)
            self.garden_helper.add_item_to_inventory(ctx.author.id, item_to_buy["id"])

        else:
            await ctx.send(embed=discord.Embed(title="❌ Unknown Item Type",
                                               description=f"Dave says: The **{item_to_buy['name']}** is a what now? I'm not sure how to give this to you! (Invalid item type in config).",
                                               color=discord.Color.red()))
            return

        current_dave_stock = self.game_state_helper.get_global_state("dave_shop_stock", [])

        if item_index < len(current_dave_stock):
            current_dave_stock[item_index]["stock"] -= 1

        self.game_state_helper.set_global_state("dave_shop_stock", current_dave_stock)

        await ctx.send(embed=discord.Embed(
            title="✅ Purchase Successful!",
            description=f"You have successfully purchased **{item_to_buy.get('name')}** for **{price:,}** "
                        f"{self.CURRENCY_EMOJI}.",
            color=discord.Color.green()
        ))

    @commands.command(name="storage")
    @is_cog_ready()
    async def storage_command(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """Displays the contents of your storage shed or that of another user."""

        target_user = user or ctx.author
        profile = self.garden_helper.get_user_profile_view(target_user.id)

        if not self.garden_helper.user_has_storage_shed(profile):
            user_display = "You do" if target_user == ctx.author else f"User {target_user.mention} does"
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"{user_display} not currently possess a Storage Shed. It can be acquired from the "
                            f"`{ctx.prefix}ruxshop`.",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Asset Management Systems")
            await ctx.send(embed=embed)
            return

        display_lines, occupied_slots, capacity = self.garden_helper.get_formatted_storage_contents(profile)

        embed = discord.Embed(
            title=f"📦 {target_user.display_name}'s Storage Shed Inventory",
            description=f"Displaying current botanical asset storage for {target_user.mention}.\nCapacity: "
                        f"**{occupied_slots}/{capacity}** slots utilized.",
            color=discord.Color.dark_teal()
        )

        if occupied_slots == 0:
            embed.description += "\n\nThis storage shed is currently empty."
        else:
            col1_limit = 4
            col1 = "\n".join(display_lines[:col1_limit])
            col2 = "\n".join(display_lines[col1_limit:])

            embed.add_field(name="Shed Slots 1-4", value=col1, inline=True)
            if capacity > 4:
                embed.add_field(name="Shed Slots 5-8", value=col2 if col2 else "All empty.", inline=True)

        footer_text = "Penny - Asset Management Systems"
        if target_user == ctx.author:
            footer_text += f" • Use {ctx.prefix}store & {ctx.prefix}unstore"
        embed.set_footer(text=footer_text)
        await ctx.send(embed=embed)

    @commands.command(name="store")
    @is_cog_ready()
    @is_not_locked()
    async def store_command(self, ctx: commands.Context, *plot_numbers: int):
        """Moves plants from specified garden plots into your storage shed."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        if not self.garden_helper.user_has_storage_shed(profile):
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"User {ctx.author.mention}, you do not currently possess a Storage Shed. "
                            f"It can be acquired from `{ctx.prefix}ruxshop`.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        if not plot_numbers:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Storage Transfer",
                description=f"User {ctx.author.mention}, please specify the garden plot numbers containing the plants "
                            f"you wish to move to storage.\nSyntax: `{ctx.prefix}store <plot_num_1> [plot_num_2] ...`",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        moved_plants_summary = []
        error_messages = []

        plots_to_actually_store = []
        for plot_num in set(plot_numbers):
            plot_idx_0based = plot_num - 1

            if not (0 <= plot_idx_0based < 12):
                error_messages.append(f"Plot {plot_num}: Invalid designation (must be 1-12).")
                continue

            plant = profile.garden[plot_idx_0based]
            if not isinstance(plant, PlantedPlant):
                error_messages.append(f"Plot {plot_num}: Is empty or contains a non-storable seedling.")
                continue

            plots_to_actually_store.append(plot_idx_0based)

        for plot_idx in plots_to_actually_store:
            success, message = self.garden_helper.store_plant(ctx.author.id, plot_idx)

            if success:
                moved_plants_summary.append(message)
            else:
                error_messages.append(f"Plot {plot_idx + 1}: Failed to store. Reason: {message}")

        if not moved_plants_summary:
            desc = "No plants were successfully moved to storage."
            if error_messages:
                desc += "\n\n**Issues Encountered:**\n" + "\n".join([f"• {msg}" for msg in error_messages])
            await ctx.send(
                embed=discord.Embed(title="❌ Storage Transfer Failed", description=desc, color=discord.Color.red()))
            return

        desc = f"User {ctx.author.mention}, asset transfer to storage successful.\n\n**Transfer Details:**\n"
        desc += "\n".join([f"• {summary}" for summary in moved_plants_summary])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plants could not be stored due to the following issues:\n" + \
                    "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="✅ Plants Moved to Storage", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Asset Management Systems")
        await ctx.send(embed=embed)

    @commands.command(name="unstore")
    @is_cog_ready()
    @is_not_locked()
    async def unstore_command(self, ctx: commands.Context, *storage_space_numbers: int):
        """Moves plants from specified storage shed slots back into your garden."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        if not self.garden_helper.user_has_storage_shed(profile):
            embed = discord.Embed(
                title="🔒 Storage Shed Inaccessible",
                description=f"User {ctx.author.mention}, you do not currently possess a Storage Shed.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        if not storage_space_numbers:
            embed = discord.Embed(
                title="⚠️ Insufficient Parameters for Storage Retrieval",
                description=f"User {ctx.author.mention}, please specify the storage space numbers of the plants you "
                            f"wish to retrieve.\nSyntax: `{ctx.prefix}unstore <space_num_1> ...`",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        retrieved_plants_summary = []
        error_messages = []

        storage_capacity = self.garden_helper.get_storage_capacity(profile)

        slots_to_unstore = []

        for slot_num in set(storage_space_numbers):
            slot_idx_0based = slot_num - 1

            if not (0 <= slot_idx_0based < storage_capacity):
                error_messages.append(
                    f"Storage Slot {slot_num}: Invalid or inaccessible (Capacity: {storage_capacity}).")
                continue

            if profile.storage_shed[slot_idx_0based] is None:
                error_messages.append(f"Storage Slot {slot_num}: Is empty.")
                continue

            slots_to_unstore.append(slot_idx_0based)

        for slot_idx in slots_to_unstore:
            success, message = self.garden_helper.unstore_plant(ctx.author.id, slot_idx)

            if success:
                retrieved_plants_summary.append(message)
            else:
                error_messages.append(f"Storage Slot {slot_idx + 1}: Failed to retrieve. Reason: {message}")

        if not retrieved_plants_summary:
            desc = "No plants were successfully retrieved from storage."
            if error_messages:
                desc += "\n\n**Issues Encountered:**\n" + "\n".join([f"• {msg}" for msg in error_messages])
            await ctx.send(
                embed=discord.Embed(title="❌ Storage Retrieval Failed", description=desc, color=discord.Color.red()))
            return

        desc = f"User {ctx.author.mention}, asset retrieval from storage successful.\n\n**Retrieval Details:**\n"
        desc += "\n".join([f"• {summary}" for summary in retrieved_plants_summary])

        if error_messages:
            desc += "\n\n**System Advisory:** Some plants could not be retrieved due to the following issues:\n" + \
                    "\n".join([f"• {msg}" for msg in error_messages])

        embed = discord.Embed(title="✅ Plants Retrieved from Storage", description=desc, color=discord.Color.green())
        embed.set_footer(text="Penny - Asset Management Systems")
        await ctx.send(embed=embed)

    @commands.command(name="trade")
    @is_cog_ready()
    @is_not_locked()
    async def trade_command(self, ctx: commands.Context, recipient: discord.User, money_to_give: int,
                            *want_slots_input: str):
        """Initiate an asset exchange proposal with another user (Sun for Plants)."""

        sender = ctx.author

        if recipient.bot:
            embed = discord.Embed(title="❌ Invalid Trade Target Entity",
                                  description="Automated system entities (bots) are not authorized for asset exchange.",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Entity Check")
            await ctx.send(embed=embed)
            return

        if sender.id == recipient.id:
            embed = discord.Embed(title="❌ Invalid Trade Operation: Self-Target",
                                  description="Self-trading protocols are not permitted.", color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Operation Check")
            await ctx.send(embed=embed)
            return

        if self.lock_helper.get_user_lock(recipient.id):
            embed = discord.Embed(title="❌ Target User Currently Engaged",
                                  description=f"User {recipient.mention} is currently involved in another system "
                                              f"operation and cannot trade at this time.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        if money_to_give < 0 or not want_slots_input:
            embed = discord.Embed(title="❌ Missing or Invalid Parameters",
                                  description=f"User {ctx.author.mention}, please specify a non-negative sun amount "
                                              f"and the plot number(s) you wish to acquire.\nSyntax: "
                                              f"`{ctx.prefix}trade @User <sun> <plot1> ...`",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Command Syntax")
            await ctx.send(embed=embed)
            return

        try:
            want_slots_0_indexed = sorted(list(set([int(s) - 1 for s in want_slots_input])))
        except ValueError:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Parameter: Plot Designators",
                                               description="Plot designators must be numerical values.",
                                               color=discord.Color.red()))
            return

        sender_profile = self.garden_helper.get_user_profile_view(sender.id)
        if sender_profile.balance < money_to_give:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Solar Reserves",
                                               description=f"Your proposal to offer {money_to_give:,} "
                                                           f"{self.CURRENCY_EMOJI} exceeds your current balance of {sender_profile.balance:,}.",
                                               color=discord.Color.red()))
            return

        recipient_profile = self.garden_helper.get_user_profile_view(recipient.id)
        plants_to_receive_info = []
        for r_slot_idx in want_slots_0_indexed:
            if not (0 <= r_slot_idx < 12):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Target Asset",
                                                   description=f"Plot {r_slot_idx + 1} is an invalid plot number.",
                                                   color=discord.Color.red()))
                return

            if not self.garden_helper.is_slot_unlocked(recipient_profile, r_slot_idx + 1):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Target Asset",
                                                   description=f"Plot {r_slot_idx + 1} is locked for "
                                                               f"{recipient.mention}.",
                                                   color=discord.Color.red()))
                return

            plant = recipient_profile.garden[r_slot_idx]

            if not isinstance(plant, PlantedPlant):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Target Asset",
                                                   description=f"The item in {recipient.mention}'s plot "
                                                               f"{r_slot_idx + 1} is not a mature, tradable plant.",
                                                   color=discord.Color.red()))
                return

            plants_to_receive_info.append({"r_slot_index": r_slot_idx, "plant_data": dataclasses.asdict(plant)})

        free_sender_plots = sum(1 for i, p in enumerate(sender_profile.garden) if
                                p is None and self.garden_helper.is_slot_unlocked(sender_profile, i + 1))

        if free_sender_plots < len(plants_to_receive_info):
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Garden Capacity",
                                               description=f"You need {len(plants_to_receive_info)} empty garden "
                                                           f"plot(s) to receive these plants, but you "
                                                           f"only have {free_sender_plots}.",
                                               color=discord.Color.red()))
            return

        trade_id = f"TR{int(time.time()) % 10000:04d}"
        trade_details = {
            "id": trade_id, "sender_id": sender.id, "recipient_id": recipient.id, "trade_type": "plant",
            "money_sender_gives": money_to_give, "plants_sender_receives_info": plants_to_receive_info,
            "status": "pending", "timestamp": TimeHelper.get_current_timestamp()
        }

        self.trade_helper.propose_trade(sender, recipient, trade_details)

        plant_names_str = "\n".join(
            [f"    • **{p['plant_data']['name']}** from plot {p['r_slot_index'] + 1}" for p in plants_to_receive_info])

        offer_desc = (f"User {sender.mention} has proposed an asset exchange with you.\n\n"
                      f"**Proposal:**\n"
                      f"  ➢ **{sender.display_name}** offers: **{money_to_give:,}** {self.CURRENCY_EMOJI}\n"
                      f"  ➢ In exchange for your asset(s):\n{plant_names_str}\n\n"
                      f"To **accept**, transmit: `{ctx.prefix}accept {trade_id}`\n"
                      f"To **decline**, transmit: `{ctx.prefix}decline {trade_id}`\n\n"
                      f"This proposal will automatically expire in **60 seconds**.")

        dm_embed = discord.Embed(title="🛰️ Incoming Asset Exchange Proposal", description=offer_desc,
                                 color=discord.Color.teal())
        dm_embed.set_footer(text=f"Trade Proposal ID: {trade_id}")

        try:
            await recipient.send(embed=dm_embed)
            await ctx.send(embed=discord.Embed(title="✅ Proposal Transmitted",
                                               description=f"Your proposal (`{trade_id}`) has been sent to "
                                                           f"{recipient.mention}. They have 60 seconds to respond.",
                                               color=discord.Color.green()))
        except discord.Forbidden:
            self.trade_helper.resolve_trade(trade_id)
            await ctx.send(embed=discord.Embed(title="❌ Transmission Failure",
                                               description=f"Could not DM {recipient.mention}. Their DMs may be "
                                                           f"disabled. Trade cancelled.",
                                               color=discord.Color.red()))
            return

        await asyncio.sleep(60.0)

        if self.trade_helper.resolve_trade(trade_id):
            timeout_embed = discord.Embed(title="⏰ Asset Exchange Proposal Expired",
                                          description=f"The proposal (`{trade_id}`) between {sender.mention} and "
                                                      f"{recipient.mention} has expired due to no response.",
                                          color=discord.Color.light_grey())
            for user in [sender, recipient]:
                try:
                    await user.send(embed=timeout_embed)
                except (discord.Forbidden, AttributeError):
                    pass

    @commands.command(name="tradeitem")
    @is_cog_ready()
    @is_not_locked()
    async def tradeitem_command(self, ctx: commands.Context, recipient: discord.User, sun_offered: int,
                                *item_ids: str):
        """Propose to buy multiple Material items from another user's inventory for sun."""

        sender = ctx.author

        if recipient.bot:
            embed = discord.Embed(title="❌ Invalid Trade Target Entity",
                                  description="Automated system entities (bots) are not authorized for asset exchange.",
                                  color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Entity Check")
            await ctx.send(embed=embed)
            return

        if sender.id == recipient.id:
            embed = discord.Embed(title="❌ Invalid Trade Operation: Self-Target",
                                  description="Self-trading protocols are not permitted.", color=discord.Color.red())
            embed.set_footer(text="Penny - Secure Exchange System: Operation Check")
            await ctx.send(embed=embed)
            return

        if not item_ids:
            await ctx.send(embed=discord.Embed(title="❌ Missing Parameters",
                                               description=f"Please specify the ID(s) of the Material(s) you wish to "
                                                           f"acquire.\nSyntax: `{ctx.prefix}tradeitem @user <sun> "
                                                           f"<item_id_1> ...`",
                                               color=discord.Color.red()))
            return

        if self.lock_helper.get_user_lock(recipient.id):
            embed = discord.Embed(title="❌ Target User Currently Engaged",
                                  description=f"User {recipient.mention} is currently involved in another system "
                                              f"operation and cannot trade at this time.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        if sun_offered < 0:
            await ctx.send(embed=discord.Embed(title=f"❌ Invalid Parameter",
                                               description=f"The sun offered must be a non-negative amount.",
                                               color=discord.Color.red()))
            return

        sender_profile = self.garden_helper.get_user_profile_view(sender.id)
        if sender_profile.balance < sun_offered:
            await ctx.send(embed=discord.Embed(title="❌ Insufficient Solar Reserves",
                                               description=f"Your proposal to offer {sun_offered:,} "
                                                           f"{self.CURRENCY_EMOJI} exceeds your current balance.",
                                               color=discord.Color.red()))
            return

        recipient_profile = self.garden_helper.get_user_profile_view(recipient.id)
        recipient_inv_counter = recipient_profile.inventory

        requested_items_counter = Counter()
        errors = []
        mat_id_map = {k.lower(): k for k in self.data_loader.materials_data.keys()}

        for item_input in item_ids:
            item_lower = item_input.lower()

            if item_lower in mat_id_map:
                requested_items_counter[mat_id_map[item_lower]] += 1
            else:
                errors.append(f"Item ID '{item_input}' is not a recognized tradable Material.")

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Item Request",
                                               description="The following issues were found:\n" + "\n".join(
                                                   f"• {e}" for e in errors), color=discord.Color.red()))
            return

        validated_items_info = []
        for item_id, count in requested_items_counter.items():
            item_name = self.data_loader.materials_data.get(item_id, item_id)

            if recipient_inv_counter.get(item_id, 0) < count:
                errors.append(
                    f"Recipient has {recipient_inv_counter.get(item_id, 0)} of **{item_name}**, but you requested "
                    f"{count}.")
                continue
            validated_items_info.append({"id": item_id, "name": item_name, "count": count})

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Proposal Validation Failed",
                                               description="Your trade could not be sent:\n" + "\n".join(
                                                   f"• {e}" for e in errors), color=discord.Color.red()))
            return

        trade_id = f"TI{int(time.time()) % 10000:04d}"
        trade_details = {
            "id": trade_id, "sender_id": sender.id, "recipient_id": recipient.id, "trade_type": "item",
            "sun_sender_offers": sun_offered, "items_info_list": validated_items_info, "status": "pending",
            "timestamp": TimeHelper.get_current_timestamp()
        }

        self.trade_helper.propose_trade(sender, recipient, trade_details)

        items_for_msg = "\n".join([f"    • **{item['name']}** x{item['count']}" for item in validated_items_info])
        offer_desc = (f"User {sender.mention} has proposed a Material exchange with you.\n\n"
                      f"**Proposal:**\n"
                      f"  ➢ **{sender.display_name}** offers: **{sun_offered:,}** {self.CURRENCY_EMOJI}\n"
                      f"  ➢ In exchange for your Material(s):\n{items_for_msg}\n\n"
                      f"To **accept**, transmit: `{ctx.prefix}accept {trade_id}`\n"
                      f"To **decline**, transmit: `{ctx.prefix}decline {trade_id}`\n\n"
                      f"This proposal will automatically expire in **60 seconds**.")

        dm_embed = discord.Embed(title="💎 Incoming Material Exchange Proposal", description=offer_desc,
                                 color=discord.Color.purple())
        dm_embed.set_footer(text=f"Trade Proposal ID: {trade_id}")

        try:
            await recipient.send(embed=dm_embed)
            await ctx.send(embed=discord.Embed(title="✅ Proposal Transmitted",
                                               description=f"Your Material exchange proposal (`{trade_id}`) has been "
                                                           f"sent to {recipient.mention}.",
                                               color=discord.Color.green()))
        except discord.Forbidden:
            self.trade_helper.resolve_trade(trade_id)
            await ctx.send(embed=discord.Embed(title="❌ Transmission Failure",
                                               description=f"Unable to DM {recipient.mention}. Trade cancelled.",
                                               color=discord.Color.red()))
            return

        await asyncio.sleep(60)
        if expired_trade := self.trade_helper.resolve_trade(trade_id):
            sender = self.bot.get_user(expired_trade["sender_id"])
            recipient = self.bot.get_user(expired_trade["recipient_id"])
            timeout_embed = discord.Embed(title="⏰ Material Exchange Proposal Expired",
                                          description=f"The proposal (`{trade_id}`) between {sender.mention} and "
                                                      f"{recipient.mention} has expired.",
                                          color=discord.Color.light_grey())

            for user in [sender, recipient]:
                if user:
                    try:
                        await user.send(embed=timeout_embed)
                    except (discord.Forbidden, AttributeError):
                        pass

    @commands.command(name="accept")
    @is_cog_ready()
    async def accept_command(self, ctx: commands.Context, trade_id: str):
        """Confirm and execute a pending asset exchange proposal you received."""

        trade_peek = self.trade_helper.pending_trades.get(trade_id)

        if not trade_peek:
            embed = discord.Embed(title="❌ Invalid Proposal Identifier",
                                  description=f"The ID (`{trade_id}`) does not correspond to an active proposal.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if trade_peek.get("recipient_id") != ctx.author.id:
            embed = discord.Embed(title="❌ Unauthorized Action", description="This proposal is not addressed to you.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        trade = self.trade_helper.resolve_trade(trade_id)
        if not trade:
            embed = discord.Embed(title="❌ Proposal No Longer Active",
                                  description="This proposal has just expired or was cancelled.",
                                  color=discord.Color.orange())
            await ctx.send(embed=embed)
            return

        sender_id = trade["sender_id"]
        recipient_id = trade["recipient_id"]
        sender_profile = self.garden_helper.get_user_profile_view(sender_id)
        recipient_profile = self.garden_helper.get_user_profile_view(recipient_id)

        trade_type = trade.get("trade_type", "plant")
        success = False
        message = "Critical Error: Unknown trade type."
        changes = None

        if trade_type == "plant":
            sender_unlocked_slots = {i + 1 for i in range(12) if
                                     self.garden_helper.is_slot_unlocked(sender_profile, i + 1)}
            success, message, changes = self.trade_helper.execute_plant_trade(
                trade_data=trade,
                sender_profile=sender_profile,
                recipient_profile=recipient_profile,
                sender_unlocked_slots=sender_unlocked_slots
            )
        elif trade_type == "item":
            success, message, changes = self.trade_helper.execute_item_trade(
                trade_data=trade,
                sender_profile=sender_profile,
                recipient_profile=recipient_profile
            )

        sender = self.bot.get_user(sender_id)

        if success and changes:
            for update in changes.get("balance_updates", []):
                if update["amount"] > 0:
                    self.garden_helper.add_balance(update["user_id"], update["amount"])
                else:
                    self.garden_helper.remove_balance(update["user_id"], -update["amount"])

            for move in changes.get("plant_moves", []):
                self.garden_helper.set_garden_plot(move["from_user_id"], move["from_plot_idx"], None)
                self.garden_helper.set_garden_plot(move["to_user_id"], move["to_plot_idx"], move["plant_data"])

            for transfer in changes.get("item_transfers", []):
                self.garden_helper.remove_item_from_inventory(transfer["from_user_id"], transfer["item_id"],
                                                                    transfer["quantity"])
                self.garden_helper.add_item_to_inventory(transfer["to_user_id"], transfer["item_id"],
                                                               transfer["quantity"])

            embed_acceptor = discord.Embed(title="✅ Asset Exchange Confirmed & Executed",
                                           description=f"You accepted proposal `{trade_id}` from "
                                                       f"{sender.mention if sender else 'the other user'}."
                                                       f"\n**Details:** {message}",
                                           color=discord.Color.green())
            await ctx.send(embed=embed_acceptor)
            if sender:
                try:
                    embed_sender = discord.Embed(title="✅ Proposal Accepted",
                                                 description=f"Your proposal (`{trade_id}`) with {ctx.author.mention} "
                                                             f"was accepted and executed.",
                                                 color=discord.Color.green())
                    await sender.send(embed=embed_sender)
                except discord.Forbidden:
                    pass
        else:
            embed_acceptor = discord.Embed(title="❌ Asset Exchange Failed During Final Execution",
                                           description=f"While finalizing proposal `{trade_id}`, an error occurred: "
                                                       f"**{message}**\n\nNo assets were exchanged.",
                                           color=discord.Color.red())
            await ctx.send(embed=embed_acceptor)
            if sender:
                try:
                    embed_sender = discord.Embed(title="❌ Proposal Execution Failed",
                                                 description=f"Your proposal (`{trade_id}`) with {ctx.author.mention} "
                                                             f"failed final validation: **{message}**",
                                                 color=discord.Color.red())
                    await sender.send(embed=embed_sender)
                except discord.Forbidden:
                    pass

    @commands.command(name="decline")
    @is_cog_ready()
    async def decline_command(self, ctx: commands.Context, trade_id: str):
        """Reject a pending asset exchange proposal or cancel one you initiated."""

        trade_peek = self.trade_helper.pending_trades.get(trade_id)

        if not trade_peek:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Proposal Identifier",
                                               description=f"The ID (`{trade_id}`) is invalid or does not involve you.",
                                               color=discord.Color.red()))
            return

        is_sender = trade_peek.get("sender_id") == ctx.author.id
        is_recipient = trade_peek.get("recipient_id") == ctx.author.id

        if not (is_sender or is_recipient):
            await ctx.send(
                embed=discord.Embed(title="❌ Unauthorized Action", description="This proposal does not involve you.",
                                    color=discord.Color.red()))
            return

        trade = self.trade_helper.resolve_trade(trade_id)
        if not trade:
            await ctx.send(
                embed=discord.Embed(title="❌ Proposal Not Active", description="This proposal is no longer pending.",
                                    color=discord.Color.orange()))
            return

        action = "cancelled" if is_sender else "declined"
        other_party_id = trade["recipient_id"] if is_sender else trade["sender_id"]
        other_party = self.bot.get_user(other_party_id)

        action_title = f"❌ Asset Exchange Proposal {action.capitalize()}"
        action_desc = f"User {ctx.author.mention} has successfully **{action}** asset exchange proposal (`{trade_id}`)."
        await ctx.send(embed=discord.Embed(title=action_title, description=action_desc, color=discord.Color.red()))

        if other_party:
            try:
                other_party_desc = f"Asset exchange proposal (`{trade_id}`) with {ctx.author.mention} was **{action}**."
                await other_party.send(
                    embed=discord.Embed(title=action_title, description=other_party_desc, color=discord.Color.red()))
            except discord.Forbidden:
                pass

    @commands.command(name="fuse")
    @is_cog_ready()
    @is_not_locked()
    async def fuse_command(self, ctx: commands.Context, *args: str):
        """Fuse plants from plots and/or Material items from your inventory."""

        if len(args) < 2:
            embed = discord.Embed(title="⚠️ Insufficient Components for Fusion",
                                  description=f"User {ctx.author.mention}, fusion protocol requires a minimum of two "
                                              f"components.\nSyntax: `{ctx.prefix}fuse <plot_num_1> <item_id_1> ...`",
                                  color=discord.Color.orange())
            embed.set_footer(text="Penny - Fusion Systems Interface")
            await ctx.send(embed=embed)
            return

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)

        first_plot_mentioned = None
        validated_plots_info = []
        requested_items_counter = Counter()
        errors = []

        plot_args = [cmd_arg for cmd_arg in args if cmd_arg.isdigit()]
        if len(plot_args) != len(set(plot_args)):
            errors.append("Duplicate plots were mentioned. Each plot can only be used once per fusion attempt.")

        processed_plots = set()

        mat_id_map = {name.lower(): mat_id for mat_id, name in self.data_loader.materials_data.items()}
        mat_id_map.update({mat_id.lower(): mat_id for mat_id in self.data_loader.materials_data.keys()})

        for cmd_arg in args:
            if cmd_arg.isdigit():
                plot_num = int(cmd_arg)

                if first_plot_mentioned is None:
                    first_plot_mentioned = plot_num

                if plot_num in processed_plots:
                    continue

                processed_plots.add(plot_num)

                if not (1 <= plot_num <= 12):
                    errors.append(f"Plot {plot_num}: Invalid number.")
                elif not self.garden_helper.is_slot_unlocked(profile, plot_num):
                    errors.append(f"Plot {plot_num}: Locked.")
                else:
                    plant = profile.garden[plot_num - 1]
                    if isinstance(plant, PlantedPlant):
                        validated_plots_info.append({"data": plant, "slot_1based": plot_num})
                    else:
                        errors.append(f"Plot {plot_num}: Is empty or has a non-fusable seedling.")
            else:
                arg_lower = cmd_arg.lower()
                canonical_id = mat_id_map.get(arg_lower)
                if canonical_id:
                    requested_items_counter[canonical_id] += 1
                else:
                    errors.append(f"'{cmd_arg}' is not a valid plot number or fusable material.")

        for item_id, count in requested_items_counter.items():
            if profile.inventory.get(item_id, 0) < count:
                item_name = self.data_loader.materials_data.get(item_id, item_id)
                errors.append(
                    f"You need {count}x **{item_name}** but only have "
                    f"{profile.inventory.get(item_id, 0)}.")

        if first_plot_mentioned is None:
            errors.append("Fusion requires at least one plant from a plot to determine the result's location.")

        if errors:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Input Error",
                                               description="Fusion protocol aborted due to input failures:\n\n"
                                                           + "\n".join(f"• {e}" for e in errors),
                                               color=discord.Color.red()))
            return

        base_components = []
        deconstruction_errors = []
        for plot_info in validated_plots_info:
            components, errors = self.fusion_helper.deconstruct_plant(dataclasses.asdict(plot_info["data"]))
            base_components.extend(components)
            deconstruction_errors.extend(errors)

        for item_id, count in requested_items_counter.items():
            item_name = self.data_loader.materials_data.get(item_id, item_id)
            base_components.extend([item_name] * count)

        if deconstruction_errors:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Deconstruction Error",
                                               description="Errors occurred during component analysis:\n\n" + "\n".join(
                                                   f"• {e}" for e in deconstruction_errors), color=discord.Color.red()))
            return

        fusion_result_data = self.fusion_helper.find_fusion_match(base_components)

        consumed_list_str = [f"**{p['data'].name}** (Plot {p['slot_1based']})" for p in validated_plots_info]
        consumed_list_str.extend(
            [f"**{self.data_loader.materials_data.get(item_id, item_id)}** x{count}" for item_id, count in
             requested_items_counter.items()])

        if not fusion_result_data:
            desc = f"The combination of components from {', '.join(consumed_list_str)} does not match any known " \
                   f"fusion recipe."
            await ctx.send(embed=discord.Embed(title="🚫 No Matching Fusion Recipe Found", description=desc,
                                               color=discord.Color.orange()))
            return

        result_plant_name = fusion_result_data.name
        fusion_visibility = fusion_result_data.visibility
        is_new = fusion_result_data.id not in profile.discovered_fusions and fusion_visibility != "invisible"
        output_slot = first_plot_mentioned

        lock_message = f"Awaiting confirmation to fuse components into a **{result_plant_name}**."
        self.lock_helper.add_lock(ctx.author.id, "fusion", lock_message)

        confirm_desc = (f"User {ctx.author.mention}, the following components will be consumed:\n"
                        f"  • {', '.join(consumed_list_str)}\n\n"
                        f"This combination will create: **{result_plant_name}{' [NEW]' if is_new else ''}**\n\n"
                        f"The result will be placed in plot **{output_slot}**. Proceed? (yes/no)")

        embed = discord.Embed(title="🧬 Fusion Confirmation Required", description=confirm_desc,
                              color=discord.Color.teal())
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for("message", timeout=60.0,
                                          check=lambda m: m.author == ctx.author and m.channel == ctx.channel
                                          and m.content.lower() in ["yes", "y", "no", "n"])

            if msg.content.lower() in ["no", "n"]:
                await ctx.send(embed=discord.Embed(title="🚫 Fusion Cancelled",
                                                   description="Fusion protocol has been cancelled by user directive.",
                                                   color=discord.Color.light_grey()))
                return
        except asyncio.TimeoutError:
            await ctx.send(embed=discord.Embed(title="⏰ Fusion Timed Out",
                                               description="Confirmation not received. The operation has been "
                                                           "automatically cancelled.",
                                               color=discord.Color.light_grey()))
            return
        finally:
            self.lock_helper.remove_lock_for_user(ctx.author.id)

        for item_id, count in requested_items_counter.items():
            self.garden_helper.remove_item_from_inventory(ctx.author.id, item_id, count)

        for plot_info in validated_plots_info:
            self.garden_helper.set_garden_plot(ctx.author.id, plot_info["slot_1based"] - 1, None)

        new_plant = PlantedPlant(id = fusion_result_data.id, name = result_plant_name, type = fusion_result_data.type)
        self.garden_helper.set_garden_plot(ctx.author.id, output_slot - 1, new_plant)

        bonus_text = ""
        if is_new:
            self.garden_helper.add_fusion_discovery(ctx.author.id, fusion_result_data.id)
            bonus = int(0.5 * self.sales_helper.get_sale_price(new_plant.type))
            if bonus > 0:
                self.garden_helper.add_balance(ctx.author.id, bonus)
                bonus_text = f"\n\n**New Fusion Discovery!** You've been awarded a bonus of **{bonus:,}** " \
                             f"{self.CURRENCY_EMOJI}!"

        unlock_text = ""
        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        if fusion_visibility != "invisible":
            newly_unlocked_bgs = self.background_helper.check_for_unlocks(
                profile.discovered_fusions, profile.unlocked_backgrounds
            )
            if newly_unlocked_bgs:
                unlocked_names = []
                for bg in newly_unlocked_bgs:
                    self.garden_helper.add_unlocked_background(ctx.author.id, bg.id)
                    unlocked_names.append(f"**{bg.name}**")
                unlock_text = f"\n\n🎉 **Background Unlocked!** You have unlocked the {', '.join(unlocked_names)} " \
                              f"garden background! Use `{ctx.prefix}background` to manage it."

        success_desc = f"Fusion successful! A **{result_plant_name}** has been cultivated in plot {output_slot}." \
                       + bonus_text + unlock_text
        success_embed = discord.Embed(title="✅ Fusion Protocol Complete", description=success_desc,
                                      color=discord.Color.green())
        success_embed.set_footer(text="Penny - Fusion Systems Interface")

        image_file_to_send = self.image_helper.get_image_file_for_plant(fusion_result_data.id)
        if image_file_to_send:
            success_embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        await ctx.send(embed=success_embed, file=image_file_to_send)

    @commands.group(name="almanac", invoke_without_command=True)
    @is_cog_ready()
    async def almanac_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Displays your discovered fusions. Use subcommands for more actions."""

        if ctx.invoked_subcommand is not None:
            return

        is_list_intent = (
                not full_args or
                any(":" in cmd_arg for cmd_arg in full_args.split()) or
                (full_args and full_args.strip().split()[-1].isdigit())
        )

        if is_list_intent:
            profile = self.garden_helper.get_user_profile_view(ctx.author.id)
            discovered_ids = set(profile.discovered_fusions)

            discovered_fusions_to_display = [f for f in self.fusion_helper.visible_fusions if f.id in discovered_ids]
            for fid in discovered_ids:
                if hidden_fusion := self.fusion_helper.hidden_fusions_by_id.get(fid):
                    discovered_fusions_to_display.append(hidden_fusion)

            if not discovered_fusions_to_display:
                await ctx.send(embed=discord.Embed(title=f"🔬 {ctx.author.display_name}'s Almanac",
                                                   description="You have not discovered any fusions yet.",
                                                   color=discord.Color.purple()))
                return

            parsed_args = self.fusion_helper.parse_almanac_args(full_args)
            filters, page = parsed_args['filters'], parsed_args['page']
            filtered_fusions = self.fusion_helper.apply_almanac_filters(discovered_fusions_to_display, filters,
                                                                        discovered_ids)

            if not filtered_fusions:
                await ctx.send(embed=discord.Embed(title="ℹ️ Almanac Search",
                                                   description="No discovered fusions match your specified filters.",
                                                   color=discord.Color.purple()))
                return

            total_visible_fusions = len(self.fusion_helper.visible_fusions)
            discovered_hidden_count = sum(1 for fid in discovered_ids if fid in self.fusion_helper.hidden_fusions_by_id)
            total_almanac_fusions = total_visible_fusions + discovered_hidden_count

            items_per_page = 10
            total_pages = max(1, (len(filtered_fusions) + items_per_page - 1) // items_per_page)
            page = max(1, min(page, total_pages))
            page_entries = sorted(filtered_fusions, key=lambda x: x.name)[
                           (page - 1) * items_per_page: page * items_per_page]

            title = f"🔬 {ctx.author.display_name}'s Almanac ({len(discovered_ids)}/{total_almanac_fusions}) " \
                    f"(Page {page}/{total_pages})"
            embed = discord.Embed(title=title, color=discord.Color.purple())

            display_lines = []
            for i, f in enumerate(page_entries, start=(page - 1) * items_per_page + 1):
                recipe_str = self.fusion_helper.format_recipe_string(f.recipe)
                display_lines.append(f"**{i}.** **{f.name}**\nRecipe: {recipe_str}")

            embed.description = "\n\n".join(display_lines)
            embed.set_footer(
                text=f"Use {ctx.prefix}almanac [filters] [page]. Filters: name:<str> contains:<str> tier:<#>")
            await ctx.send(embed=embed)

        else:
            await self.almanac_info_command.callback(self, ctx, fusion_query=full_args.strip())

    @almanac_command.command(name="info")
    async def almanac_info_command(self, ctx: commands.Context, *, fusion_query: str):
        """Shows detailed info for a specific discovered fusion."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        discovered_ids = set(profile.discovered_fusions)

        fusion_def = self.fusion_helper.find_defined_fusion(fusion_query)

        if not fusion_def or fusion_def.visibility == "invisible":
            embed = discord.Embed(title="ℹ️ Recipe Unknown",
                                  description=f"The fusion recipe for **'{fusion_query}'** could not be found.",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        if fusion_def.visibility == "hidden" and fusion_def.id not in discovered_ids:
            embed = discord.Embed(title="ℹ️ Recipe Unknown",
                                  description=f"The fusion recipe for **'{fusion_query}'** could not be found.",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        if fusion_def.id not in discovered_ids:
            embed = discord.Embed(title="ℹ️ Fusion Not Discovered",
                                  description=f"You have not discovered **{fusion_def.name}** yet. ",
                                  color=discord.Color.purple())
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(title=f"🌿 Almanac Entry: {fusion_def.name}",
                              description=f"Detailed schematics for **{fusion_def.name}** from your almanac.",
                              color=discord.Color.purple())
        embed.add_field(name="Asset ID", value=f"`{fusion_def.id}`", inline=True)
        embed.add_field(name="Classification Tier", value=f"`{fusion_def.type}`", inline=True)
        embed.add_field(name="Fusion Recipe",
                        value=self.fusion_helper.format_recipe_string(fusion_def.recipe), inline=False)

        image_file_to_send = self.image_helper.get_image_file_for_plant(fusion_def.id)

        if image_file_to_send:
            embed.set_image(url=f"attachment://{image_file_to_send.filename}")

        embed.set_footer(text="Penny - Fusion Experimentation Log")
        await ctx.send(embed=embed, file=image_file_to_send)

    @almanac_command.command(name="available")
    async def almanac_available_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Lists all fusions you can make right now."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        discovered_ids = set(profile.discovered_fusions)
        parsed_args = self.fusion_helper.parse_almanac_args(full_args)
        filters, page = parsed_args['filters'], parsed_args['page']

        user_assets = self.fusion_helper.get_user_whole_assets_with_source(profile)

        all_craftable_fusions = []
        for fusion_def in self.fusion_helper.visible_fusions:
            plan, _ = self.fusion_helper.find_crafting_plan(
                recipe_counter=Counter(fusion_def.recipe),
                user_assets=user_assets,
                fusion_id_to_check=fusion_def.id
            )

            if plan is not None:
                have_assets_list = [asset['name'] for asset in plan]

                info = {
                    "fusion_def": fusion_def,
                    "plan": plan,
                    "is_new": fusion_def.id not in discovered_ids,
                    "have_list": have_assets_list
                }
                all_craftable_fusions.append(info)
        
        craftable_fusion_def = [info['fusion_def'] for info in all_craftable_fusions]
        plans_by_fusion_id = {info['fusion_def'].id: info['plan'] for info in all_craftable_fusions}
        filtered_fusions = self.fusion_helper.apply_almanac_filters(craftable_fusion_def, filters, discovered_ids, 
                                                                    plans_by_fusion_id=plans_by_fusion_id)
        
        filtered_results_info = [info for info in all_craftable_fusions if info['fusion_def'] in filtered_fusions]

        if not filtered_results_info:
            desc = "You cannot make any fusions that match your filters with your current assets."
            await ctx.send(
                embed=discord.Embed(title="✅ Available Fusions", description=desc, color=discord.Color.purple()))
            return

        items_per_page = 5
        sorted_entries = sorted(filtered_results_info,
                                key=lambda f: (not f['is_new'], len(f['fusion_def'].recipe), f['fusion_def'].name))

        total_pages = max(1, (len(sorted_entries) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        page_entries = sorted_entries[(page - 1) * items_per_page: page * items_per_page]

        embed = discord.Embed(title=f"✅ Available Fusions (Page {page}/{total_pages})", color=discord.Color.purple())

        for info in page_entries:
            f = info['fusion_def']
            new_tag = " **[NEW]**" if info['is_new'] else ""
            storage_items_in_plan = [asset for asset in info.get("plan", []) if asset.get("source") == "storage"]
            storage_tag = " 📦" if storage_items_in_plan else ""
            recipe_str = self.fusion_helper.format_recipe_string(f.recipe)

            have_list = info.get('have_list', [])
            have_str = ", ".join(
                [f"**{name}** x{count}" for name, count in Counter(have_list).items()]) if have_list else "None"

            if not storage_tag:
                fuse_args = [str(a['index'] + 1) if a['source'] == 'garden' else a['id'] for a in info.get('plan', [])]
                command_str = f"`{ctx.prefix}fuse {' '.join(fuse_args)}`"
            else:
                unstore_indices = sorted([str(asset['index'] + 1) for asset in storage_items_in_plan])
                command_str = f"`{ctx.prefix}unstore {' '.join(unstore_indices)}`"

            value_str = f"Recipe: {recipe_str}\nHave: {have_str}\n{command_str}"
            embed.add_field(name=f"▫️ {f.name}{new_tag}{storage_tag}", value=value_str, inline=False)

        embed.set_footer(
            text=f"Use {ctx.prefix}almanac available [filters] [page]. Filters: name:<str> contains:<str> tier:<#> "
                 f"discovered:<bool> storage:<bool>")
        await ctx.send(embed=embed)

    @almanac_command.command(name="discover")
    async def almanac_discover_command(self, ctx: commands.Context, *, full_args: str = ""):
        """Lists potential discoveries using at least one of your plants or materials."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        discovered_ids = set(profile.discovered_fusions)
        parsed_args = self.fusion_helper.parse_almanac_args(full_args)
        filters, page = parsed_args['filters'], parsed_args['page']

        user_assets = self.fusion_helper.get_user_whole_assets_with_source(profile)
        if any(f['key'] == 'storage' and f['value'] == 'false' for f in filters):
            user_assets = [asset for asset in user_assets if asset.get("source") != "storage"]

        potential_fusions = []
        material_names = self.fusion_helper.all_materials_by_name

        valid_user_assets = self.fusion_helper.get_valid_crafting_components(user_assets)
        sorted_user_assets = sorted(
            valid_user_assets,
            key=lambda x: len(self.fusion_helper.deconstruct_plant(x)[0]),
            reverse=True
        )

        for fusion_def in self.fusion_helper.visible_fusions:
            if fusion_def.id in discovered_ids:
                continue

            recipe_counter = Counter(fusion_def.recipe)
            plan, needed = self.fusion_helper.find_crafting_plan(
                recipe_counter=recipe_counter,
                user_assets=user_assets,
                fusion_id_to_check=fusion_def.id
            )

            have_assets_list = []
            if plan is not None:
                have_assets_list = [p.get('name', 'Unknown') for p in plan]
                sort_group = 0
            else:
                temp_needed = recipe_counter.copy()

                for asset in sorted_user_assets:
                    asset_components, _ = self.fusion_helper.deconstruct_plant(asset)
                    asset_counter = Counter(asset_components)

                    if all(temp_needed.get(item, 0) >= count for item, count in asset_counter.items()):
                        temp_needed -= asset_counter
                        have_assets_list.append(asset['name'])

                sort_group = 3
                if have_assets_list:
                    if any(comp not in material_names for comp in have_assets_list):
                        sort_group = 1
                    else:
                        sort_group = 2
            
            info = {
                "fusion_def": fusion_def,
                "plan" : plan,
                "need_counter": needed,
                "have_list": have_assets_list,
                "sort_group": sort_group
            }

            potential_fusions.append(info)

        missing_filter_value = None
        temp_filters = list(filters)
        for f in temp_filters:
            if f['key'] == 'missing':
                try:
                    missing_filter_value = int(f['value'])
                except ValueError:
                    pass
                filters.remove(f)
        
        potential_fusions_def = [info['fusion_def'] for info in potential_fusions]
        filtered_fusions = self.fusion_helper.apply_almanac_filters(potential_fusions_def, filters, discovered_ids)
        filtered_ids = {f.id for f in filtered_fusions}

        filtered_results = [info for info in potential_fusions if info['fusion_def'].id in filtered_ids]

        if missing_filter_value is not None:
            filtered_results = [f for f in filtered_results if
                                sum(f.get('need_counter', Counter()).values()) == missing_filter_value]

        if not filtered_results:
            await ctx.send(embed=discord.Embed(title="🌱 Potential Discoveries",
                                               description="No undiscovered recipes match your criteria.",
                                               color=discord.Color.purple()))
            return

        def sort_key(info):
            group = info.get('sort_group', 3)
            f_def = info['fusion_def']
            if group < 2:
                key1 = sum(info.get('need_counter', Counter()).values())
                key2 = len(f_def.recipe)
                key3 = f_def.name
                return group, key1, key2, key3
            elif group == 2:
                key1 = -len(info.get('have_list', []))
                key2 = len(f_def.recipe)
                key3 = f_def.name
                return group, key1, key2, key3
            else: 
                key1 = len(f_def.recipe)
                key2 = f_def.name
                key3 = 0
                return group, key1, key2, key3

        sorted_entries = sorted(filtered_results, key=sort_key)

        items_per_page = 5
        total_pages = max(1, (len(sorted_entries) + items_per_page - 1) // items_per_page)
        page = max(1, min(page, total_pages))
        page_entries = sorted_entries[(page - 1) * items_per_page: page * items_per_page]

        embed = discord.Embed(title=f"🌱 Potential Discoveries (Page {page}/{total_pages})",
                              color=discord.Color.purple())

        for info in page_entries:
            f = info['fusion_def']
            value_lines = []
            if info['plan'] is not None:
                recipe_str = self.fusion_helper.format_recipe_string(f.recipe)
                have_str = ", ".join(
                    [f"**{name}** x{count}" for name, count in Counter(info.get('have_list', [])).items()])
                storage_items_in_plan = [asset for asset in info.get("plan", []) if asset.get("source") == "storage"]
                storage_tag = " 📦" if storage_items_in_plan else ""
                header = f"✅ **Ready to Fuse!**{storage_tag}\nRecipe: {recipe_str}\nHave: {have_str}"

                if not storage_tag:
                    fuse_args = [str(a['index'] + 1) if a['source'] == 'garden' else a['id'] for a in info['plan']]
                    command_str = f"`{ctx.prefix}fuse {' '.join(fuse_args)}`"
                    value_lines.append(f"{header}\n{command_str}")
                else:
                    unstore_indices = sorted([str(asset['index'] + 1) for asset in storage_items_in_plan])
                    command_str = f"`{ctx.prefix}unstore {' '.join(unstore_indices)}`"
                    value_lines.append(f"{header}\n{command_str}")
            else:
                recipe_str = self.fusion_helper.format_recipe_string(f.recipe)
                value_lines.append(f"Recipe: {recipe_str}")

                have_list = info.get('have_list', [])
                if have_list:
                    have_str = ", ".join([f"**{name}** x{count}" for name, count in Counter(have_list).items()])
                    value_lines.append(f"Have: {have_str}")

                need_counter = info.get('need_counter', Counter())
                if any(count > 0 for count in need_counter.values()):
                    need_str = ", ".join([f"**{name}** x{count}" for name, count in need_counter.items() if count > 0])
                    value_lines.append(f"Need: {need_str}")

            embed.add_field(name=f"▫️ {f.name}", value="\n".join(value_lines) or " ", inline=False)

        embed.set_footer(
            text=f"Use {ctx.prefix}almanac discover [filters] [page]. Filters: name:<str> contains:<str> tier:<#> "
                 f"storage:<bool> missing:<#>")
        await ctx.send(embed=embed)

    @commands.group(name="background", invoke_without_command=True)
    @is_cog_ready()
    async def background_command(self, ctx: commands.Context, *, background_name: Optional[str] = None):
        """View and set your unlocked garden backgrounds."""

        if background_name:
            await self.background_set_command.callback(self, ctx, background_name=background_name)
        else:
            await self.background_list_command.callback(self, ctx)

    @background_command.command(name="list")
    async def background_list_command(self, ctx: commands.Context):
        """Displays all the garden backgrounds you have unlocked."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        unlocked_ids = profile.unlocked_backgrounds
        active_id = profile.active_background

        embed = discord.Embed(
            title=f"🖼️ {ctx.author.display_name}'s Unlocked Backgrounds",
            description=f"You have unlocked **{len(unlocked_ids)}** background(s). Use `{ctx.prefix}bg set <name>` to "
                        f"change your active background.",
            color=discord.Color.dark_magenta()
        )

        display_lines = []
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def.id in unlocked_ids:
                is_active = "✅" if bg_def.id == active_id else "▫️"
                display_lines.append(f"{is_active} **{bg_def.name}**")

        embed.add_field(name="Available Backgrounds", value="\n".join(display_lines) or "None unlocked.")
        await ctx.send(embed=embed)

    @background_command.command(name="set")
    async def background_set_command(self, ctx: commands.Context, *, background_name: str):
        """Sets your active garden background."""

        profile = self.garden_helper.get_user_profile_view(ctx.author.id)
        unlocked_ids = profile.unlocked_backgrounds

        target_bg = None
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def.name.lower() == background_name.lower():
                target_bg = bg_def
                break

        if not target_bg:
            await ctx.send(embed=discord.Embed(title="❌ Background Not Found",
                                               description=f"No background named '{background_name}' exists.",
                                               color=discord.Color.red()))
            return

        if target_bg.id not in unlocked_ids:
            await ctx.send(embed=discord.Embed(title="❌ Background Locked",
                                               description=f"You have not unlocked the **{target_bg.name}** "
                                                           f"background yet.",
                                               color=discord.Color.red()))
            return

        self.garden_helper.set_active_background(ctx.author.id, target_bg.id)

        embed = discord.Embed(
            title="✅ Background Set!",
            description=f"Your active garden background has been set to **{target_bg.name}**. Your profile will now "
                        f"reflect this change.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    
    @commands.group(name="gardenadmin")
    @is_cog_ready()
    @commands.is_owner()
    async def cmd_debug_group(self, ctx: commands.Context):
        """Base command for owner-only Zen Garden debug utilities."""
        pass

    @cmd_debug_group.command(name="setsun")
    async def debug_setsun_command(self, ctx: commands.Context, amount: int, target_user: discord.Member):
        """Sets a user's balance to a specific amount."""

        if amount < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Amount cannot be negative. Use a positive integer or zero.",
                                               color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        original_balance = profile.balance

        self.garden_helper.set_balance(target_user.id, amount)
        profile = self.garden_helper.get_user_profile_view(target_user.id)

        embed = discord.Embed(
            title="⚙️ Debug: Solar Energy Set Protocol",
            description=f"Successfully set the solar energy balance for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Amount", value=f"{amount:,}", inline=True)
        embed.add_field(name="Original Balance", value=f"{original_balance:,} {self.CURRENCY_EMOJI}", inline=False)
        embed.add_field(name="New Balance", value=f"{profile.balance:,} {self.CURRENCY_EMOJI}", inline=False)
        embed.set_footer(text="Penny - Administrative Financial Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="setsunmastery")
    async def debug_setsunmastery_command(self, ctx: commands.Context, level: int, target_user: discord.Member):
        """Sets a user's Sun Mastery level."""

        if level < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Mastery level cannot be negative. Use a positive integer "
                                                           "or zero.",
                                               color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        original_mastery = profile.sun_mastery

        self.garden_helper.set_sun_mastery(target_user.id, level)
        profile = self.garden_helper.get_user_profile_view(target_user.id)

        sun_mastery_bonus = 1 + (0.1 * level)

        embed = discord.Embed(
            title="⚙️ Debug: Sun Mastery Level Set Protocol",
            description=f"Successfully set the Sun Mastery level for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Level", value=f"{level}", inline=True)
        embed.add_field(name="Original Sun Mastery", value=f"{original_mastery}", inline=False)
        embed.add_field(name="New Sun Mastery", value=f"{profile.sun_mastery} ({sun_mastery_bonus:.2f}x sell boost)",
                        inline=False)
        embed.set_footer(text="Penny - Administrative Stat Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="settimemastery")
    async def debug_settimemastery_command(self, ctx: commands.Context, level: int, target_user: discord.Member):
        """Sets a user's Time Mastery level."""

        if level < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Input",
                                               description="Mastery level cannot be negative. Use a positive integer "
                                                           "or zero.",
                                               color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        original_mastery = profile.time_mastery

        self.garden_helper.set_time_mastery(target_user.id, level)
        profile = self.garden_helper.get_user_profile_view(target_user.id)

        time_mastery_bonus = 1 + (0.1 * level)

        embed = discord.Embed(
            title="⚙️ Debug: Time Mastery Level Set Protocol",
            description=f"Successfully set the Time Mastery level for User {target_user.mention}.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target User", value=target_user.mention, inline=True)
        embed.add_field(name="Set Level", value=f"{level}", inline=True)
        embed.add_field(name="Original Time Mastery", value=f"{original_mastery}", inline=False)
        embed.add_field(name="New Time Mastery",
                        value=f"{profile.time_mastery} ({time_mastery_bonus:.2f}x growth boost)", inline=False)
        embed.set_footer(text="Penny - Administrative Stat Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="additem")
    async def debug_additem_command(self, ctx: commands.Context, target_user: discord.Member, item_id: str,
                                    quantity: int = 1):
        """Adds an item to a user's inventory by ID."""

        if quantity <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Quantity must be a positive number.",
                                    color=discord.Color.red()))
            return

        all_items = self.shop_helper.get_all_item_definitions()
        actual_item_key = next((k for k, v in all_items.items() if k.lower() == item_id.lower()), None)
        item_details = all_items.get(actual_item_key)

        if not actual_item_key or not item_details:
            await ctx.send(embed=discord.Embed(title="❌ Item Not Found",
                                               description=f"The ID `{item_id}` does not correspond to any known item.",
                                               color=discord.Color.red()))
            return

        self.garden_helper.add_item_to_inventory(target_user.id, actual_item_key, quantity)
        
        item_name = item_details.name
        embed = discord.Embed(
            title="⚙️ Debug: Item Addition Protocol",
            description=f"Successfully added **{item_name}** (`{actual_item_key}`) x{quantity} to "
                        f"{target_user.mention}'s inventory.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Inventory Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="removeitem")
    async def debug_removeitem_command(self, ctx: commands.Context, target_user: discord.Member, item_id: str, quantity: int = 1):
        """Removes one or more instances of an item from a user's inventory."""

        if quantity <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Quantity must be a positive number.",
                                    color=discord.Color.red()))
            return
            
        profile = self.garden_helper.get_user_profile_view(target_user.id)
        inventory = profile.inventory

        item_id_lower = item_id.lower()
        actual_item_key = next((k for k in inventory if k.lower() == item_id_lower), None)

        if actual_item_key:
            if inventory.get(actual_item_key, 0) < quantity:
                await ctx.send(embed=discord.Embed(
                    title="⚙️ Debug: Insufficient Quantity",
                    description=f"User only has {inventory.get(actual_item_key, 0)} of this item. Cannot remove {quantity}.",
                    color=discord.Color.yellow()
                ))
                return

            self.garden_helper.remove_item_from_inventory(target_user.id, actual_item_key, quantity)

            all_items = self.shop_helper.get_all_item_definitions()
            item_details = all_items.get(actual_item_key)
            item_name = item_details.name

            embed = discord.Embed(
                title="⚙️ Debug: Item Removal Protocol",
                description=f"Successfully removed **{item_name}** (`{actual_item_key}`) x{quantity} from "
                            f"{target_user.mention}'s inventory.",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title="⚙️ Debug: Item Not Found in Inventory",
                description=f"Item with ID `{item_id}` not found in {target_user.mention}'s inventory. No changes "
                            f"were made.",
                color=discord.Color.yellow()
            )

        embed.set_footer(text="Penny - Administrative Inventory Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.group(name="addplant")
    async def debug_addplant_group(self, ctx: commands.Context):
        """Base command for adding plants to a user's garden."""
        pass

    @debug_addplant_group.command(name="baseplant")
    async def debug_addplant_baseplant(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                       plant_id: str):
        """Adds a specific base plant to a user's garden plot."""

        plant_definition = self.plant_helper.get_base_plant_by_id(plant_id)
        if not plant_definition:
            await ctx.send(embed=discord.Embed(title="❌ Plant Not Found",
                                               description=f"The ID `{plant_id}` does not correspond to any known base "
                                                           f"plant.",
                                               color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return

        if not self.garden_helper.is_slot_unlocked(profile, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return

        if profile.garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        new_plant = PlantedPlant(
            id=plant_definition.id,
            name=plant_definition.name,
            type=plant_definition.type
        )

        self.garden_helper.set_garden_plot(target_user.id, plot_index, new_plant)

        embed = discord.Embed(
            title="⚙️ Debug: Base Plant Added",
            description=f"Successfully added **{new_plant.name}** to plot {plot_number} for "
                        f"{target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @debug_addplant_group.command(name="fusion")
    async def debug_addplant_fusion(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                    fusion_id: str):
        """Adds a specific fusion plant to a user's garden plot."""

        fusion_definition = self.fusion_helper.find_defined_fusion(fusion_id)
        if not fusion_definition:
            await ctx.send(embed=discord.Embed(title="❌ Fusion Not Found",
                                               description=f"The ID `{fusion_id}` does not correspond to any known "
                                                           f"fusion.",
                                               color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return

        if not self.garden_helper.is_slot_unlocked(profile, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return

        if profile.garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        new_plant = PlantedPlant(
            id=fusion_definition.id,
            name=fusion_definition.name,
            type=fusion_definition.type
        )
        self.garden_helper.set_garden_plot(target_user.id, plot_index, new_plant)

        embed = discord.Embed(
            title="⚙️ Debug: Fusion Plant Added",
            description=f"Successfully added **{new_plant.name}** to plot {plot_number} for "
                        f"{target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @debug_addplant_group.command(name="custom")
    async def debug_addplant_custom(self, ctx: commands.Context, target_user: discord.Member, plot_number: int, *,
                                    custom_plant_dict_str: str):
        """Adds a custom plant object (from dict) to a user's garden."""

        try:
            custom_plant_obj = json.loads(custom_plant_dict_str)
            if not isinstance(custom_plant_obj, dict):
                raise ValueError("Input must be a valid JSON dictionary.")

            if not all(k in custom_plant_obj for k in ["id", "name", "type"]):
                await ctx.send(embed=discord.Embed(title="❌ Invalid Dictionary",
                                                   description="The provided dictionary string is missing one or more "
                                                               "required keys (`id`, `name`, `type`).",
                                                   color=discord.Color.red()))
                return
        except json.JSONDecodeError:
            await ctx.send(embed=discord.Embed(title="❌ JSON Error",
                                               description="Failed to parse the provided string as a valid JSON "
                                                           "dictionary.",
                                               color=discord.Color.red()))
            return
        except ValueError as e:
            await ctx.send(embed=discord.Embed(title="❌ Value Error", description=str(e), color=discord.Color.red()))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        plot_index = plot_number - 1

        if not (0 <= plot_index < 12):
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Plot", description="Plot number must be between 1 and 12.",
                                    color=discord.Color.red()))
            return

        if not self.garden_helper.is_slot_unlocked(profile, plot_number):
            await ctx.send(embed=discord.Embed(title="❌ Plot Locked",
                                               description=f"Plot {plot_number} is locked for user "
                                                           f"{target_user.mention}.",
                                               color=discord.Color.red()))
            return

        if profile.garden[plot_index] is not None:
            await ctx.send(embed=discord.Embed(title="❌ Plot Occupied",
                                               description=f"Plot {plot_number} for user {target_user.mention} is "
                                                           f"already occupied.",
                                               color=discord.Color.red()))
            return

        try:
            custom_plant_to_add = PlantedPlant(**custom_plant_obj)
        except TypeError:
            await ctx.send(embed=discord.Embed(title="❌ Dictionary Mismatch",
                                               description="The keys in the provided dictionary do not match the required fields for a plant.",
                                               color=discord.Color.red()))
            return

        self.garden_helper.set_garden_plot(target_user.id, plot_index, custom_plant_to_add)

        embed = discord.Embed(
            title="⚙️ Debug: Custom Plant Added",
            description=f"Successfully added custom plant **{custom_plant_to_add.name}** to plot {plot_number} "
                        f"for {target_user.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Data Added", value=f"```json\n{json.dumps(custom_plant_obj, indent=2)}\n```")
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="speed")
    async def debug_speed_command(self, ctx: commands.Context, minutes: Optional[int] = None):
        """Sets or displays the global plant growth duration in minutes."""

        current_duration = self.game_state_helper.get_global_state("plant_growth_duration_minutes")

        if minutes is None:
            embed = discord.Embed(
                title="⚙️ Debug: Plant Growth Speed Setting",
                description=f"The current global plant growth duration is set to **{current_duration} minutes**.",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Use {ctx.prefix}debug speed <minutes> to change it")
            await ctx.send(embed=embed)
            return

        if minutes <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Growth duration must be a positive integer.",
                                    color=discord.Color.red()))
            return

        self.game_state_helper.set_global_state("plant_growth_duration_minutes", minutes)

        embed = discord.Embed(
            title="✅ Debug: Plant Growth Speed Updated",
            description=f"Global plant growth duration has been updated from {current_duration} minutes to "
                        f"**{minutes} minutes**.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Growth Cycle Configuration")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="replenishstock")
    async def debug_replenishstock_command(self, ctx: commands.Context, item_id: str, amount: int = 1):
        """Adds stock to a limited item in Rux's shop."""

        item_details = self.data_loader.rux_shop_data.get(item_id)
        if not item_details or item_details.category != "limited":
            embed = discord.Embed(title="❌ Invalid Item",
                                  description=f"'{item_id}' is not a valid, limited-stock item in rux_shop.json.",
                                  color=discord.Color.red())
            await ctx.send(embed=embed)
            return

        if amount <= 0:
            await ctx.send(
                embed=discord.Embed(title="❌ Invalid Input", description="Amount must be a positive integer.",
                                    color=discord.Color.red()))
            return

        current_stock = self.game_state_helper.get_rux_stock(item_id)
        new_stock = current_stock + amount
        self.game_state_helper.set_rux_stock(item_id, new_stock)

        embed = discord.Embed(
            title="⚙️ Debug: Stock Replenishment Protocol",
            description=f"Successfully replenished stock for **{item_details.name}** (`{item_id}`).",
            color=discord.Color.green()
        )
        embed.add_field(name="Amount Added", value=f"+{amount}", inline=True)
        embed.add_field(name="Previous Stock", value=f"{current_stock}", inline=True)
        embed.add_field(name="New Stock", value=f"{new_stock}", inline=True)
        embed.set_footer(text="Penny - Administrative Stock Management Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="refreshpennyshop")
    async def debug_refreshpennyshop_command(self, ctx: commands.Context):
        """Forces an immediate refresh of Penny's Treasures shop stock."""

        await ctx.send(embed=discord.Embed(title="⚙️ Debug: Penny's Shop Refresh",
                                           description="Forcing an immediate refresh of Penny's Treasures stock...",
                                           color=discord.Color.orange()))

        await self.shop_helper.refresh_penny_shop_if_needed(self.logger, force=True)

        await self.logger.log_to_discord(f"Debug: Penny's Shop manually refreshed by {ctx.author.name}.", "INFO")
        await ctx.send(embed=discord.Embed(title="✅ Debug: Penny's Shop Refreshed",
                                           description="Penny's Treasures stock has been successfully refreshed with "
                                                       "new items.",
                                           color=discord.Color.green()))

    @cmd_debug_group.command(name="pennyshoprefresh")
    async def debug_pennyshoprefresh_command(self, ctx: commands.Context, interval_hours: Optional[int] = None):
        """Sets or displays the Penny's Shop refresh interval in hours."""

        current_interval = self.game_state_helper.get_global_state("treasure_shop_refresh_interval_hours", 1)

        if interval_hours is None:
            embed = discord.Embed(
                title="⚙️ Debug: Penny's Shop Refresh Interval",
                description=f"The current refresh interval for Penny's Treasures is **{current_interval} hours**.\n"
                            f"Valid intervals are positive numbers that divide 24 evenly (1, 2, 3, 4, 6, 8, 12, 24).",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Use {ctx.prefix}debug pennyshoprefresh <hours> to change it")
            await ctx.send(embed=embed)
            return

        if interval_hours <= 0 or 24 % interval_hours != 0:
            embed = discord.Embed(
                title="❌ Invalid Interval",
                description="The interval must be a positive number of hours that divides 24 evenly (e.g., 1, 2, 3, 4, "
                            "6, 8, 12, 24).",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        self.game_state_helper.set_global_state("treasure_shop_refresh_interval_hours", interval_hours)

        embed = discord.Embed(
            title="✅ Debug: Penny's Shop Interval Updated",
            description=f"The refresh interval for Penny's Treasures has been changed from {current_interval} hours "
                        f"to **{interval_hours} hours**.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="refreshdaveshop")
    async def debug_refreshdaveshop_command(self, ctx: commands.Context):
        """Forces an immediate refresh of Crazy Dave's shop stock."""

        await ctx.send(embed=discord.Embed(title="⚙️ Debug: Dave's Shop Refresh",
                                           description="Forcing an immediate refresh of Crazy Dave's Twiddydinkies "
                                                       "stock...",
                                           color=discord.Color.orange()))

        await self.shop_helper.refresh_dave_shop_if_needed(self.logger, force=True)

        await self.logger.log_to_discord(f"Debug: Dave's Shop manually refreshed by {ctx.author.name}.", "INFO")
        await ctx.send(embed=discord.Embed(title="✅ Debug: Dave's Shop Refreshed",
                                           description="Crazy Dave's stock has been successfully refreshed.",
                                           color=discord.Color.green()))

    @cmd_debug_group.command(name="unlockbg")
    async def debug_unlockbg_command(self, ctx: commands.Context, target_user: discord.Member, *, background_name: str):
        """Unlocks a specific garden background for a user."""

        target_bg_def = None
        for bg_def in self.background_helper.all_backgrounds:
            if bg_def.name.lower() == background_name.lower():
                target_bg_def = bg_def
                break

        if not target_bg_def:
            await ctx.send(embed=discord.Embed(
                title="❌ Background Not Found",
                description=f"No background with the name '{background_name}' could be found in the loaded data.",
                color=discord.Color.red()
            ))
            return

        profile = self.garden_helper.get_user_profile_view(target_user.id)
        unlocked_bgs = profile.unlocked_backgrounds
        bg_id_to_unlock = target_bg_def.id

        if bg_id_to_unlock in unlocked_bgs:
            await ctx.send(embed=discord.Embed(
                title="⚙️ Debug: Background Already Unlocked",
                description=f"User {target_user.mention} already has the **{target_bg_def.name}** background "
                            f"unlocked.",
                color=discord.Color.blue()
            ))
            return

        self.garden_helper.add_unlocked_background(target_user.id, bg_id_to_unlock)

        embed = discord.Embed(
            title="✅ Debug: Background Unlocked",
            description=f"Successfully unlocked the **{target_bg_def.name}** background for {target_user.mention}.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Penny - Administrative Override Systems")
        await ctx.send(embed=embed)

    @cmd_debug_group.command(name="dumpdata")
    async def debug_dumpdata_command(self, ctx: commands.Context):
        """Dumps the entire current game state into a JSON file."""
        try:
            game_state_dict = self.game_state_helper.game_state
            json_bytes = json.dumps(game_state_dict, indent=4).encode('utf-8')
            buffer = io.BytesIO(json_bytes)
            file = discord.File(buffer, filename=f"zen_garden_data_{int(time.time())}.json")

            embed = discord.Embed(
                title="⚙️ Debug: Game State Dump",
                description="The current in-memory game state has been successfully serialized.",
                color=discord.Color.green()
            )
            embed.set_footer(text="Penny - Administrative Data Systems")
            await ctx.send(embed=embed, file=file)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Error During Data Dump",
                description=f"An unexpected error occurred during data serialization:\n`{e}`",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Administrative Data Systems")
            await ctx.send(embed=embed)

    @cmd_debug_group.command(name="loaddata")
    async def debug_loaddata_command(self, ctx: commands.Context):
        """Loads and completely overwrites the game state from an attached JSON file, then auto-reloads the cog."""
        if not ctx.message.attachments:
            embed = discord.Embed(
                title="❌ Missing Attachment",
                description="Please attach the `data.json` file when running this command.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Administrative Input Error")
            await ctx.send(embed=embed)
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.json'):
            embed = discord.Embed(
                title="❌ Invalid File Type",
                description="The attached file must be a `.json` file.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Administrative Input Error")
            await ctx.send(embed=embed)
            return

        try:
            json_bytes = await attachment.read()
            loaded_data = json.loads(json_bytes)

            if not isinstance(loaded_data, dict) or "users" not in loaded_data or "global_state" not in loaded_data:
                embed = discord.Embed(
                    title="❌ Invalid JSON Structure",
                    description="The JSON file is missing the required top-level keys (`users`, `global_state`).",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Penny - Administrative Data Systems")
                await ctx.send(embed=embed)
                return

            self.game_state_helper.game_state = loaded_data
            await self.game_state_helper.commit_to_disk()

            embed = discord.Embed(
                title="✅ Game State Overwritten Successfully",
                description="The new data has been saved. **Reloading the cog now to apply changes...**",
                color=discord.Color.green()
            )
            embed.set_footer(text="Penny - Administrative Data Systems")
            await ctx.send(embed=embed)

            core_cog = self.bot.get_cog("Core")
            if core_cog:
                core_cog.reload(ctx, "arg")
            else:
                await ctx.send("⚠️ Could not find the Core cog to trigger a reload. Please reload manually.")

        except json.JSONDecodeError:
            embed = discord.Embed(
                title="❌ JSON Parsing Error",
                description="The attached file is not a valid JSON. The operation has been cancelled.",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Administrative Data Systems")
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="❌ Critical Error During Load",
                description=f"An unexpected error occurred while processing the file or saving the state:\n`{e}`",
                color=discord.Color.red()
            )
            embed.set_footer(text="Penny - Administrative Data Systems")
            await ctx.send(embed=embed)
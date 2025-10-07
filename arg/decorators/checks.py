import discord
from redbot.core import commands


def is_not_locked():
    """
    A commands.check decorator that fails if the command author is locked.
    Uses the LockHelper to check the user's status.
    """

    async def predicate(ctx: commands.Context):
        # The cog instance is accessible via ctx.cog
        if not hasattr(ctx.cog, 'lock_helper'):
            # Failsafe in case the cog isn't fully loaded or is misconfigured
            return True

        lock = ctx.cog.lock_helper.get_user_lock(ctx.author.id)
        if lock:
            embed = discord.Embed(
                title=f"❌ Action Locked: Pending {lock.get('type', 'Action').capitalize()}",
                description=f"User {ctx.author.mention}, your actions are locked. Reason:\n\n*_"
                            f"{lock.get('message', 'You are busy with another task.')}_*",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Penny - Global Lock System")
            await ctx.send(embed=embed)
            return False
        return True

    return commands.check(predicate)


def is_cog_ready():
    """
    A commands.check decorator that fails if the cog's main data has not yet been loaded.
    This prevents commands from running during the initial startup sequence.
    """

    async def predicate(ctx: commands.Context):
        # The _initialized flag is on the cog instance
        if not getattr(ctx.cog, '_initialized', False):
            embed = discord.Embed(
                title="⏳ System Initializing",
                description="Penny's systems are still coming online. Please wait a moment and try your command again.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed, delete_after=10)
            return False
        return True

    return commands.check(predicate)
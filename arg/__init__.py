from .arg import arg


async def setup(bot):
    cog = arg(bot)
    r = bot.add_cog(cog)
    if r is not None:
        await r

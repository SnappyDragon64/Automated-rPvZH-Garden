from .arg import ARG


async def setup(bot):
    cog = ARG(bot)
    r = bot.add_cog(cog)
    if r is not None:
        await r

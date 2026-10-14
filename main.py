import discord
import logging
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="손목걸고 ", intents=intents)


@bot.before_invoke
async def delete_command_message(ctx):
    try:
        await ctx.message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.exception(
            "명령어 메시지 삭제에 실패했습니다 (command=%s, user_id=%s)",
            ctx.command,
            ctx.author.id,
        )


_cogs_loaded = False

@bot.event
async def on_ready():
    global _cogs_loaded
    # cogs 폴더 내의 모든 파이썬 파일을 확장(Cog)으로 로드합니다.
    # (재연결 시 on_ready가 다시 불릴 수 있으므로 최초 1회만 로드)
    if not _cogs_loaded:
        if not os.path.exists('./cogs'):
            os.makedirs('./cogs')
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and filename != '__init__.py':
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f'Loaded cog: {filename}')
                except Exception as exc:
                    print(f'Failed to load cog {filename}: {exc}')
        _cogs_loaded = True

async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
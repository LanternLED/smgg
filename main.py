import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="손목걸고 ", intents=intents)

@bot.event
async def on_ready():
    # cogs 폴더 내의 모든 파이썬 파일을 확장(Cog)으로 로드합니다.
    if not os.path.exists('./cogs'):
        os.makedirs('./cogs')
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'Loaded cog: {filename}')
            except Exception as exc:
                print(f'Failed to load cog {filename}: {exc}')

async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
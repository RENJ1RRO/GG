import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import json
import os
import sys
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

load_dotenv()

# ==== КОНФИГУРАЦИЯ ====
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # ИСПОЛЬЗУЙТЕ .env ФАЙЛ!
TARGET_CHANNEL_ID = 1454493797781078151  # ID вашего голосового канала
GUILD_ID = 1454493732262117545  # ID вашего сервера
# ======================

if not DISCORD_TOKEN:
    logging.critical("❌ Токен не найден! Создайте файл .env с DISCORD_TOKEN=ваш_токен")
    sys.exit(1)

# Включение необходимых интентов
intents = discord.Intents.default()
intents.message_content = True  # Нужно включить в настройках бота!
intents.voice_states = True
intents.guilds = True
intents.members = True  # Нужно включить в настройках бота!

bot = commands.Bot(
    command_prefix='!', 
    intents=intents,
    help_command=None  # Отключаем стандартную команду help
)

# Файлы для сохранения
DATA_FILE = 'voice_time.json'
STATE_FILE = 'bot_state.json'

class LoveBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_time = self.load_data()
        self.join_time = {}
        self.reconnect_attempts = 0
        
        # Запускаем задачи
        self.keep_voice_alive.start()
        self.auto_save.start()
        
    def cog_unload(self):
        self.keep_voice_alive.cancel()
        self.auto_save.cancel()
        self.save_all_data()
    
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_data(self):
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(self.voice_time, f, indent=4)
        except Exception as e:
            logging.error(f"Ошибка сохранения: {e}")
    
    def save_all_data(self):
        """Сохранить все данные"""
        self.save_data()
        logging.info("💾 Все данные сохранены")
    
    @tasks.loop(seconds=30)
    async def keep_voice_alive(self):
        """Поддерживаем голосовое соединение"""
        try:
            # Если бот не в голосовом канале - подключаемся
            if not self.bot.voice_clients:
                await self.connect_to_voice()
            
            # Обновляем время для активных пользователей
            current_time = datetime.datetime.now()
            for user_id, join_dt in list(self.join_time.items()):
                time_spent = (current_time - join_dt).total_seconds()
                self.voice_time[user_id] = self.voice_time.get(user_id, 0) + time_spent
                self.join_time[user_id] = current_time
                
        except Exception as e:
            logging.error(f"Ошибка в keep_voice_alive: {e}")
    
    @tasks.loop(minutes=5)
    async def auto_save(self):
        """Автосохранение данных"""
        try:
            self.save_data()
            if datetime.datetime.now().minute % 30 == 0:  # Каждые 30 минут
                total_hours = sum(self.voice_time.values()) / 3600
                logging.info(f"💕 Всего времени вместе: {total_hours:.1f} часов")
        except Exception as e:
            logging.error(f"Ошибка автосохранения: {e}")
    
    async def connect_to_voice(self):
        """Подключение к голосовому каналу"""
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                logging.error("❌ Сервер не найден")
                return False
            
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if not channel:
                logging.error("❌ Голосовой канал не найден")
                return False
            
            # Подключаемся к каналу
            await channel.connect()
            logging.info(f"✅ Подключился к каналу: {channel.name}")
            
            # Записываем время для тех, кто уже в канале
            for member in channel.members:
                if not member.bot:
                    self.join_time[str(member.id)] = datetime.datetime.now()
            
            self.reconnect_attempts = 0
            return True
            
        except discord.errors.ClientException as e:
            if "Already connected" in str(e):
                return True
            logging.error(f"❌ Ошибка подключения: {e}")
            return False
        except Exception as e:
            self.reconnect_attempts += 1
            logging.error(f"❌ Ошибка подключения (попытка {self.reconnect_attempts}): {e}")
            return False
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Отслеживаем голосовую активность"""
        if member.bot:
            return
        
        user_id = str(member.id)
        
        # Пользователь зашел в наш канал
        if after.channel and after.channel.id == TARGET_CHANNEL_ID:
            self.join_time[user_id] = datetime.datetime.now()
            logging.info(f"💖 {member.name} зашел(ла) в канал")
            
            # Приветствуем в текстовом канале
            await self.send_welcome_message(member)
        
        # Пользователь вышел из нашего канала
        elif before.channel and before.channel.id == TARGET_CHANNEL_ID:
            if user_id in self.join_time:
                time_spent = (datetime.datetime.now() - self.join_time[user_id]).total_seconds()
                self.voice_time[user_id] = self.voice_time.get(user_id, 0) + time_spent
                
                # Сохраняем
                self.save_data()
                
                # Логируем
                hours = time_spent / 3600
                minutes = (time_spent % 3600) / 60
                logging.info(f"💕 {member.name} провел(а): {int(hours)}ч {int(minutes)}м")
                
                del self.join_time[user_id]
    
    async def send_welcome_message(self, member):
        """Отправляем приветственное сообщение"""
        try:
            # Ищем текстовый канал
            guild = member.guild
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    # Проверяем, когда последний раз приветствовали этого пользователя
                    last_key = f"last_welcome_{member.id}"
                    if hasattr(self, last_key):
                        last_time = getattr(self, last_key)
                        if (datetime.datetime.now() - last_time).seconds < 300:  # 5 минут
                            return
                    
                    # Отправляем сообщение
                    messages = [
                        f"💖 Привет, {member.mention}! Рад тебя видеть!",
                        f"🌟 {member.mention} присоединился(ась)! Как же я скучал(а)!",
                        f"💕 {member.mention} вернулся(ась)! Моё сердце забилось чаще!",
                        f"✨ {member.mention} с нами! Самый лучший момент дня!"
                    ]
                    
                    await channel.send(messages[hash(member.id) % len(messages)])
                    
                    # Запоминаем время
                    setattr(self, last_key, datetime.datetime.now())
                    break
                    
        except Exception as e:
            logging.error(f"Ошибка при отправке приветствия: {e}")

@bot.event
async def on_ready():
    """Событие при запуске бота"""
    logging.info(f"💖 Бот {bot.user.name} запущен!")
    logging.info(f"🆔 ID бота: {bot.user.id}")
    
    # Устанавливаем статус
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="вашу любовь 💕"
        ),
        status=discord.Status.online
    )
    
    # Пытаемся подключиться к голосовому каналу
    cog = bot.get_cog('LoveBot')
    if cog:
        await asyncio.sleep(2)  # Ждем немного
        await cog.connect_to_voice()
    
    logging.info("✅ Бот готов к работе!")

@bot.command(name='любовь')
async def love_time(ctx):
    """Показать время, проведенное вместе"""
    cog = bot.get_cog('LoveBot')
    if not cog:
        await ctx.send("💔 Система еще загружается, подожди немного...")
        return
    
    user_id = str(ctx.author.id)
    total_time = cog.voice_time.get(user_id, 0)
    
    # Добавляем текущую сессию
    if user_id in cog.join_time:
        current_session = (datetime.datetime.now() - cog.join_time[user_id]).total_seconds()
        total_time += current_session
    
    # Рассчет
    days = int(total_time // 86400)
    hours = int((total_time % 86400) // 3600)
    minutes = int((total_time % 3600) // 60)
    seconds = int(total_time % 60)
    
    # Красивый embed
    embed = discord.Embed(
        title="💖 Ваше Время Любви",
        color=discord.Color.from_rgb(255, 182, 193)  # Светло-розовый
    )
    
    # Разные сообщения в зависимости от времени
    if total_time < 3600:  # Меньше часа
        message = "Это только начало прекрасной истории! 💫"
    elif total_time < 86400:  # Меньше дня
        message = "Каждый час с тобой - это счастье! 🌟"
    else:
        message = "Настоящая любовь с каждым днем становится только сильнее! 💕"
    
    time_text = []
    if days > 0:
        time_text.append(f"{days} дней")
    if hours > 0:
        time_text.append(f"{hours} часов")
    if minutes > 0:
        time_text.append(f"{minutes} минут")
    if seconds > 0 and days == 0:  # Секунды только если меньше дня
        time_text.append(f"{seconds} секунд")
    
    embed.add_field(
        name="⏱️ Вместе проведено:",
        value="**" + " ".join(time_text) + "**",
        inline=False
    )
    
    # Дополнительная статистика
    embed.add_field(
        name="📊 Интересные факты:",
        value=f"• {int(total_time/60):,} минут вместе\n"
              f"• {int(total_time):,} секунд счастья\n"
              f"• {int((total_time/3600)*60):,} кружек чая\n"
              f"• {int(total_time/1800):,} песен прослушано",
        inline=False
    )
    
    embed.set_footer(text=message)
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command(name='статус')
async def bot_status(ctx):
    """Показать статус бота"""
    cog = bot.get_cog('LoveBot')
    
    embed = discord.Embed(
        title="🤖 Статус Бота Любви",
        color=discord.Color.green() if bot.voice_clients else discord.Color.red()
    )
    
    # Информация о голосовом соединении
    if bot.voice_clients:
        vc = bot.voice_clients[0]
        members_in_channel = [m for m in vc.channel.members if not m.bot]
        
        voice_status = f"✅ **Подключен к:** {vc.channel.name}\n"
        voice_status += f"👥 **Людей в канале:** {len(members_in_channel)}\n"
        
        if members_in_channel:
            names = ", ".join([m.display_name for m in members_in_channel[:3]])
            if len(members_in_channel) > 3:
                names += f" и ещё {len(members_in_channel)-3}"
            voice_status += f"💕 **Сейчас с вами:** {names}"
    else:
        voice_status = "❌ **Не подключен к голосовому каналу**\n"
        voice_status += "⏳ *Пытаюсь подключиться...*"
    
    embed.add_field(name="🔊 Голосовое соединение", value=voice_status, inline=False)
    
    # Статистика времени
    if cog:
        total_seconds = sum(cog.voice_time.values())
        total_hours = total_seconds / 3600
        
        stats = f"💾 **Отслеживается:** {len(cog.voice_time)} чел.\n"
        stats += f"⏱️ **Всего времени:** {total_hours:.1f} часов\n"
        stats += f"❤️ **Сейчас активно:** {len(cog.join_time)} чел."
        
        embed.add_field(name="📈 Статистика", value=stats, inline=True)
    
    # Системная информация
    sys_info = f"🏓 **Пинг:** {round(bot.latency * 1000)}мс\n"
    sys_info += f"🕐 **Время работы:** {str(datetime.datetime.now() - bot.start_time).split('.')[0]}"
    
    embed.add_field(name="⚙️ Система", value=sys_info, inline=True)
    
    # Романтичная цитата
    quotes = [
        "Любовь не измеряется часами, а чувствами! 💞",
        "Каждая секунда с любимым бесценна! ⏳✨",
        "Настоящая любовь только начинается! 💘",
        "Время, проведенное с тобой, летит незаметно! 🕊️"
    ]
    
    embed.set_footer(text=quotes[hash(str(ctx.author.id)) % len(quotes)])
    
    await ctx.send(embed=embed)

@bot.command(name='помощь')
async def help_command(ctx):
    """Показать список команд"""
    embed = discord.Embed(
        title="💖 Помощь по командам бота",
        description="Бот для отслеживания времени, проведенного вместе в голосовом канале",
        color=discord.Color.blue()
    )
    
    commands_list = [
        ("!любовь", "Показать сколько времени вы провели вместе"),
        ("!статус", "Показать текущий статус бота и соединения"),
        ("!помощь", "Показать это сообщение")
    ]
    
    for cmd, desc in commands_list:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    embed.add_field(
        name="💕 Особенности",
        value="• Бот автоматически подключается к вашему голосовому каналу\n"
              "• Работает 24/7 с авто-восстановлением\n"
              "• Сохраняет всю историю времени\n"
              "• Отправляет милые приветствия",
        inline=False
    )
    
    embed.set_footer(text="Любите друг друга! 💘")
    
    await ctx.send(embed=embed)

@bot.event
async def on_disconnect():
    logging.warning("🔌 Бот отключился")
    cog = bot.get_cog('LoveBot')
    if cog:
        cog.save_all_data()

@bot.event
async def on_resumed():
    logging.info("🔁 Соединение восстановлено")
    # Пытаемся переподключиться
    cog = bot.get_cog('LoveBot')
    if cog:
        await asyncio.sleep(3)
        await cog.connect_to_voice()

# Обработка ошибок
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"💔 Неизвестная команда. Используй **!помощь** для списка команд")
    else:
        logging.error(f"Ошибка команды: {error}")

# Главная функция
async def main():
    async with bot:
        await bot.add_cog(LoveBot(bot))
        bot.start_time = datetime.datetime.now()
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    # Простой запуск без сложных обработчиков сигналов
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n💖 Бот завершает работу...")
        cog = bot.get_cog('LoveBot')
        if cog:
            cog.save_all_data()
    except Exception as e:
        logging.critical(f"Критическая ошибка: {e}")

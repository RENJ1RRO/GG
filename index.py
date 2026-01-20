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
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TARGET_CHANNEL_ID = 1454493797781078151  # ID вашего голосового канала
GUILD_ID = 1454493732262117545  # ID вашего сервера
# ======================

if not DISCORD_TOKEN:
    logging.critical("Токен не найден! Проверьте файл .env")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Файлы для сохранения
DATA_FILE = 'voice_time.json'
STATE_FILE = 'bot_state.json'
CONFIG_FILE = 'config.json'

class LoveBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_time = self.load_data()
        self.join_time = {}
        self.reconnect_attempts = 0
        self.last_afk_check = datetime.datetime.now()
        
        # Запускаем задачи
        self.keep_alive.start()
        self.auto_reconnect.start()
        self.auto_save.start()
        self.check_afk.start()
        
    def cog_unload(self):
        self.keep_alive.cancel()
        self.auto_reconnect.cancel()
        self.auto_save.cancel()
        self.check_afk.cancel()
        self.save_all_data()
    
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save_data(self):
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(self.voice_time, f, indent=4)
        except:
            pass
    
    def save_all_data(self):
        """Сохранить все данные перед выходом"""
        self.save_data()
        
        # Сохраняем состояние
        state = {
            'is_in_voice': bool(self.bot.voice_clients),
            'last_save': datetime.datetime.now().isoformat()
        }
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=4)
        except:
            pass
    
    @tasks.loop(seconds=60)
    async def keep_alive(self):
        """Поддерживаем активность бота"""
        try:
            # Обновляем время для всех в голосовом канале
            current_time = datetime.datetime.now()
            for user_id, join_dt in list(self.join_time.items()):
                if isinstance(join_dt, str):
                    join_dt = datetime.datetime.fromisoformat(join_dt)
                time_spent = (current_time - join_dt).total_seconds()
                self.voice_time[user_id] = self.voice_time.get(user_id, 0) + time_spent
                self.join_time[user_id] = current_time
            
            # Показываем статус каждые 30 минут
            if datetime.datetime.now().minute % 30 == 0:
                logging.info("Бот активен. Войс клиентов: " + str(len(self.bot.voice_clients)))
                
        except Exception as e:
            logging.error(f"Ошибка в keep_alive: {e}")
    
    @tasks.loop(seconds=10)
    async def auto_reconnect(self):
        """Автоматическое подключение к голосовому каналу"""
        try:
            # Если бот не в голосовом канале
            if not self.bot.voice_clients:
                guild = self.bot.get_guild(GUILD_ID)
                if guild:
                    channel = guild.get_channel(TARGET_CHANNEL_ID)
                    if channel and isinstance(channel, discord.VoiceChannel):
                        try:
                            await channel.connect()
                            logging.info(f"✅ Подключился к {channel.name}")
                            self.reconnect_attempts = 0
                            
                            # Восстанавливаем время для пользователей в канале
                            for member in channel.members:
                                if not member.bot:
                                    self.join_time[str(member.id)] = datetime.datetime.now()
                            
                        except discord.errors.ClientException:
                            # Бот уже подключен где-то еще
                            pass
                        except Exception as e:
                            self.reconnect_attempts += 1
                            if self.reconnect_attempts % 10 == 0:
                                logging.warning(f"Не могу подключиться (попытка {self.reconnect_attempts}): {e}")
            
            # Проверяем качество соединения
            for vc in self.bot.voice_clients:
                if vc.is_connected():
                    # Периодически проверяем соединение
                    if datetime.datetime.now().second % 30 == 0:
                        # Отправляем тихий пакет для поддержания соединения
                        if vc.ws:
                            try:
                                await vc.ws.keep_alive()
                            except:
                                pass
            
        except Exception as e:
            logging.error(f"Ошибка в auto_reconnect: {e}")
    
    @tasks.loop(minutes=1)
    async def auto_save(self):
        """Автосохранение данных"""
        try:
            self.save_data()
            # Каждые 5 минут логируем
            if datetime.datetime.now().minute % 5 == 0:
                logging.info("💾 Данные сохранены")
                total_time = sum(self.voice_time.values())
                hours = total_time / 3600
                logging.info(f"📊 Всего времени накоплено: {hours:.1f} часов")
        except Exception as e:
            logging.error(f"Ошибка автосохранения: {e}")
    
    @tasks.loop(minutes=5)
    async def check_afk(self):
        """Проверка AFK статуса и переподключение если нужно"""
        try:
            for vc in self.bot.voice_clients:
                if vc.is_connected():
                    # Если канал пустой дольше 5 минут, переподключаемся
                    if len(vc.channel.members) <= 1:  # Только бот
                        if (datetime.datetime.now() - self.last_afk_check).seconds > 300:
                            logging.info("Канал пустой, проверяю соединение...")
                            await vc.disconnect()
                            await asyncio.sleep(2)
                    else:
                        self.last_afk_check = datetime.datetime.now()
        except Exception as e:
            logging.error(f"Ошибка в check_afk: {e}")
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Отслеживание голосовой активности"""
        if member.bot:
            return
            
        user_id = str(member.id)
        
        # Пользователь зашел в войс
        if after.channel and after.channel.id == TARGET_CHANNEL_ID:
            self.join_time[user_id] = datetime.datetime.now()
            logging.info(f'❤️ {member.name} присоединился к вам')
            
            # Приветственное сообщение (только раз в 10 минут)
            if not hasattr(self, 'last_greeting'):
                self.last_greeting = {}
            
            now = datetime.datetime.now()
            if user_id not in self.last_greeting or (now - self.last_greeting.get(user_id, now)).seconds > 600:
                try:
                    # Отправляем в текстовый канал
                    for channel in member.guild.text_channels:
                        if channel.permissions_for(member.guild.me).send_messages:
                            await channel.send(f"💖 Привет, {member.mention}! Рад видеть тебя снова!")
                            self.last_greeting[user_id] = now
                            break
                except:
                    pass
        
        # Пользователь вышел из войса
        elif before.channel and before.channel.id == TARGET_CHANNEL_ID:
            if user_id in self.join_time:
                join_dt = self.join_time[user_id]
                if isinstance(join_dt, str):
                    join_dt = datetime.datetime.fromisoformat(join_dt)
                
                time_spent = (datetime.datetime.now() - join_dt).total_seconds()
                self.voice_time[user_id] = self.voice_time.get(user_id, 0) + time_spent
                
                # Сохраняем сразу
                self.save_data()
                
                # Логируем
                hours = time_spent / 3600
                minutes = (time_spent % 3600) / 60
                logging.info(f'💕 {member.name} провел(а) с вами: {int(hours)}ч {int(minutes)}м')
                
                del self.join_time[user_id]

@bot.event
async def on_ready():
    logging.info(f'💖 Бот {bot.user.name} готов к романтическому общению!')
    logging.info(f'ID бота: {bot.user.id}')
    logging.info(f'Сервер ID: {GUILD_ID}')
    logging.info(f'Целевой канал ID: {TARGET_CHANNEL_ID}')
    
    # Устанавливаем статус
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="вашу любовь 💕"
        )
    )
    
    # Пытаемся сразу подключиться к каналу
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if channel:
                await channel.connect()
                logging.info(f"✅ Соединение установлено с каналом: {channel.name}")
                
                # Восстанавливаем время для тех, кто уже в канале
                cog = bot.get_cog('LoveBot')
                if cog:
                    for member in channel.members:
                        if not member.bot:
                            cog.join_time[str(member.id)] = datetime.datetime.now()
    except Exception as e:
        logging.warning(f"Не удалось сразу подключиться: {e}")

@bot.command(name='время')
async def time_command(ctx):
    """Показать сколько времени вы провели вместе"""
    cog = bot.get_cog('LoveBot')
    if not cog:
        await ctx.send("Система еще не готова, подождите немного...")
        return
    
    user_id = str(ctx.author.id)
    total_time = cog.voice_time.get(user_id, 0)
    
    # Добавляем текущую сессию если она есть
    if user_id in cog.join_time:
        join_dt = cog.join_time[user_id]
        if isinstance(join_dt, str):
            join_dt = datetime.datetime.fromisoformat(join_dt)
        current_session = (datetime.datetime.now() - join_dt).total_seconds()
        total_time += current_session
    
    # Рассчет времени
    days = int(total_time // (24 * 3600))
    hours = int((total_time % (24 * 3600)) // 3600)
    minutes = int((total_time % 3600) // 60)
    
    # Создаем красивый embed
    embed = discord.Embed(
        title="💖 Ваше время вместе",
        color=discord.Color.from_rgb(255, 105, 180)  # Розовый цвет
    )
    
    if days > 0:
        time_text = f"{days} дней {hours} часов {minutes} минут"
    else:
        time_text = f"{hours} часов {minutes} минут"
    
    embed.add_field(
        name=f"С {ctx.author.display_name}",
        value=f"**{time_text}**\n\n"
              f"Это примерно:\n"
              f"• {days*24 + hours} полных часов\n"
              f"• {int(total_time/60):,} минут\n"
              f"• {int(total_time):,} секунд",
        inline=False
    )
    
    # Расчет процентов
    total_seconds_in_month = 30 * 24 * 3600  # 30 дней
    percentage = (total_time / total_seconds_in_month) * 100
    
    embed.add_field(
        name="📊 Статистика",
        value=f"Вы провели **{percentage:.1f}%** времени этого месяца вместе!",
        inline=False
    )
    
    # Романтическое сообщение
    if total_time > 3600:  # Больше часа
        messages = [
            "Каждая минута с тобой — это счастье! 💕",
            "Время летит незаметно, когда мы вместе! ⏰❤️",
            "Это только начало нашей прекрасной истории! 📖✨",
            "С каждым часом моя любовь к тебе только крепнет! 🌹",
            "Ты делаешь каждую секунду особенной! 🌟"
        ]
        embed.set_footer(text=messages[hash(user_id) % len(messages)])
    
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command(name='статус')
async def status_command(ctx):
    """Показать статус бота"""
    cog = bot.get_cog('LoveBot')
    
    embed = discord.Embed(
        title="🤖 Статус бота любви",
        color=discord.Color.green()
    )
    
    # Информация о соединении
    if bot.voice_clients:
        vc = bot.voice_clients[0]
        status = "✅ Подключен"
        channel_info = f"Канал: {vc.channel.name}"
        members = len([m for m in vc.channel.members if not m.bot])
        channel_info += f"\nЛюдей в канале: {members}"
    else:
        status = "🔄 Подключаюсь..."
        channel_info = f"Канал ID: {TARGET_CHANNEL_ID}"
    
    embed.add_field(name="Голосовое соединение", value=f"{status}\n{channel_info}", inline=False)
    
    # Статистика
    if cog:
        total_users = len(cog.voice_time)
        active_now = len(cog.join_time)
        
        total_seconds = sum(cog.voice_time.values())
        total_hours = total_seconds / 3600
        
        embed.add_field(name="📊 Статистика", 
                       value=f"Отслеживается: {total_users} чел.\n"
                             f"Сейчас активны: {active_now} чел.\n"
                             f"Всего времени: {total_hours:.1f} часов", 
                       inline=True)
    
    # Системная информация
    embed.add_field(name="⚙️ Система", 
                   value=f"Пинг: {round(bot.latency * 1000)}мс\n"
                         f"Серверов: {len(bot.guilds)}\n"
                         f"Время работы: {str(datetime.datetime.now() - bot.start_time).split('.')[0]}", 
                   inline=True)
    
    # Романтичный факт
    facts = [
        "Любовь измеряется не временем, а мгновениями! 💫",
        "Каждая секунда с любимым — это подарок судьбы! 🎁",
        "Настоящая любовь только крепчает со временем! 💕",
        "Время, проведенное с тобой, бесценно! ⏳❤️"
    ]
    embed.set_footer(text=facts[hash(str(ctx.author.id)) % len(facts)])
    
    await ctx.send(embed=embed)

@bot.command(name='сброс')
@commands.has_permissions(administrator=True)
async def reset_command(ctx):
    """Сбросить статистику (только для администратора)"""
    cog = bot.get_cog('LoveBot')
    if cog:
        cog.voice_time = {}
        cog.save_data()
        await ctx.send("✅ Статистика сброшена! Начинаем новую историю любви! 💖")
    else:
        await ctx.send("❌ Не удалось сбросить статистику")

@bot.event
async def on_disconnect():
    logging.warning("🔌 Бот отключился от Discord")
    cog = bot.get_cog('LoveBot')
    if cog:
        cog.save_all_data()

@bot.event
async def on_resumed():
    logging.info("🔁 Бот восстановил соединение")
    # Пытаемся переподключиться к голосовому каналу
    await asyncio.sleep(2)
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild and not bot.voice_clients:
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if channel:
                await channel.connect()
    except:
        pass

# Обработка завершения
import atexit
import signal

def cleanup():
    logging.info("💾 Сохранение данных перед выходом...")
    if 'bot' in globals():
        cog = bot.get_cog('LoveBot')
        if cog:
            cog.save_all_data()
    logging.info("👋 Бот завершает работу")

atexit.register(cleanup)

# Запуск бота
async def main():
    async with bot:
        await bot.add_cog(LoveBot(bot))
        bot.start_time = datetime.datetime.now()
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    # Обработка Ctrl+C
    import signal as sig
    import asyncio as aio
    
    def signal_handler(signum, frame):
        print("\n💕 Получен сигнал завершения...")
        aio.get_event_loop().create_task(shutdown())
    
    async def shutdown():
        logging.info("Завершение работы...")
        cog = bot.get_cog('LoveBot')
        if cog:
            cog.save_all_data()
        await bot.close()
    
    sig.signal(sig.SIGINT, signal_handler)
    sig.signal(sig.SIGTERM, signal_handler)
    
    try:
        aio.run(main())
    except KeyboardInterrupt:
        print("\n💖 Бот завершает работу...")
    finally:
        cleanup()

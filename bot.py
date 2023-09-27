import discord
from discord.ext import commands, tasks
import yt_dlp
import os
import logging
import sys
import asyncio
import random
import string
import requests

# Code made by: spyflow
# Discord: spyflow
# GitHub: https://github.com/spyflow
# Contact: contact.spyflow@spyflow.net

intents = discord.Intents.default()
intents.typing = False
intents.presences = True
intents.message_content = True
inactive_time = 300
bot = commands.Bot(command_prefix='!', intents=intents)
queue = []  # Playlist
sname = []  # List of song names
current_song = None  # Currently playing song
inactive_timer = None  # Inactivity timer
ufo = "idle"

# Initialize the yt-dlp downloader
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': 'music/%(id)s',  # Nombre de archivo de salida
}

ydl = yt_dlp.YoutubeDL(ydl_opts)

# Configure the logger
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
logger.addHandler(handler)


# Search for a video on YouTube
def searchinyt(prompt):
    # Parámetros de búsqueda
    api_key = 'YOUR_YOUTUBE_V3_API_KEY'
    params = {
        'q': prompt,
        'part': 'snippet',
        'type': 'video',
        'key': api_key,
    }

    # URL de la API de YouTube
    url = 'https://www.googleapis.com/youtube/v3/search'

    # Realiza la solicitud a la API de YouTube
    response = requests.get(url, params=params)

    # Comprueba si la solicitud fue exitosa
    if response.status_code == 200:
        data = response.json()

        # Verifica si hay resultados
        if 'items' in data and len(data['items']) > 0:
            # Obtén el enlace del primer resultado
            first_video_id = data['items'][0]['id']['videoId']
            video_link = f'https://www.youtube.com/watch?v={first_video_id}'
            return video_link

    return None


@bot.event
async def on_ready():
    logger.info(f'Connected as {bot.user.name}')
    await update_presence.start()

@tasks.loop(seconds=15)
async def update_presence():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,  # Change the type to 'listening'
            name=ufo
        )
    )

@bot.event
async def on_command(ctx):
    author = ctx.author
    command = ctx.command
    logger.info(f'Command "{command.name}" used by {author.name}#{author.discriminator}')

@bot.command()
async def play(ctx, *args):
    global current_song  # Declared as a global variable
    global channel

    voice_channel = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_channel is not None and voice_channel.channel != ctx.author.voice.channel:
        await ctx.send('I am already connected to a different voice channel.')
        return

    if not (voice_channel and voice_channel.is_connected()):
        channel = ctx.message.author.voice.channel
        voice_channel = await channel.connect()
        logger.info(f'Bot joined voice channel: {channel.name}')

    # Join all the words provided in the input into a single search query
    search_query = ' '.join(args)

    try:
        # Check if the input looks like a URL
        if search_query.startswith('http'):
            url = search_query
        else:
            # If not a URL, use searchinyt to search for the video
            url = searchinyt(search_query)

        ydl = yt_dlp.YoutubeDL(ydl_opts)
        info_dict = ydl.extract_info(url, download=True)

        # Create a random 5-letter text called atext
        atext = "".join(random.choice(string.ascii_letters) for _ in range(5))

        # renames the file to id+atext.mp3
        os.rename(f'music/{info_dict["id"]}.mp3', f'music/{info_dict["id"]}{atext}.mp3')

        song_name = info_dict['title']  # Get the song's name
        file_path = f'music/{info_dict["id"]}{atext}.mp3'  # Get the file path

        queue.append(file_path)
        sname.append(song_name)

        if not current_song:
            play_next_song(voice_channel, ctx)  # Pass ctx as a parameter to the play_next_song function

        logger.info(f'Added to queue: {song_name}')

        # If there is a song playing, send a message that it has been added to the queue
        if len(queue) >= 1:
            await ctx.send(f'Added to queue: {song_name}')
    except Exception as e:
        logger.warning(f'Error playing the song: {str(e)}')

@bot.command()
async def skip(ctx):
    if current_song:
        voice_channel = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        voice_channel.stop()
        logger.info('Song skipped')
        await ctx.send('Song skipped')

@bot.command()
async def leave(ctx):
    voice_channel = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_channel.is_connected():
        await voice_channel.disconnect()
        queue.clear()
        sname.clear()
        current_song = None
        if inactive_timer:
            inactive_timer.cancel()
        logger.info('Disconnected due to command')
        await ctx.send('Disconnected')

@bot.command()
async def ping(ctx):
    voice_channel = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_channel and voice_channel.is_connected():
        latency = voice_channel.latency * 1000  # Latency in milliseconds
        await ctx.send(f'Current latency: {latency:.2f} ms')
        # If the latency is greater than 100, send a message that the latency is high
        if latency > 100:
            await ctx.send(f'Latency is very high')
            logger.warning(f'Latency is high "{latency:.2f} ms"')
    else:
        await ctx.send('I am not connected to any voice channel.')

@bot.command()
async def author(ctx):
    await ctx.send('Author: <@!533093302031876096>')

@bot.command()
async def autor(ctx):
    await ctx.send('Author: <@!533093302031876096>')

def cleanup(file_path):
    #os.remove(file_path)
    logger.info(f'File deleted: {file_path}')

def play_next_song(voice_channel, ctx):
    global current_song  # Declare as a global variable
    global inactive_timer  # Declare as a global variable
    global ufo # Declare as a global variable

    if queue:
        file_path = queue.pop(0) # Get the first file in the queue
        ufo = sname[0]
        song_name = sname.pop(0) # Get the first song name in the queue
        current_song = file_path # Set the current song

        voice_channel.play(discord.FFmpegPCMAudio(file_path), after=lambda e: song_finished(file_path, ctx))  # Pass ctx as a parameter
        logger.info(f'Playing song: {file_path}: {song_name}') # Log the song's name
        asyncio.run_coroutine_threadsafe(ctx.send(f'Playing song: {song_name}'), bot.loop) # Send a message that the song is playing
        # Reset the inactivity timer
        if inactive_timer:
            inactive_timer.cancel() # Cancel the timer
        inactive_timer = bot.loop.call_later(inactive_time, check_inactive, voice_channel, ctx) # Pass ctx as a parameter
    else:
        current_song = None # Reset the current song
        ufo = "idle"

def song_finished(file_path, ctx):  # Add ctx as a parameter
    cleanup(file_path)
    logger.info(f'Song finished: {file_path}')

    # Continue playing the next song in the queue
    voice_channel = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    play_next_song(voice_channel, ctx)  # Pass ctx as a parameter

def check_inactive(voice_channel, ctx):
    global current_song  # Declare as a global variable

    # Disconnect from the voice channel due to inactivity
    if not current_song:
        voice_channel.stop()
        asyncio.run_coroutine_threadsafe(voice_channel.disconnect(), bot.loop)
        logger.info('Disconnected due to inactivity')
        asyncio.run_coroutine_threadsafe(ctx.send('Disconnected due to inactivity'), bot.loop)

# Start
bot.run('YOUR_BOT_TOKEN')

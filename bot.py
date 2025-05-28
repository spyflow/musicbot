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
import dotenv
import shutil

# Code made by: spyflow
# Discord: spyflow
# GitHub: https://github.com/spyflow
# Contact: contact.spyflow@spyflow.net

# --- Bot Configuration ---
intents = discord.Intents.default()  # Default intents
intents.typing = False  # Disable typing events to reduce unnecessary load
intents.presences = True  # Enable presence updates (for bot's status)
intents.message_content = True  # Enable message content access (required for commands)

inactive_time = 300  # Time in seconds before the bot disconnects due to inactivity
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Guild Player State Management ---
class GuildPlayerState:
    """Encapsulates all playback-related state for a single guild."""
    def __init__(self, guild_id: int, bot_instance: commands.Bot):
        self.guild_id: int = guild_id
        self.bot: commands.Bot = bot_instance # Used for scheduling tasks like timers
        self.queue: list[str] = []  # List of file paths for songs
        self.song_titles: list[str] = []  # List of song titles corresponding to the queue
        self.current_song_path: str | None = None  # File path of the currently playing song
        self.current_song_title: str | None = None # Title of the currently playing song
        self.inactive_timer: asyncio.TimerHandle | None = None  # Timer for inactivity disconnect
        self.voice_client: discord.VoiceClient | None = None  # The voice client for this guild
        self.last_ctx: commands.Context | None = None  # Last command context for sending messages

    def __repr__(self):
        return (f"<GuildPlayerState guild_id={self.guild_id} "
                f"queue_len={len(self.queue)} "
                f"vc_connected={'Yes' if self.voice_client and self.voice_client.is_connected() else 'No'}>")

guild_states: dict[int, GuildPlayerState] = {}

def get_or_create_guild_state(ctx: commands.Context) -> GuildPlayerState:
    """
    Retrieves or creates the GuildPlayerState for the guild associated with the context.
    Updates last_ctx for existing states.
    """
    guild_id = ctx.guild.id
    if guild_id not in guild_states:
        logger.info(f"Creating new GuildPlayerState for guild ID: {guild_id} ({ctx.guild.name})")
        guild_states[guild_id] = GuildPlayerState(guild_id=guild_id, bot_instance=bot)
    
    # Always update last_ctx to ensure messages are sent to the most recent relevant channel.
    # Also ensures the bot instance is current if it were to change (though it doesn't in this app's lifecycle).
    guild_states[guild_id].last_ctx = ctx
    guild_states[guild_id].bot = bot # Ensure bot instance is up-to-date (mostly for completeness)
    return guild_states[guild_id]

# --- YouTube Downloader Configuration ---
# Options for the yt-dlp library, which handles downloading audio from YouTube.
ydl_opts = {
    'format': 'bestaudio/best',  # Select the best audio-only format.
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',  # Use FFmpeg to extract audio.
        'preferredcodec': 'mp3',  # Convert the audio to MP3 format.
        'preferredquality': '192',  # Set preferred audio quality to 192 kbps.
    }],
    # 'outtmpl': 'music/%(id)s.%(ext)s', # Removed: To be set dynamically per guild.
    'noplaylist': True,  # Disable downloading entire playlists if a playlist URL is given.
    'quiet': True, # Suppress yt-dlp console output unless there are errors.
    'default_search': 'ytsearch', # Use ytsearch for non-URL queries.
}

# ydl = yt_dlp.YoutubeDL(ydl_opts) # Removed: Instance will be created per download.

# --- Logging Configuration ---
# Standard Python logging setup.
logger = logging.getLogger('discord')  # Get the logger instance used by discord.py.
logger.setLevel(logging.INFO)  # Set the minimum log level to INFO.
handler = logging.StreamHandler(sys.stdout)  # Create a handler to output logs to standard output.
# You could also use logging.FileHandler("bot.log") to write to a file.
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s') # Define log message format.
handler.setFormatter(formatter)
logger.addHandler(handler)  # Add the configured handler to the logger.

# --- Environment Variable Loading ---
# Load API keys and tokens from a .env file for security and configurability.
dotenv.load_dotenv()
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')

# Critical check: Ensure API keys are loaded. Exit if not.
if not YOUTUBE_API_KEY:
    logger.critical("CRITICAL: YOUTUBE_API_KEY not found in environment variables. The bot cannot search videos.")
    sys.exit("Exiting: YOUTUBE_API_KEY not set. Please check your .env file or environment variables.")

if not DISCORD_BOT_TOKEN:
    logger.critical("CRITICAL: DISCORD_BOT_TOKEN not found in environment variables. The bot cannot connect to Discord.")
    sys.exit("Exiting: DISCORD_BOT_TOKEN not set. Please check your .env file or environment variables.")

# Create music directory if it doesn't exist
if not os.path.exists('music'):
    os.makedirs('music')
    logger.info("Created 'music' directory for storing downloaded songs.")


# --- YouTube Search Function ---
def search_youtube(prompt: str):
    """
    Searches for a video on YouTube using the YouTube Data API v3.

    Args:
        prompt (str): The search query provided by the user.

    Returns:
        str | None: The URL of the first video result if found, otherwise None.
    """
    if not prompt: # Basic validation
        logger.warning("search_youtube called with an empty prompt.")
        return None

    logger.info(f"Searching YouTube for: '{prompt}'")
    params = {
        'q': prompt,  # The search query.
        'part': 'snippet',  # Specifies that the API response should include the video's snippet.
        'type': 'video',  # Restrict search results to videos only.
        'key': YOUTUBE_API_KEY,  # Your YouTube Data API key.
        'maxResults': 1  # We only need the first result.
    }
    youtube_api_url = 'https://www.googleapis.com/youtube/v3/search'

    try:
        response = requests.get(youtube_api_url, params=params, timeout=5) # Added timeout
        response.raise_for_status()  # Raise an HTTPError for bad responses (4XX or 5XX).
        data = response.json()

        if data.get('items'): # Check if 'items' key exists and is not empty.
            first_video_id = data['items'][0]['id']['videoId']
            video_link = f'https://www.youtube.com/watch?v={first_video_id}'
            logger.info(f"YouTube search successful for '{prompt}', found video ID: {first_video_id}")
            return video_link
        else:
            logger.warning(f"No video items found in YouTube API response for prompt: '{prompt}'. Response: {data}")
            return None
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred during YouTube search for '{prompt}': {http_err} - Response: {response.text}")
        return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Request error occurred during YouTube search for '{prompt}': {req_err}")
        return None
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"An unexpected error occurred in search_youtube for prompt '{prompt}': {e}", exc_info=True)
        return None


# --- Discord Bot Event Handlers ---
@bot.event
async def on_ready():
    """
    Event handler triggered when the bot successfully connects to Discord and is ready.
    This is typically used for initialization tasks.
    """
    logger.info(f'Bot connected as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f"Bot is ready and listening on {len(bot.guilds)} server(s).")
    if not update_presence.is_running(): # Ensure task isn't started multiple times on reconnect
        update_presence.start()  # Start the periodic task to update the bot's presence.


@tasks.loop(seconds=15)
async def update_presence():
    """
    Periodic task that updates the bot's Discord presence (its activity status).
    Runs every 15 seconds to show what the bot is "listening to".
    """
    activity_type = discord.ActivityType.listening
    # Ensures current_activity_name is not excessively long for presence.
    # activity_name = current_activity_name[:128] if current_activity_name else "nothing"
    # New generic presence:
    activity = discord.Activity(type=discord.ActivityType.listening, name="music via !play")
    # Alternative dynamic presence:
    # activity = discord.Activity(type=discord.ActivityType.playing, name=f"music on {len(bot.guilds)} servers")

    try:
        await bot.change_presence(activity=activity)
        logger.debug(f"Presence updated to: {activity.name}")
    except Exception as e: # Catch potential errors during presence update
        logger.warning(f"Could not update presence: {e}")


@bot.event
async def on_command(ctx: commands.Context):
    """
    Event handler triggered whenever a command is invoked by a user.
    This is used here for logging command usage.
    """
    if ctx.command is not None:  # Ensure it's a recognized command and not just a message.
        guild_name = ctx.guild.name if ctx.guild else "Direct Message"
        guild_id = ctx.guild.id if ctx.guild else "N/A"
        logger.info(
            f'Command "{ctx.command.name}" invoked by {ctx.author.name}#{ctx.author.discriminator} (ID: {ctx.author.id}) '
            f'in guild "{guild_name}" (ID: {guild_id})'
        )
    # If you wanted to log all messages that might be commands (even if invalid), you'd log outside the if.


# --- Discord Bot Commands ---
@bot.command(name='play', help='Plays a song from YouTube (URL or search query). Usage: !play <song name or URL>')
async def play(ctx: commands.Context, *, search_query: str = ""): # Use * to consume all arguments as a single search_query string
    """
    Command to play a song from YouTube.
    Accepts a direct YouTube URL or a search query to find a video.
    Downloads the audio, adds it to a queue, and starts playback if not already playing.

    Args:
        ctx (commands.Context): The context of the command.
        search_query (str): The song name or YouTube URL provided by the user.
    """
    guild_state = get_or_create_guild_state(ctx)
    # 'channel' for voice connection is managed by voice_client from ctx or new connection.

    if not search_query:
        await ctx.send("Please provide a song name or YouTube URL after the `!play` command. Usage: `!play <song name or URL>`")
        return

    # Ensure the user who invoked the command is in a voice channel.
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You are not connected to a voice channel. Please join one to play music.")
        return

    user_voice_channel = ctx.author.voice.channel
    # Use guild_state.voice_client
    if guild_state.voice_client and guild_state.voice_client.channel != user_voice_channel:
        await ctx.send(f"I am already in a different voice channel: '{guild_state.voice_client.channel.name}'.")
        return

    # Connect to the user's voice channel if not already connected.
    if not guild_state.voice_client or not guild_state.voice_client.is_connected():
        try:
            # Disconnect if connected to a different channel or in a broken state
            if guild_state.voice_client:
                logger.info(f"Found existing voice client for guild {ctx.guild.id}, ensuring it's disconnected before reconnecting.")
                await guild_state.voice_client.disconnect(force=True)
                guild_state.voice_client = None

            guild_state.voice_client = await user_voice_channel.connect()
            logger.info(f"Bot joined voice channel: '{user_voice_channel.name}' in guild '{ctx.guild.name}'.")
        except discord.ClientException as e:
            logger.error(f"Error connecting to voice channel '{user_voice_channel.name}': {e}")
            guild_state.voice_client = None # Ensure it's None on failure
            await ctx.send(f"Could not join your voice channel. Error: {e}")
            return
    else: # Bot is already in the correct voice channel
        logger.info(f"Bot is already in voice channel: '{guild_state.voice_client.channel.name}'.")


    # Determine if the input is a URL or a search query.
    url_to_download = ""
    if search_query.startswith('http://') or search_query.startswith('https://'):
        url_to_download = search_query
        logger.info(f"Direct URL provided for download: {url_to_download}")
    else:
        # User provided a search query, not a direct URL.
        await ctx.send(f"Searching for '{search_query}' on YouTube...") # Provide feedback
        url_to_download = search_youtube(search_query) # This function now logs its own errors/warnings.
        if url_to_download:
            logger.info(f"YouTube search for '{search_query}' found URL: {url_to_download}")

    if not url_to_download:
        await ctx.send(f"Could not find a video for: '{search_query}'. Please try a different search term or URL.")
        return

    # Guild-specific download path setup
    guild_id = str(ctx.guild.id)
    guild_id = str(ctx.guild.id)
    guild_music_dir = os.path.join('music', guild_id)
    os.makedirs(guild_music_dir, exist_ok=True) # Ensure guild_music_dir is created early

    info_dict = None
    file_path_to_play = None 
    title_to_play = None

    try:
        # Step 1: Extract info (no download)
        info_ydl_opts = ydl_opts.copy()
        info_ydl_opts['noplaylist'] = True
        info_ydl_opts['quiet'] = True
        info_ydl_opts.pop('postprocessors', None) # Avoid full processing for info extraction

        logger.info(f"Extracting video information for: {url_to_download}")
        with yt_dlp.YoutubeDL(info_ydl_opts) as ydl_info_extractor:
            try:
                pre_info_dict = ydl_info_extractor.extract_info(url_to_download, download=False)
            except Exception as e:
                logger.error(f"Failed to extract initial video info for {url_to_download}: {e}")
                await ctx.send(f"Error: Could not fetch initial information for the song. It might be an invalid link or network issue.")
                return
        
        video_id = pre_info_dict.get('id')
        if not video_id:
            logger.error(f"Could not determine video ID for {url_to_download} from pre-extraction.")
            await ctx.send("Error: Could not determine video ID before download.")
            return
            
        title_to_play = pre_info_dict.get('title', 'Unknown Title')
        expected_ext = 'mp3' # Expected extension after postprocessing
        potential_cached_path = os.path.join(guild_music_dir, f"{video_id}.{expected_ext}") 

        # Step 2: Check cache
        if os.path.exists(potential_cached_path):
            logger.info(f"Cache hit: Using existing file {potential_cached_path} for video ID {video_id}")
            file_path_to_play = potential_cached_path
            info_dict = pre_info_dict # Use the info we already fetched
            await ctx.send(f"Found '{title_to_play}' in cache. Adding to queue.")
        else:
            logger.info(f"Cache miss for video ID {video_id} ('{title_to_play}'). Proceeding with download.")
            await ctx.send(f"Downloading audio for '{title_to_play}' ({url_to_download})... This may take a moment.")
            
            # Step 3: Download if not in cache
            download_opts = ydl_opts.copy() 
            download_opts['outtmpl'] = os.path.join(guild_music_dir, '%(id)s.%(ext)s')
            # Ensure postprocessors are present for actual download and conversion
            if 'postprocessors' not in download_opts: # Should be inherited from global ydl_opts
                 download_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            
            with yt_dlp.YoutubeDL(download_opts) as ydl_downloader:
                info_dict_download = ydl_downloader.extract_info(url_to_download, download=True)

            # Path determination logic (from previous implementation)
            song_title_download = info_dict_download.get('title', title_to_play) # Prefer download title
            video_id_download = info_dict_download.get('id', video_id) # Prefer download ID
            
            expected_dl_path = os.path.join(guild_music_dir, f"{video_id_download}.mp3")
            actual_final_path = None

            if 'requested_downloads' in info_dict_download and info_dict_download['requested_downloads']:
                rd_info = info_dict_download['requested_downloads'][0]
                if 'filepath' in rd_info and os.path.exists(rd_info['filepath']):
                    actual_final_path = rd_info['filepath']
                    logger.info(f"Using actual file path from info_dict_download['requested_downloads']: {actual_final_path}")

            if actual_final_path:
                file_path_to_play = actual_final_path
            elif os.path.exists(expected_dl_path):
                file_path_to_play = expected_dl_path
                logger.info(f"Using expected file path after download: {file_path_to_play}")
            else:
                original_ext = info_dict_download.get('ext')
                original_file_path = os.path.join(guild_music_dir, f"{video_id_download}.{original_ext}")
                if original_ext and original_ext != 'mp3' and os.path.exists(original_file_path):
                    file_path_to_play = original_file_path
                    logger.warning(f"MP3 not found at {expected_dl_path} after download. Using file with original extension: {file_path_to_play}")
                else:
                    logger.error(f"Critical: Downloaded file for {video_id_download} not found at {expected_dl_path} or with original extension {original_file_path} after download.")
                    await ctx.send(f"Error: Could not locate the downloaded file for '{song_title_download}' after download.")
                    return

            if not file_path_to_play or not os.path.exists(file_path_to_play):
                 logger.error(f"Failed to locate file after download for {video_id_download}")
                 await ctx.send(f"Error: Could not locate file for '{song_title_download}' after download.")
                 return
            
            info_dict = info_dict_download # Use the full info from download
            title_to_play = song_title_download # Update title from download info

            logger.info(f"Final file path after download set to: {file_path_to_play} for video ID {video_id_download}")
            logger.info(f"Download complete for '{title_to_play}'. File saved to: {file_path_to_play}")

        # Step 4: Common logic to add to queue
        if file_path_to_play and title_to_play:
            logger.info(f"Adding to queue: '{title_to_play}' from {file_path_to_play}")
            guild_state.queue.append(file_path_to_play)
            guild_state.song_titles.append(title_to_play)
            await ctx.send(f"Added to queue: '{title_to_play}'") # Message now reflects cached or downloaded
            
            if not guild_state.current_song_path and guild_state.voice_client and guild_state.voice_client.is_connected():
                play_next_song(guild_state)
            elif not guild_state.voice_client or not guild_state.voice_client.is_connected(): # This condition might be redundant if play_next_song handles it
                logger.warning("File added to queue, but voice client is not connected. Cannot start playback.")
                await ctx.send("I'm not connected to a voice channel anymore. Please use !leave and !play again if needed.")
        else:
            # This case should ideally not be reached if video_id and title_to_play are always determined.
            logger.error(f"file_path_to_play or title_to_play not set. Cannot add to queue. Video ID: {video_id if video_id else 'unknown'}")
            await ctx.send("An error occurred: could not determine song details to add to queue.")

        # If no song is currently playing and the bot is connected, start playback.
        if not guild_state.current_song_path and guild_state.voice_client and guild_state.voice_client.is_connected():
            play_next_song(guild_state) # Pass guild_state
        elif not guild_state.voice_client or not guild_state.voice_client.is_connected():
            logger.warning("Download complete but voice client is not connected. Cannot start playback.")
            await ctx.send("I'm not connected to a voice channel anymore. Please use !leave and !play again.")


    except yt_dlp.utils.DownloadError as e:
        # Specific error handling for yt-dlp download issues.
        logger.error(f"yt-dlp download error for '{url_to_download}': {str(e)}")
        await ctx.send(f"Error downloading the song. It might be region-locked, private, deleted, or an invalid link.")
    except Exception as e:
        # General error handling for other issues during the play command.
        logger.error(f"Unexpected error in play command for query '{search_query}': {e}", exc_info=True)
        await ctx.send(f"An unexpected error occurred while trying to process your request.")


@bot.command(name='skip', help='Skips the currently playing song.')
async def skip(ctx: commands.Context):
    """
    Command to skip the currently playing song.
    It stops the current playback, which then triggers the 'after' callback
    (song_finished) in `voice_client.play` to play the next song or handle queue end.
    """
    guild_state = get_or_create_guild_state(ctx)
    voice_client = guild_state.voice_client # Use voice_client from guild_state

    if voice_client and voice_client.is_playing():
        logger.info(f"Skip command invoked by {ctx.author.name} for guild {ctx.guild.id}. Stopping current song.")
        voice_client.stop()  # Stopping playback triggers song_finished.
        await ctx.send('Song skipped.')
    elif voice_client and not voice_client.is_playing() and guild_state.current_song_path:
        # This case handles if playback somehow stopped but state wasn't cleared.
        logger.info(f"Skip command for guild {ctx.guild.id}: Nothing actively playing, but a song ('{guild_state.current_song_path}') was marked as current. Attempting to advance queue.")
        play_next_song(guild_state) # This will clear current_song_path if queue is empty or play next.
        await ctx.send('Trying to play the next song as current one was stuck...')
    else:
        await ctx.send('No song is currently playing to skip.')


@bot.command(name='leave', help='Makes the bot leave the voice channel and clears the song queue.')
async def leave(ctx: commands.Context):
    """
    Command for the bot to leave the voice channel for this guild.
    It also clears the song queue and resets related playback state for the guild.
    """
    guild_state = get_or_create_guild_state(ctx)
    voice_client = guild_state.voice_client

    if voice_client and voice_client.is_connected():
        logger.info(f"Bot leaving voice channel '{voice_client.channel.name}' in guild '{ctx.guild.name}' due to 'leave' command by {ctx.author.name}.")
        await voice_client.disconnect()
        guild_state.voice_client = None # Important to nullify after disconnect

        # Clear queue and reset guild-specific playback state.
        guild_state.queue.clear()
        guild_state.song_titles.clear()
        guild_state.current_song_path = None
        guild_state.current_song_title = None # Reset activity name for this guild's context
        if guild_state.inactive_timer:
            guild_state.inactive_timer.cancel()
            guild_state.inactive_timer = None
            logger.info(f"Inactivity timer for guild {ctx.guild.id} cancelled due to 'leave' command.")
        
        await ctx.send('Disconnected from voice channel and cleared the song queue for this server.')

        # Delete guild-specific cache directory
        guild_id_str = str(guild_state.guild_id) # Use guild_state.guild_id for consistency
        guild_music_dir = os.path.join('music', guild_id_str)

        if os.path.exists(guild_music_dir):
            try:
                shutil.rmtree(guild_music_dir)
                logger.info(f"Successfully deleted cache directory for guild {guild_id_str}: {guild_music_dir}")
                # Optionally inform user, but primary message is above.
                # await ctx.send("Song cache for this server has been cleared.") 
            except OSError as e:
                logger.error(f"Error deleting cache directory {guild_music_dir} for guild {guild_id_str}: {e.strerror}")
                # await ctx.send(f"Note: Could not fully clear the song cache for this server: {e.strerror}")
        else:
            logger.info(f"Cache directory {guild_music_dir} for guild {guild_id_str} not found. No deletion needed.")

        # Optionally, remove the state from the global dictionary:
        # if ctx.guild.id in guild_states:
        #     del guild_states[ctx.guild.id]
        #     logger.info(f"GuildPlayerState for guild {ctx.guild.id} removed from global states.")
    else:
        await ctx.send('I am not currently in a voice channel on this server.')


@bot.command(name='ping', help="Checks the bot's voice connection latency.")
async def ping(ctx: commands.Context):
    """
    Command to check the bot's latency to the Discord voice server for this guild.
    Provides the round-trip voice latency in milliseconds.
    """
    guild_state = get_or_create_guild_state(ctx)
    voice_client = guild_state.voice_client

    if voice_client and voice_client.is_connected():
        latency_ms = voice_client.latency * 1000  # Latency is given in seconds by discord.py.
        logger.info(f"Ping command: Voice latency for guild '{ctx.guild.name}' is {latency_ms:.2f} ms.")
        await ctx.send(f'Voice connection latency for this server: {latency_ms:.2f} ms')
        if latency_ms > 150:  # Arbitrary threshold for "high" latency.
            await ctx.send('Note: The voice latency is a bit high, which might affect audio quality.')
    else:
        await ctx.send('I am not connected to a voice channel on this server. Voice latency cannot be measured.')


@bot.command(name='author', help='Shows information about the bot author.')
async def author(ctx: commands.Context):
    """
    Command to display information about the author of the bot.
    """
    # Consider making the author info configurable or more detailed if needed for your use case.
    await ctx.send('This bot was made by spyflow (Discord: spyflow, GitHub: https://github.com/spyflow).')


@bot.command(name='clearcache', help='Clears all downloaded songs for this server. Usage: !clearcache')
async def clearcache(ctx: commands.Context):
    """
    Command to manually clear the song cache for the current guild.
    Deletes the guild-specific music directory and all its contents.
    """
    guild_id_str = str(ctx.guild.id) # Use a distinct variable name
    guild_music_dir = os.path.join('music', guild_id_str)

    guild_state = get_or_create_guild_state(ctx) # Get current guild state

    # Check if a song from this guild's cache is currently playing
    if guild_state.voice_client and guild_state.voice_client.is_playing() and \
       guild_state.current_song_path and guild_state.current_song_path.startswith(guild_music_dir):
        await ctx.send("A song from this server's cache is currently playing. "
                       "Please stop playback (e.g., with `!leave` or by skipping all songs) before clearing the cache.")
        return

    if os.path.exists(guild_music_dir):
        try:
            shutil.rmtree(guild_music_dir)
            logger.info(f"User {ctx.author.name} (ID: {ctx.author.id}) cleared cache for guild {guild_id_str} (Name: {ctx.guild.name}): {guild_music_dir}")
            await ctx.send("Successfully cleared the song cache for this server. All downloaded songs for this server have been removed.")
        except OSError as e:
            logger.error(f"Error deleting cache directory {guild_music_dir} for guild {guild_id_str} on user command by {ctx.author.name}: {e.strerror}")
            await ctx.send(f"Error: Could not clear the song cache. An OS error occurred: {e.strerror}")
        except Exception as e:
            logger.error(f"Unexpected error deleting cache directory {guild_music_dir} for guild {guild_id_str} by {ctx.author.name}: {e}", exc_info=True)
            await ctx.send("An unexpected error occurred while trying to clear the cache.")
    else:
        logger.info(f"User {ctx.author.name} (ID: {ctx.author.id}) tried to clear cache for guild {guild_id_str} (Name: {ctx.guild.name}), but directory {guild_music_dir} was not found.")
        await ctx.send("There are no cached songs for this server to clear.")


# --- Core Music Playback Logic & Utility Functions ---
def cleanup(file_path: str):
    """
    Handles post-playback actions for an audio file.
    Originally, this deleted the file. Now, it primarily logs or could be used for other non-destructive cleanup.

    Args:
        file_path (str): The path to the audio file that was played.
    """
    try:
        if os.path.exists(file_path): # Check if the file actually exists
            # os.remove(file_path) # File deletion disabled for caching
            logger.info(f'Song finished, file retained in cache: {file_path}')
        else:
            logger.warning(f"Cleanup/post-playback: File path already non-existent: {file_path}")
    except OSError as e:
        # Log detailed OS error if other operations fail (no deletion attempted).
        logger.error(f"Error during cleanup operations for file {file_path} (no deletion attempted): {e.strerror} (Code: {e.errno})")
    except Exception as e:
        logger.error(f"Unexpected error in cleanup (no deletion attempted) for file {file_path}: {e}", exc_info=True)


def play_next_song(guild_state: GuildPlayerState):
    """
    Plays the next song in the queue.
    This is a synchronous function that's called when a song finishes (via 'after' callback)
    or when the 'play' command is used and no song is currently playing.
    It manages the global state for `current_song`, `current_activity_name`, and `inactive_timer`.

    Args:
        guild_state: GuildPlayerState: The playback state object for the specific guild.
    """
    # Removed global variable access, now uses guild_state attributes.
    voice_client = guild_state.voice_client # Get voice_client from guild_state
    ctx = guild_state.last_ctx # Use the last known context for this guild

    if not voice_client or not voice_client.is_connected():
        logger.warning(f"play_next_song (guild {guild_state.guild_id}): voice_client is not valid or not connected. Clearing queue.")
        guild_state.queue.clear()
        guild_state.song_titles.clear()
        guild_state.current_song_path = None
        guild_state.current_song_title = None
        if guild_state.inactive_timer:
            guild_state.inactive_timer.cancel()
            guild_state.inactive_timer = None
        return
    
    if not ctx:
        logger.error(f"play_next_song (guild {guild_state.guild_id}): last_ctx is None. Cannot send messages. Aborting playback for this guild.")
        # Potentially clear queue or attempt recovery, but for now, log and exit for this guild.
        # This situation might occur if the bot starts up and a timer fires before any command is run in a guild.
        return

    if guild_state.queue:  # If there are songs in the guild's queue
        file_path = guild_state.queue.pop(0)
        song_title = guild_state.song_titles.pop(0) if guild_state.song_titles else "Unknown Title"

        guild_state.current_song_path = file_path
        guild_state.current_song_title = song_title

        logger.info(f"Attempting to play (guild {guild_state.guild_id}): '{song_title}' from {file_path} in guild '{ctx.guild.name}'.")

        try:
            # Crucial check: Ensure the audio file exists before trying to play.
            if not os.path.exists(file_path):
                logger.error(f"File not found for playback: {file_path}. Song: '{song_title}'. Skipping.")
                asyncio.run_coroutine_threadsafe(
                    ctx.send(f"Error: Audio file for '{song_title}' not found. Skipping song."), bot.loop
                )
                # cleanup(file_path) # File path is non-existent, cleanup would warn.
                                  # If it was a symlink, actual file might exist but we don't know its path.
                                  # For now, simply log and try next song.
                logger.warning(f"File {file_path} was not found for playback. It might have been deleted or was never properly created.")
                guild_state.current_song_path = None # Ensure state is cleared
                guild_state.current_song_title = None
                play_next_song(guild_state)  # Try to play the next song in the queue.
                return

            # Play the audio. The 'after' parameter specifies a callback (song_finished)
            # to be executed once playback completes or is stopped.
            audio_source = discord.FFmpegPCMAudio(file_path)
            voice_client.play(
                audio_source,
                after=lambda e: song_finished(file_path, guild_state, error=e) # Pass guild_state
            )
            asyncio.run_coroutine_threadsafe(ctx.send(f"Now playing: '{song_title}'"), guild_state.bot.loop)

            if guild_state.inactive_timer:
                guild_state.inactive_timer.cancel()
            # Pass guild_state to check_inactive
            guild_state.inactive_timer = guild_state.bot.loop.call_later(inactive_time, check_inactive, guild_state)
            logger.info(f"Inactivity timer reset/started for {inactive_time}s in guild '{ctx.guild.name}' (ID: {guild_state.guild_id}).")

        except Exception as e:
            # Catch-all for unexpected errors during playback setup.
            logger.error(f"Error trying to play {file_path} for song '{song_title}': {e}", exc_info=True)
            asyncio.run_coroutine_threadsafe(
                ctx.send(f"An error occurred while trying to play '{song_title}'. Check logs for details."), guild_state.bot.loop
            )
            cleanup(file_path)
            guild_state.current_song_path = None
            guild_state.current_song_title = None
            play_next_song(guild_state) # Attempt to play the next song for this guild.

    else:  # If the guild's queue is empty
        logger.info(f"Queue is empty for guild '{ctx.guild.name}' (ID: {guild_state.guild_id}). No more songs to play.")
        guild_state.current_song_path = None
        guild_state.current_song_title = None
        # The inactivity timer is NOT reset here. If a song just finished and the queue is now empty,
        # the existing timer (started when that song began) will eventually call check_inactive.
        # If 'leave' was called, the timer is explicitly cancelled.
        # If 'play' is called on an empty queue, a new timer starts with the new song.
        # This ensures that check_inactive is the one to decide if the bot should leave.


def song_finished(file_path: str, guild_state: GuildPlayerState, error=None):
    """
    Callback function executed when a song finishes playing or is stopped (e.g., by `!skip`).
    It cleans up the audio file and triggers playing the next song if available.

    Args:
        file_path (str): The path of the song that finished.
        guild_state (GuildPlayerState): The playback state for the guild.
        error (Exception, optional): Any error that occurred during playback.
    """
    ctx = guild_state.last_ctx # Get last context for this guild
    voice_client = guild_state.voice_client

    if error:
        logger.error(f"Playback error for {file_path} in guild {guild_state.guild_id}: {error}")
        if ctx:
            asyncio.run_coroutine_threadsafe(
                ctx.send(f"An error occurred with '{os.path.basename(file_path)}' during playback."), guild_state.bot.loop
            )

    logger.info(f"Song finished: '{os.path.basename(file_path)}' in guild {guild_state.guild_id}. Performing post-playback actions.")
    cleanup(file_path) # cleanup now handles logging retention or other non-destructive actions
    guild_state.current_song_path = None # Mark no song is playing before calling play_next
    guild_state.current_song_title = None


    if voice_client and voice_client.is_connected():
        play_next_song(guild_state)
    else:
        logger.info(f"Song finished (guild {guild_state.guild_id}), but bot is no longer connected. Clearing queue for this guild.")
        guild_state.queue.clear()
        guild_state.song_titles.clear()
        # current_song_path already None
        if guild_state.inactive_timer:
            guild_state.inactive_timer.cancel()
            guild_state.inactive_timer = None


def check_inactive(guild_state: GuildPlayerState):
    """
    Callback for the inactivity timer for a specific guild.
    Checks if the bot is inactive in that guild and disconnects if so.

    Args:
        guild_state (GuildPlayerState): The playback state for the guild.
    """
    ctx = guild_state.last_ctx # Get last context for this guild
    voice_client = guild_state.voice_client

    if guild_state.current_song_path or (voice_client and voice_client.is_playing()):
        logger.info(f"Inactivity check for guild {guild_state.guild_id}: Bot is active. Timer will be reset by new song if any.")
        return

    logger.info(f"Inactivity check: Bot is inactive in guild {guild_state.guild_id} ('{ctx.guild.name if ctx else 'Unknown Guild Name'}').")
    if voice_client and voice_client.is_connected():
        logger.info(f"Disconnecting due to inactivity from guild {guild_state.guild_id}.")
        asyncio.run_coroutine_threadsafe(voice_client.disconnect(), guild_state.bot.loop)
        guild_state.voice_client = None # Nullify voice client for this guild

        if ctx: # Only send message if we have a context
            asyncio.run_coroutine_threadsafe(
                ctx.send('Disconnected due to inactivity. The song queue has been cleared.'), guild_state.bot.loop
            )
        else: # No context to send message
            logger.warning(f"No last_ctx available for guild {guild_state.guild_id} during inactivity disconnect message.")


        guild_state.queue.clear()
        guild_state.song_titles.clear()
        # current_song_path is already None if we reached here
        if guild_state.inactive_timer:
            guild_state.inactive_timer.cancel()
            guild_state.inactive_timer = None
            logger.info(f"Inactivity timer cleared for guild {guild_state.guild_id}.")
    else:
        logger.info(f"Inactivity check for guild {guild_state.guild_id}: Bot already disconnected or voice_client is invalid.")
        if guild_state.inactive_timer: # Ensure timer is cleaned up
            guild_state.inactive_timer.cancel()
            guild_state.inactive_timer = None


# --- Bot Startup ---
# Standard Python practice: ensure the bot runs only when the script is executed directly.
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        # Fallback if logger isn't fully set up or if .env is missing.
        print("FATAL ERROR: DISCORD_BOT_TOKEN environment variable not set. The bot cannot start.")
        logger.critical("FATAL ERROR: DISCORD_BOT_TOKEN environment variable not set. The bot cannot start.")
    else:
        logger.info("Attempting to start the bot...")
        try:
            bot.run(DISCORD_BOT_TOKEN)  # Run the bot with the Discord token.
        except discord.LoginFailure:
            logger.critical("Login Failure: Invalid Discord token. Please check your DISCORD_BOT_TOKEN.")
        except Exception as e:
            logger.critical(f"An unexpected error occurred during bot startup: {e}", exc_info=True)

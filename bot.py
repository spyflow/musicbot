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

# --- Song Metadata Class ---
class SongMetadata:
    """Represents metadata for a cached song."""
    def __init__(self, video_id: str, title: str, file_path: str, size_bytes: int):
        self.video_id: str = video_id
        self.title: str = title
        self.file_path: str = file_path
        self.size_bytes: int = size_bytes
        self.weight: int = 0  # Initialized to 0, will be set/incremented

    def __repr__(self):
        return (f"<SongMetadata video_id='{self.video_id}' "
                f"title='{self.title[:20]}...' "
                f"weight={self.weight} "
                f"size={self.size_bytes}>")

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

# --- Global Cache Configuration ---
MAX_CACHE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB
current_cache_size_bytes = 0 # This will be properly initialized later
global_song_metadata: dict[str, SongMetadata] = {}

# Create music and global_cache directory if it doesn't exist
base_music_dir = 'music'
global_cache_dir_name = 'global_cache'
global_cache_path = os.path.join(base_music_dir, global_cache_dir_name)

if not os.path.exists(base_music_dir):
    os.makedirs(base_music_dir)
    logger.info(f"Created '{base_music_dir}' directory.")

if not os.path.exists(global_cache_path):
    os.makedirs(global_cache_path)
    logger.info(f"Created '{global_cache_path}' directory for global music cache.")

# --- Cache Initialization ---
def initialize_cache_state():
    """
    Initializes the current_cache_size_bytes and potentially prunes global_song_metadata
    based on files actually present in the global_cache_path.
    This should be called once at bot startup.
    """
    global current_cache_size_bytes # Allow modification of global variable
    
    logger.info(f"Initializing cache state from directory: {global_cache_path}")
    actual_files_in_cache = {} # video_id: file_path
    
    if not os.path.isdir(global_cache_path):
        logger.warning(f"Global cache directory {global_cache_path} not found during initialization.")
        current_cache_size_bytes = 0
        return

    for filename in os.listdir(global_cache_path):
        file_path = os.path.join(global_cache_path, filename)
        if os.path.isfile(file_path):
            video_id_from_filename, ext = os.path.splitext(filename)
            if ext == '.mp3': # Assuming all cached files are .mp3
                actual_files_in_cache[video_id_from_filename] = file_path

    total_size = 0
    metadata_to_keep = {}

    # Sync metadata with actual files
    for video_id, metadata_entry in global_song_metadata.items():
        if video_id in actual_files_in_cache:
            # File exists, metadata is valid, ensure file path is correct
            metadata_entry.file_path = actual_files_in_cache[video_id] # Update path just in case
            try:
                metadata_entry.size_bytes = os.path.getsize(metadata_entry.file_path) # Get actual current size
                total_size += metadata_entry.size_bytes
                metadata_to_keep[video_id] = metadata_entry
                logger.debug(f"Cache init: Keeping metadata for '{metadata_entry.title}', size: {metadata_entry.size_bytes}")
            except OSError as e:
                logger.warning(f"Cache init: Error getting size for {metadata_entry.file_path} (ID: {video_id}): {e}. Excluding from cache count.")
            del actual_files_in_cache[video_id] # Remove from dict as it's processed
        else:
            # Metadata exists but file doesn't (orphan metadata)
            logger.warning(f"Cache init: Metadata for video ID '{video_id}' ('{metadata_entry.title}') exists, but file {metadata_entry.file_path} not found. Removing metadata.")

    # Process files that exist but have no metadata (orphan files)
    for video_id_orphan, file_path_orphan in actual_files_in_cache.items():
        logger.warning(f"Cache init: Orphan file '{file_path_orphan}' (ID: {video_id_orphan}) found in cache directory without corresponding metadata. Consider deleting it manually or implement auto-deletion.")
        # Optionally, could try to create metadata if info can be fetched, or delete the file.
        # For now, just log. It won't be part of current_cache_size_bytes unless metadata is created.

    global_song_metadata.clear()
    global_song_metadata.update(metadata_to_keep)
    current_cache_size_bytes = total_size
    logger.info(f"Cache initialization complete. current_cache_size_bytes: {current_cache_size_bytes} bytes. Metadata entries: {len(global_song_metadata)}")


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

    # Use global cache path
    # guild_id = str(ctx.guild.id) # No longer needed for path construction
    # guild_music_dir = os.path.join('music', guild_id) # Old path
    guild_music_dir = global_cache_path # New global cache path
    # os.makedirs(guild_music_dir, exist_ok=True) # Already created at bot startup

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
        # potential_cached_path now uses global_cache_path (via guild_music_dir assignment in the previous step)
        potential_cached_path = os.path.join(guild_music_dir, f"{video_id}.{expected_ext}")

        # Step 2: Check cache
        if os.path.exists(potential_cached_path):
            logger.info(f"Cache hit: Using existing file {potential_cached_path} for video ID {video_id}")
            file_path_to_play = potential_cached_path
            info_dict = pre_info_dict # Use the info we already fetched
            await ctx.send(f"Found '{title_to_play}' in global cache. Adding to queue.")
        else: # Song is not in cache, needs download
            logger.info(f"Cache miss for video ID {video_id} ('{title_to_play}'). Proceeding with download to global cache.")
            
            # --- Eviction Logic (Before Download) ---
            global current_cache_size_bytes # Needed for modification
            new_song_title_for_evict_log = pre_info_dict.get('title', 'Unknown Title') # For logging during eviction
            new_song_size_bytes = pre_info_dict.get('filesize') or pre_info_dict.get('filesize_approx')

            if not new_song_size_bytes:
                logger.warning(f"Could not determine estimated size for new song '{new_song_title_for_evict_log}' (ID: {video_id}) before download. Eviction might not be accurate or skipped.")
                # Fallback: use a default average size, or skip eviction if too risky.
                # For now, if size is unknown, we might not evict enough.
                # Consider assigning a default average if this happens often: new_song_size_bytes = 10 * 1024 * 1024 # 10MB example

            if new_song_size_bytes: # Only proceed with eviction if song size estimate is available
                while (current_cache_size_bytes + new_song_size_bytes > MAX_CACHE_SIZE_BYTES) and global_song_metadata:
                    if not global_song_metadata: # Should be caught by the loop condition, but as safeguard
                        logger.info("Cache is empty, cannot evict further.")
                        break
                    
                    # Find song with the lowest weight to evict
                    try:
                        song_to_evict_id = min(global_song_metadata, key=lambda k: global_song_metadata[k].weight)
                        song_to_evict = global_song_metadata[song_to_evict_id]
                    except ValueError: # Handles empty global_song_metadata if it somehow happens
                        logger.info("Tried to find song to evict in empty metadata. Stopping eviction.")
                        break

                    logger.info(f"Eviction needed. Attempting to evict song: '{song_to_evict.title}' (ID: {song_to_evict_id}, Weight: {song_to_evict.weight}, Size: {song_to_evict.size_bytes}) to make space for '{new_song_title_for_evict_log}'.")

                    try:
                        os.remove(song_to_evict.file_path)
                        current_cache_size_bytes -= song_to_evict.size_bytes
                        del global_song_metadata[song_to_evict_id]
                        logger.info(f"Evicted '{song_to_evict.title}'. Cache size now: {current_cache_size_bytes}")
                        if ctx: # Send message only if context is available
                           asyncio.create_task(ctx.send(f"Cache full. Evicted '{song_to_evict.title}' (Weight: {song_to_evict.weight}) to make space."))
                    except OSError as e:
                        logger.error(f"Error evicting file {song_to_evict.file_path}: {e}. Stopping eviction process.")
                        # If file removal fails, we should stop to avoid inconsistency.
                        break 
                    except KeyError:
                        # This might happen if another process/task somehow removed the metadata already.
                        logger.error(f"Tried to evict {song_to_evict_id} but it was already removed from metadata. Recalculating for next eviction candidate.")
                        # No break here, try to find another song. Size was not decremented.
                        continue # Recalculate next eviction candidate

                    if not global_song_metadata: # Check again if cache became empty
                        logger.info("Cache became empty during eviction process.")
                        break
            elif (current_cache_size_bytes > MAX_CACHE_SIZE_BYTES): # No new song size, but cache is already over limit
                 logger.warning(f"Cache is over limit ({current_cache_size_bytes} > {MAX_CACHE_SIZE_BYTES}) but new song size is unknown. Cannot perform targeted eviction.")
            # --- End of Eviction Logic ---

            # Attempt to find a direct stream URL from pre_info_dict
            stream_url = None
            if pre_info_dict.get('url'): # Often a direct media URL or HLS/DASH manifest
                stream_url = pre_info_dict['url']
                logger.info(f"Found primary stream URL for '{title_to_play}': {stream_url}")
            else: # Look for audio formats
                for f in pre_info_dict.get('formats', []):
                    if f.get('vcodec') == 'none' and f.get('acodec') != 'none' and f.get('url'):
                        stream_url = f['url']
                        logger.info(f"Found audio stream format URL for '{title_to_play}': {stream_url}")
                        break
            
            if stream_url:
                logger.info(f"Streaming '{title_to_play}' from URL while downloading in background.")
                await ctx.send(f"Streaming '{title_to_play}' while downloading to cache...")
                
                # Add stream URL to queue for immediate playback
                file_path_to_play = stream_url # Play from URL

                # Create and schedule background download task
                # The download_opts for the background task should be the full conversion ones
                bg_download_opts = ydl_opts.copy()
                bg_download_opts['outtmpl'] = os.path.join(global_cache_path, '%(id)s.%(ext)s')
                # Ensure postprocessors for MP3 conversion
                if 'postprocessors' not in bg_download_opts:
                     bg_download_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]

                asyncio.create_task(download_song_to_cache_task(
                    original_url=url_to_download, # The initial URL query (e.g. youtube watch URL)
                    download_options=bg_download_opts,
                    video_id_to_update=video_id, # video_id from pre_info_dict
                    title_for_logs=title_to_play,
                    expected_final_path_template=os.path.join(global_cache_path, f"{video_id}.mp3")
                ))
                # Note: Metadata for this song (video_id) will be initially minimal or absent
                # until download_song_to_cache_task completes and updates it.
                # Weight will be incremented when play_next_song is called with the stream_url.

            else: # No suitable stream URL found, proceed with full download before playback
                logger.info(f"No suitable stream URL found for '{title_to_play}'. Downloading fully before playback.")
                await ctx.send(f"Downloading audio for '{title_to_play}' ({url_to_download})... This may take a moment.")
                
                # Standard download process (as it was before streaming attempt)
                download_opts_full = ydl_opts.copy()
                download_opts_full['outtmpl'] = os.path.join(guild_music_dir, '%(id)s.%(ext)s')
                if 'postprocessors' not in download_opts_full:
                     download_opts_full['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]

                with yt_dlp.YoutubeDL(download_opts_full) as ydl_downloader:
                    info_dict_download = ydl_downloader.extract_info(url_to_download, download=True)

                song_title_download = info_dict_download.get('title', title_to_play)
                video_id_download = info_dict_download.get('id', video_id)
                expected_dl_path = os.path.join(guild_music_dir, f"{video_id_download}.mp3")
                actual_final_path = None

                if 'requested_downloads' in info_dict_download and info_dict_download['requested_downloads']:
                    rd_info = info_dict_download['requested_downloads'][0]
                    if 'filepath' in rd_info and os.path.exists(rd_info['filepath']):
                        actual_final_path = rd_info['filepath']
                
                if actual_final_path:
                    file_path_to_play = actual_final_path
                elif os.path.exists(expected_dl_path):
                    file_path_to_play = expected_dl_path
                else:
                    original_ext = info_dict_download.get('ext')
                    original_file_path = os.path.join(guild_music_dir, f"{video_id_download}.{original_ext}")
                    if original_ext and original_ext != 'mp3' and os.path.exists(original_file_path):
                        file_path_to_play = original_file_path
                    else:
                        logger.error(f"Critical: Downloaded file for {video_id_download} not found at {expected_dl_path} or {original_file_path}.")
                        await ctx.send(f"Error: Could not locate file for '{song_title_download}' after download.")
                        return
                
                info_dict = info_dict_download
                title_to_play = song_title_download
                logger.info(f"Full download complete for '{title_to_play}'. File: {file_path_to_play}")

        # Step 4: Common logic to add to queue (modified to handle stream URLs and downloaded files)
        if file_path_to_play and title_to_play:
            video_id_of_song = video_id # From pre_info_dict, consistent ID

            # If it's a stream URL, size is unknown until download completes.
            # If it's a file path, we can get its size.
            is_stream = file_path_to_play.startswith('http') 
            song_size_bytes = 0

            if not is_stream: # It's a local file (either from cache or full download)
                try:
                    if os.path.exists(file_path_to_play):
                        song_size_bytes = os.path.getsize(file_path_to_play)
                    else:
                        logger.error(f"Local file {file_path_to_play} not found for metadata size.")
                except OSError as e:
                    logger.error(f"OS error getting size of local file {file_path_to_play}: {e}")
            
            # Metadata handling:
            # If streaming, metadata entry might be temporary or updated later by download_song_to_cache_task.
            # If from cache (already os.path.exists(potential_cached_path)), weight is incremented.
            # If fully downloaded (not streaming path), new metadata is created.
            if video_id_of_song in global_song_metadata:
                global_song_metadata[video_id_of_song].weight += 1
                # If it was streamed and now we have the file path from cache, ensure file_path is local
                if not is_stream and global_song_metadata[video_id_of_song].file_path.startswith('http'):
                     global_song_metadata[video_id_of_song].file_path = file_path_to_play
                     global_song_metadata[video_id_of_song].size_bytes = song_size_bytes # Update size too
                logger.info(f"Incremented weight for song '{title_to_play}' (ID: {video_id_of_song}) to {global_song_metadata[video_id_of_song].weight}.")
            elif not is_stream: # New song, fully downloaded, not streaming
                # This part handles songs that were fully downloaded without prior streaming attempt
                current_cache_size_bytes += song_size_bytes # Add actual size
                metadata = SongMetadata(
                    video_id=video_id_of_song,
                    title=title_to_play,
                    file_path=file_path_to_play,
                    size_bytes=song_size_bytes
                )
                metadata.weight = 1
                global_song_metadata[video_id_of_song] = metadata
                logger.info(f"Added new fully downloaded song '{title_to_play}' (ID: {video_id_of_song}) to metadata. Weight: 1, Size: {song_size_bytes}. Cache size: {current_cache_size_bytes}")
            # If it IS a stream and not in metadata, download_song_to_cache_task will handle its metadata creation.
            # We avoid adding a stream URL directly to metadata here, task will add the final file path.

            logger.info(f"Adding to queue: '{title_to_play}' (source: {'STREAM' if is_stream else 'FILE'})")
            guild_state.queue.append(file_path_to_play) # Can be stream URL or file path
            guild_state.song_titles.append(title_to_play)
            await ctx.send(f"Added to queue: '{title_to_play}'")
            
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

        # The cache is global, so it's not cleared when leaving a guild.
        logger.info(f"Left voice channel in guild {guild_state.guild_id}. Global cache is not affected.")

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
    Command to manually clear the **global song cache**.
    Deletes all cached songs and resets cache metadata.
    """
    global current_cache_size_bytes # Allow modification
    guild_state = get_or_create_guild_state(ctx)

    if guild_state.voice_client and guild_state.voice_client.is_playing() and guild_state.current_song_path:
        # Check if the currently playing song's path (which could be a URL) is from our cache metadata
        # This is a bit tricky if current_song_path is a stream URL not yet in metadata.
        # A simpler check is fine: if anything is playing, defer clearcache.
        await ctx.send("A song is currently playing. "
                       "Please stop playback (e.g., with `!leave` or by skipping all songs) before clearing the global cache.")
        return

    logger.info(f"User {ctx.author.name} (ID: {ctx.author.id}) initiated global cache clearing.")
    files_deleted_count = 0
    errors_deleting_count = 0

    # Iterate over a copy for safe deletion from original dict
    for video_id, metadata in list(global_song_metadata.items()): # Use list() for a copy
        try:
            if os.path.exists(metadata.file_path):
                os.remove(metadata.file_path)
                logger.info(f"Deleted from global cache: {metadata.file_path} (ID: {video_id})")
                files_deleted_count += 1
            else:
                logger.warning(f"File {metadata.file_path} for ID {video_id} not found during clearcache, but metadata existed.")
            # Remove metadata entry regardless of whether file existed, to ensure clean state
            del global_song_metadata[video_id] 
        except OSError as e:
            logger.error(f"Error deleting file {metadata.file_path} from global cache: {e}")
            errors_deleting_count += 1
        except KeyError:
            logger.error(f"KeyError trying to delete {video_id} from metadata during clearcache. Already removed?")


    # Reset cache state
    global_song_metadata.clear() # Should be mostly empty if all dels succeeded, but clear to be sure.
    current_cache_size_bytes = 0

    if errors_deleting_count > 0:
        await ctx.send(f"Global song cache clearing finished. Successfully deleted {files_deleted_count} file(s). "
                       f"Encountered errors deleting {errors_deleting_count} file(s). Check logs for details. "
                       f"Cache size is now {current_cache_size_bytes} bytes.")
    else:
        await ctx.send(f"Successfully cleared the global song cache. Deleted {files_deleted_count} file(s). "
                       f"Cache is now empty ({current_cache_size_bytes} bytes).")

# --- Core Music Playback Logic & Utility Functions ---
def cleanup(file_path: str):
    """
    Handles post-playback actions for an audio file.
    Files are retained in the global cache, so this function primarily logs.
    Args:
        file_path (str): The path to the audio file that was played.
    """
    try:
        if os.path.exists(file_path): # Check if the file actually exists
            logger.info(f'Song finished, file retained in global cache: {file_path}')
        else:
            logger.warning(f"Cleanup/post-playback: File path {file_path} already non-existent.")
    except OSError as e:
        logger.error(f"Error during cleanup check for file {file_path} (no deletion attempted): {e.strerror} (Code: {e.errno})")
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
            # If file_path is a URL, os.path.exists will be false.
            # FFmpegPCMAudio handles URLs, so we only need to check os.path.exists for local files.
            is_url = file_path.startswith('http')
            if not is_url and not os.path.exists(file_path):
                logger.error(f"Local file not found for playback: {file_path}. Song: '{song_title}'. Skipping.")
                asyncio.run_coroutine_threadsafe(
                    ctx.send(f"Error: Audio file for '{song_title}' not found. Skipping song."), bot.loop
                )
                logger.warning(f"File {file_path} was not found for playback. It might have been deleted or was never properly created.")
                guild_state.current_song_path = None 
                guild_state.current_song_title = None
                play_next_song(guild_state)
                return

            # Play the audio (URL or local file path).
            # Add FFmpeg options to handle potential issues with certain stream types or network conditions.
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            audio_source = discord.FFmpegPCMAudio(file_path, **ffmpeg_options)
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


async def download_song_to_cache_task(original_url: str, download_options: dict, video_id_to_update: str, title_for_logs: str, expected_final_path_template: str):
    """
    Downloads a song to the cache in the background.
    Updates metadata and cache size upon completion.
    """
    global current_cache_size_bytes # Allow modification

    logger.info(f"Background download started for '{title_for_logs}' (ID: {video_id_to_update}) from {original_url}")
    download_success = False
    final_file_path = None
    actual_song_size = 0

    try:
        with yt_dlp.YoutubeDL(download_options) as ydl:
            info_dict_download = ydl.extract_info(original_url, download=True)
        
        # Determine actual downloaded file path (similar to logic in play command)
        # Note: ydl_opts['outtmpl'] in download_options should result in expected_final_path_template
        # but we verify to be sure.
        if os.path.exists(expected_final_path_template):
            final_file_path = expected_final_path_template
        else: # Fallback if extension was different or some other issue
            downloaded_video_id = info_dict_download.get('id', video_id_to_update)
            original_ext_dl = info_dict_download.get('ext')
            temp_path = os.path.join(global_cache_path, f"{downloaded_video_id}.{original_ext_dl}")
            if os.path.exists(temp_path) and original_ext_dl != 'mp3': # Check if it's the pre-conversion path
                 logger.warning(f"Background download for '{title_for_logs}': MP3 may not be at expected path. Found {temp_path}. This might indicate an issue if conversion was expected.")
                 # For now, we assume the postprocessor created the .mp3 at expected_final_path_template
                 # If not, this part needs more robust handling of file paths from yt-dlp.

        if os.path.exists(expected_final_path_template): # Re-check after considering alternatives
            final_file_path = expected_final_path_template
            actual_song_size = os.path.getsize(final_file_path)
            download_success = True
            logger.info(f"Background download complete for '{title_for_logs}'. File: {final_file_path}, Size: {actual_song_size}")
        else:
            logger.error(f"Background download for '{title_for_logs}': Final file {expected_final_path_template} not found after download attempt.")
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp download error in background for '{title_for_logs}': {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in background download task for '{title_for_logs}': {e}", exc_info=True)

    if download_success and final_file_path:
        # Update metadata
        if video_id_to_update in global_song_metadata:
            # Song was streamed, metadata might exist (e.g. from weight increment) but needs file_path and size
            global_song_metadata[video_id_to_update].file_path = final_file_path
            global_song_metadata[video_id_to_update].size_bytes = actual_song_size
            # Weight was already incremented at streaming time if it was played.
            # If it was added to queue but skipped before playing, weight might be 0 or from previous plays.
            # If it's a new song, weight should be 1. This is tricky if it was never played from stream.
            # For simplicity, if it's already in metadata, we assume its weight is being managed.
            # If it was NOT in metadata (e.g. stream was added to queue but bot restarted before play), add it.
            logger.info(f"Updated metadata for cached song '{title_for_logs}' (ID: {video_id_to_update}). Path: {final_file_path}, Size: {actual_song_size}")
        else: # New song, first time seeing it (stream wasn't played or metadata was lost)
            metadata = SongMetadata(
                video_id=video_id_to_update,
                title=title_for_logs,
                file_path=final_file_path,
                size_bytes=actual_song_size
            )
            metadata.weight = 1 # Initial weight for new cached song
            global_song_metadata[video_id_to_update] = metadata
            current_cache_size_bytes += actual_song_size # Add to cache size only if truly new
            logger.info(f"Added new metadata for cached song '{title_for_logs}' (ID: {video_id_to_update}). Weight: 1, Size: {actual_song_size}. Cache now: {current_cache_size_bytes}")
        
        # Potentially, re-check eviction if the actual downloaded size is much larger than estimate
        # This is complex, for now, eviction is done pre-download based on estimate.
    elif not download_success:
        logger.warning(f"Background download failed for '{title_for_logs}'. It will not be added to cache from this attempt.")
        # If metadata was tentatively added for streaming, it should be cleaned up or marked as invalid path.
        # Current logic: metadata is only fully added with file_path upon successful download.
        # If streaming started and incremented weight on a non-existent metadata, that's a minor inconsistency.

# --- Bot Startup ---
# Standard Python practice: ensure the bot runs only when the script is executed directly.
if __name__ == "__main__":
    initialize_cache_state() # Initialize cache size and metadata from disk
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

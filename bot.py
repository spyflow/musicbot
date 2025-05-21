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

# --- Global State Variables ---
# These variables manage the bot's state regarding music playback and activity.
queue = []  # A list of file paths for songs waiting to be played.
song_titles = []  # A list of human-readable song titles, corresponding to the 'queue'.
current_song = None  # Stores the file path of the song currently being played. None if no song is active.
inactive_timer = None  # Holds the asyncio.TimerHandle for the inactivity disconnect timer.
current_activity_name = "idle"  # String displayed as the bot's activity (e.g., "Listening to [song name]").

# --- YouTube Downloader Configuration ---
# Options for the yt-dlp library, which handles downloading audio from YouTube.
ydl_opts = {
    'format': 'bestaudio/best',  # Select the best audio-only format.
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',  # Use FFmpeg to extract audio.
        'preferredcodec': 'mp3',  # Convert the audio to MP3 format.
        'preferredquality': '192',  # Set preferred audio quality to 192 kbps.
    }],
    'outtmpl': 'music/%(id)s.%(ext)s',  # Define output template: music/VIDEO_ID.mp3 (or other extension).
    'noplaylist': True,  # Disable downloading entire playlists if a playlist URL is given.
    'quiet': True, # Suppress yt-dlp console output unless there are errors.
    'default_search': 'ytsearch', # Use ytsearch for non-URL queries.
}

ydl = yt_dlp.YoutubeDL(ydl_opts) # Create a yt-dlp instance with the specified options.

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
    activity_name = current_activity_name[:128] if current_activity_name else "nothing"

    activity = discord.Activity(type=activity_type, name=activity_name)
    try:
        await bot.change_presence(activity=activity)
        logger.debug(f"Presence updated to: Listening to {activity_name}")
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
    global current_song  # Manages the currently playing song's file path.
    # 'channel' for voice connection is managed by voice_client from ctx or new connection.

    if not search_query:
        await ctx.send("Please provide a song name or YouTube URL after the `!play` command. Usage: `!play <song name or URL>`")
        return

    # Ensure the user who invoked the command is in a voice channel.
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You are not connected to a voice channel. Please join one to play music.")
        return

    user_voice_channel = ctx.author.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    # If bot is in a voice channel but it's different from the user's, inform the user.
    if voice_client and voice_client.channel != user_voice_channel:
        await ctx.send(f"I am already in a different voice channel: '{voice_client.channel.name}'.")
        return

    # Connect to the user's voice channel if not already connected.
    if not voice_client:
        try:
            voice_client = await user_voice_channel.connect()
            logger.info(f"Bot joined voice channel: '{user_voice_channel.name}' in guild '{ctx.guild.name}'.")
        except discord.ClientException as e:
            logger.error(f"Error connecting to voice channel '{user_voice_channel.name}': {e}")
            await ctx.send(f"Could not join your voice channel. Error: {e}")
            return
    else: # Bot is already in the correct voice channel
        logger.info(f"Bot is already in voice channel: '{voice_client.channel.name}'.")


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

    try:
        await ctx.send(f"Downloading audio for '{url_to_download}'... This may take a moment.") # Download feedback
        # Download audio using yt-dlp. This is a blocking I/O operation.
        # For larger bots, consider running this in a separate thread using asyncio.to_thread (Python 3.9+)
        # or a thread pool executor to avoid blocking the bot's main event loop.
        info_dict = ydl.extract_info(url_to_download, download=True)

        song_title = info_dict.get('title', 'Unknown Title')
        video_id = info_dict.get('id', 'unknown_id') # Used for filename to avoid special characters.
        # File path construction relies on 'outtmpl' in ydl_opts and 'preferredcodec'.
        file_path = f"music/{video_id}.mp3"

        logger.info(f"Download complete for '{song_title}'. File saved to: {file_path}")

        # Add the downloaded song to the queue.
        queue.append(file_path)
        song_titles.append(song_title)
        await ctx.send(f"Added to queue: '{song_title}'")

        # If no song is currently playing and the bot is connected, start playback.
        if not current_song and voice_client and voice_client.is_connected():
            play_next_song(voice_client, ctx)
        elif not voice_client or not voice_client.is_connected():
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
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if voice_client and voice_client.is_playing():
        logger.info(f"Skip command invoked by {ctx.author.name}. Stopping current song.")
        voice_client.stop()  # Stopping playback triggers song_finished.
        await ctx.send('Song skipped.')
    elif voice_client and not voice_client.is_playing() and current_song:
        # This case handles if playback somehow stopped but state wasn't cleared.
        # Forcing play_next_song can help recover the queue.
        logger.info(f"Skip command: Nothing actively playing, but a song ('{current_song}') was marked as current. Attempting to advance queue.")
        play_next_song(voice_client, ctx) # This will clear current_song if queue is empty or play next.
        await ctx.send('Trying to play the next song as current one was stuck...')
    else:
        await ctx.send('No song is currently playing to skip.')


@bot.command(name='leave', help='Makes the bot leave the voice channel and clears the song queue.')
async def leave(ctx: commands.Context):
    """
    Command for the bot to leave the voice channel.
    It also clears the song queue and resets related playback state variables.
    """
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if voice_client and voice_client.is_connected():
        logger.info(f"Bot leaving voice channel '{voice_client.channel.name}' in guild '{ctx.guild.name}' due to 'leave' command by {ctx.author.name}.")
        await voice_client.disconnect()

        # Clear queue and reset global playback state.
        queue.clear()
        song_titles.clear()
        global current_song, inactive_timer, current_activity_name
        current_song = None
        current_activity_name = "idle" # Reset activity name.
        if inactive_timer:
            inactive_timer.cancel()
            inactive_timer = None
            logger.info("Inactivity timer cancelled due to 'leave' command.")
        await ctx.send('Disconnected from voice channel and cleared the song queue.')
    else:
        await ctx.send('I am not currently in a voice channel.')


@bot.command(name='ping', help="Checks the bot's voice connection latency.")
async def ping(ctx: commands.Context):
    """
    Command to check the bot's latency to the Discord voice server.
    Provides the round-trip voice latency in milliseconds.
    """
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if voice_client and voice_client.is_connected():
        latency_ms = voice_client.latency * 1000  # Latency is given in seconds by discord.py.
        logger.info(f"Ping command: Voice latency for guild '{ctx.guild.name}' is {latency_ms:.2f} ms.")
        await ctx.send(f'Voice connection latency: {latency_ms:.2f} ms')
        if latency_ms > 150:  # Arbitrary threshold for "high" latency.
            await ctx.send('Note: The voice latency is a bit high, which might affect audio quality.')
    else:
        await ctx.send('I am not connected to a voice channel. Voice latency cannot be measured.')


@bot.command(name='author', help='Shows information about the bot author.')
async def author(ctx: commands.Context):
    """
    Command to display information about the author of the bot.
    """
    # Consider making the author info configurable or more detailed if needed for your use case.
    await ctx.send('This bot was made by spyflow (Discord: spyflow, GitHub: https://github.com/spyflow).')


# --- Core Music Playback Logic & Utility Functions ---
def cleanup(file_path: str):
    """
    Deletes the specified audio file from the local 'music/' directory.
    This is called after a song has finished playing or if an error occurs during its processing.

    Args:
        file_path (str): The path to the audio file to be deleted.
    """
    try:
        if os.path.exists(file_path):  # Check if the file actually exists before attempting deletion.
            os.remove(file_path)
            logger.info(f'Successfully deleted audio file: {file_path}')
        else:
            logger.warning(f"Cleanup attempted for a non-existent file: {file_path}")
    except OSError as e:
        # Log detailed OS error if deletion fails.
        logger.error(f"Error deleting file {file_path}: {e.strerror} (Code: {e.errno})")
    except Exception as e:
        logger.error(f"Unexpected error in cleanup for file {file_path}: {e}", exc_info=True)


def play_next_song(voice_client: discord.VoiceClient, ctx: commands.Context):
    """
    Plays the next song in the queue.
    This is a synchronous function that's called when a song finishes (via 'after' callback)
    or when the 'play' command is used and no song is currently playing.
    It manages the global state for `current_song`, `current_activity_name`, and `inactive_timer`.

    Args:
        voice_client (discord.VoiceClient): The voice client instance for the guild.
        ctx (commands.Context): The context of the command that initiated playback or
                                from which subsequent songs are played. Used for sending messages
                                and for retrieving guild information.
    """
    global current_song, inactive_timer, current_activity_name

    if not voice_client or not voice_client.is_connected():
        logger.warning("play_next_song called but voice_client is not valid or not connected. Clearing queue.")
        queue.clear()
        song_titles.clear()
        current_song = None
        current_activity_name = "idle"
        if inactive_timer:
            inactive_timer.cancel()
            inactive_timer = None
        return

    if queue:  # If there are songs in the queue
        file_path = queue.pop(0)  # Get the first file path from the queue.
        # Pop corresponding song title, default to "Unknown Title" if lists are somehow mismatched.
        song_title = song_titles.pop(0) if song_titles else "Unknown Title"

        current_song = file_path  # Mark this song as currently playing.
        current_activity_name = song_title  # Update bot's presence.

        logger.info(f"Attempting to play: '{song_title}' from {file_path} in guild '{ctx.guild.name}'.")

        try:
            # Crucial check: Ensure the audio file exists before trying to play.
            if not os.path.exists(file_path):
                logger.error(f"File not found for playback: {file_path}. Song: '{song_title}'. Skipping.")
                asyncio.run_coroutine_threadsafe(
                    ctx.send(f"Error: Audio file for '{song_title}' not found. Skipping song."), bot.loop
                )
                cleanup(file_path) # Attempt to cleanup (e.g. if it was a broken symlink)
                current_song = None # Reset current_song as it's unplayable
                current_activity_name = "idle"
                play_next_song(voice_client, ctx)  # Try to play the next song in the queue.
                return

            # Play the audio. The 'after' parameter specifies a callback (song_finished)
            # to be executed once playback completes or is stopped.
            audio_source = discord.FFmpegPCMAudio(file_path)
            voice_client.play(
                audio_source,
                after=lambda e: song_finished(file_path, ctx, voice_client, error=e) # Pass voice_client
            )
            # Schedule the "Now playing" message to be sent in the event loop (ctx.send is async).
            asyncio.run_coroutine_threadsafe(ctx.send(f"Now playing: '{song_title}'"), bot.loop)

            # Reset or start the inactivity timer. This timer ensures the bot disconnects if idle.
            if inactive_timer:
                inactive_timer.cancel()
            inactive_timer = bot.loop.call_later(inactive_time, check_inactive, voice_client, ctx)
            logger.info(f"Inactivity timer reset/started for {inactive_time}s in guild '{ctx.guild.name}'.")

        except Exception as e:
            # Catch-all for unexpected errors during playback setup.
            logger.error(f"Error trying to play {file_path} for song '{song_title}': {e}", exc_info=True)
            asyncio.run_coroutine_threadsafe(
                ctx.send(f"An error occurred while trying to play '{song_title}'. Check logs for details."), bot.loop
            )
            cleanup(file_path) # Clean up the failed song file.
            current_song = None # Reset current_song.
            current_activity_name = "idle"
            play_next_song(voice_client, ctx) # Attempt to play the next song.

    else:  # If the queue is empty
        logger.info(f"Queue is empty for guild '{ctx.guild.name}'. No more songs to play.")
        current_song = None
        current_activity_name = "idle"
        # The inactivity timer is NOT reset here. If a song just finished and the queue is now empty,
        # the existing timer (started when that song began) will eventually call check_inactive.
        # If 'leave' was called, the timer is explicitly cancelled.
        # If 'play' is called on an empty queue, a new timer starts with the new song.
        # This ensures that check_inactive is the one to decide if the bot should leave.


def song_finished(file_path: str, ctx: commands.Context, voice_client: discord.VoiceClient, error=None):
    """
    Callback function executed when a song finishes playing or is stopped (e.g., by `!skip`).
    It cleans up the audio file and triggers playing the next song if available.

    Args:
        file_path (str): The path of the song that finished.
        ctx (commands.Context): The original command context.
        voice_client (discord.VoiceClient): The voice client instance.
        error (Exception, optional): Any error that occurred during playback. Defaults to None.
                                     Passed by the 'after' callback in voice_client.play().
    """
    if error:
        # Log any errors that occurred during playback.
        logger.error(f"Playback error for {file_path} in guild '{ctx.guild.name}': {error}")
        # Optionally, send a message to the channel, but be mindful of spamming if errors are frequent.
        # asyncio.run_coroutine_threadsafe(ctx.send(f"An error occurred with '{os.path.basename(file_path)}' during playback."), bot.loop)

    logger.info(f"Song finished: '{os.path.basename(file_path)}' in guild '{ctx.guild.name}'. Cleaning up file.")
    cleanup(file_path)  # Delete the audio file.

    # Check if the bot is still connected to a voice channel before trying to play the next song.
    if voice_client and voice_client.is_connected():
        play_next_song(voice_client, ctx)  # Proceed to play the next song.
    else:
        logger.info(f"Song finished, but bot is no longer connected to voice in guild '{ctx.guild.name}'. Clearing queue.")
        # If bot disconnected unexpectedly (e.g., kicked), clear queue and reset state.
        queue.clear()
        song_titles.clear()
        global current_song, current_activity_name, inactive_timer
        current_song = None
        current_activity_name = "idle"
        if inactive_timer:
            inactive_timer.cancel()
            inactive_timer = None


def check_inactive(voice_client: discord.VoiceClient, ctx: commands.Context):
    """
    Callback for the inactivity timer. Scheduled by `bot.loop.call_later`.
    Checks if the bot is inactive (i.e., not playing anything and queue is empty)
    and disconnects from the voice channel if it is.

    Args:
        voice_client (discord.VoiceClient): The voice client instance at the time the timer was set.
        ctx (commands.Context): The original command context (used for sending messages and guild info).
    """
    global current_song, inactive_timer, current_activity_name

    # Check if a song is supposed to be playing or is actively playing.
    # voice_client.is_playing() is a more reliable check for active audio transmission.
    if current_song or (voice_client and voice_client.is_playing()):
        logger.info(f"Inactivity check for guild '{ctx.guild.name}': Bot is active (song playing or current_song is set). Timer will be reset by new song if any.")
        return  # Bot is active, so do nothing. The timer would have been (or will be) reset by a new song.

    # If no song is set and nothing is playing, the bot is considered inactive.
    logger.info(f"Inactivity check: Bot is inactive in '{voice_client.channel.name if voice_client else 'Unknown Channel'}' of guild '{ctx.guild.name}'.")
    if voice_client and voice_client.is_connected():
        logger.info(f"Disconnecting due to inactivity from '{voice_client.channel.name}' in guild '{ctx.guild.name}'.")
        # Schedule disconnection and message sending on the bot's event loop.
        asyncio.run_coroutine_threadsafe(voice_client.disconnect(), bot.loop)
        asyncio.run_coroutine_threadsafe(ctx.send('Disconnected due to inactivity. The song queue has been cleared.'), bot.loop)

        # Fully clear queue and reset playback state.
        queue.clear()
        song_titles.clear()
        current_song = None  # Ensure current_song is None.
        current_activity_name = "idle"
        if inactive_timer:  # Should be this timer instance, but good practice to check.
            inactive_timer.cancel()
            inactive_timer = None
            logger.info(f"Inactivity timer cleared for guild '{ctx.guild.name}'.")
    else:
        logger.info(f"Inactivity check for guild '{ctx.guild.name}': Bot already disconnected or voice_client is invalid.")
        # Ensure timer is cleaned up if it somehow runs when bot is already disconnected.
        if inactive_timer:
            inactive_timer.cancel()
            inactive_timer = None


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

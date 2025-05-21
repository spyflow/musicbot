# MusicBot for Discord

This is a simple Discord bot for playing music from YouTube videos in a voice channel. The bot is written in Python and uses the Discord API and pytube library to fetch and play music.

> [!WARNING]  
> This project has been discontinued and will no longer receive updates.

## Features

- Play music from YouTube videos in a voice channel.
- Add songs to a queue and skip songs.
- Display current song as Discord presence.

## Getting Started

1. Clone this repository to your local machine.

```bash
git clone https://github.com/spyflow/musicbot.git
```

2. Install the required dependencies:

```bash
pip install discord.py yt-dlp pynacl python-dotenv
```
3. Install ffmpeg
```bash
sudo apt install ffmpeg
```

## Environment Variables

This bot requires certain API keys and tokens to be configured as environment variables.

1.  **Create a `.env` file** in the root directory of the project.
2.  **Add the following lines** to the `.env` file, replacing `your_youtube_api_key_here` and `your_discord_bot_token_here` with your actual credentials:

    ```env
    YOUTUBE_API_KEY=your_youtube_api_key_here
    DISCORD_BOT_TOKEN=your_discord_bot_token_here
    ```

3.  **Install `python-dotenv`:**
    If you are using a virtual environment, make sure to install `python-dotenv` which is used to load these variables from the `.env` file:
    ```bash
    pip install python-dotenv
    ```
    You will also need to add `import dotenv` and `dotenv.load_dotenv()` at the beginning of `bot.py`.

4. [Create a Discord bot](https://discordpy.readthedocs.io/en/stable/discord.html) and obtain its token.

5. Run the bot:

```bash
python bot.py
```

## Usage

- Invite the bot to your Discord server.
- Use the `!play` command followed by a YouTube URL to play a song.
- Use the `!skip` command to skip the current song.
- Use the `!leave` command to make the bot leave the voice channel.
- Use the `!ping` command to check the bot's latency.
- Use the `!author` or `!autor` command to get information about the author.

## Contributing

Contributions are welcome! If you'd like to contribute to this project, please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bug fix.
3. Make your changes and test them thoroughly.
4. Create a pull request with a clear description of your changes.

## Contact

- Author: SpyFLow
- Discord: [Discord](https://discord.com/users/533093302031876096)
- GitHub: [https://github.com/spyflow](https://github.com/spyflow)
- Email: [contact.spyflow@spyflow.net](mailto:contact.spyflow@spyflow.net)

Thank you for using the MusicBot! Enjoy listening to music in your Discord server!

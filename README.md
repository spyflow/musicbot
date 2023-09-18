# MusicBot for Discord

This is a simple Discord bot for playing music from YouTube videos in a voice channel. The bot is written in Python and uses the Discord API and pytube library to fetch and play music.

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
pip install discord.py pytube
```
3. Install ffmpeg
```bash
sudo apt install ffmpeg
```   

4. [Create a Discord bot](https://discordpy.readthedocs.io/en/stable/discord.html) and obtain its token.

5. Replace `'YOUR_BOT_TOKEN'` in the last line of the code with your bot's token.

6. Run the bot:

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
- Discord: spyflow
- GitHub: [https://github.com/spyflow](https://github.com/spyflow)
- Email: [contact.spyflow@spyflow.net](mailto:contact.spyflow@spyflow.net)

Thank you for using the MusicBot! Enjoy listening to music in your Discord server!

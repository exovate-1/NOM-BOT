import discord
from discord.ext import commands
import asyncio
import random
import json
import os
import yt_dlp
import functools
import re
from datetime import timedelta
import subprocess
import shutil

# --- Import dotenv and load environment variables ---
from dotenv import load_dotenv # Import load_dotenv
load_dotenv() # Load the environment variables from .env file

# --- Configuration ---
# Get the bot token from environment variables (now loaded from .env)
TOKEN = os.getenv("DISCORD_BOT_TOKEN") 

if TOKEN is None:
    print("ERROR: DISCORD_BOT_TOKEN environment variable not set. Please set it in your .env file or system environment.")
    exit(1) # Exit if token is not found

# Define Discord Intents: These tell Discord what events your bot wants to receive.
intents = discord.Intents.default()
intents.message_content = True  # Required for reading command messages (less crucial for slash commands but good to have)
intents.members = True          # Required for on_member_join and member tracking
intents.voice_states = True     # Required for music features (connecting to voice)

# Initialize the bot
# The command_prefix is still needed for regular commands, but slash commands don't use it.
bot = commands.Bot(command_prefix="!", intents=intents) 

# --- Data Storage (for giveaways and members) ---
GIVEAWAY_DATA_FILE = 'giveaways.json'
MEMBER_DATA_FILE = 'members.json'

def load_data(filename):
    """Loads data from a JSON file."""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {} # Return empty dictionary if file doesn't exist

def save_data(data, filename):
    """Saves data to a JSON file."""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4) # Pretty print JSON for readability

# Load existing data when the bot starts
giveaways = load_data(GIVEAWAY_DATA_FILE)
members_db = load_data(MEMBER_DATA_FILE)

# --- Music Bot Configuration (for SoundCloud) ---
# Suppress annoying warnings from yt-dlp
yt_dlp.utils.bug_reports_message = lambda: ''

# yt-dlp options for extracting audio information
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True, # Set to True to prevent playing entire playlists by default
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0', # Bind to ipv4 since ipv6 addresses can cause issues
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5' # Helps with stream stability
}

# Initialize yt-dlp with our options
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# Custom class to handle audio source for discord.py
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url') # The actual stream URL
        self.webpage_url = data.get('webpage_url') # Original webpage URL (e.g., SoundCloud link)
        self.duration = data.get('duration') # Song duration in seconds

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        # run_in_executor allows running blocking code (like yt-dlp extraction)
        # in a separate thread so the bot's main loop doesn't freeze.
        data = await loop.run_in_executor(None, functools.partial(ytdl.extract_info, url, download=not stream))

        if 'entries' in data:
            # If a playlist was detected (e.g., a SoundCloud set), take the first entry.
            # You'd need more complex logic for full playlist queuing.
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord and syncs slash commands."""
    print(f'💖 {bot.user.name} is ready to spread cuteness! ✨')
    # Set the bot's activity/presence
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="cute SoundCloud tunes! 🎶"))
    
    # --- FFmpeg Debugging Check ---
    # This block will print messages to your terminal when the bot starts,
    # helping you confirm if FFmpeg is found and executable.
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"DEBUG: FFmpeg found at: {ffmpeg_path}")
        try:
            process = subprocess.run([ffmpeg_path, '-version'], capture_output=True, text=True, check=True)
            print(f"DEBUG: FFmpeg version output:\n{process.stdout.splitlines()[0]}")
        except subprocess.CalledProcessError as e:
            print(f"DEBUG ERROR: FFmpeg command failed to run: {e}")
            print(f"DEBUG ERROR: Stderr: {e.stderr}")
        except FileNotFoundError:
            print("DEBUG ERROR: FFmpeg executable could not be found by subprocess. (Shouldn't happen if shutil.which worked)")
    else:
        print("DEBUG: FFmpeg not found in system PATH by shutil.which(). Music commands might fail!")
    # --- End FFmpeg Debugging Check ---

    # Sync slash commands: Important for them to appear in Discord
    try:
        # Guild sync is faster for testing, global sync can take up to an hour
        # If you want global commands, use await bot.tree.sync() without an argument
        synced = await bot.tree.sync() # or await bot.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID)) for specific guild
        print(f"Synced {len(synced)} command(s) 🚀")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.event
async def on_member_join(member):
    """Records new members joining the server."""
    guild_id = str(member.guild.id)
    user_id = str(member.id)

    if guild_id not in members_db:
        members_db[guild_id] = {}
    
    # Store join date and initialize giveaway wins
    members_db[guild_id][user_id] = {
        "joined_at": str(member.joined_at.isoformat()), # Store as ISO format string
        "giveaways_won": 0
    }
    save_data(members_db, MEMBER_DATA_FILE)
    print(f"Recorded new member: {member.name} in {member.guild.name}")
    # You could send a cute welcome message to a specific channel here!

# --- Music Commands (as Slash Commands) ---
@bot.tree.command(name='play', description='Plays a song from SoundCloud! Use a link or search query.')
@discord.app_commands.describe(query='The SoundCloud link or search query (e.g., "cute song", "soundcloud.com/track/...")')
async def play(interaction: discord.Interaction, query: str):
    """
    Plays a song from SoundCloud.
    Supports SoundCloud URLs directly or searches SoundCloud based on the query.
    Uses slash command interaction.
    """
    # Defer the interaction response to show "Bot is thinking..."
    # This is crucial because music loading can take a few seconds,
    # and Discord requires a response within a short timeframe (3 seconds).
    await interaction.response.defer(ephemeral=False) # ephemeral=False means everyone sees the response

    # Check if user is in a voice channel
    if not interaction.user.voice:
        await interaction.followup.send("Aw, you're not in a voice channel! Please join one first. 🥺")
        return

    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        # If bot is not in a voice channel, connect to the user's channel
        try:
            voice_client = await channel.connect()
        except asyncio.TimeoutError:
            await interaction.followup.send("Couldn't connect to the voice channel in time. 😥")
            return
        except discord.ClientException:
            await interaction.followup.send("I'm already connected to a voice channel somewhere else! 😫")
            return
    else:
        # If bot is in another channel, move to the user's channel
        if voice_client.channel != channel:
            await voice_client.move_to(channel)

    music_source_url = query
    # Regex to detect common SoundCloud URLs
    soundcloud_regex = r"^(https?:\/\/)?(www\.)?soundcloud\.com\/.+"
    
    if not re.match(soundcloud_regex, query):
        # If it's not a SoundCloud URL, force a SoundCloud search
        music_source_url = f"scsearch:{query}" 

    try:
        # Stop any currently playing audio before starting a new one
        if voice_client.is_playing():
            voice_client.stop()

        player = await YTDLSource.from_url(music_source_url, loop=bot.loop, stream=True)
        voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)
        
        embed = discord.Embed(
            title="🎶 Now Playing on SoundCloud! ✨",
            description=f"**[{player.title}]({player.webpage_url})**\n\n_Enjoy the cute tunes!_ 💖",
            color=discord.Color.from_rgb(255, 192, 203) # Pastel Pink
        )
        embed.set_thumbnail(url="https://i.imgur.com/your_cute_music_icon.png") # Replace with a cute music icon URL
        
        # Format duration nicely (e.g., 3:45)
        if player.duration:
            minutes = player.duration // 60
            seconds = player.duration % 60
            embed.set_footer(text=f"Duration: {minutes}:{seconds:02d} | Requested by {interaction.user.display_name}")
        else:
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        # Send the combined "searching" and "now playing" message as a followup to the deferred response
        await interaction.followup.send(embed=embed)

    except Exception as e:
        error_message = str(e)
        if "ffmpeg was not found" in error_message:
            await interaction.followup.send(
                "Oopsie! Couldn't play that song. **FFmpeg was not found!** 💔\n"
                "Please make sure FFmpeg is installed on the server and added to its PATH. "
                "Contact the bot owner for help if you're not the owner. 🥺"
            )
        else:
            await interaction.followup.send(
                f"Oopsie! Couldn't play that song from SoundCloud. Error: `{e}` 💔\n"
                f"Please try a different link or search query!"
            )

@bot.tree.command(name='stop', description='Stops the music and disconnects! 🛑')
async def stop(interaction: discord.Interaction):
    """Stops the current music and disconnects the bot from the voice channel."""
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        await interaction.response.send_message("Music stopped! Bye-bye for now! 👋")
    else:
        await interaction.response.send_message("I'm not playing anything right now! 🤫", ephemeral=True)

@bot.tree.command(name='pause', description='Pauses the music! ⏸️')
async def pause(interaction: discord.Interaction):
    """Pauses the currently playing music."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await interaction.response.send_message("Music paused! Take a little break. ⏸️")
    else:
        await interaction.response.send_message("I'm not playing anything to pause! 🎶", ephemeral=True)

@bot.tree.command(name='resume', description='Resumes the music! ▶️')
async def resume(interaction: discord.Interaction):
    """Resumes the paused music."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await interaction.response.send_message("Music resumed! Let's get back to the cute tunes! ▶️")
    else:
        await interaction.response.send_message("I'm not paused right now! 🎶", ephemeral=True)

# --- Giveaway Commands (as Slash Commands) ---
@bot.tree.command(name='giveaway', description='Start a super cute giveaway! 🎉')
@discord.app_commands.describe(
    duration='How long the giveaway lasts (e.g., 30s, 5m, 1h, 2d)',
    winners='Number of winners',
    prize='The prize for the giveaway'
)
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def start_giveaway(interaction: discord.Interaction, duration: str, winners: int, prize: str):
    """
    Starts a new giveaway.
    Example: /giveaway duration:1h winners:3 prize:"Cute Plushie"
    """
    await interaction.response.defer(ephemeral=False) # Defer publicly

    time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    
    try:
        amount = int(duration[:-1])
        unit = duration[-1].lower()
        total_seconds = amount * time_units.get(unit, 0)
    except (ValueError, IndexError):
        await interaction.followup.send("Please provide a valid duration (e.g., `30s`, `5m`, `1h`, `2d`). ⏳")
        return

    if total_seconds <= 0:
        await interaction.followup.send("Giveaway duration must be positive! 💖")
        return
    if winners <= 0:
        await interaction.followup.send("You need at least one winner for a cute giveaway! 🎁")
        return

    end_time = discord.utils.utcnow() + timedelta(seconds=total_seconds)

    embed = discord.Embed(
        title=f"✨ **Giveaway Alert!** ✨",
        description=f"Win: **{prize}**\n\nReact with 🎉 to enter!\n\nEnds: <t:{int(end_time.timestamp())}:R> (at <t:{int(end_time.timestamp())}:T>)",
        color=discord.Color.from_rgb(255, 105, 180) # Hot Pink
    )
    embed.set_footer(text=f"Hosted by {interaction.user.display_name} 💖 | Winners: {winners}")
    embed.set_thumbnail(url="https://i.imgur.com/your_cute_giveaway_icon.png") # Replace with a cute giveaway icon URL

    message = await interaction.followup.send(embed=embed)
    await message.add_reaction("🎉") # Add the reaction for users to enter

    # Store giveaway data
    giveaways[str(message.id)] = {
        "channel_id": interaction.channel.id,
        "prize": prize,
        "winners": winners,
        "end_time": end_time.timestamp(),
        "host_id": interaction.user.id,
        "participants": [] # Participants will be gathered from reactions later
    }
    save_data(giveaways, GIVEAWAY_DATA_FILE)

    # Schedule the giveaway to end after the specified duration
    await asyncio.sleep(total_seconds)
    await end_giveaway(message.id)

# Error handling for has_permissions specific to slash commands
@start_giveaway.error
async def start_giveaway_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.followup.send("Aww, you don't have the cute permissions to use that command! 🚫 (Requires `Manage Server` permission)", ephemeral=True) 
    elif isinstance(error, discord.app_commands.CommandOnCooldown): # Example if you add cooldowns later
        await interaction.followup.send(f"This command is on cooldown! Try again in {error.retry_after:.1f} seconds. ⏳", ephemeral=True)
    else:
        print(f"An unexpected error occurred in /giveaway: {error}")
        await interaction.followup.send("Oh dear! An unexpected error happened. Please try again later! 🥺", ephemeral=True)


async def end_giveaway(message_id):
    """Handles the ending of a giveaway, selects winners, and announces them."""
    if str(message_id) not in giveaways:
        return # Giveaway might have been deleted or already ended

    giveaway = giveaways[str(message_id)]
    channel = bot.get_channel(giveaway["channel_id"])
    if not channel:
        return # Channel might have been deleted or bot lost access

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        print(f"Giveaway message {message_id} not found in channel {channel.id}. Skipping end.")
        del giveaways[str(message_id)]
        save_data(giveaways, GIVEAWAY_DATA_FILE)
        return

    reactions = message.reactions
    participants = []

    # Iterate through reactions to find users who reacted with 🎉
    for reaction in reactions:
        if str(reaction.emoji) == "🎉":
            # Fetch all users who reacted (can be slow for many reactions)
            async for user in reaction.users():
                if not user.bot: # Exclude bots from participants
                    participants.append(user)
            break

    if not participants:
        # No participants entered the giveaway
        embed = discord.Embed(
            title="Aww, no winners! 😭",
            description=f"The giveaway for **{giveaway['prize']}** ended with no participants. Better luck next time!",
            color=discord.Color.light_grey()
        )
        await channel.send(embed=embed)
    else:
        # Select winners randomly, ensuring not to pick more winners than participants
        actual_winners = min(giveaway["winners"], len(participants))
        selected_winners = random.sample(participants, actual_winners)

        winner_mentions = [winner.mention for winner in selected_winners]
        winner_text = ", ".join(winner_mentions)

        embed = discord.Embed(
            title="🎉 **Giveaway Ended!** 🎉",
            description=f"The giveaway for **{giveaway['prize']}** has concluded!\n\n**Winners:** {winner_text}!\n\n_Congratulations, cuties!_ 💖",
            color=discord.Color.from_rgb(173, 216, 230) # Light Blue
        )
        embed.set_thumbnail(url="https://i.imgur.com/your_cute_trophy_icon.png") # Replace with a cute trophy icon URL
        await channel.send(embed=embed)

        # Update member data for winners
        for winner in selected_winners:
            guild_id = str(channel.guild.id)
            user_id = str(winner.id)
            if guild_id not in members_db:
                members_db[guild_id] = {}
            if user_id not in members_db[guild_id]:
                # If a winner somehow isn't in DB (e.g., bot started after they joined)
                members_db[guild_id][user_id] = {
                    "joined_at": str(winner.joined_at.isoformat()) if winner.joined_at else "Unknown",
                    "giveaways_won": 0
                }
            members_db[guild_id][user_id]["giveaways_won"] += 1
        save_data(members_db, MEMBER_DATA_FILE)

    # Remove the giveaway from active list
    del giveaways[str(message_id)]
    save_data(giveaways, MEMBER_DATA_FILE) # Corrected to save to MEMBER_DATA_FILE

@bot.tree.command(name='reroll', description='Reroll a giveaway winner! 🍀')
@discord.app_commands.describe(message_id='The message ID of the original giveaway post to reroll')
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def reroll_giveaway(interaction: discord.Interaction, message_id: str): # message_id as string for flexible input
    """Rerolls a winner for a specified giveaway message."""
    await interaction.response.defer(ephemeral=False)

    try:
        # Fetch the original giveaway message
        giveaway_message = await interaction.channel.fetch_message(int(message_id))
        
        reactions = giveaway_message.reactions
        participants = []

        for reaction in reactions:
            if str(reaction.emoji) == "🎉":
                async for user in reaction.users():
                    if not user.bot:
                        participants.append(user)
                break
        
        if not participants:
            await interaction.followup.send("No participants found to reroll from! 😔")
            return

        # Select a new random winner
        new_winner = random.choice(participants)
        
        embed = discord.Embed(
            title="🍀 **Reroll!** 🍀",
            description=f"A new winner has been chosen for the giveaway! Congrats to {new_winner.mention}!",
            color=discord.Color.from_rgb(152, 251, 152) # Pale Green
        )
        await interaction.followup.send(embed=embed)

        # Update member's giveaway wins for the new winner
        guild_id = str(interaction.guild.id)
        user_id = str(new_winner.id)
        if guild_id not in members_db:
            members_db[guild_id] = {}
        if user_id not in members_db[guild_id]:
            members_db[guild_id][user_id] = {
                "joined_at": str(new_winner.joined_at.isoformat()) if new_winner.joined_at else "Unknown",
                "giveaways_won": 0
            }
        members_db[guild_id][user_id]["giveaways_won"] += 1
        save_data(members_db, MEMBER_DATA_FILE)

    except discord.NotFound:
        await interaction.followup.send("Couldn't find a giveaway message with that ID. Are you sure it's the right one? 🤔")
    except Exception as e:
        await interaction.followup.send(f"An error occurred during reroll: `{e}` 😩")

@reroll_giveaway.error
async def reroll_giveaway_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.followup.send("Aww, you don't have the cute permissions to use that command! 🚫 (Requires `Manage Server` permission)", ephemeral=True)
    else:
        print(f"An unexpected error occurred in /reroll: {error}")
        await interaction.followup.send("Oh dear! An unexpected error happened. Please try again later! 🥺", ephemeral=True)


# --- Member Tracking Commands (as Slash Commands) ---
@bot.tree.command(name='myprofile', description='See your cute stats! 🌸')
async def my_profile(interaction: discord.Interaction):
    """Displays the user's recorded profile, including join date and giveaway wins."""
    await interaction.response.defer(ephemeral=False) # Make response public

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    if guild_id in members_db and user_id in members_db[guild_id]:
        member_data = members_db[guild_id][user_id]
        joined_at_iso = member_data.get("joined_at", "Unknown")
        giveaways_won = member_data.get("giveaways_won", 0)

        # Convert ISO format string back to datetime for Discord's timestamp formatting
        try:
            joined_datetime = discord.utils.parse_time(joined_at_iso)
            joined_text = f"<t:{int(joined_datetime.timestamp())}:F>" # Full timestamp
        except ValueError:
            joined_text = joined_at_iso # Fallback if parsing fails

        embed = discord.Embed(
            title=f"🌸 {interaction.user.display_name}'s Cute Profile 🌸",
            description=f"Joined the server: **{joined_text}**\nGiveaways won: **{giveaways_won}** 🎉",
            color=discord.Color.from_rgb(255, 223, 0) # Gold
        )
        # Use user's avatar if available, otherwise a default cute icon
        embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else "https://i.imgur.com/your_cute_avatar_icon.png") 
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("Aww, I don't have your profile data yet! It usually populates when you join the server or win a giveaway. 🥺")

@bot.tree.command(name='guildstats', description='See adorable server stats! 📊')
@discord.app_commands.checks.has_permissions(manage_guild=True)
async def guild_stats(interaction: discord.Interaction):
    """Displays adorable statistics for the current guild."""
    await interaction.response.defer(ephemeral=False)

    guild_id = str(interaction.guild.id)
    total_members = interaction.guild.member_count # Use member_count for total members
    
    total_giveaways_won_by_server_members = 0
    if guild_id in members_db:
        for user_data in members_db[guild_id].values():
            total_giveaways_won_by_server_members += user_data.get("giveaways_won", 0)

    embed = discord.Embed(
        title=f"📊 {interaction.guild.name}'s Adorable Stats! 📊",
        description=f"Total Members: **{total_members}** 👥\nTotal Giveaways Won by Members: **{total_giveaways_won_by_server_members}** 🏆",
        color=discord.Color.from_rgb(180, 180, 255) # Lavender
    )
    await interaction.followup.send(embed=embed)

@guild_stats.error
async def guild_stats_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.followup.send("Aww, you don't have the cute permissions to use that command! 🚫 (Requires `Manage Server` permission)", ephemeral=True)
    else:
        print(f"An unexpected error occurred in /guildstats: {error}")
        await interaction.followup.send("Oh dear! An unexpected error happened. Please try again later! 🥺", ephemeral=True)

# --- Run the Bot ---
bot.run(TOKEN)

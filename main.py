import os
import urllib.parse
import requests
import re
import string
import time
import random
import json
from yt_dlp import YoutubeDL
from tkinter import Tk, ttk, filedialog, StringVar, messagebox
from dotenv import load_dotenv
import spotipy  
from spotipy import SpotifyOAuth
from spotipy.oauth2 import SpotifyOauthError
import threading
import logging
from fake_useragent import UserAgent
import subprocess
import sys
import platform
import tempfile
import shutil
from pydub import AudioSegment

# Setup logging for troubleshooting
logging.basicConfig(filename="downloader.log", level=logging.INFO, format='%(asctime)s - %(message)s')

# Check for required dependencies
def check_dependencies():
    missing_deps = []
    
    # Check for FFmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        missing_deps.append("FFmpeg")
    
    # Check for aria2c (optional)
    try:
        subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        logging.warning("aria2c not found - some download methods may be slower")
    
    if missing_deps:
        error_msg = "Missing required dependencies:\n\n"
        for dep in missing_deps:
            error_msg += f"- {dep}\n"
        error_msg += "\nPlease install the missing dependencies:\n"
        error_msg += "Windows: Download from https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip\n"
        error_msg += "macOS: brew install ffmpeg\n"
        error_msg += "Linux: sudo apt-get install ffmpeg"
        messagebox.showerror("Missing Dependencies", error_msg)
        return False
    return True

# Load environment variables
load_dotenv(dotenv_path='.env')

# Setup Spotify API credentials
client_id = os.getenv("SPOTIFY_CLIENT_ID")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

# Create an instance of the SpotifyOAuth class
try:
    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="user-library-read playlist-read-private playlist-read-collaborative",
    )
except SpotifyOauthError as e:
    print(f"Spotify OAuth setup error: {e}")
    logging.error(f"Spotify OAuth setup error: {e}")
    exit(1)

# Get access token
token_info = sp_oauth.get_cached_token()
if not token_info:
    auth_url = sp_oauth.get_authorize_url()
    print("Please go to this URL and authorize the app:", auth_url)
    auth_code = input("Enter the authorization code: ")
    token_info = sp_oauth.get_access_token(auth_code)

access_token = token_info["access_token"]
playlists = {}

def get_auth_header(token):
    return {"Authorization": "Bearer " + token}

# Function to update the dropdown menu
def update_playlist_dropdown():
    playlist_names = list(playlists.keys())
    playlist_menu = playlist_dropdown["menu"]
    playlist_menu.delete(0, "end")
    for name in playlist_names:
        playlist_menu.add_command(label=name, 
                                  command=lambda value=name: selected_playlist.set(value))
    if playlist_names:
        selected_playlist.set(playlist_names[0])

# Function to fetch user playlists
def get_user_playlists(token):
    print("Retrieving user playlists...")
    headers = get_auth_header(token)
    response = requests.get("https://api.spotify.com/v1/me/playlists", headers=headers)
    response_json = response.json()
    for item in response_json["items"]:
        playlists[item["name"]] = item["id"]
    print("Playlists retrieved successfully.")
    update_playlist_dropdown()

# Sanitize filename to remove invalid characters for file saving
def sanitize_filename(filename):
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    return ''.join(c for c in filename if c in valid_chars)

# Global variable to control the downloading process
is_downloading = True

# Function to stop the download process
def stop_downloading():
    global is_downloading
    is_downloading = False
    status_label.config(text="Downloading stopped.")

# Fetch tracks from the selected playlist and display the number of tracks retrieved
def get_playlist_tracks(token, playlist_id):
    print(f"Retrieving tracks for playlist ID: {playlist_id}")
    
    # Setup Spotipy with the provided token
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri))
    
    tracks = []
    limit = 100  # Spotify's maximum limit per request
    offset = 0
    
    # Loop to fetch tracks with pagination using offset
    while True:
        response = sp.playlist_tracks(playlist_id, limit=limit, offset=offset)
        tracks.extend(response['items'])
        
        # Logging and print status
        print(f"Fetched {len(response['items'])} tracks, total: {len(tracks)}")
        
        # Break the loop if fewer than 'limit' tracks are returned (i.e., we've fetched all tracks)
        if len(response['items']) < limit:
            break
        
        # Increment the offset for the next batch of tracks
        offset += limit

    total_tracks = len(tracks)
    print(f"{total_tracks} tracks retrieved successfully.")
    
    # Update the status label to show the number of tracks retrieved
    screen.after(0, lambda: status_label.config(text=f"{total_tracks} tracks retrieved successfully."))
    
    return tracks

# Function to update the progress in the GUI
def update_status(current_track, total_tracks):
    status_label.config(text=f"Downloading song {current_track} of {total_tracks}...")

def get_random_user_agent():
    try:
        ua = UserAgent()
        return ua.random
    except:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

def search_youtube(query):
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
        'Keep-Alive': 'timeout=15, max=100',
        'Connection': 'keep-alive',
    }
    
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        video_ids = re.findall(r"watch\?v=(\S{11})", response.text)
        return list(set(video_ids))[:3]  # Return top 3 unique video IDs
    except Exception as e:
        logging.error(f"Error searching YouTube: {e}")
        return []

def check_chrome_cookies():
    """Check if Chrome cookies are available"""
    try:
        # Different paths for different operating systems
        if platform.system() == "Windows":
            chrome_path = os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
        elif platform.system() == "Darwin":  # macOS
            chrome_path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Google", "Chrome")
        elif platform.system() == "Linux":
            chrome_path = os.path.join(os.path.expanduser("~"), ".config", "google-chrome")
        else:
            return False
            
        # Check if the directory exists
        if not os.path.exists(chrome_path):
            logging.warning(f"Chrome path not found: {chrome_path}")
            return False
            
        # Check for Default profile
        default_profile = os.path.join(chrome_path, "Default")
        if not os.path.exists(default_profile):
            # Try to find any profile
            profiles = [d for d in os.listdir(chrome_path) if os.path.isdir(os.path.join(chrome_path, d)) and d.startswith("Profile")]
            if not profiles:
                logging.warning("No Chrome profiles found")
                return False
                
        return True
    except Exception as e:
        logging.error(f"Error checking Chrome cookies: {e}")
        return False

def convert_to_mp3(input_path, output_path):
    """Convert audio file to MP3 using pydub"""
    try:
        audio = AudioSegment.from_file(input_path)
        audio.export(output_path, format='mp3', bitrate='192k')
        return True
    except Exception as e:
        logging.error(f"Error converting audio with pydub: {e}")
        return False

def download_with_ytdlp(video_url, output_path, track_name):
    """Download a video using yt-dlp with advanced options to avoid bot detection"""
    try:
        # Create a temporary file for the output
        temp_output = os.path.join(os.path.dirname(output_path), f"temp_{track_name}.%(ext)s")
        
        # Advanced options to avoid bot detection
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Keep-Alive': 'timeout=15, max=100',
                'Connection': 'keep-alive',
            },
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'file_access_retries': 10,
            'extractor_retries': 10,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'geo_bypass_ip_block': '0.0.0.0/0',
            'merge_output_format': 'mp3',
        }
        
        # Only add cookies if Chrome is available
        if check_chrome_cookies():
            try:
                ydl_opts['cookiesfrombrowser'] = ('chrome',)
                logging.info("Using Chrome cookies for download")
            except Exception as e:
                logging.warning(f"Failed to use Chrome cookies: {e}")
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Find the downloaded file and convert it to MP3 if needed
        temp_dir = os.path.dirname(temp_output)
        for file in os.listdir(temp_dir):
            if file.startswith(f"temp_{track_name}"):
                input_file = os.path.join(temp_dir, file)
                if not file.endswith('.mp3'):
                    if convert_to_mp3(input_file, output_path):
                        os.remove(input_file)
                        return True
                    return False
                else:
                    os.rename(input_file, output_path)
                    return True
                
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp download: {e}")
        return False

def download_with_invidious(video_id, output_path):
    """Try to download using Invidious API as a fallback"""
    try:
        # List of Invidious instances
        instances = [
            "https://invidious.snopyta.org",
            "https://invidious.kavin.rocks",
            "https://invidious.tube",
            "https://invidious.xyz",
            "https://invidious.slipfox.xyz",
            "https://invidious.privacydev.net",
            "https://invidious.sethforprivacy.com",
            "https://invidious.weblibre.org",
            "https://invidious.esmailelbob.xyz",
            "https://invidious.poast.org",
            "https://invidious.moomoo.me",
            "https://invidious.1d4.us",
            "https://invidious.kavin.rocks",
            "https://invidious.woodland.cafe",
            "https://invidious.rawbit.ninja"
        ]
        
        # Try each instance until one works
        for instance in instances:
            try:
                # Get video info from Invidious
                api_url = f"{instance}/api/v1/videos/{video_id}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Find the best audio format
                    audio_formats = [f for f in data.get('adaptiveFormats', []) 
                                    if f.get('type', '').startswith('audio/')]
                    
                    if audio_formats:
                        # Sort by bitrate and get the best one
                        best_audio = max(audio_formats, key=lambda x: x.get('bitrate', 0))
                        audio_url = best_audio.get('url')
                        
                        if audio_url:
                            # Download the audio
                            audio_response = requests.get(audio_url, stream=True, timeout=30)
                            
                            if audio_response.status_code == 200:
                                with open(output_path, 'wb') as f:
                                    for chunk in audio_response.iter_content(chunk_size=8192):
                                        if chunk:
                                            f.write(chunk)
                                return True
            except Exception as e:
                logging.error(f"Error with Invidious instance {instance}: {e}")
                continue
                
        return False
    except Exception as e:
        logging.error(f"Error in Invidious download: {e}")
        return False

def download_with_yt_dlp_cli(video_url, output_path):
    """Try to download using yt-dlp CLI as a last resort"""
    try:
        # Create a temporary file for the output
        temp_output = os.path.join(os.path.dirname(output_path), f"temp_cli_{os.path.basename(output_path)}")
        
        # Build the command
        cmd = [
            "yt-dlp",
            "--format", "bestaudio/best",
            "--output", temp_output,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192K",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "--geo-bypass",
            "--no-check-certificate",
            video_url
        ]
        
        # Only add cookies if Chrome is available
        if check_chrome_cookies():
            cmd.extend(["--cookies-from-browser", "chrome"])
        
        # Run the command
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # Find the downloaded file and rename it to the final output path
            temp_dir = os.path.dirname(temp_output)
            for file in os.listdir(temp_dir):
                if file.startswith("temp_cli_") and file.endswith(".mp3"):
                    os.rename(os.path.join(temp_dir, file), output_path)
                    return True
                    
        logging.error(f"yt-dlp CLI error: {result.stderr}")
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp CLI download: {e}")
        return False

def download_with_yt_dlp_direct(video_url, output_path):
    """Try to download using yt-dlp with direct options"""
    try:
        # Create a temporary file for the output
        temp_output = os.path.join(os.path.dirname(output_path), f"temp_direct_{os.path.basename(output_path)}")
        
        # Simple options without cookies
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': get_random_user_agent(),
            },
            'socket_timeout': 30,
            'retries': 10,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Find the downloaded file and rename it to the final output path
        temp_dir = os.path.dirname(temp_output)
        for file in os.listdir(temp_dir):
            if file.startswith("temp_direct_") and file.endswith(".mp3"):
                os.rename(os.path.join(temp_dir, file), output_path)
                return True
                
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp direct download: {e}")
        return False

def download_with_yt_dlp_alternative(video_url, output_path):
    """Try to download using yt-dlp with alternative options"""
    try:
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp()
        temp_output = os.path.join(temp_dir, "output.%(ext)s")
        
        # Alternative options that might bypass bot detection
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Keep-Alive': 'timeout=15, max=100',
                'Connection': 'keep-alive',
            },
            'socket_timeout': 30,
            'retries': 10,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'geo_bypass_ip_block': '0.0.0.0/0',
            'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
            'merge_output_format': 'mp3',
        }
        
        # Only add aria2c if it's available
        try:
            subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
            ydl_opts['external_downloader'] = 'aria2c'
            ydl_opts['external_downloader_args'] = ['--min-split-size=1M', '--max-connection-per-server=16', '--max-concurrent-downloads=16', '--split=16']
        except (subprocess.SubprocessError, FileNotFoundError):
            logging.warning("aria2c not found - using default downloader")
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Find the downloaded file and convert it to MP3 if needed
        for file in os.listdir(temp_dir):
            input_file = os.path.join(temp_dir, file)
            if not file.endswith('.mp3'):
                if convert_to_mp3(input_file, output_path):
                    shutil.rmtree(temp_dir)
                    return True
            else:
                shutil.copy(input_file, output_path)
                shutil.rmtree(temp_dir)
                return True
                
        shutil.rmtree(temp_dir)
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp alternative download: {e}")
        try:
            shutil.rmtree(temp_dir)
        except:
            pass
        return False

def download_with_yt_dlp_legacy(video_url, output_path):
    """Try to download using yt-dlp with legacy options"""
    try:
        # Create a temporary file for the output
        temp_output = os.path.join(os.path.dirname(output_path), f"temp_legacy_{os.path.basename(output_path)}")
        
        # Legacy options that might work better
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            },
            'socket_timeout': 30,
            'retries': 10,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
            'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
            'legacy_server_connect': True,
            'merge_output_format': 'mp3',
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Find the downloaded file and convert it to MP3 if needed
        temp_dir = os.path.dirname(temp_output)
        for file in os.listdir(temp_dir):
            if file.startswith("temp_legacy_"):
                input_file = os.path.join(temp_dir, file)
                if not file.endswith('.mp3'):
                    if convert_to_mp3(input_file, output_path):
                        os.remove(input_file)
                        return True
                    return False
                else:
                    os.rename(input_file, output_path)
                    return True
                
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp legacy download: {e}")
        return False

def download_with_yt_dlp_anonymous(video_url, output_path):
    """Try to download using yt-dlp with anonymous options"""
    try:
        # Create a temporary file for the output
        temp_output = os.path.join(os.path.dirname(output_path), f"temp_anon_{os.path.basename(output_path)}")
        
        # Anonymous options that might bypass bot detection
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': temp_output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            },
            'socket_timeout': 30,
            'retries': 10,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'geo_bypass_ip_block': '0.0.0.0/0',
            'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
            'legacy_server_connect': True,
            'no_cookies': True,
            'no_cache_dir': True,
            'merge_output_format': 'mp3',
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
            
        # Find the downloaded file and convert it to MP3 if needed
        temp_dir = os.path.dirname(temp_output)
        for file in os.listdir(temp_dir):
            if file.startswith("temp_anon_"):
                input_file = os.path.join(temp_dir, file)
                if not file.endswith('.mp3'):
                    if convert_to_mp3(input_file, output_path):
                        os.remove(input_file)
                        return True
                    return False
                else:
                    os.rename(input_file, output_path)
                    return True
                
        return False
    except Exception as e:
        logging.error(f"Error in yt-dlp anonymous download: {e}")
        return False

# Download songs by searching YouTube and using yt-dlp
def download_songs(selected_playlist):
    global is_downloading
    is_downloading = True

    user_path = path_label.cget("text")
    
    # Error handling for invalid download path
    if user_path == "Select Download Path:":
        messagebox.showerror("Error", "Please select a valid download path.")
        return

    download_folder = os.path.join(user_path, sanitize_filename(selected_playlist).replace(" ", "_"))
    
    # Error handling for directory creation
    try:
        if not os.path.exists(download_folder):
            os.makedirs(download_folder)
    except OSError as e:
        messagebox.showerror("Error", f"Failed to create download directory: {e}")
        return

    playlist_id = playlists[selected_playlist]
    tracks = get_playlist_tracks(access_token, playlist_id)
    total_tracks = len(tracks)

    # Retry logic for track downloads
    for track_num, track in enumerate(tracks, start=1):
        if not is_downloading:
            print("Downloading stopped by user.")
            break

        # Update progress in the GUI (call from main thread)
        screen.after(0, update_status, track_num, total_tracks)

        sanitized_track_name = sanitize_filename(f"{track['track']['artists'][0]['name']} - {track['track']['name']}")
        final_file = os.path.join(download_folder, f"{sanitized_track_name}.mp3")

        # Check if the file already exists
        if os.path.exists(final_file):
            print(f"Skipping, already downloaded: {final_file}")
            continue

        success = False
        retries = 3  # Number of retries
        while retries > 0 and not success:
            try:
                print(f"Processing {track['track']['name']} by {track['track']['artists'][0]['name']}... (Track {track_num}/{total_tracks})")
                logging.info(f"Processing {track['track']['name']} by {track['track']['artists'][0]['name']}...")

                search_query = f"{track['track']['name']} {track['track']['artists'][0]['name']} audio"
                video_ids = search_youtube(search_query)

                if not video_ids:
                    print("No videos found, retrying with different search...")
                    retries -= 1
                    time.sleep(random.uniform(2, 4))  # Random delay between retries
                    continue

                for video_id in video_ids:
                    try:
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        # Try multiple download methods in sequence
                        print(f"Attempting to download: {video_url}")
                        
                        # Method 1: Try with Invidious API (most reliable for bypassing bot detection)
                        if not success:
                            print("Trying download with Invidious API...")
                            success = download_with_invidious(video_id, final_file)
                            
                        # Method 2: Try with yt-dlp anonymous
                        if not success:
                            print("Trying download with yt-dlp anonymous...")
                            success = download_with_yt_dlp_anonymous(video_url, final_file)
                            
                        # Method 3: Try with yt-dlp legacy
                        if not success:
                            print("Trying download with yt-dlp legacy...")
                            success = download_with_yt_dlp_legacy(video_url, final_file)
                            
                        # Method 4: Try with yt-dlp alternative
                        if not success:
                            print("Trying download with yt-dlp alternative...")
                            success = download_with_yt_dlp_alternative(video_url, final_file)
                            
                        # Method 5: Try with yt-dlp library
                        if not success:
                            print("Trying download with yt-dlp library...")
                            success = download_with_ytdlp(video_url, final_file, sanitized_track_name)
                            
                        # Method 6: Try with yt-dlp CLI
                        if not success:
                            print("Trying download with yt-dlp CLI...")
                            success = download_with_yt_dlp_cli(video_url, final_file)
                            
                        # Method 7: Try with yt-dlp direct
                        if not success:
                            print("Trying download with yt-dlp direct...")
                            success = download_with_yt_dlp_direct(video_url, final_file)
                        
                        if success:
                            print(f"Downloaded successfully: {final_file}")
                            logging.info(f"Downloaded successfully: {final_file}")
                            time.sleep(random.uniform(1, 2))  # Random delay between downloads
                            break
                        else:
                            print(f"All download methods failed for video: {video_id}")
                            logging.warning(f"All download methods failed for video: {video_id}")
                            
                    except Exception as e:
                        print(f"Error downloading video: {e}")
                        logging.error(f"Error downloading video for {track['track']['name']}: {e}")
                        continue

                if not success:
                    retries -= 1
                    print(f"Retrying... {retries} attempts left.")
                    logging.warning(f"Retrying download for {track['track']['name']}... {retries} attempts left.")
                    time.sleep(random.uniform(2, 4))  # Random delay before retrying

            except Exception as e:
                print(f"Error processing track {track['track']['name']}: {e}")
                logging.error(f"Error processing track {track['track']['name']}: {e}")
                retries -= 1
                time.sleep(random.uniform(2, 4))  # Random delay before retrying

        # Clear references to the track to save memory
        del track

    screen.after(0, status_label.config, {'text': "Download completed."})
    logging.info("Download completed for playlist.")

# Function to start download in a new thread
def start_download():
    threading.Thread(target=lambda: download_songs(selected_playlist.get()), daemon=True).start()

# Allow the user to select a download path
def select_path():
    global path_label
    path = filedialog.askdirectory()
    if path:
        path_label.config(text=path)

# GUI setup
screen = Tk()
screen.title('Spotify Downloader')
screen.geometry("600x400")

# Styling
style = ttk.Style(screen)
style.theme_use('clam')

# Layout with improved spacing
frame = ttk.Frame(screen, padding="20")
frame.pack(fill='both', expand=True)

# Path selection
path_label = ttk.Label(frame, text="Select Download Path:")
path_label.pack(pady=10)
select_path_button = ttk.Button(frame, text="Browse", command=select_path)
select_path_button.pack(pady=10)

selected_playlist = StringVar()
playlist_dropdown = ttk.OptionMenu(frame, selected_playlist, "Loading playlists...")
playlist_dropdown.pack(pady=10)

get_user_playlists(access_token)

download_button = ttk.Button(frame, text="Download", command=start_download)
download_button.pack(pady=10)

stop_button = ttk.Button(frame, text="Stop Downloading", command=stop_downloading)
stop_button.pack(pady=10)

status_label = ttk.Label(frame, text="")
status_label.pack(pady=10)

screen.mainloop()

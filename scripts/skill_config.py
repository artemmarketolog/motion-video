"""User-owned paths and explicit credential file; no workspace discovery."""
import os
from pathlib import Path
from dotenv import dotenv_values

SKILL_NAME = 'motion-video'
CONFIG_HOME = Path((os.getenv('XDG_CONFIG_HOME') or str(Path.home() / '.config'))).expanduser()
DATA_HOME = Path((os.getenv('XDG_DATA_HOME') or str(Path.home() / '.local/share'))).expanduser()
CACHE_HOME = Path((os.getenv('XDG_CACHE_HOME') or str(Path.home() / '.cache'))).expanduser()
ENV_FILE = Path(os.getenv('MOTION_VIDEO_ENV_FILE', str(CONFIG_HOME / 'media-skills' / (SKILL_NAME + '.env')))).expanduser()
VOICE_ENV = CONFIG_HOME / 'media-skills' / 'elevenlabs-voice.env'   # ELEVEN_API_KEY is shared with the voice skill
VALUES = {**(dotenv_values(VOICE_ENV) if VOICE_ENV.is_file() else {}), **(dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {})}

def setting(name, default=None):
    return os.getenv(name) or VALUES.get(name) or default

DATA_DIR = Path(setting('MOTION_VIDEO_DATA_DIR', str(DATA_HOME / SKILL_NAME))).expanduser()
CACHE_DIR = Path(setting('MOTION_VIDEO_CACHE_DIR', str(CACHE_HOME / SKILL_NAME))).expanduser()

def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path

def require_key(name):
    value = setting(name)
    if not value:
        raise ValueError(f'Configure {name} in the environment or {ENV_FILE}; never paste keys into a chat.')
    return value

# Studio: your working folder — projects/, MAKING-OF-INDEX.md, clients.json, sources/, shots/, music/, fonts/.
STUDIO = Path(setting('MOTION_VIDEO_STUDIO', str(Path.home() / 'video-studio'))).expanduser()
PROJECTS = STUDIO / 'projects'

RUNTIME = Path(setting('MOTION_VIDEO_RUNTIME', str(DATA_HOME / 'motion-video/runtime'))).expanduser().resolve()

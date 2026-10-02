#!/usr/bin/env python3
"""Voiceover with word timings, cached per exact text; tempo change without re-generation.

  voice.py tts --voice narrator --file work/script.txt --tempo 1.15 --out work/voice.wav [--take 1] [--dry-run]
  voice.py asr output/master-r3.mp4 --text work/script.txt  # paid ASR cross-check (gpt-4o-mini-transcribe)

tts: ElevenLabs Eleven v4 through the elevenlabs-voice core (voices from elevenlabs-voice/voices.json; --model eleven_v3 is the fallback). Same text + voice + settings + take =
cache hit, no paid call. A failed or uncertain call is marked unknown_billed and
never retried automatically. Output: <out>.wav (48 kHz) and <out>.words.json with
timings already divided by --tempo. For explainers keep one script file per scene:
editing one scene then regenerates only that scene's voice.
asr: takes audio or a finished video (the audio track is extracted, music included); audio tags
like [confident] and <break .../> in the script are ignored; "60" and "шестьдесят" count as the same.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from skill_config import DATA_DIR, CACHE_DIR, ENV_FILE, RUNTIME, setting, require_key

CORE = Path(setting('ELEVENLABS_VOICE_SKILL', str(Path(__file__).resolve().parents[2] / 'elevenlabs-voice'))).expanduser() / 'scripts/eleven.py'
CACHE = DATA_DIR / 'tts'
OPENAI_ENV = ENV_FILE


def helper():
    """The elevenlabs-voice core (Eleven v4 by default, voices.json registry), loaded directly."""
    if not CORE.is_file():
        raise ValueError('Install https://github.com/artemmarketolog/elevenlabs-voice next to motion-video, or set ELEVENLABS_VOICE_SKILL.')
    sys.path.insert(0, str(CORE.parent))
    spec = importlib.util.spec_from_file_location('eleven', CORE)
    eleven = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eleven)

    class Core:
        VOICES = eleven.voices()
        DEFAULT_MODEL = eleven.DEFAULT_MODEL
        _load_env = staticmethod(eleven.load_env)

        @staticmethod
        def generate(text, voice_id, model, stability=None, similarity=None, speed=None):
            r = eleven.speak(text, voice_id, model, stability, similarity, None, speed, voice_is_id=True)
            return r['audio'], r['words']
    return Core


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tts(args):
    text = (Path(args.file).read_text() if args.file else args.text).strip()
    if not text:
        raise ValueError('empty text')
    mod = helper()
    if args.voice not in mod.VOICES:
        raise ValueError(f'unknown voice {args.voice}; known: {", ".join(sorted(mod.VOICES))}')
    request = {'text': text, 'voice': args.voice, 'voice_id': mod.VOICES[args.voice], 'model': args.model,
               'stability': args.stability, 'similarity': args.similarity, 'speed': args.speed,
               'take': args.take, 'core': sha_file(CORE)}
    key = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    mp3, words, meta = CACHE / f'{key}.mp3', CACHE / f'{key}.words.json', CACHE / f'{key}.json'
    if args.dry_run:
        return {'key': key, 'cached': meta.exists(), 'chars': len(text), 'network_calls': 0}
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = True
    with (CACHE / f'{key}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if meta.exists():
            m = json.loads(meta.read_text())
            if not (m['status'] == 'success' and mp3.exists() and m['sha256'] == sha_file(mp3)):
                raise ValueError(f"take {args.take} is {m['status']}; check ElevenLabs history, then use a new --take deliberately")
        else:
            cached = False
            meta.write_text(json.dumps({**request, 'status': 'dispatching'}, ensure_ascii=False))
            try:
                mod._load_env()
                audio, w = mod.generate(text, mod.VOICES[args.voice], args.model, args.stability,
                                        args.similarity, speed=args.speed)
                mp3.write_bytes(audio)
                words.write_text(json.dumps(w, ensure_ascii=False))
                meta.write_text(json.dumps({**request, 'status': 'success', 'sha256': sha_file(mp3)}, ensure_ascii=False))
            except Exception as error:
                meta.write_text(json.dumps({**request, 'status': 'unknown_billed'}, ensure_ascii=False))
                raise ValueError(f'TTS result uncertain ({type(error).__name__}); not retried. Check provider history.')
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    af = f'atempo={args.tempo},' if args.tempo != 1 else ''
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(mp3), '-af', f'{af}aresample=48000', '-ac', '1', str(out)], check=True)
    scaled = [{**w, 'start': round(w['start'] / args.tempo, 3), 'end': round(w['end'] / args.tempo, 3)}
              for w in json.loads(words.read_text())]
    wpath = out.with_suffix('.words.json')
    wpath.write_text(json.dumps(scaled, ensure_ascii=False, indent=1))
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(out)],
                               capture_output=True, text=True).stdout)
    return {'file': str(out), 'words': str(wpath), 'duration_s': round(dur, 3), 'cached': cached, 'key': key,
            'first_word_s': scaled[0]['start'] if scaled else None, 'last_word_end_s': scaled[-1]['end'] if scaled else None}


def asr(args):
    key = require_key('OPENAI_API_KEY')
    import requests
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / 'speech.mp3'      # video or large file → mono audio well under the 25 MB API limit
        subprocess.run(['ffmpeg', '-v', 'error', '-i', args.audio, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '48k', str(clip)],
                       check=True)
        with clip.open('rb') as f:
            r = requests.post('https://api.openai.com/v1/audio/transcriptions', headers={'Authorization': f'Bearer {key}'},
                              files={'file': (clip.name, f)}, data={'model': 'gpt-4o-mini-transcribe', 'language': args.language},
                              timeout=120)
    r.raise_for_status()
    heard = r.json()['text'].strip()

    def norm(s):
        s = re.sub(r'\[[^\]]*\]|<[^>]*>', ' ', s)          # [confident], <break time="0.5s"/>
        return [w.strip('.,!?:;«»"()—–-…').lower().replace('ё', 'е') for w in s.split() if w.strip('.,!?:;«»"()—–-…')]
    expected = norm(Path(args.text).read_text()) if args.text else []
    got = norm(heard)
    numeric = any(is_number(w) for w in got)
    missing = [w for w in expected if w not in got and not (is_number(w) and numeric)]
    return {'heard': heard, 'missing_words': missing,
            'note': 'ASR finds dropped or swallowed words; numbers in digits or words count as present when the '
                    'transcript has any number. It does not prove stress or intonation. Listen when possible.'}


NUMBER_WORD = re.compile(
    r'(ноль|нол[яюе]|один|одн(а|о|ого|ой|ому|у|им)|дв(а|е|ух|ум|умя)|тр(и|ех|ем|емя)|четыр(е|ех|ем|ьмя)'
    r'|(пят|шест|сем|восем|девят|десят)(ь|и|ью)'
    r'|(один|две|три|четыр|пят|шест|сем|восем|девят)надцат(ь|и|ью)|(двадцат|тридцат)(ь|и|ью)|сорок(а)?'
    r'|(пят|шест|сем|восем)ьдесят|(пят|шест|сем|восем)идесяти|девяност(о|а)|ст(о|а)|двест(и)|трист(а)|четырест(а)'
    r'|(пят|шест|сем|восем|девят)сот|тысяч\w*|миллион\w*|полтор(а|ы))')


def is_number(w):
    return bool(re.fullmatch(r'[\d\s.,%–-]+', w)) or bool(NUMBER_WORD.fullmatch(w))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('tts')
    src = t.add_mutually_exclusive_group(required=True)
    src.add_argument('--file')
    src.add_argument('--text')
    t.add_argument('--voice', required=True)
    t.add_argument('--out', required=True)
    t.add_argument('--tempo', type=float, default=1.0, help='ffmpeg atempo after generation (for example 1.15)')
    t.add_argument('--model', default='eleven_v4')
    t.add_argument('--stability', type=float, default=None)
    t.add_argument('--similarity', type=float, default=None)
    t.add_argument('--speed', type=float, default=None, help='v3/v2 only; for v4 use --tempo')
    t.add_argument('--take', default='1')
    t.add_argument('--dry-run', action='store_true')
    a = sub.add_parser('asr')
    a.add_argument('audio')
    a.add_argument('--text')
    a.add_argument('--language', default='ru')
    args = parser.parse_args()
    if args.cmd == 'tts' and not 0.5 <= args.tempo <= 2:
        parser.error('--tempo 0.5..2')
    print(json.dumps(tts(args) if args.cmd == 'tts' else asr(args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, BlockingIOError) as e:
        print(f'voice: {e}', file=sys.stderr)
        sys.exit(2)

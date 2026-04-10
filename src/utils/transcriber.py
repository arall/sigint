"""
Audio transcription using OpenAI-compatible Whisper API or local Whisper.

Supports:
  - OpenAI Whisper API (set OPENAI_API_KEY env var)
  - Self-hosted whisper server (set WHISPER_API_URL env var)
  - Local whisper fallback (if installed)

Environment variables:
  OPENAI_API_KEY    - OpenAI API key (uses api.openai.com)
  WHISPER_API_URL   - Custom endpoint URL (e.g. http://myserver:8000/v1/audio/transcriptions)
  WHISPER_BACKEND   - Force backend: "api", "local", or "auto" (default: auto)
  WHISPER_LANGUAGES - Expected languages, comma-separated (e.g. "es,en")
                      First language is used as primary hint; improves accuracy
                      for short/noisy audio that Whisper might misdetect.
"""

import os
import json
import urllib.request

# Load .env from project root if present
_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                if _key.strip() not in os.environ:
                    os.environ[_key.strip()] = _val.strip()

# Load .env file if present (sudo strips environment variables)
def _load_dotenv():
    """Load key=value pairs from .env file into os.environ."""
    # Search upward from this file's directory
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        env_path = os.path.join(d, '.env')
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    if key not in os.environ:
                        os.environ[key] = val
            break
        d = os.path.dirname(d)

_load_dotenv()
import urllib.error

_model = None
_model_name = None

# OpenAI-compatible API endpoint
OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"


def _build_multipart(audio_path, model_name, language=None, prompt=None):
    """Build multipart form data for Whisper API."""
    boundary = "----WhisperBoundary9876543210"
    body = b""

    # File field
    filename = os.path.basename(audio_path)
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += b"Content-Type: audio/wav\r\n\r\n"
    with open(audio_path, "rb") as f:
        body += f.read()
    body += b"\r\n"

    # Model field
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="model"\r\n\r\n'
    body += model_name.encode() + b"\r\n"

    # Language field (optional)
    if language:
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="language"\r\n\r\n'
        body += language.encode() + b"\r\n"

    # Prompt field (optional) — helps guide the model
    if prompt:
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        body += prompt.encode() + b"\r\n"

    body += f"--{boundary}--\r\n".encode()
    return boundary, body


def _transcribe_api(audio_path, model_name="whisper-1", language=None, prompt=None):
    """Transcribe via OpenAI-compatible API."""
    custom_url = os.environ.get("WHISPER_API_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    if custom_url:
        url = custom_url
    elif api_key:
        url = OPENAI_API_URL
    else:
        return None  # No API available

    boundary, body = _build_multipart(audio_path, model_name, language, prompt)

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            text = result.get("text", "").strip()
            return text if text else None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"  Whisper API error {e.code}: {error_body[:200]}")
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  Whisper API connection error: {e}")
        return None


def _transcribe_local(audio_path, model_name="base", language=None):
    """Transcribe using local Whisper model."""
    global _model, _model_name

    try:
        import whisper
    except ImportError:
        return None

    if _model is None or _model_name != model_name:
        _model = whisper.load_model(model_name)
        _model_name = model_name

    kwargs = {}
    if language:
        kwargs["language"] = language

    result = _model.transcribe(audio_path, **kwargs)
    text = result.get("text", "").strip()
    return text if text else None


def _get_language_hints(language=None):
    """Resolve language and prompt hint from args and WHISPER_LANGUAGES env var.

    Returns (language_code, prompt) where language_code is the primary language
    to pass to the API, and prompt is a hint string listing expected languages.
    The --language CLI arg takes priority over the env var.
    """
    if language:
        return language, None

    env_langs = os.environ.get("WHISPER_LANGUAGES", "").strip()
    if not env_langs:
        return None, None

    # Parse comma-separated language codes (e.g. "es,en")
    langs = [l.strip().lower() for l in env_langs.split(",") if l.strip()]
    if not langs:
        return None, None

    # Use first language as primary hint to the API
    primary = langs[0]

    # Build a prompt hint listing all expected languages — this guides Whisper
    # to stay within these languages instead of hallucinating others
    lang_names = {
        "es": "Spanish", "ca": "Catalan", "en": "English", "fr": "French",
        "pt": "Portuguese", "de": "German", "it": "Italian", "eu": "Basque",
        "ar": "Arabic", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
        "ru": "Russian", "nl": "Dutch", "pl": "Polish", "sv": "Swedish",
    }
    if len(langs) > 1:
        names = [lang_names.get(l, l.upper()) for l in langs]
        prompt = f"This audio may be in {', '.join(names)}."
    else:
        prompt = None

    return primary, prompt


# Known Whisper hallucination patterns — these appear on noisy/silent audio
# when Whisper fills in common phrases instead of returning empty text.
_HALLUCINATION_PATTERNS = [
    "subtítulos",
    "subtitulos",
    "amara.org",
    "suscríbete",
    "suscribete",
    "gracias por ver",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
    "sous-titres",
    "sous-titre",
    "sous titres réalisés",
    "untertitel",
    "copyright",
    "www.",
    ".com",
    ".org",
]


def _is_hallucination(text):
    """Check if transcription text matches known Whisper hallucination patterns."""
    if not text:
        return True
    lower = text.lower().strip()
    # Very short results on radio audio are almost always hallucinations
    if len(lower) < 3:
        return True
    return any(pattern in lower for pattern in _HALLUCINATION_PATTERNS)


def transcribe(audio_path, model_name="base", language=None):
    """Transcribe a WAV file to text.

    Args:
        audio_path: Path to WAV file.
        model_name: Whisper model size (tiny, base, small for local;
                     whisper-1 for OpenAI API). Auto-selected based on backend.
        language: Language code (e.g. "en", "es"). None for auto-detect.
                  If not set, uses WHISPER_LANGUAGES env var.

    Returns:
        Transcription text, or None if no backend available or hallucination.
    """
    backend = os.environ.get("WHISPER_BACKEND", "auto").lower()
    lang, prompt = _get_language_hints(language)

    result = None
    if backend == "api":
        result = _transcribe_api(audio_path, language=lang, prompt=prompt)
    elif backend == "local":
        result = _transcribe_local(audio_path, model_name, lang)
    else:
        # Auto: try API first (faster), fall back to local
        api_available = os.environ.get("WHISPER_API_URL") or os.environ.get("OPENAI_API_KEY")
        if api_available:
            result = _transcribe_api(audio_path, language=lang, prompt=prompt)
        if result is None:
            result = _transcribe_local(audio_path, model_name, lang)

    if _is_hallucination(result):
        return None
    return result

"""Additional engines. No credentials are saved or sent to model repositories."""
from pathlib import Path
import math
import httpx

ROOT = Path(__file__).resolve().parent
PERSIAN_MODEL = ROOT / 'models' / 'persian-v4-ct2'
SCRIBE_LIMIT = 5_000_000_000


class EngineError(Exception):
    pass


def local_model_name(name):
    if name != 'persian-v4':
        return name
    if not all((PERSIAN_MODEL / f).is_file() for f in ('model.bin', 'config.json', 'tokenizer.json')):
        raise EngineError('مدل Persian v4 هنوز آماده نیست. فایل prepare-persian.bat را در پوشهٔ برنامه اجرا کنید؛ سپس دوباره همین مدل را انتخاب کنید.')
    return str(PERSIAN_MODEL)


def scribe_segments(payload):
    """Keep provider word timings; split at speaker changes, punctuation or 20s."""
    result, words, start, end, speaker = [], [], None, None, None
    def flush():
        nonlocal words, start, end
        if words:
            result.append({'start':start, 'end':end, 'text':' '.join(words),
                           'speaker':speaker, 'review':False})
        words, start, end = [], None, None
    for word in payload.get('words', []):
        if word.get('type') != 'word':
            continue
        text = str(word.get('text', '')).strip()
        a, b = word.get('start'), word.get('end')
        if not text or not isinstance(a, (int,float)) or not isinstance(b, (int,float)):
            continue
        if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a:
            continue
        who = word.get('speaker_id')
        if words and (who != speaker or b - start > 20):
            flush()
        if start is None:
            start, speaker = a, who
        end = b
        words.append(text)
        if text.endswith(('.', '!', '؟', '?', '؛')):
            flush()
    flush()
    if payload.get('text', '').strip() and not result:
        raise EngineError('سرویس متن بدون زمان‌بندی معتبر برگرداند؛ امکان ساخت زیرنویس وجود ندارد.')
    return result


def transcribe_scribe(path, api_key, zero_retention, is_cancelled):
    if is_cancelled():
        return []
    try:
        with httpx.Client(timeout=httpx.Timeout(1800, connect=30), follow_redirects=False) as client:
            with open(path, 'rb') as audio:
                response = client.post('https://api.elevenlabs.io/v1/speech-to-text',
                    params={'enable_logging':'false' if zero_retention else 'true'},
                    headers={'xi-api-key':api_key},
                    data={'model_id':'scribe_v2', 'language_code':'fas',
                          'diarize':'true', 'tag_audio_events':'false', 'timestamps_granularity':'word'},
                    files={'file':('audio' + Path(path).suffix, audio, 'application/octet-stream')})
        if response.status_code in (401,403):
            raise EngineError('کلید API، مجوز Scribe یا دسترسی حساب به نگه‌داری صفر را بررسی کنید. نگه‌داری صفر نیازمند حساب سازمانی است.')
        if response.status_code == 429:
            raise EngineError('سقف اعتبار یا تعداد درخواست‌های ElevenLabs رسیده است؛ حساب را بررسی کنید.')
        if not response.is_success:
            raise EngineError(f'سرویس Scribe خطای {response.status_code} برگرداند. درخواست خودکار تکرار نشد.')
        if is_cancelled():
            return []
        return scribe_segments(response.json())
    except EngineError:
        raise
    except (httpx.HTTPError, ValueError):
        raise EngineError('ارتباط با Scribe قطع شد یا پاسخ نامعتبر بود. ممکن است درخواست در سرویس پردازش شده باشد؛ پیش از ارسال مجدد، حساب را بررسی کنید.') from None

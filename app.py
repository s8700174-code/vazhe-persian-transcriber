"""Local Persian speech transcription. Run: python app.py."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from engines import EngineError, local_model_name, transcribe_scribe, PERSIAN_MODEL, SCRIBE_LIMIT

# Download public weights without telemetry or implicit account credentials.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 10 * 1024 * 1024 * 1024
SIZE_ERROR = "حداکثر حجم فایل ۱۰ گیگابایت است."
MODELS = {"large-v3", "medium", "small", "turbo", "persian-v4", "scribe-v2"}
EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".mp4", ".webm", ".wma", ".opus"}
app = FastAPI(title="واژه | تبدیل گفتار فارسی", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
jobs: dict[str, dict] = {}
lock = threading.Lock()
worker = ThreadPoolExecutor(max_workers=1)
model_cache: dict = {}
log = logging.getLogger("v2t")


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.method in {"POST", "DELETE"}:
        if request.headers.get("x-v2t-client") != "local":
            return JSONResponse({"detail": "درخواست نامعتبر است."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "فقط رابط محلی مجاز است."}, status_code=403)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "اندازهٔ درخواست نامعتبر است."}, status_code=400)
        if size > MAX_BYTES + 1024 * 1024:
            return JSONResponse({"detail": SIZE_ERROR}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def normalize(text: str) -> str:
    return text.translate(str.maketrans({"ي": "ی", "ك": "ک"})).strip()


def update(job_id, **values):
    with lock:
        jobs[job_id].update(values)


def cancelled(job_id):
    with lock:
        return jobs[job_id]["cancel_requested"]


def run_transcription(job_id: str, path: str, model_name: str, device: str, prompt: str, vad: bool,
                      api_key: str = '', zero_retention: bool = True):
    started = time.monotonic()
    try:
        if cancelled(job_id):
            return
        if model_name == 'scribe-v2':
            update(job_id, status='transcribing', message='ارسال به ElevenLabs و انتظار برای پاسخ؛ متن پس از پاسخ سرویس نمایش داده می‌شود.')
            items = transcribe_scribe(path, api_key, zero_retention, lambda: cancelled(job_id))
            for item in items:
                item['text'] = normalize(item['text'])
            update(job_id, segments=items, duration=max((s['end'] for s in items), default=0),
                   status='done', progress=100, message='پاسخ Scribe دریافت شد؛ متن را بازبینی کنید.')
            return
        update(job_id, status="loading", message="آماده‌سازی مدل؛ در اولین اجرا فایل‌های مدل دانلود می‌شوند.")
        from faster_whisper import WhisperModel
        key = (model_name, device)
        if key not in model_cache:
            model_cache.clear()
            model_cache[key] = WhisperModel(
                local_model_name(model_name), device=device,
                compute_type="int8_float16" if device == "cuda" else "int8",
                download_root=str(ROOT / "models"), cpu_threads=max(1, min(8, (os.cpu_count() or 4) - 1)),
            )
        if cancelled(job_id):
            return
        update(job_id, status="transcribing", message="در حال شنیدن و تبدیل گفتار فارسی…")
        segments, info = model_cache[key].transcribe(
            path, language="fa", task="transcribe", beam_size=5,
            initial_prompt=prompt or None, vad_filter=vad,
            vad_parameters={"min_silence_duration_ms": 700},
            condition_on_previous_text=False, word_timestamps=True,
        )
        update(job_id, duration=info.duration)
        for segment in segments:
            if cancelled(job_id):
                return
            text = normalize(segment.text)
            if not text:
                continue
            item = {
                "start": round(segment.start, 3), "end": round(segment.end, 3), "text": text,
                # A review hint, not a calibrated accuracy percentage.
                "review": segment.avg_logprob < -0.8 or segment.no_speech_prob > 0.5,
            }
            with lock:
                jobs[job_id]["segments"].append(item)
                jobs[job_id]["progress"] = min(99, round(segment.end / max(info.duration, 1) * 100))
        update(job_id, status="done", progress=100, message="تبدیل کامل شد. متن را با صوت تطبیق دهید.")
    except EngineError as error:
        update(job_id, status='error', message=str(error))
    except Exception:
        log.exception("Transcription failed: %s", job_id)
        message = "تبدیل انجام نشد. اتصال اینترنت برای دانلود اولیهٔ مدل و معتبر بودن فایل صوتی را بررسی کنید."
        if device == "cuda":
            message += " برای خطای حافظه یا کتابخانه‌های CUDA، پردازنده را روی CPU قرار دهید یا مدل کوچک‌تر انتخاب کنید."
        update(job_id, status="error", message=message)
    finally:
        Path(path).unlink(missing_ok=True)
        if cancelled(job_id):
            update(job_id, status="cancelled", message="پردازش متوقف شد؛ نسخهٔ موقت صوت حذف شد.")
        update(job_id, elapsed=round(time.monotonic() - started, 1))


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "max_mb": MAX_BYTES // (1024 * 1024), "max_bytes": MAX_BYTES, "local": True,
            "persian_ready": all((PERSIAN_MODEL / f).is_file() for f in ('model.bin','config.json','tokenizer.json'))}


@app.post("/api/jobs", status_code=202)
async def create_job(file: UploadFile = File(...), model: str = Form("large-v3"),
                     device: str = Form("cpu"), prompt: str = Form(""), vad: str = Form("true"),
                     api_key: str = Form(''), cloud_consent: str = Form('false'), zero_retention: str = Form('true')):
    if model not in MODELS or device not in {"cpu", "cuda"} or vad not in {"true", "false"}:
        raise HTTPException(400, "تنظیمات مدل نامعتبر است.")
    if model == 'scribe-v2':
        if cloud_consent != 'true':
            raise HTTPException(400, 'برای Scribe باید ارسال همین صوت به ElevenLabs را تأیید کنید.')
        if not api_key.strip() or len(api_key) > 512 or any(c in api_key for c in '\r\n'):
            raise HTTPException(400, 'کلید API معتبر وارد کنید.')
        if zero_retention not in {'true','false'}:
            raise HTTPException(400, 'تنظیم نگه‌داری داده نامعتبر است.')
        if file.size is not None and file.size >= SCRIBE_LIMIT:
            raise HTTPException(413, 'حجم فایل برای Scribe باید کمتر از ۵ میلیارد بایت باشد.')
        if prompt:
            raise HTTPException(400, 'واژه‌های راهنما در اتصال Scribe این نسخه ارسال نمی‌شوند.')
    elif model == 'persian-v4':
        try:
            local_model_name(model)
        except EngineError as error:
            raise HTTPException(400, str(error)) from None
    if len(prompt) > 1500:
        raise HTTPException(400, "واژه‌های راهنما باید کمتر از ۱۵۰۰ نویسه باشند.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in EXTENSIONS:
        raise HTTPException(400, "فرمت فایل پشتیبانی نمی‌شود.")
    job_id = uuid.uuid4().hex
    with lock:
        if any(j["status"] in {"uploading", "queued", "loading", "transcribing"} for j in jobs.values()):
            raise HTTPException(409, "یک فایل در حال پردازش است. تا پایان یا توقف آن صبر کنید.")
        # Results live in memory only; keep bounded history.
        while len(jobs) >= 20:
            del jobs[next(iter(jobs))]
        jobs[job_id] = {"id": job_id, "status": "uploading", "progress": 0,
                        "segments": [], "duration": 0, "elapsed": 0,
                        "message": "در صف پردازش", "cancel_requested": False, "model":model}
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="v2t-", suffix=suffix, delete=False) as stream:
            path = stream.name
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, SIZE_ERROR)
                if model == 'scribe-v2' and size >= SCRIBE_LIMIT:
                    raise HTTPException(413, 'حجم فایل برای Scribe باید کمتر از ۵ میلیارد بایت باشد.')
                stream.write(chunk)
        if not size:
            raise HTTPException(400, "فایل انتخاب‌شده خالی است.")
        update(job_id, status="queued")
        worker.submit(run_transcription, job_id, path, model, device, prompt.strip(), vad == "true",
                      api_key.strip() if model == 'scribe-v2' else '', zero_retention == 'true')
        return {"id": job_id}
    except BaseException:
        if path:
            Path(path).unlink(missing_ok=True)
        with lock:
            jobs.pop(job_id, None)
        raise
    finally:
        await file.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "پردازش پیدا نشد؛ ممکن است برنامه دوباره اجرا شده باشد.")
        return {**jobs[job_id], "segments": list(jobs[job_id]["segments"])}


@app.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str):
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "پردازش پیدا نشد.")
        if jobs[job_id]["status"] in {"queued", "loading", "transcribing"}:
            jobs[job_id]["cancel_requested"] = True
            jobs[job_id]["message"] = "توقف پس از پایان بخش جاری؛ دانلود یا آماده‌سازی مدل ممکن است زمان ببرد."
            if jobs[job_id].get('model') == 'scribe-v2':
                jobs[job_id]['message'] = 'در انتظار پایان درخواست ارسالی؛ لغو محلی، ارسال قبلی به سرویس یا هزینهٔ آن را برنمی‌گرداند.'
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)

# Vazhe — Persian Audio Transcriber

A local-first transcription workspace with a Persian RTL interface, editable timed text, synchronized audio playback and TXT / SRT / VTT exports.

Vazhe combines a Python/FastAPI service with a lightweight browser interface. Local inference uses faster-whisper. An optional ElevenLabs Scribe adapter sends audio to the provider only after explicit confirmation for that upload.

## Features

- Persian transcription with selectable local models and CPU or CUDA execution.
- Incremental local transcription, organized into approximately three-minute editing blocks.
- Seek to a sentence or play an individual block while reviewing the original audio.
- Preserve edits as later segments arrive; export the edited text with sentence timings.
- Review hints for selected segments; these are not accuracy percentages.
- Optional Persian-v4 model preparation and Scribe integration.
- One active job at a time, bounded in-memory history and temporary-upload cleanup.

## Quick start

Python 3.11+ is required; the current local test environment uses Python 3.12. On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

Open **http://127.0.0.1:8765**. Keep the terminal open. `start.bat` is a convenience launcher that creates an environment and installs missing dependencies.

On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, then `.venv/bin/python app.py`. These platforms have not been independently validated for this release.

The first local transcription downloads the selected model into `models/`. No weights are included in this repository. The default large-v3 model needs several gigabytes of disk space and can be slow on CPU; smaller models are available. GPU execution needs a compatible CUDA/cuDNN environment and does not silently fall back to CPU.

`requirements-lock.txt` records the original Windows environment, including optional model-conversion packages; use `requirements.txt` for the normal installation.

## Engines

| Engine | Processing | Setup |
| --- | --- | --- |
| faster-whisper | Local after the model is downloaded | Select large-v3, medium, small or turbo |
| Persian v4 | Local after preparation | Run `prepare-persian.bat` after setting up Python; downloads and converts the pinned upstream model |
| Scribe v2 | ElevenLabs cloud | Enter your own API key and confirm sending this audio; provider account/credits required |

The Scribe adapter requests zero retention by default. Account eligibility must be checked with the provider; a rejected request is not retried with weaker retention. Local cancellation cannot retract a submitted cloud request or guarantee reversal of provider charges. The key is not stored in files, browser storage or job responses.

## Data handling and limitations

The service binds to loopback only and is intended for one local user. It is not a hosted multi-user application. No private recordings, transcripts, API credentials or model weights are distributed.

Results are held in process memory for up to 20 jobs. Browser edits are not persisted: export before refreshing or closing. Reattaching the original audio after refresh enables playback without overwriting the recovered server result. Temporary uploads are deleted on completion, handled errors or cancellation; abrupt process termination may leave a temporary file.

One file up to 10 GiB is accepted; the Scribe adapter has a lower limit of less than 5 billion bytes. Playback depends on browser codec support. Local models do not identify speakers; Scribe speaker IDs are provider labels, not verified identities. No live microphone transcription or measured Persian accuracy guarantee is claimed. Always review output against the source audio.

## Validation

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -v
```

The 14 unit/API tests cover request validation, job lifecycle, cleanup, origin restrictions, consent, API-key isolation and mocked engine responses. They do not measure real-world speech accuracy or prove the cloud provider is reachable.

An optional real inference smoke test, `python tests/engine_smoke.py`, downloads a small model and decodes synthetic audio. It is not part of the default tests and is not a Persian accuracy benchmark.

## Project structure

- `app.py`: local API and transcription job lifecycle.
- `engines.py`: optional engines and provider response normalization.
- `static/`: Persian interface, editing, playback and exports.
- `tests/`: deterministic API tests and optional inference smoke test.
- `prepare_persian.py`: pinned model download/conversion helper.

## Portfolio scope and reuse

This repository presents the application source, not a claim of a paid client delivery. No open-source license is granted for the application in this publication; contact the owner for reuse permission. Third-party libraries and downloaded models retain their own licenses and terms; model weights are not redistributed.

[Project inquiries](https://ponisha.ir/profile/sabaghi_ir) · [Developer profile](https://github.com/s8700174-code)

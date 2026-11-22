# AI Clipping Maker (Starter MVP)

This project has two source choices:
- **Upload video:** sends a video file to the backend and exports a selected time range as MP4.
- **YouTube link:** embeds a YouTube preview using YouTube's privacy-enhanced player. It does not download or extract YouTube video streams.

## Important scope
This is a working starter for manual clip selection, not automatic AI highlight detection yet. Automatic highlight detection requires a transcription/analysis service and a secure backend. Do not put API keys in `static/index.html`.

Use only videos you own or have permission to edit. Respect YouTube's terms and the creator's rights.

## Requirements
- Python 3.10+
- FFmpeg installed and available as `ffmpeg` on PATH

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```
Open http://127.0.0.1:8000

## Deploying
GitHub Pages can host only the static frontend; it cannot run this Python/FFmpeg backend. To export clips online, deploy the whole app (frontend + FastAPI backend + FFmpeg) on a server that supports Python and FFmpeg, then configure the frontend API URL for that host. For a beginner, test locally first.

## Next features
1. AI speech transcription and highlight ranking
2. 9:16 crop with subject tracking
3. Burned-in captions and SRT export
4. Multiple clip suggestions
5. User accounts and storage

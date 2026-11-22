
from pathlib import Path
import subprocess
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AI Shorts Maker")

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "message": "AI Shorts Maker is running"}


@app.post("/api/clip")
async def create_clip(
    video: UploadFile = File(...),
    start: float = Form(...),
    end: float = Form(...)
):
    if start < 0 or end <= start:
        raise HTTPException(
            status_code=400,
            detail="Please choose valid start and end times."
        )

    if end - start > 180:
        raise HTTPException(
            status_code=400,
            detail="Maximum clip duration is 180 seconds."
        )

    if not video.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    suffix = Path(video.filename).suffix.lower()
    allowed = {".mp4", ".mov", ".mkv", ".webm"}

    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Supported formats: MP4, MOV, MKV and WEBM."
        )

    if not shutil_which_ffmpeg():
        raise HTTPException(
            status_code=500,
            detail="FFmpeg is not installed on the server."
        )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / f"source{suffix}"
            output = Path(tmp) / "clip.mp4"

            size = 0
            with source.open("wb") as f:
                while True:
                    chunk = await video.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)

                    if size > 500 * 1024 * 1024:
                        raise HTTPException(
                            status_code=413,
                            detail="Video must be smaller than 500 MB."
                        )

                    f.write(chunk)

            if size == 0:
                raise HTTPException(status_code=400, detail="Empty video.")

            duration = end - start

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(source),
                "-t", str(duration),
                "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output)
            ]

            run = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if run.returncode != 0 or not output.exists():
                raise HTTPException(
                    status_code=500,
                    detail="Video processing failed."
                )

            clip_bytes = output.read_bytes()

            from fastapi.responses import Response
            return Response(
                content=clip_bytes,
                media_type="video/mp4",
                headers={
                    "Content-Disposition": 'attachment; filename="short.mp4"'
                }
            )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="Processing timeout. Try a shorter video."
        )
    finally:
        await video.close()


def shutil_which_ffmpeg():
    import shutil
    return shutil.which("ffmpeg")

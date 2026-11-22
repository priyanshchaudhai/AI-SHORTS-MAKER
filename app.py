from pathlib import Path
import shutil, subprocess, tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AI Clipping Maker")
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
def home():
    return RedirectResponse("/static/index.html")

@app.post("/api/clip")
async def create_clip(video: UploadFile = File(...), start: float = Form(...), end: float = Form(...)):
    if start < 0 or end <= start or end - start > 600:
        raise HTTPException(400, "Choose a valid clip range up to 10 minutes.")
    if not video.filename:
        raise HTTPException(400, "Please choose a video file.")
    suffix = Path(video.filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}:
        raise HTTPException(400, "Unsupported video type. Try MP4, MOV, MKV, WEBM or AVI.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(500, "FFmpeg is not installed on the server.")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / ("source" + suffix)
        output = Path(tmp) / "clip.mp4"
        size = 0
        with source.open("wb") as f:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > 500 * 1024 * 1024:
                    raise HTTPException(413, "Video is larger than the 500 MB starter limit.")
                f.write(chunk)
        cmd = [
            "ffmpeg", "-y", "-ss", str(start), "-i", str(source),
            "-t", str(end-start), "-vf", "scale='min(1080,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", str(output)
        ]
        run = subprocess.run(cmd, capture_output=True, text=True)
        if run.returncode != 0 or not output.exists():
            raise HTTPException(500, "FFmpeg could not process this video. Try an MP4 file.")
        return Response(content=output.read_bytes(), media_type="video/mp4", headers={"Content-Disposition": 'attachment; filename="my-short.mp4"'})

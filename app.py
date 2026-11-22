from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AI Shorts Maker")

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
UPLOADS = BASE / "uploads"

STATIC.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)

app.mount(
    "/static",
    StaticFiles(directory=STATIC),
    name="static"
)


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    format: str = Form("9:16")
):
    allowed = {
        ".mp4", ".mov", ".mkv", ".avi", ".webm"
    }

    extension = Path(file.filename or "").suffix.lower()

    if extension not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Please upload a valid video file."
        )

    if format not in ["9:16", "16:9", "1:1"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid video format."
        )

    filename = f"{uuid4().hex}{extension}"
    save_path = UPLOADS / filename

    total_size = 0
    max_size = 500 * 1024 * 1024

    try:
        with open(save_path, "wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Video is too large. Maximum size is 500 MB."
                    )

                output.write(chunk)

    except Exception:
        save_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    return {
        "success": True,
        "message": "Video uploaded successfully!",
        "filename": filename,
        "format": format
    }

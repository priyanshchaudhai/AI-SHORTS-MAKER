from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from processor import process_video

app = FastAPI(title="AI Shorts Maker")

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"

for folder in [STATIC, UPLOADS, OUTPUTS]:
    folder.mkdir(exist_ok=True)

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
    allowed = [".mp4", ".mov", ".mkv", ".avi", ".webm"]
    extension = Path(file.filename or "").suffix.lower()

    if extension not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Invalid video format"
        )

    if format not in ["9:16", "16:9", "1:1"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid output format"
        )

    job_id = uuid4().hex
    video_path = UPLOADS / f"{job_id}{extension}"
    output_dir = OUTPUTS / job_id

    total_size = 0
    max_size = 500 * 1024 * 1024

    try:
        with open(video_path, "wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Maximum video size is 500 MB"
                    )

                output.write(chunk)

    finally:
        await file.close()

    try:
        results = process_video(
            video_path,
            output_dir,
            format
        )

        shorts = []

        for item in results:
            shorts.append({
                "video": item["video"],
                "captions": item["captions"],
                "video_url": f"/download/{job_id}/{item['video']}",
                "captions_url": f"/download/{job_id}/{item['captions']}"
            })

        return {
            "success": True,
            "message": "AI Shorts generated successfully!",
            "job_id": job_id,
            "shorts": shorts
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Video processing failed: {str(error)}"
        )

    finally:
        video_path.unlink(missing_ok=True)


@app.get("/download/{job_id}/{filename}")
def download_short(job_id: str, filename: str):
    if (
        not job_id.isalnum()
        or Path(filename).name != filename
        or not filename.endswith((".mp4", ".srt"))
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid file request"
        )

    file_path = OUTPUTS / job_id / filename

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return FileResponse(
        file_path,
        filename=filename
)

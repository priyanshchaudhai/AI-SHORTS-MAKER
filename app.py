from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
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

app.mount("/static", StaticFiles(directory=STATIC), name="static")

JOBS = {}


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


def run_processing(job_id, video_path, output_dir, video_format):
    try:
        JOBS[job_id].update({
            "status": "processing",
            "progress": 5,
            "message": "Starting AI processing..."
        })

        def update_progress(value, message):
            JOBS[job_id].update({
                "progress": value,
                "message": message
            })

        results = process_video(
            video_path,
            output_dir,
            video_format,
            progress_callback=update_progress
        )

        shorts = []

        for item in results:
            shorts.append({
                "video": item["video"],
                "captions": item["captions"],
                "video_url": f"/download/{job_id}/{item['video']}",
                "captions_url": f"/download/{job_id}/{item['captions']}"
            })

        JOBS[job_id].update({
            "status": "completed",
            "progress": 100,
            "message": "AI Shorts generated successfully!",
            "shorts": shorts
        })

    except Exception as error:
        JOBS[job_id].update({
            "status": "failed",
            "progress": 0,
            "message": str(error)
        })

    finally:
        video_path.unlink(missing_ok=True)


@app.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format: str = Form("9:16")
):
    allowed = [".mp4", ".mov", ".mkv", ".avi", ".webm"]
    extension = Path(file.filename or "").suffix.lower()

    if extension not in allowed:
        raise HTTPException(400, "Invalid video format")

    if format not in ["9:16", "16:9", "1:1"]:
        raise HTTPException(400, "Invalid output format")

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
                        413,
                        "Maximum video size is 500 MB"
                    )

                output.write(chunk)

    except Exception:
        video_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    JOBS[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Video uploaded. Waiting for AI processing...",
        "shorts": []
    }

    background_tasks.add_task(
        run_processing,
        job_id,
        video_path,
        output_dir,
        format
    )

    return {
        "success": True,
        "job_id": job_id,
        "message": "Video uploaded successfully!"
    }


@app.get("/status/{job_id}")
def get_status(job_id: str):
    if not job_id.isalnum():
        raise HTTPException(400, "Invalid job ID")

    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    return job


@app.get("/download/{job_id}/{filename}")
def download_short(job_id: str, filename: str):
    if (
        not job_id.isalnum()
        or Path(filename).name != filename
        or not filename.endswith((".mp4", ".srt"))
    ):
        raise HTTPException(400, "Invalid file request")

    file_path = OUTPUTS / job_id / filename

    if not file_path.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(file_path, filename=filename)

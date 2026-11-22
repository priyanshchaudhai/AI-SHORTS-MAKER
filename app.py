
import os
import re
import uuid
import threading
import subprocess
from pathlib import Path

import imageio_ffmpeg
from faster_whisper import WhisperModel

from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

BASE = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE / "uploads"
OUTPUT_FOLDER = BASE / "outputs"

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

MODEL = None
JOBS = {}
JOB_LOCK = threading.Lock()

MAX_SHORTS = 6

FORMATS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080)
}


def get_model():
    global MODEL

    if MODEL is None:
        MODEL = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8"
        )

    return MODEL


def run_ffmpeg(args):
    return subprocess.run(
        [FFMPEG] + args,
        capture_output=True,
        text=True,
        timeout=1800
    )


def get_video_duration(path):
    result = run_ffmpeg(["-i", str(path)])

    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        result.stderr
    )

    if not match:
        raise ValueError("Could not read video duration")

    hours, minutes, seconds = match.groups()

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(seconds)
    )


def select_best_clips(segments, video_duration, clip_length):

    if video_duration < clip_length:
        raise ValueError(
            f"Video must be at least {clip_length} seconds long"
        )

    keywords = [
        "important", "secret", "amazing",
        "surprising", "why", "how",
        "best", "never", "because",
        "however", "finally", "interesting",
        "incredible", "remember", "actually"
    ]

    candidates = []

    last_start = video_duration - clip_length
    start = 0

    while start <= last_start:
        end = start + clip_length

        relevant = [
            s for s in segments
            if s["start"] < end and s["end"] > start
        ]

        text = " ".join(s["text"] for s in relevant)
        words = text.split()

        if len(words) >= 10:
            lower_text = text.lower()

            keyword_score = sum(
                1 for word in keywords
                if word in lower_text
            )

            speech_score = min(len(words), 250)

            score = speech_score + keyword_score * 12

            candidates.append({
                "start": start,
                "end": end,
                "score": score
            })

        start += 5

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    selected = []

    for candidate in candidates:

        overlaps = any(
            candidate["start"] < item["end"]
            and candidate["end"] > item["start"]
            for item in selected
        )

        if not overlaps:
            selected.append(candidate)

        if len(selected) >= MAX_SHORTS:
            break

    selected.sort(key=lambda x: x["start"])

    if not selected:
        raise ValueError(
            "No suitable clips found. Try a video with more speech."
        )

    return selected


def srt_time(seconds):

    milliseconds = int(seconds * 1000)

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{milliseconds:03}"
    )


def create_srt(segments, start, end, output_path):

    lines = []
    index = 1

    for segment in segments:

        if segment["end"] <= start:
            continue

        if segment["start"] >= end:
            continue

        clip_start = max(0, segment["start"] - start)
        clip_end = min(
            end - start,
            segment["end"] - start
        )

        if clip_end <= clip_start:
            continue

        lines.extend([
            str(index),
            f"{srt_time(clip_start)} --> {srt_time(clip_end)}",
            segment["text"].strip(),
            ""
        ])

        index += 1

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )


def update_job(job_id, **values):

    with JOB_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)


def process_video(job_id, filename, clip_length, video_format):

    try:

        video_path = UPLOAD_FOLDER / filename
        job_folder = OUTPUT_FOLDER / job_id

        job_folder.mkdir(exist_ok=True)

        update_job(
            job_id,
            status="processing",
            progress=5,
            message="Reading video..."
        )

        duration = get_video_duration(video_path)

        if duration < clip_length:
            raise ValueError(
                f"Video must be at least {clip_length} seconds long"
            )

        update_job(
            job_id,
            progress=15,
            message="Loading AI speech model..."
        )

        model = get_model()

        update_job(
            job_id,
            progress=25,
            message="AI is analyzing speech..."
        )

        transcription, info = model.transcribe(
            str(video_path),
            beam_size=1,
            vad_filter=True
        )

        segments = []

        for segment in transcription:
            segments.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip()
            })

        if not segments:
            raise ValueError("No speech detected in video")

        update_job(
            job_id,
            progress=55,
            message="Finding the best moments..."
        )

        clips = select_best_clips(
            segments,
            duration,
            clip_length
        )

        width, height = FORMATS[video_format]

        results = []

        for index, clip in enumerate(clips, start=1):

            start = clip["start"]
            end = clip["end"]

            mp4_name = f"short_{index}.mp4"
            srt_name = f"short_{index}.srt"

            mp4_path = job_folder / mp4_name
            srt_path = job_folder / srt_name

            update_job(
                job_id,
                progress=55 + int(
                    index / len(clips) * 40
                ),
                message=f"Creating Short {index} of {len(clips)}..."
            )

            create_srt(
                segments,
                start,
                end,
                srt_path
            )

            video_filter = (
                f"scale={width}:{height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1"
            )

            command = [
                "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(end - start),
                "-vf", video_filter,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(mp4_path)
            ]

            result = run_ffmpeg(command)

            if result.returncode != 0:
                raise RuntimeError(
                    "Video rendering failed: "
                    + result.stderr[-1500:]
                )

            results.append({
                "clip": index,
                "video": mp4_name,
                "captions": srt_name,
                "video_url": f"/download/{job_id}/{mp4_name}",
                "captions_url": f"/download/{job_id}/{srt_name}",
                "start": round(start, 2),
                "end": round(end, 2),
                "duration": round(end - start, 2)
            })

        update_job(
            job_id,
            status="completed",
            progress=100,
            message="All clips created successfully!",
            clips=results,
            shorts=results,
            language=info.language
        )

    except Exception as error:

        update_job(
            job_id,
            status="failed",
            progress=0,
            message=str(error)
        )


@app.route("/")
def home():
    return send_from_directory(BASE, "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/upload", methods=["POST"])
def upload_video():

    if "video" not in request.files:
        return jsonify({
            "error": "Video file missing"
        }), 400

    video = request.files["video"]

    if not video.filename:
        return jsonify({
            "error": "Filename missing"
        }), 400

    extension = Path(video.filename).suffix.lower()

    allowed = [
        ".mp4", ".mov", ".mkv",
        ".avi", ".webm"
    ]

    if extension not in allowed:
        return jsonify({
            "error": "Unsupported video format"
        }), 400

    filename = f"{uuid.uuid4().hex}{extension}"

    video.save(UPLOAD_FOLDER / filename)

    return jsonify({
        "message": "Video uploaded successfully",
        "filename": filename
    })


@app.route("/process", methods=["POST"])
def start_processing():

    data = request.get_json(silent=True) or {}

    filename = data.get("filename", "")

    if (
        not filename
        or Path(filename).name != filename
    ):
        return jsonify({
            "error": "Invalid filename"
        }), 400

    try:
        clip_length = int(data.get("duration", 30))
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid duration"
        }), 400

    if clip_length not in (30, 60):
        return jsonify({
            "error": "Duration must be 30 or 60 seconds"
        }), 400

    video_format = data.get("format", "9:16")

    if video_format not in FORMATS:
        return jsonify({
            "error": "Invalid video format"
        }), 400

    video_path = UPLOAD_FOLDER / filename

    if not video_path.is_file():
        return jsonify({
            "error": "Uploaded video not found"
        }), 404

    job_id = uuid.uuid4().hex

    with JOB_LOCK:
        JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": "Waiting for processing...",
            "clips": [],
            "duration": clip_length,
            "format": video_format
        }

    thread = threading.Thread(
        target=process_video,
        args=(
            job_id,
            filename,
            clip_length,
            video_format
        ),
        daemon=True
    )

    thread.start()

    return jsonify({
        "message": "Processing started",
        "job_id": job_id,
        "status_url": f"/status/{job_id}"
    }), 202


@app.route("/status/<job_id>")
def processing_status(job_id):

    with JOB_LOCK:
        job = JOBS.get(job_id)

    if job is None:
        return jsonify({
            "error": "Job not found"
        }), 404

    return jsonify(job)


@app.route("/download/<job_id>/<filename>")
def download_clip(job_id, filename):

    if (
        Path(job_id).name != job_id
        or Path(filename).name != filename
    ):
        return jsonify({
            "error": "Invalid path"
        }), 400

    folder = OUTPUT_FOLDER / job_id

    if not folder.is_dir():
        return jsonify({
            "error": "Job not found"
        }), 404

    return send_from_directory(
        folder,
        filename,
        as_attachment=True
    )


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )

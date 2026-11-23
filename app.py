
import os
import uuid
import threading
import subprocess
import shutil
from pathlib import Path

from flask import Flask, request, jsonify, send_file, render_template_string
from faster_whisper import WhisperModel

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE_DIR = Path("/tmp/ai_shorts_maker")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

jobs = {}
processing_lock = threading.Lock()
model = None

def get_model():
    global model
    if model is None:
        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=2
        )
    return model

def run_command(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return result

def get_duration(video_path):
    result = run_command([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ])
    return float(result.stdout.strip())

def process_video(job_id, video_path):
    try:
        jobs[job_id]["status"] = "Loading AI model"
        jobs[job_id]["progress"] = 10

        whisper = get_model()

        jobs[job_id]["status"] = "Transcribing audio"
        jobs[job_id]["progress"] = 25

        segments, info = whisper.transcribe(
            str(video_path),
            beam_size=1,
            vad_filter=True
        )

        segments = list(segments)

        jobs[job_id]["progress"] = 45
        jobs[job_id]["status"] = "Preparing short clips"

        duration = get_duration(video_path)
        clip_length = 60
        total_clips = max(1, int((duration + clip_length - 1) // clip_length))

        output_folder = OUTPUT_DIR / job_id
        output_folder.mkdir(parents=True, exist_ok=True)

        clip_files = []

        for i in range(total_clips):
            start = i * clip_length
            length = min(clip_length, duration - start)

            if length <= 0:
                continue

            output_file = output_folder / f"short_{i+1}.mp4"

            jobs[job_id]["status"] = (
                f"Rendering clip {i+1} of {total_clips}"
            )

            command = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(length),
                "-vf",
                "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
                "scale=1080:1920",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_file)
            ]

            run_command(command)
            clip_files.append(output_file.name)

            progress = 45 + int(((i + 1) / total_clips) * 50)
            jobs[job_id]["progress"] = min(progress, 95)

        jobs[job_id]["clips"] = clip_files
        jobs[job_id]["progress"] = 100
        jobs[job_id]["status"] = "Completed"

    except Exception as e:
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = str(e)[:1500]

    finally:
        try:
            video_path.unlink(missing_ok=True)
        except Exception:
            pass

        processing_lock.release()


HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Shorts Maker</title>
<style>
body {
    background:#111827;
    color:white;
    font-family:Arial,sans-serif;
    padding:20px;
    margin:0;
}
.container {
    max-width:650px;
    margin:30px auto;
    background:#1f2937;
    padding:25px;
    border-radius:15px;
}
h1 {text-align:center;color:#38bdf8;}
button {
    background:#0ea5e9;
    border:none;
    padding:12px 20px;
    border-radius:8px;
    color:white;
    font-size:16px;
    cursor:pointer;
    width:100%;
}
input {width:100%;margin:20px 0;}
.progress {
    background:#374151;
    border-radius:10px;
    height:25px;
    overflow:hidden;
    margin-top:20px;
}
.bar {
    height:100%;
    background:#0ea5e9;
    width:0%;
    transition:width .3s;
}
#status {margin-top:20px;text-align:center;}
a {color:#38bdf8;display:block;margin:12px 0;}
</style>
</head>
<body>
<div class="container">
<h1>AI Shorts Maker</h1>
<p>Upload your video to create vertical 60-second clips.</p>

<input type="file" id="video" accept="video/*">
<button onclick="uploadVideo()">Create Shorts</button>

<div class="progress">
<div class="bar" id="bar"></div>
</div>

<div id="status">Ready</div>
<div id="downloads"></div>
</div>

<script>
let currentJob = null;

async function uploadVideo() {
    const file = document.getElementById("video").files[0];

    if (!file) {
        alert("Please select a video.");
        return;
    }

    const btn = document.querySelector("button");
    btn.disabled = true;
    document.getElementById("downloads").innerHTML = "";
    document.getElementById("status").innerText = "Uploading video...";

    const data = new FormData();
    data.append("video", file);

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: data
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Upload failed");
        }

        currentJob = result.job_id;
        pollStatus();

    } catch (error) {
        document.getElementById("status").innerText =
            "Error: " + error.message;
        btn.disabled = false;
    }
}

async function pollStatus() {
    if (!currentJob) return;

    try {
        const response = await fetch("/status/" + currentJob);
        const data = await response.json();

        document.getElementById("bar").style.width =
            data.progress + "%";

        document.getElementById("status").innerText =
            data.status + " (" + data.progress + "%)";

        if (data.status === "Completed") {
            let html = "<h3>Your Shorts:</h3>";

            data.clips.forEach(function(clip) {
                html += '<a href="/download/' +
                    currentJob + '/' + encodeURIComponent(clip) +
                    '">Download ' + clip + '</a>';
            });

            document.getElementById("downloads").innerHTML = html;
            document.querySelector("button").disabled = false;
            currentJob = null;
            return;
        }

        if (data.status === "Failed") {
            document.getElementById("status").innerText =
                "Failed: " + (data.error || "Unknown error");
            document.querySelector("button").disabled = false;
            currentJob = null;
            return;
        }

        setTimeout(pollStatus, 3000);

    } catch (error) {
        document.getElementById("status").innerText =
            "Connection interrupted. Rechecking processing status...";
        setTimeout(pollStatus, 5000);
    }
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/upload", methods=["POST"])
def upload():
    if not processing_lock.acquire(blocking=False):
        return jsonify({
            "error": "Another video is processing. Please wait."
        }), 429

    try:
        if "video" not in request.files:
            processing_lock.release()
            return jsonify({"error": "No video selected"}), 400

        file = request.files["video"]

        if not file.filename:
            processing_lock.release()
            return jsonify({"error": "Invalid file"}), 400

        job_id = str(uuid.uuid4())
        video_path = UPLOAD_DIR / f"{job_id}.mp4"

        file.save(video_path)

        jobs[job_id] = {
            "status": "Queued",
            "progress": 0,
            "clips": [],
            "error": None
        }

        thread = threading.Thread(
            target=process_video,
            args=(job_id, video_path),
            daemon=True
        )
        thread.start()

        return jsonify({"job_id": job_id})

    except Exception as e:
        if processing_lock.locked():
            processing_lock.release()
        return jsonify({"error": str(e)}), 500

@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job)

@app.route("/download/<job_id>/<filename>")
def download(job_id, filename):
    folder = OUTPUT_DIR / job_id
    file_path = folder / filename

    if not file_path.exists() or file_path.parent != folder:
        return jsonify({"error": "File not found"}), 404

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=filename
    )

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "Video is too large. Maximum 500 MB."}), 413

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )

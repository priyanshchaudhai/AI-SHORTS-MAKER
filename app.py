import os
import uuid
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename

from processor import process_video

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

BASE = Path("/tmp/ai_shorts")
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"

UPLOADS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()
processing_lock = threading.Lock()


# ---------------- JOB UPDATE ----------------

def update_job(job_id, progress, status):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["progress"] = int(progress)
            jobs[job_id]["status"] = status


# ---------------- PROCESS JOB ----------------

def process_job(job_id, video_path, video_format):
    output_folder = OUTPUTS / job_id

    try:
        update_job(job_id, 2, "Starting video analysis")

        output_folder.mkdir(parents=True, exist_ok=True)

        def progress_callback(value, message):
            update_job(job_id, value, message)

        clips = process_video(
            video_path,
            output_folder,
            video_format=video_format,
            progress_callback=progress_callback
        )

        with jobs_lock:
            jobs[job_id]["clips"] = clips
            jobs[job_id]["progress"] = 100
            jobs[job_id]["status"] = "Completed"
            jobs[job_id]["error"] = None

    except Exception as e:
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "Failed"
                jobs[job_id]["error"] = str(e)[:2000]
                jobs[job_id]["progress"] = 0

    finally:
        try:
            video_path.unlink(missing_ok=True)
        except Exception:
            pass

        processing_lock.release()


# ---------------- FRONTEND ----------------

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Viral Shorts Maker</title>
<style>
body {
    background:#101827;
    color:white;
    font-family:Arial,sans-serif;
    margin:0;
    padding:20px;
}
.container {
    max-width:700px;
    margin:40px auto;
    background:#1e293b;
    padding:25px;
    border-radius:16px;
}
h1 {
    text-align:center;
    color:#38bdf8;
}
input, select {
    margin:20px 0;
    width:100%;
    box-sizing:border-box;
    padding:12px;
}
button {
    width:100%;
    padding:14px;
    background:#0284c7;
    color:white;
    border:0;
    border-radius:10px;
    font-size:17px;
    cursor:pointer;
}
button:disabled {
    opacity:.5;
}
.progress {
    background:#334155;
    height:24px;
    border-radius:12px;
    overflow:hidden;
    margin-top:20px;
}
.bar {
    height:100%;
    background:#22c55e;
    width:0%;
    transition:width .4s;
}
#status {
    text-align:center;
    margin-top:20px;
}
a {
    display:block;
    color:#38bdf8;
    margin:15px 0;
}
.note {
    color:#94a3b8;
    font-size:14px;
}
</style>
</head>
<body>
<div class="container">
<h1>AI Viral Shorts Maker</h1>

<p>Upload your video. AI will analyze speech,
find interesting moments and create Shorts.</p>

<input type="file" id="video" accept="video/*">

<label for="format">Video format</label>

<select id="format">
<option value="9:16">9:16 Vertical</option>
<option value="16:9">16:9 Landscape</option>
<option value="1:1">1:1 Square</option>
</select>

<button id="btn" onclick="uploadVideo()">
Find Viral Moments
</button>

<div class="progress">
<div class="bar" id="bar"></div>
</div>

<div id="status">Ready</div>
<div id="downloads"></div>

<p class="note">
AI selects transcript-based moments.
Viral performance is not guaranteed.
</p>
</div>

<script>
let job = null;
let polling = false;

async function uploadVideo() {
    const file = document.getElementById("video").files[0];

    if (!file) {
        alert("Select a video first.");
        return;
    }

    const btn = document.getElementById("btn");
    btn.disabled = true;

    document.getElementById("downloads").innerHTML = "";
    document.getElementById("bar").style.width = "0%";
    document.getElementById("status").innerText = "Uploading video...";

    const form = new FormData();
    form.append("video", file);
    form.append("format", document.getElementById("format").value);

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: form
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Upload failed");
        }

        job = data.job_id;
        polling = false;
        checkStatus();

    } catch (e) {
        document.getElementById("status").innerText =
            "Error: " + e.message;
        btn.disabled = false;
    }
}

async function checkStatus() {
    if (!job || polling) return;

    polling = true;

    try {
        const response = await fetch("/status/" + job);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Status unavailable");
        }

        document.getElementById("bar").style.width =
            data.progress + "%";

        document.getElementById("status").innerText =
            data.status + " (" + data.progress + "%)";

        if (data.status === "Completed") {
            let html = "<h3>Created Shorts</h3>";

            data.clips.forEach(function(clip, index) {
                html += "<h4>Short " + (index + 1) + "</h4>";

                html += '<a href="/download/' + job + '/' +
                    encodeURIComponent(clip.video) + '">' +
                    'Download Video</a>';

                if (clip.captions) {
                    html += '<a href="/download/' + job + '/' +
                        encodeURIComponent(clip.captions) + '">' +
                        'Download Subtitles</a>';
                }
            });

            document.getElementById("downloads").innerHTML = html;
            document.getElementById("btn").disabled = false;
            job = null;
            polling = false;
            return;
        }

        if (data.status === "Failed") {
            document.getElementById("status").innerText =
                "Failed: " + (data.error || "Unknown error");

            document.getElementById("btn").disabled = false;
            job = null;
            polling = false;
            return;
        }

        polling = false;
        setTimeout(checkStatus, 3000);

    } catch (e) {
        polling = false;

        document.getElementById("status").innerText =
            "Connection interrupted. Retrying...";

        setTimeout(checkStatus, 5000);
    }
}
</script>
</body>
</html>
"""


# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return HTML


@app.route("/upload", methods=["POST"])
def upload():

    if not processing_lock.acquire(blocking=False):
        return jsonify({
            "error": "Another video is processing. Please wait."
        }), 429

    video_path = None

    try:
        if "video" not in request.files:
            return jsonify({"error": "Video missing"}), 400

        file = request.files["video"]

        if not file.filename:
            return jsonify({"error": "Invalid filename"}), 400

        video_format = request.form.get("format", "9:16")

        allowed_formats = {"9:16", "16:9", "1:1"}

        if video_format not in allowed_formats:
            return jsonify({"error": "Invalid video format"}), 400

        original_name = secure_filename(file.filename)

        extension = Path(original_name).suffix.lower()

        if not extension:
            extension = ".mp4"

        job_id = str(uuid.uuid4())

        video_path = UPLOADS / f"{job_id}{extension}"

        file.save(video_path)

        with jobs_lock:
            jobs[job_id] = {
                "status": "Queued",
                "progress": 0,
                "clips": [],
                "error": None
            }

        thread = threading.Thread(
            target=process_job,
            args=(job_id, video_path, video_format),
            daemon=True
        )

        thread.start()

        return jsonify({"job_id": job_id})

    except Exception as e:

        if video_path and video_path.exists():
            video_path.unlink(missing_ok=True)

        return jsonify({"error": str(e)}), 500

    finally:
        # Lock remains held when a processing thread starts.
        # If no job was started, release it here.
        if video_path is None or not video_path.exists():
            if processing_lock.locked():
                processing_lock.release()


@app.route("/status/<job_id>")
def status(job_id):

    with jobs_lock:
        job = jobs.get(job_id)

        if job is None:
            return jsonify({"error": "Job not found"}), 404

        return jsonify(job.copy())


@app.route("/download/<job_id>/<filename>")
def download(job_id, filename):

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    safe_name = Path(filename).name

    if safe_name != filename:
        return jsonify({"error": "Invalid filename"}), 400

    folder = OUTPUTS / job_id
    path = folder / safe_name

    if not path.is_file():
        return jsonify({"error": "File not found"}), 404

    return send_file(
        str(path),
        as_attachment=True,
        download_name=safe_name
    )


@app.errorhandler(413)
def too_large(error):
    return jsonify({
        "error": "Maximum upload size is 500 MB."
    }), 413


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error."
    }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
)

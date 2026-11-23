import re
import subprocess
import shutil
from pathlib import Path

import imageio_ffmpeg
from faster_whisper import WhisperModel


MODEL = None

CHUNK_SECONDS = 300
CLIP_LENGTH = 40
STEP = 10
MAX_CLIPS = 3

HOOK_WORDS = {
    "secret", "truth", "mistake", "never", "always",
    "why", "how", "amazing", "crazy", "insane",
    "important", "money", "success", "failure",
    "lesson", "learn", "best", "worst", "stop",
    "listen", "believe", "remember", "problem",
    "solution", "warning", "tip", "trick",
    "million", "powerful", "change", "actually",
    "surprising", "because", "free", "danger",
    "wrong", "right", "easy", "imagine", "real"
}

HOOK_PHRASES = [
    "the truth is",
    "here is why",
    "here's why",
    "the biggest mistake",
    "you need to",
    "you should never",
    "what if",
    "let me tell you",
    "the secret",
    "this is important",
    "most people",
    "nobody tells you",
    "listen to me",
    "the problem is",
    "the reason is",
    "you can actually",
    "this is how"
]


# ---------------- MODEL ----------------

def get_model(progress_callback=None):
    global MODEL

    if MODEL is None:
        if progress_callback:
            progress_callback(5, "Loading AI speech model...")

        MODEL = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=2,
            num_workers=1
        )

    return MODEL


# ---------------- FFMPEG ----------------

def run_ffmpeg(command, timeout=1800):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed: " + result.stderr[-2000:]
        )

    return result


def get_duration(video_path, ffmpeg):
    # Try ffprobe first.
    ffprobe = shutil.which("ffprobe")

    if ffprobe:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            try:
                value = float(result.stdout.strip())

                if value > 0:
                    return value
            except ValueError:
                pass

    # Fallback: decode video and obtain duration from transcript.
    return None


# ---------------- TRANSCRIPT ----------------

def transcribe_chunks(audio_chunks, progress_callback=None):
    model = get_model(progress_callback)

    transcript = []
    total = len(audio_chunks)

    for index, audio_chunk in enumerate(audio_chunks):

        if progress_callback:
            progress_callback(
                10 + int(index / max(total, 1) * 35),
                f"AI analyzing audio {index + 1}/{total}..."
            )

        offset = index * CHUNK_SECONDS

        segments, info = model.transcribe(
            str(audio_chunk),
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False
        )

        for segment in segments:
            text = segment.text.strip()

            if not text:
                continue

            transcript.append({
                "start": float(segment.start) + offset,
                "end": float(segment.end) + offset,
                "text": text
            })

    transcript.sort(key=lambda item: item["start"])

    return transcript


# ---------------- VIRAL SCORING ----------------

def score_window(segments, start, end):

    selected = [
        segment for segment in segments
        if segment["end"] > start
        and segment["start"] < end
    ]

    if not selected:
        return 0

    text = " ".join(
        segment["text"] for segment in selected
    ).lower()

    words = re.findall(r"\b[\w']+\b", text)
    word_count = len(words)

    if word_count < 15:
        return 0

    score = 0

    # Keyword scoring
    for word in HOOK_WORDS:
        matches = len(
            re.findall(
                r"\b" + re.escape(word) + r"\b",
                text
            )
        )

        score += min(matches, 3) * 1.5

    # Hook phrase scoring
    for phrase in HOOK_PHRASES:
        if phrase in text:
            score += 5

    duration = max(end - start, 1)
    words_per_second = word_count / duration

    if 1.8 <= words_per_second <= 3.5:
        score += 8
    elif words_per_second > 1:
        score += 4

    score += text.count("?") * 2
    score += text.count("!") * 2

    score += min(len(selected), 20) * 0.4

    if word_count < 25:
        score -= 8

    return score


def find_moments(transcript, video_duration):

    if video_duration <= CLIP_LENGTH:
        return [{
            "start": 0.0,
            "end": video_duration,
            "score": score_window(
                transcript, 0, video_duration
            )
        }]

    candidates = []

    for start in range(0, int(video_duration), STEP):

        end = min(start + CLIP_LENGTH, video_duration)

        if end - start < 15:
            continue

        score = score_window(
            transcript,
            start,
            end
        )

        if score > 0:
            candidates.append({
                "start": float(start),
                "end": float(end),
                "score": float(score)
            })

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    selected = []

    for candidate in candidates:

        overlapping = False

        for existing in selected:

            overlap = max(
                0,
                min(candidate["end"], existing["end"])
                - max(candidate["start"], existing["start"])
            )

            if overlap > 10:
                overlapping = True
                break

        if not overlapping:
            selected.append(candidate)

        if len(selected) >= MAX_CLIPS:
            break

    selected.sort(key=lambda item: item["start"])

    return selected


# ---------------- SUBTITLES ----------------

def srt_time(seconds):

    total_ms = max(0, round(seconds * 1000))

    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{millis:03}"
    )


def create_srt(transcript, clip_start, clip_end, srt_path):

    lines = []
    number = 1

    for segment in transcript:

        if segment["end"] <= clip_start:
            continue

        if segment["start"] >= clip_end:
            continue

        start = max(segment["start"], clip_start) - clip_start
        end = min(segment["end"], clip_end) - clip_start

        if end <= start:
            continue

        text = segment["text"].strip()

        if not text:
            continue

        lines.extend([
            str(number),
            f"{srt_time(start)} --> {srt_time(end)}",
            text,
            ""
        ])

        number += 1

    srt_path.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )


# ---------------- RENDER ----------------

def render_clip(
    video_path,
    moment,
    transcript,
    output_video,
    output_srt,
    video_format,
    ffmpeg
):

    start = moment["start"]
    end = moment["end"]

    formats = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080)
    }

    if video_format not in formats:
        raise ValueError("Unsupported video format.")

    width, height = formats[video_format]

    create_srt(
        transcript,
        start,
        end,
        output_srt
    )

    # Escape paths for FFmpeg subtitles filter.
    srt_path = str(output_srt).replace("\\", "/")

    srt_path = (
        srt_path
        .replace(":", "\\:")
        .replace("'", "\\'")
    )

    subtitle_filter = (
        f"subtitles='{srt_path}':"
        "force_style='FontSize=22,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=120'"
    )

    video_filter = (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        + subtitle_filter
    )

    run_ffmpeg([
        ffmpeg,
        "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(end - start),
        "-vf", video_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_video)
    ], timeout=1800)


# ---------------- MAIN PROCESS ----------------

def process_video(
    video_path,
    output_dir,
    video_format="9:16",
    progress_callback=None
):

    def update(value, message):
        if progress_callback:
            progress_callback(value, message)

    video_path = Path(video_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    temp_audio = output_dir / "_audio_chunks"

    if temp_audio.exists():
        shutil.rmtree(temp_audio)

    temp_audio.mkdir(parents=True)

    try:

        update(3, "Extracting audio...")

        audio_pattern = str(
            temp_audio / "audio_%03d.wav"
        )

        run_ffmpeg([
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-f", "segment",
            "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1",
            audio_pattern
        ], timeout=1800)

        audio_chunks = sorted(
            temp_audio.glob("audio_*.wav")
        )

        if not audio_chunks:
            raise RuntimeError(
                "Could not extract audio."
            )

        update(8, "Transcribing audio...")

        transcript = transcribe_chunks(
            audio_chunks,
            update
        )

        if not transcript:
            raise RuntimeError(
                "No speech detected in video."
            )

        transcript_duration = max(
            segment["end"] for segment in transcript
        )

        actual_duration = get_duration(
            video_path,
            ffmpeg
        )

        video_duration = (
            actual_duration
            if actual_duration
            else transcript_duration
        )

        if video_duration <= 0:
            raise RuntimeError(
                "Could not determine video duration."
            )

        update(48, "Finding viral moments...")

        moments = find_moments(
            transcript,
            video_duration
        )

        if not moments:
            raise RuntimeError(
                "No suitable clips found."
            )

        results = []

        for index, moment in enumerate(moments, start=1):

            update(
                50 + int(
                    (index - 1) / len(moments) * 45
                ),
                f"Rendering Short {index}/{len(moments)}..."
            )

            output_video = (
                output_dir / f"short_{index}.mp4"
            )

            output_srt = (
                output_dir / f"short_{index}.srt"
            )

            render_clip(
                video_path,
                moment,
                transcript,
                output_video,
                output_srt,
                video_format,
                ffmpeg
            )

            results.append({
                "video": output_video.name,
                "captions": output_srt.name,
                "start": round(moment["start"], 2),
                "end": round(moment["end"], 2),
                "score": round(moment["score"], 2)
            })

        update(100, "Completed")

        return results

    finally:

        shutil.rmtree(
            temp_audio,
            ignore_errors=True
                )

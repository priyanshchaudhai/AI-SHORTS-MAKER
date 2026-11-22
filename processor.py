
import subprocess
from pathlib import Path
import shutil

import imageio_ffmpeg
from faster_whisper import WhisperModel

MODEL = None
CHUNK_SECONDS = 300  # 5 minutes


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


def make_srt_time(seconds):
    total_ms = max(0, round(seconds * 1000))

    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def run_ffmpeg(command, timeout=1800):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed: " + result.stderr[-1500:]
        )


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
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    temp_audio = output_dir / "_audio_chunks"

    if temp_audio.exists():
        shutil.rmtree(temp_audio)

    temp_audio.mkdir(parents=True)

    try:
        update(3, "Extracting audio in chunks...")

        audio_pattern = str(temp_audio / "audio_%03d.wav")

        # Extract audio into 5-minute chunks.
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

        audio_chunks = sorted(temp_audio.glob("audio_*.wav"))

        if not audio_chunks:
            raise ValueError("Could not extract audio from video.")

        update(8, "Loading AI speech model...")

        model = get_model(update)

        transcript = []
        total_chunks = len(audio_chunks)

        for chunk_index, audio_chunk in enumerate(audio_chunks):
            update(
                10 + int(chunk_index / total_chunks * 35),
                f"AI analyzing audio chunk {chunk_index + 1} of {total_chunks}..."
            )

            offset = chunk_index * CHUNK_SECONDS

            segments, info = model.transcribe(
                str(audio_chunk),
                vad_filter=True,
                beam_size=1,
                condition_on_previous_text=False
            )

            for segment in segments:
                transcript.append({
                    "start": float(segment.start) + offset,
                    "end": float(segment.end) + offset,
                    "text": segment.text.strip()
                })

        transcript.sort(key=lambda item: item["start"])

        if not transcript:
            raise ValueError(
                "No speech detected. Try a video with clear speech."
            )

        duration = transcript[-1]["end"]

        if duration <= 0:
            raise ValueError("Could not determine video duration.")

        update(48, "AI analysis completed. Finding clips...")

        clip_length = 30

        keywords = [
            "wow", "amazing", "secret", "important",
            "best", "why", "how", "incredible",
            "never", "because", "mistake", "tip",
            "problem", "solution", "learn"
        ]

        windows = []

        start = 0

        while start < duration:
            end = min(start + clip_length, duration)

            if end - start >= 5:
                selected = []
                speech_duration = 0
                keyword_score = 0

                for segment in transcript:
                    overlap = max(
                        0,
                        min(segment["end"], end)
                        - max(segment["start"], start)
                    )

                    if overlap > 0:
                        selected.append(segment)
                        speech_duration += overlap

                        text = segment["text"].lower()

                        keyword_score += sum(
                            1 for word in keywords
                            if word in text
                        )

                if selected:
                    score = speech_duration + keyword_score * 2

                    windows.append({
                        "score": score,
                        "start": start,
                        "end": end,
                        "segments": selected
                    })

            start += clip_length

        windows.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        selected_windows = []

        for candidate in windows:
            overlaps = any(
                candidate["start"] < chosen["end"]
                and candidate["end"] > chosen["start"]
                for chosen in selected_windows
            )

            if not overlaps:
                selected_windows.append(candidate)

            if len(selected_windows) >= 3:
                break

        if not selected_windows:
            raise ValueError("No suitable clips found.")

        selected_windows.sort(key=lambda item: item["start"])

        formats = {
            "9:16": "1080:1920",
            "16:9": "1920:1080",
            "1:1": "1080:1080"
        }

        if video_format not in formats:
            raise ValueError("Unsupported output format.")

        width, height = formats[video_format].split(":")

        results = []

        for index, item in enumerate(selected_windows, start=1):
            start = item["start"]
            end = item["end"]
            selected = item["segments"]

            update(
                55 + int((index - 1) / len(selected_windows) * 40),
                f"Rendering Short {index} of {len(selected_windows)}..."
            )

            output_video = output_dir / f"short_{index}.mp4"
            output_srt = output_dir / f"short_{index}.srt"

            filter_video = (
                f"scale={width}:{height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )

            run_ffmpeg([
                ffmpeg,
                "-y",
                "-ss", str(start),
                "-i", str(video_path),
                "-t", str(end - start),
                "-vf", filter_video,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_video)
            ], timeout=1800)

            subtitles = []

            for segment in selected:
                sub_start = max(segment["start"], start) - start
                sub_end = min(segment["end"], end) - start

                if sub_end <= sub_start:
                    continue

                subtitles.append(
                    f"{len(subtitles) + 1}\n"
                    f"{make_srt_time(sub_start)} --> "
                    f"{make_srt_time(sub_end)}\n"
                    f"{segment['text']}\n"
                )

            output_srt.write_text(
                "\n".join(subtitles),
                encoding="utf-8"
            )

            results.append({
                "video": output_video.name,
                "captions": output_srt.name,
                "start": start,
                "end": end
            })

        update(100, "AI Shorts are ready!")

        return results

    finally:
        shutil.rmtree(temp_audio, ignore_errors=True)

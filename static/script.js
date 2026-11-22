const form = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoFile");
const formatInput = document.getElementById("format");
const statusText = document.getElementById("status");

const resultsBox = document.createElement("div");
resultsBox.id = "results";
form.after(resultsBox);

form.addEventListener("submit", async function(event) {
    event.preventDefault();

    const file = videoInput.files[0];

    if (!file) {
        statusText.textContent = "Please select a video!";
        return;
    }

    const formData = new FormData();

    formData.append("file", file);
    formData.append("format", formatInput.value);

    resultsBox.replaceChildren();

    statusText.textContent =
        "Uploading video and processing with AI... Please wait.";

    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "AI Processing...";

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || "Processing failed");
        }

        statusText.textContent =
            result.message || "AI Shorts generated!";

        if (!result.shorts || result.shorts.length === 0) {
            statusText.textContent =
                "No suitable clips found in this video.";
            return;
        }

        const heading = document.createElement("h2");
        heading.textContent = "Your AI Shorts 🎬";
        resultsBox.appendChild(heading);

        result.shorts.forEach((short, index) => {
            const card = document.createElement("div");

            card.style.padding = "15px";
            card.style.margin = "15px 0";
            card.style.background = "#252f48";
            card.style.borderRadius = "12px";

            const title = document.createElement("h3");
            title.textContent = "Short Video " + (index + 1);

            const video = document.createElement("video");
            video.src = short.video_url;
            video.controls = true;
            video.playsInline = true;
            video.style.width = "100%";
            video.style.maxWidth = "300px";

            const download = document.createElement("a");
            download.href = short.video_url;
            download.download = short.video;
            download.textContent = "⬇ Download Short Video";

            const captions = document.createElement("a");
            captions.href = short.captions_url;
            captions.download = short.captions;
            captions.textContent = "⬇ Download Captions";

            download.style.display = "block";
            captions.style.display = "block";
            download.style.marginTop = "12px";
            captions.style.marginTop = "10px";

            card.append(
                title,
                video,
                download,
                captions
            );

            resultsBox.appendChild(card);
        });

    } catch (error) {
        statusText.textContent = "Error: " + error.message;

    } finally {
        button.disabled = false;
        button.textContent = "🚀 Generate AI Shorts";
    }
});

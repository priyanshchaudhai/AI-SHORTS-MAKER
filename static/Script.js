const form = document.getElementById("uploadForm");
const videoInput = document.getElementById("videoFile");
const formatInput = document.getElementById("format");
const statusText = document.getElementById("status");

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

    statusText.textContent = "Uploading video... Please wait.";

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || "Upload failed");
        }

        statusText.textContent =
            result.message || "Video uploaded successfully!";

    } catch (error) {
        statusText.textContent =
            "Error: " + error.message;
    }
});

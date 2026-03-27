async function analyze() {

    const resumes = document.getElementById("resumeInput").files;
    const jdText = document.getElementById("jdText").value;

    if (resumes.length === 0 || jdText.trim() === "") {
        alert("Upload resumes and paste Job Description");
        return;
    }

    const formData = new FormData();

    for (let file of resumes) {
        formData.append("resumes", file);
    }

    formData.append("jd", jdText);

    const response = await fetch("/analyze", {
        method: "POST",
        body: formData
    });

    if (response.ok) {
        alert("Analysis Complete!");
    } else {
        alert("Error in analysis");
    }
}

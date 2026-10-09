const notesInput = document.getElementById("notes-input");
const fileInput = document.getElementById("notes-file");
const dateInput = document.getElementById("meeting-date");
const statusOutput = document.getElementById("api-status");
const markdownOutput = document.getElementById("notes-output");

fileInput?.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (file) notesInput.value = await file.text();
});

document.getElementById("process-notes")?.addEventListener("click", async () => {
  if (!notesInput.value.trim()) {
    statusOutput.textContent = "Error: ingresá las notas primero";
    return;
  }
  if (fileInput.files.length > 0 && !dateInput.value) {
    statusOutput.textContent = "Error: ingresá la fecha de la reunión para procesar el archivo";
    dateInput.focus();
    return;
  }

  statusOutput.textContent = "Procesando...";
  try {
    const body = {notes: notesInput.value};
    if (dateInput.value) body.meeting_date = dateInput.value;
    const response = await fetch("/api/extract", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || "No se pudo procesar");

    markdownOutput.textContent = data.markdown;
    markdownOutput.classList.remove("text-neutral-500");
    markdownOutput.classList.add("text-neutral-200");
    statusOutput.textContent = "Completado";
  } catch (error) {
    statusOutput.textContent = `Error: ${error.message}`;
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    document.getElementById("process-notes")?.click();
  }
});

const form = document.getElementById("scan-form");
const input = document.getElementById("qr_code");
const panel = document.getElementById("status-panel");
const statusText = document.getElementById("status-text");

let pollTimer = null;

function setPanel(state, message) {
  panel.className = `status-panel status-${state}`;
  statusText.textContent = message;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollAttendee(attendeeId) {
  try {
    const res = await fetch(`/api/checkin/${attendeeId}/`);
    if (!res.ok) {
      setPanel("error", "Lost track of attendee status.");
      stopPolling();
      return;
    }
    const data = await res.json();
    if (data.status === "CHECKED_IN") {
      setPanel("checked-in", `${data.name} is checked in. Badge printed!`);
      stopPolling();
    } else if (data.status === "PENDING") {
      setPanel("pending", `${data.name}: badge printing... please wait.`);
    } else {
      setPanel("error", `${data.name}: badge printing failed. Please rescan.`);
      stopPolling();
    }
  } catch (err) {
    setPanel("error", "Network error while checking status.");
    stopPolling();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  stopPolling();
  const qr_code = input.value.trim();
  if (!qr_code) return;

  setPanel("pending", "Scanning...");

  try {
    const res = await fetch("/api/checkin/scan/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ qr_code }),
    });
    const data = await res.json();

    if (res.status === 202) {
      setPanel("pending", `${data.attendee.name}: badge printing... please wait.`);
      pollTimer = setInterval(() => pollAttendee(data.attendee.id), 1500);
    } else if (res.status === 409 && data.error === "already_checked_in") {
      setPanel("error", "This attendee is already checked in.");
    } else if (res.status === 409 && data.error === "print_already_in_progress") {
      setPanel("pending", "A badge is already printing for this attendee.");
    } else if (res.status === 404) {
      setPanel("error", "QR code not recognized.");
    } else {
      setPanel("error", data.detail || "Something went wrong.");
    }
  } catch (err) {
    setPanel("error", "Network error while scanning.");
  }

  input.value = "";
  input.focus();
});

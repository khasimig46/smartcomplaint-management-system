const $ = (id) => document.getElementById(id);
const token = localStorage.getItem("scms_token");
const user = JSON.parse(localStorage.getItem("scms_user") || "null");
let gps = null;

if (!token) location.href = "/login";
$("who").textContent = user ? `${user.name} (${user.role})` : "";

const say = (text, ok) => { $("message").textContent = text; $("message").className = ok ? "ok" : "err"; };
const clearErrors = () => document.querySelectorAll(".field-err").forEach((e) => (e.textContent = ""));
const showErrors = (fields) => Object.entries(fields || {}).forEach(([k, v]) => {
  const el = document.querySelector(`.field-err[data-for="${k}"]`);
  if (el) el.textContent = v;
});

async function loadCategories() {
  const cats = await (await fetch("/categories")).json();
  $("categorySelect").innerHTML = cats.map((c) => `<option>${c}</option>`).join("");
}

$("gpsBtn").addEventListener("click", () => {
  if (!navigator.geolocation) { $("gpsText").textContent = "GPS not supported by this browser"; return; }
  $("gpsText").textContent = "Locating...";
  navigator.geolocation.getCurrentPosition(
    (p) => { gps = { latitude: p.coords.latitude, longitude: p.coords.longitude };
             $("gpsText").textContent = `${gps.latitude.toFixed(5)}, ${gps.longitude.toFixed(5)}`; },
    () => { $("gpsText").textContent = "Location permission denied (optional)"; });
});

$("suggestBtn").addEventListener("click", async () => {
  clearErrors(); say("");
  const text = `${$("title").value}. ${$("description").value}`.trim();
  const res = await fetch("/suggest-category", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  const data = await res.json();
  if (!res.ok) { say(data.error); return; }
  $("suggestions").innerHTML = data.map((s, i) => `
    <div class="card">
      <strong>${i + 1}. ${s.category}</strong> &mdash; ${s.confidence}% confidence
      <div class="bar"><div style="width:${s.confidence}%"></div></div>
    </div>`).join("");
  $("categorySelect").value = data[0].category;   // pre-select top suggestion
  $("results").classList.remove("hidden");
});

$("submitBtn").addEventListener("click", async () => {
  clearErrors(); say("");
  const fd = new FormData();
  fd.append("title", $("title").value);
  fd.append("description", $("description").value);
  fd.append("severity", $("severity").value);
  fd.append("category", $("categorySelect").value);
  if (gps) { fd.append("latitude", gps.latitude); fd.append("longitude", gps.longitude); }
  for (const f of $("images").files) fd.append("images", f);
  const res = await fetch("/submit-complaint", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd });
  const data = await res.json();
  if (res.status === 401) { location.href = "/login"; return; }
  if (!res.ok) { showErrors(data.fields); say(data.error); return; }
  say(`Complaint submitted. Your ticket ID is ${data.id}. Category: "${data.category}"` +
      (data.overridden ? " (manually overridden)." : "."), true);
  ["title", "description", "severity", "images"].forEach((id) => ($(id).value = ""));
  gps = null; $("gpsText").textContent = ""; $("results").classList.add("hidden");
});

loadCategories();

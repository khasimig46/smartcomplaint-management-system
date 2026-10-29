const $ = (id) => document.getElementById(id);
let suggestions = [];

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, data: await res.json() };
}

async function loadCategories() {
  const cats = await (await fetch("/categories")).json();
  $("categorySelect").innerHTML = cats.map((c) => `<option>${c}</option>`).join("");
}

$("suggestBtn").addEventListener("click", async () => {
  $("message").textContent = "";
  const { ok, data } = await post("/suggest-category", { text: $("text").value });
  if (!ok) { $("message").textContent = data.error; return; }
  suggestions = data;
  $("suggestions").innerHTML = data.map((s, i) => `
    <div class="card">
      <strong>${i + 1}. ${s.category}</strong> &mdash; ${s.confidence}% confidence
      <div class="bar"><div style="width:${s.confidence}%"></div></div>
    </div>`).join("");
  $("categorySelect").value = data[0].category;   // pre-select top suggestion
  $("results").classList.remove("hidden");
});

$("submitBtn").addEventListener("click", async () => {
  const created = await post("/submit-complaint", { text: $("text").value });
  if (!created.ok) { $("message").textContent = created.data.error; return; }
  const chosen = $("categorySelect").value;
  let final = created.data;
  if (chosen !== created.data.category) {              // manual override
    final = (await post("/override-category", {
      complaint_id: created.data.id, category: chosen,
    })).data;
  }
  $("message").textContent =
    `Complaint saved. Your ticket ID is ${final.id}. Category: "${final.category}"` +
    (final.overridden ? " (manually overridden)." : ".");
  $("text").value = ""; $("results").classList.add("hidden");
});

loadCategories();

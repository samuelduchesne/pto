/* ===================================================================
   PTO Vacation Optimizer — Web Application
   Uses Pyodide to run the Python optimizer directly in the browser.
   =================================================================== */

let pyodide = null;
let pythonReady = false;
let currentResults = null;
let activePlanIndex = 0;
const customHolidays = [];

// Month and day names
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DOW_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

// ---- Pyodide bootstrap --------------------------------------------

async function initPyodide() {
  const status = document.getElementById("loader-status");

  try {
    status.textContent = "Downloading Python runtime\u2026";
    pyodide = await loadPyodide();

    status.textContent = "Loading optimizer\u2026";
    // Fetch the Python source files and write them into the Pyodide FS
    const files = [
      { url: "py/holidays.py", path: "/home/pyodide/pto/holidays.py" },
      { url: "py/optimizer.py", path: "/home/pyodide/pto/optimizer.py" },
      { url: "py/__init__.py", path: "/home/pyodide/pto/__init__.py" },
    ];

    pyodide.FS.mkdirTree("/home/pyodide/pto");

    for (const f of files) {
      const resp = await fetch(f.url);
      const text = await resp.text();
      pyodide.FS.writeFile(f.path, text);
    }

    // Add the parent dir to sys.path so "import pto" works
    pyodide.runPython(`
import sys
sys.path.insert(0, "/home/pyodide")
`);

    // Preload the module to warm the import
    pyodide.runPython("import pto");

    pythonReady = true;
    status.textContent = "Ready!";

    // Fade out the loader
    setTimeout(() => {
      document.getElementById("pyodide-loader").classList.add("hidden");
    }, 300);
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    console.error("Pyodide init failed:", err);
  }
}

// ---- Run optimizer in Python --------------------------------------

function runOptimizer(year, budget, floating, country, holidays, strategy) {
  const holidaysJson = JSON.stringify(holidays);
  const code = `
import json, datetime
from pto.optimizer import PTOOptimizer
from pto.holidays import get_holidays

def _run():
    year = ${year}
    budget = ${budget}
    floating_count = ${floating}
    country = ${JSON.stringify(country)}
    extra = json.loads(r'${holidaysJson}')
    strategy = ${JSON.stringify(strategy)}

    holidays = []
    holiday_names = {}

    if country and country != "none":
        preset = get_holidays(country, year)
        for d, name in preset:
            holidays.append(d)
            holiday_names[(d.month, d.day)] = name

    for h in extra:
        holidays.append(datetime.date.fromisoformat(h))

    holidays = sorted(set(holidays))

    optimizer = PTOOptimizer(
        year=year,
        pto_budget=budget,
        holidays=holidays,
        floating_holidays=floating_count,
    )

    strategy_map = {
        "bridges": optimizer.optimize_max_bridges,
        "longest": optimizer.optimize_longest_vacation,
        "weekends": optimizer.optimize_extended_weekends,
        "quarterly": optimizer.optimize_quarterly,
    }

    plans = optimizer.generate_all_plans() if strategy == "all" else [strategy_map[strategy]()]

    result = {
        "year": year,
        "pto_budget": budget,
        "floating_holidays": floating_count,
        "holidays": [
            {
                "date": d.isoformat(),
                "name": holiday_names.get((d.month, d.day), d.strftime("%b %d")),
            }
            for d in holidays
        ],
        "plans": [],
    }

    for plan in plans:
        plan_data = {
            "name": plan.name,
            "description": plan.description,
            "pto_dates": [d.isoformat() for d in plan.pto_dates],
            "floating_dates": [d.isoformat() for d in plan.floating_dates],
            "blocks": [
                {
                    "start_date": b.start_date.isoformat(),
                    "end_date": b.end_date.isoformat(),
                    "total_days": b.total_days,
                    "pto_days": b.pto_days,
                    "holidays": b.holidays,
                    "weekend_days": b.weekend_days,
                }
                for b in plan.blocks
            ],
            "summary": {
                "total_vacation_days": sum(b.total_days for b in plan.blocks),
                "total_pto_used": len(plan.pto_dates) + len(plan.floating_dates),
            },
        }
        result["plans"].append(plan_data)

    return json.dumps(result)

_run()
`;

  const jsonStr = pyodide.runPython(code);
  return JSON.parse(jsonStr);
}

// ---- Form handling ------------------------------------------------

function initForm() {
  const form = document.getElementById("optimizer-form");
  const yearInput = document.getElementById("year");

  // Default to current year
  yearInput.value = new Date().getFullYear();

  // Strategy cards
  document.querySelectorAll(".strategy-card").forEach((card) => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".strategy-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  // Custom holidays
  const addBtn = document.getElementById("add-holiday-btn");
  const dateInput = document.getElementById("custom-holiday-input");

  addBtn.addEventListener("click", () => {
    const val = dateInput.value;
    if (!val) return;
    if (customHolidays.includes(val)) return;
    customHolidays.push(val);
    dateInput.value = "";
    renderCustomHolidays();
  });

  // Form submit
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!pythonReady) return;

    const btn = document.getElementById("optimize-btn");
    const btnText = btn.querySelector(".btn-text");
    const btnSpinner = btn.querySelector(".btn-spinner");
    btn.disabled = true;
    btnText.textContent = "Optimizing\u2026";
    btnSpinner.hidden = false;

    const year = parseInt(yearInput.value, 10);
    const budget = parseInt(document.getElementById("budget").value, 10);
    const floating = parseInt(document.getElementById("floating").value, 10);
    const country = document.getElementById("country").value;
    const strategy = form.querySelector('input[name="strategy"]:checked').value;

    // Run optimization in a setTimeout so the UI can update
    setTimeout(() => {
      try {
        currentResults = runOptimizer(year, budget, floating, country, customHolidays, strategy);
        activePlanIndex = 0;
        renderResults();
      } catch (err) {
        console.error("Optimization error:", err);
        alert("Optimization failed: " + err.message);
      } finally {
        btn.disabled = false;
        btnText.textContent = "Optimize My PTO";
        btnSpinner.hidden = true;
      }
    }, 50);
  });
}

function renderCustomHolidays() {
  const container = document.getElementById("custom-holidays-list");
  container.innerHTML = customHolidays
    .map((d, i) => {
      const dt = new Date(d + "T00:00:00");
      const label = dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
      return `<span class="chip">${label}<button type="button" class="chip-remove" data-index="${i}">&times;</button></span>`;
    })
    .join("");

  container.querySelectorAll(".chip-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      customHolidays.splice(parseInt(btn.dataset.index, 10), 1);
      renderCustomHolidays();
    });
  });
}

// ---- Results rendering --------------------------------------------

function renderResults() {
  if (!currentResults) return;

  const section = document.getElementById("results-section");
  section.hidden = false;

  renderSummary();
  renderTabs();
  renderActivePlan();

  // Scroll to results
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSummary() {
  const r = currentResults;
  const container = document.getElementById("results-summary");

  // Aggregate across all plans (show best values)
  const bestVacation = Math.max(...r.plans.map((p) => p.summary.total_vacation_days));
  const bestBlocks = Math.max(...r.plans.map((p) => p.blocks.length));
  const longestBlock = Math.max(...r.plans.flatMap((p) => p.blocks.map((b) => b.total_days)));

  container.innerHTML = `
    <div class="summary-card">
      <div class="value">${r.pto_budget}</div>
      <div class="label">PTO Days</div>
    </div>
    <div class="summary-card">
      <div class="value">${r.holidays.length}</div>
      <div class="label">Holidays</div>
    </div>
    <div class="summary-card">
      <div class="value">${bestVacation}</div>
      <div class="label">Best Total Days Off</div>
    </div>
    <div class="summary-card">
      <div class="value">${longestBlock}</div>
      <div class="label">Longest Block</div>
    </div>
  `;
}

function renderTabs() {
  const container = document.getElementById("plan-tabs");
  if (currentResults.plans.length <= 1) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = currentResults.plans
    .map(
      (plan, i) =>
        `<button class="plan-tab${i === activePlanIndex ? " active" : ""}" data-index="${i}">${plan.name}</button>`
    )
    .join("");

  container.querySelectorAll(".plan-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      activePlanIndex = parseInt(tab.dataset.index, 10);
      renderTabs();
      renderActivePlan();
    });
  });
}

function renderActivePlan() {
  const plan = currentResults.plans[activePlanIndex];
  if (!plan) return;

  const container = document.getElementById("plan-content");

  const blocksHtml = plan.blocks
    .map((b) => {
      const start = formatDate(b.start_date);
      const end = formatDate(b.end_date);
      return `
      <div class="block-card">
        <div class="block-card-header">
          <div class="block-dates">${start} &mdash; ${end}</div>
          <div class="block-total">${b.total_days} day${b.total_days !== 1 ? "s" : ""} off</div>
        </div>
        <div class="block-card-body">
          ${b.pto_days ? `<div class="block-stat"><span class="dot dot-pto"></span>${b.pto_days} PTO</div>` : ""}
          ${b.holidays ? `<div class="block-stat"><span class="dot dot-holiday"></span>${b.holidays} Holiday${b.holidays !== 1 ? "s" : ""}</div>` : ""}
          ${b.weekend_days ? `<div class="block-stat"><span class="dot dot-weekend"></span>${b.weekend_days} Weekend</div>` : ""}
        </div>
      </div>`;
    })
    .join("");

  container.innerHTML = `
    <div class="plan-header">
      <h3>${plan.name}</h3>
      <p>${plan.description}</p>
      <p style="margin-top:0.5rem;font-size:var(--text-sm);color:var(--c-text-secondary);">
        <strong>${plan.summary.total_vacation_days}</strong> total days off using
        <strong>${plan.summary.total_pto_used}</strong> PTO day${plan.summary.total_pto_used !== 1 ? "s" : ""}
        across <strong>${plan.blocks.length}</strong> block${plan.blocks.length !== 1 ? "s" : ""}
      </p>
    </div>
    <div class="blocks-grid">${blocksHtml}</div>
    <div class="calendar-section">
      <h4>Year at a Glance</h4>
      ${renderCalendar(plan)}
      <div class="calendar-legend">
        <div class="legend-item"><span class="legend-swatch swatch-pto"></span> PTO</div>
        <div class="legend-item"><span class="legend-swatch swatch-holiday"></span> Holiday</div>
        <div class="legend-item"><span class="legend-swatch swatch-weekend"></span> Weekend</div>
        ${plan.floating_dates.length ? '<div class="legend-item"><span class="legend-swatch swatch-floating"></span> Floating Holiday</div>' : ""}
      </div>
    </div>
  `;
}

// ---- Calendar rendering -------------------------------------------

function renderCalendar(plan) {
  const year = currentResults.year;
  const ptoSet = new Set(plan.pto_dates);
  const floatingSet = new Set(plan.floating_dates);
  const holidaySet = new Set(currentResults.holidays.map((h) => h.date));

  // Build block lookup: date string -> position info
  const blockLookup = {};
  for (const b of plan.blocks) {
    const start = new Date(b.start_date + "T00:00:00");
    const end = new Date(b.end_date + "T00:00:00");
    const totalDays = Math.round((end - start) / 86400000) + 1;
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      const key = isoDate(d);
      let pos = "block-middle";
      if (totalDays === 1) pos = "block-single";
      else if (i === 0) pos = "block-start";
      else if (i === totalDays - 1) pos = "block-end";
      blockLookup[key] = pos;
    }
  }

  let html = '<div class="calendar-year">';

  for (let m = 0; m < 12; m++) {
    html += `<div class="calendar-month">`;
    html += `<div class="calendar-month-name">${MONTH_NAMES[m]}</div>`;
    html += `<div class="calendar-grid">`;

    // Day-of-week headers (Monday-first)
    for (const d of DOW_SHORT) {
      html += `<span class="dow">${d}</span>`;
    }

    // Calculate the starting day (0=Mon in our grid)
    const firstDay = new Date(year, m, 1);
    const startDow = (firstDay.getDay() + 6) % 7; // Convert Sun=0 to Mon=0

    // Empty cells before the first day
    for (let i = 0; i < startDow; i++) {
      html += `<span class="day empty"></span>`;
    }

    // Days of the month
    const daysInMonth = new Date(year, m + 1, 0).getDate();
    for (let d = 1; d <= daysInMonth; d++) {
      const date = new Date(year, m, d);
      const key = isoDate(date);
      const dow = (date.getDay() + 6) % 7; // Mon=0

      const classes = ["day"];
      let title = "";

      if (ptoSet.has(key)) {
        classes.push("pto");
        title = "PTO day";
      } else if (floatingSet.has(key)) {
        classes.push("floating");
        title = "Floating holiday";
      } else if (holidaySet.has(key)) {
        classes.push("holiday");
        const hol = currentResults.holidays.find((h) => h.date === key);
        title = hol ? hol.name : "Holiday";
      } else if (dow >= 5) {
        classes.push("weekend");
      }

      if (blockLookup[key]) {
        classes.push("in-block", blockLookup[key]);
      }

      html += `<span class="${classes.join(" ")}" title="${title}">${d}</span>`;
    }

    html += `</div></div>`;
  }

  html += `</div>`;
  return html;
}

// ---- Helpers ------------------------------------------------------

function isoDate(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function formatDate(isoStr) {
  const d = new Date(isoStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ---- Init ---------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  initForm();
  initPyodide();
});

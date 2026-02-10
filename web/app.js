/* ===================================================================
   PTO Vacation Optimizer — Web Application
   Uses Pyodide to run the Python optimizer directly in the browser.
   =================================================================== */

let pyodide = null;
let pythonReady = false;
let currentResults = null;
let activePlanIndex = 0;
const customHolidays = [];

// Mode: "solo" or "group"
let currentMode = "solo";

// Group definitions for multi-group mode
let groups = [];
let groupIdCounter = 0;

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

// ---- Run optimizer in Python (solo mode) --------------------------

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

// ---- Run optimizer in Python (group mode) -------------------------

function runMultiGroupOptimizer(year, groupDefs, strategy) {
  // groupDefs: [{name, budget, floating, country, customHolidays}, ...]
  const groupsJson = JSON.stringify(groupDefs);
  const code = `
import json, datetime
from pto.optimizer import MultiGroupOptimizer, HolidayGroup
from pto.holidays import get_holidays

def _run():
    year = ${year}
    strategy = ${JSON.stringify(strategy)}
    group_defs = json.loads(r'''${groupsJson}''')

    groups = []
    all_holiday_names = {}

    for gdef in group_defs:
        holidays = []

        if gdef["country"] and gdef["country"] != "none":
            preset = get_holidays(gdef["country"], year)
            for d, name in preset:
                holidays.append(d)
                all_holiday_names[(d.month, d.day)] = name

        for h in gdef.get("customHolidays", []):
            holidays.append(datetime.date.fromisoformat(h))

        holidays = sorted(set(holidays))

        groups.append(HolidayGroup(
            name=gdef["name"],
            holidays=holidays,
            pto_budget=gdef["budget"],
            floating_holidays=gdef["floating"],
        ))

    optimizer = MultiGroupOptimizer(year=year, groups=groups)

    strategy_map = {
        "bridges": optimizer.optimize_max_bridges,
        "longest": optimizer.optimize_longest_vacation,
        "weekends": optimizer.optimize_extended_weekends,
        "quarterly": optimizer.optimize_quarterly,
    }

    plans = optimizer.generate_all_plans() if strategy == "all" else [strategy_map[strategy]()]

    # Collect all holidays across groups
    all_holidays = set()
    for g in groups:
        all_holidays.update(g.holidays)
    all_holidays = sorted(all_holidays)

    result = {
        "year": year,
        "mode": "group",
        "groups": [
            {"name": g.name, "pto_budget": g.pto_budget, "floating_holidays": g.floating_holidays}
            for g in groups
        ],
        "holidays": [
            {
                "date": d.isoformat(),
                "name": all_holiday_names.get((d.month, d.day), d.strftime("%b %d")),
            }
            for d in all_holidays
        ],
        "plans": [],
    }

    for plan in plans:
        plan_data = {
            "name": plan.name,
            "description": plan.description,
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
            "group_allocations": [
                {
                    "group_name": a.group_name,
                    "pto_dates": [d.isoformat() for d in a.pto_dates],
                    "floating_dates": [d.isoformat() for d in a.floating_dates],
                }
                for a in plan.group_allocations
            ],
            "summary": {
                "total_vacation_days": sum(b.total_days for b in plan.blocks),
                "total_pto_all_groups": sum(
                    len(a.pto_dates) + len(a.floating_dates)
                    for a in plan.group_allocations
                ),
            },
        }
        result["plans"].append(plan_data)

    return json.dumps(result)

_run()
`;

  const jsonStr = pyodide.runPython(code);
  return JSON.parse(jsonStr);
}

// ---- Mode toggle --------------------------------------------------

function initModeToggle() {
  const modeButtons = document.querySelectorAll(".mode-btn");
  const soloSettings = document.getElementById("solo-settings");
  const groupSettings = document.getElementById("group-settings");

  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.mode;

      if (currentMode === "solo") {
        soloSettings.hidden = false;
        groupSettings.hidden = true;
      } else {
        soloSettings.hidden = true;
        groupSettings.hidden = false;
        if (groups.length === 0) {
          addGroup("Person 1");
          addGroup("Person 2");
        }
      }
    });
  });
}

// ---- Group management ---------------------------------------------

function addGroup(defaultName) {
  const id = groupIdCounter++;
  groups.push({
    id,
    name: defaultName || `Person ${groups.length + 1}`,
    budget: 15,
    floating: 0,
    country: "us",
    customHolidays: [],
  });
  renderGroups();
}

function removeGroup(id) {
  groups = groups.filter((g) => g.id !== id);
  renderGroups();
}

function renderGroups() {
  const container = document.getElementById("groups-list");
  container.innerHTML = groups
    .map(
      (g, idx) => `
    <div class="group-card" data-group-id="${g.id}">
      <div class="group-card-header">
        <input type="text" class="group-name-input" value="${escapeAttr(g.name)}"
               data-field="name" placeholder="Name">
        ${groups.length > 1 ? `<button type="button" class="group-remove-btn" data-group-id="${g.id}">&times;</button>` : ""}
      </div>
      <div class="group-card-body">
        <div class="group-fields">
          <div class="group-field">
            <label>PTO Days</label>
            <input type="number" min="0" max="60" value="${g.budget}" data-field="budget">
          </div>
          <div class="group-field">
            <label>Floating</label>
            <input type="number" min="0" max="20" value="${g.floating}" data-field="floating">
          </div>
          <div class="group-field">
            <label>Holidays</label>
            <select data-field="country">
              <option value="us"${g.country === "us" ? " selected" : ""}>US</option>
              <option value="none"${g.country === "none" ? " selected" : ""}>None</option>
            </select>
          </div>
        </div>
        <div class="group-custom-holidays">
          <div class="custom-holidays-input">
            <input type="date" class="date-input group-holiday-input">
            <button type="button" class="btn btn-secondary btn-sm group-add-holiday-btn">Add</button>
          </div>
          <div class="chip-list group-holidays-chips">
            ${g.customHolidays
              .map((d, i) => {
                const dt = new Date(d + "T00:00:00");
                const label = dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                return `<span class="chip">${label}<button type="button" class="chip-remove group-holiday-remove" data-holiday-index="${i}">&times;</button></span>`;
              })
              .join("")}
          </div>
        </div>
      </div>
    </div>`
    )
    .join("");

  // Bind events
  container.querySelectorAll(".group-card").forEach((card) => {
    const gid = parseInt(card.dataset.groupId, 10);
    const group = groups.find((g) => g.id === gid);
    if (!group) return;

    // Name and numeric field changes
    card.querySelectorAll("input[data-field], select[data-field]").forEach((input) => {
      input.addEventListener("change", () => {
        const field = input.dataset.field;
        if (field === "budget" || field === "floating") {
          group[field] = parseInt(input.value, 10) || 0;
        } else {
          group[field] = input.value;
        }
      });
    });

    // Remove group button
    const removeBtn = card.querySelector(".group-remove-btn");
    if (removeBtn) {
      removeBtn.addEventListener("click", () => removeGroup(gid));
    }

    // Add custom holiday
    const addHolBtn = card.querySelector(".group-add-holiday-btn");
    const holInput = card.querySelector(".group-holiday-input");
    if (addHolBtn && holInput) {
      addHolBtn.addEventListener("click", () => {
        const val = holInput.value;
        if (!val || group.customHolidays.includes(val)) return;
        group.customHolidays.push(val);
        holInput.value = "";
        renderGroups();
      });
    }

    // Remove custom holiday
    card.querySelectorAll(".group-holiday-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        group.customHolidays.splice(parseInt(btn.dataset.holidayIndex, 10), 1);
        renderGroups();
      });
    });
  });
}

function escapeAttr(str) {
  return str.replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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

  // Custom holidays (solo mode)
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

  // Add group button
  document.getElementById("add-group-btn").addEventListener("click", () => {
    addGroup();
  });

  // Export PDF button
  document.getElementById("export-pdf-btn").addEventListener("click", () => {
    exportPDF();
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
    const strategy = form.querySelector('input[name="strategy"]:checked').value;

    // Run optimization in a setTimeout so the UI can update
    setTimeout(() => {
      try {
        if (currentMode === "solo") {
          const budget = parseInt(document.getElementById("budget").value, 10);
          const floating = parseInt(document.getElementById("floating").value, 10);
          const country = document.getElementById("country").value;
          currentResults = runOptimizer(year, budget, floating, country, customHolidays, strategy);
        } else {
          const groupDefs = groups.map((g) => ({
            name: g.name,
            budget: g.budget,
            floating: g.floating,
            country: g.country,
            customHolidays: g.customHolidays,
          }));
          currentResults = runMultiGroupOptimizer(year, groupDefs, strategy);
        }
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

  // Show export PDF button
  document.getElementById("export-pdf-btn").hidden = false;

  renderSummary();
  renderTabs();
  renderActivePlan();

  // Scroll to results
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSummary() {
  const r = currentResults;
  const container = document.getElementById("results-summary");
  const isGroup = r.mode === "group";

  if (isGroup) {
    const bestVacation = Math.max(...r.plans.map((p) => p.summary.total_vacation_days));
    const longestBlock = Math.max(...r.plans.flatMap((p) => p.blocks.map((b) => b.total_days)));
    const groupNames = r.groups.map((g) => g.name).join(", ");

    container.innerHTML = `
      <div class="summary-card">
        <div class="value">${r.groups.length}</div>
        <div class="label">People</div>
      </div>
      <div class="summary-card">
        <div class="value">${r.holidays.length}</div>
        <div class="label">Holidays</div>
      </div>
      <div class="summary-card">
        <div class="value">${bestVacation}</div>
        <div class="label">Best Shared Days Off</div>
      </div>
      <div class="summary-card">
        <div class="value">${longestBlock}</div>
        <div class="label">Longest Block</div>
      </div>
    `;
  } else {
    // Aggregate across all plans (show best values)
    const bestVacation = Math.max(...r.plans.map((p) => p.summary.total_vacation_days));
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

  const isGroup = currentResults.mode === "group";
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

  // Per-group allocations (group mode only)
  let allocHtml = "";
  if (isGroup && plan.group_allocations) {
    allocHtml = `<div class="group-allocations">
      <h4>Per-Person PTO Allocation</h4>
      ${plan.group_allocations
        .map((a, i) => {
          const g = currentResults.groups[i];
          const totalUsed = a.pto_dates.length + a.floating_dates.length;
          const totalBudget = g.pto_budget + g.floating_holidays;
          return `
          <div class="allocation-card">
            <div class="allocation-header">
              <strong>${a.group_name}</strong>
              <span class="allocation-usage">${totalUsed} / ${totalBudget} days used</span>
            </div>
            ${a.pto_dates.length ? `<div class="allocation-dates">
              <span class="allocation-label">PTO:</span>
              ${a.pto_dates.map((d) => `<span class="allocation-date">${formatDate(d)}</span>`).join(", ")}
            </div>` : ""}
            ${a.floating_dates.length ? `<div class="allocation-dates">
              <span class="allocation-label">Floating:</span>
              ${a.floating_dates.map((d) => `<span class="allocation-date">${formatDate(d)}</span>`).join(", ")}
            </div>` : ""}
          </div>`;
        })
        .join("")}
    </div>`;
  }

  // Determine PTO/floating sets for calendar
  let ptoDates, floatingDates;
  if (isGroup) {
    ptoDates = plan.group_allocations.flatMap((a) => a.pto_dates);
    floatingDates = plan.group_allocations.flatMap((a) => a.floating_dates);
  } else {
    ptoDates = plan.pto_dates;
    floatingDates = plan.floating_dates;
  }

  const summaryLine = isGroup
    ? `<strong>${plan.summary.total_vacation_days}</strong> shared days off using
       <strong>${plan.summary.total_pto_all_groups}</strong> total PTO days
       across <strong>${plan.blocks.length}</strong> block${plan.blocks.length !== 1 ? "s" : ""}`
    : `<strong>${plan.summary.total_vacation_days}</strong> total days off using
       <strong>${plan.summary.total_pto_used}</strong> PTO day${plan.summary.total_pto_used !== 1 ? "s" : ""}
       across <strong>${plan.blocks.length}</strong> block${plan.blocks.length !== 1 ? "s" : ""}`;

  container.innerHTML = `
    <div class="plan-header">
      <h3>${plan.name}</h3>
      <p>${plan.description}</p>
      <p style="margin-top:0.5rem;font-size:var(--text-sm);color:var(--c-text-secondary);">
        ${summaryLine}
      </p>
    </div>
    <div class="blocks-grid">${blocksHtml}</div>
    ${allocHtml}
    <div class="calendar-section">
      <h4>Year at a Glance</h4>
      ${renderCalendar(ptoDates, floatingDates, plan.blocks)}
      <div class="calendar-legend">
        <div class="legend-item"><span class="legend-swatch swatch-pto"></span> PTO</div>
        <div class="legend-item"><span class="legend-swatch swatch-holiday"></span> Holiday</div>
        <div class="legend-item"><span class="legend-swatch swatch-weekend"></span> Weekend</div>
        ${floatingDates.length ? '<div class="legend-item"><span class="legend-swatch swatch-floating"></span> Floating Holiday</div>' : ""}
      </div>
    </div>
  `;
}

// ---- Calendar rendering -------------------------------------------

function renderCalendar(ptoDatesArr, floatingDatesArr, blocks) {
  const year = currentResults.year;
  const ptoSet = new Set(ptoDatesArr);
  const floatingSet = new Set(floatingDatesArr);
  const holidaySet = new Set(currentResults.holidays.map((h) => h.date));

  // Build block lookup: date string -> position info
  const blockLookup = {};
  for (const b of blocks) {
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

// ---- PDF Export ---------------------------------------------------

function exportPDF() {
  if (!currentResults) return;

  const { jsPDF } = window.jspdf;
  const plan = currentResults.plans[activePlanIndex];
  if (!plan) return;

  const year = currentResults.year;
  const isGroup = currentResults.mode === "group";

  // Collect date sets
  let ptoDatesArr, floatingDatesArr;
  if (isGroup) {
    ptoDatesArr = plan.group_allocations.flatMap((a) => a.pto_dates);
    floatingDatesArr = plan.group_allocations.flatMap((a) => a.floating_dates);
  } else {
    ptoDatesArr = plan.pto_dates;
    floatingDatesArr = plan.floating_dates;
  }
  const ptoSet = new Set(ptoDatesArr);
  const floatingSet = new Set(floatingDatesArr);
  const holidaySet = new Set(currentResults.holidays.map((h) => h.date));
  const holidayNameMap = {};
  for (const h of currentResults.holidays) {
    holidayNameMap[h.date] = h.name;
  }

  // Block lookup for marking vacation blocks
  const blockDates = new Set();
  for (const b of plan.blocks) {
    const start = new Date(b.start_date + "T00:00:00");
    const end = new Date(b.end_date + "T00:00:00");
    const totalDays = Math.round((end - start) / 86400000) + 1;
    for (let i = 0; i < totalDays; i++) {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      blockDates.add(isoDate(d));
    }
  }

  // Landscape Letter: 792 x 612 points
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "letter" });
  const pageW = 792;
  const pageH = 612;
  const margin = 28;

  // ---- Title ----
  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.text(`${year} PTO Calendar`, pageW / 2, margin + 12, { align: "center" });

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  const subtitle = isGroup
    ? `${plan.name} | ${currentResults.groups.map((g) => g.name).join(", ")}`
    : `${plan.name}`;
  doc.text(subtitle, pageW / 2, margin + 24, { align: "center" });

  // ---- Calendar grid: 4 cols x 3 rows ----
  const gridTop = margin + 36;
  const legendHeight = 36;
  const gridBottom = pageH - margin - legendHeight;
  const availW = pageW - 2 * margin;
  const availH = gridBottom - gridTop;
  const cellW = availW / 4;
  const cellH = availH / 3;
  const gap = 6;

  for (let m = 0; m < 12; m++) {
    const col = m % 4;
    const row = Math.floor(m / 4);
    const x = margin + col * cellW + gap / 2;
    const y = gridTop + row * cellH + gap / 2;
    const w = cellW - gap;
    const h = cellH - gap;

    drawMonth(doc, x, y, w, h, year, m, ptoSet, floatingSet, holidaySet, blockDates);
  }

  // ---- Legend ----
  const legendY = pageH - margin - legendHeight + 8;
  drawLegend(doc, margin, legendY, pageW, floatingDatesArr.length > 0);

  // ---- Page 2: Holiday list and vacation blocks ----
  doc.addPage("letter", "landscape");

  let yPos = margin + 12;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.text(`${year} Vacation Plan Details`, pageW / 2, yPos, { align: "center" });
  yPos += 20;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.text("Plan: " + plan.name, margin, yPos);
  yPos += 14;

  // Holidays
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.text("Holidays:", margin, yPos);
  yPos += 12;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  for (const h of currentResults.holidays) {
    const d = new Date(h.date + "T00:00:00");
    const dateStr = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    doc.text(`  ${dateStr} - ${h.name}`, margin, yPos);
    yPos += 10;
    if (yPos > pageH - margin - 20) {
      doc.addPage("letter", "landscape");
      yPos = margin + 12;
    }
  }
  yPos += 6;

  // Vacation blocks
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.text("Vacation Blocks:", margin, yPos);
  yPos += 12;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  for (let i = 0; i < plan.blocks.length; i++) {
    const b = plan.blocks[i];
    const startD = new Date(b.start_date + "T00:00:00");
    const endD = new Date(b.end_date + "T00:00:00");
    const startStr = startD.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const endStr = endD.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const parts = [];
    if (b.pto_days) parts.push(`${b.pto_days} PTO`);
    if (b.holidays) parts.push(`${b.holidays} holiday${b.holidays > 1 ? "s" : ""}`);
    if (b.weekend_days) parts.push(`${b.weekend_days} weekend`);

    doc.text(
      `  ${i + 1}. ${startStr} - ${endStr}  (${b.total_days} days: ${parts.join(" + ")})`,
      margin, yPos
    );
    yPos += 10;
    if (yPos > pageH - margin - 20) {
      doc.addPage("letter", "landscape");
      yPos = margin + 12;
    }
  }
  yPos += 6;

  // Per-group allocations
  if (isGroup && plan.group_allocations) {
    doc.setFont("helvetica", "bold");
    doc.setFontSize(10);
    doc.text("Per-Person Allocation:", margin, yPos);
    yPos += 14;

    for (const a of plan.group_allocations) {
      doc.setFont("helvetica", "bold");
      doc.setFontSize(9);
      doc.text(a.group_name, margin + 4, yPos);
      yPos += 11;

      doc.setFont("helvetica", "normal");
      doc.setFontSize(8);

      if (a.pto_dates.length) {
        const dates = a.pto_dates.map((d) => {
          const dt = new Date(d + "T00:00:00");
          return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        });
        doc.text(`  PTO: ${dates.join(", ")}`, margin + 4, yPos);
        yPos += 10;
      }
      if (a.floating_dates.length) {
        const dates = a.floating_dates.map((d) => {
          const dt = new Date(d + "T00:00:00");
          return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        });
        doc.text(`  Floating: ${dates.join(", ")}`, margin + 4, yPos);
        yPos += 10;
      }
      yPos += 4;
      if (yPos > pageH - margin - 20) {
        doc.addPage("letter", "landscape");
        yPos = margin + 12;
      }
    }
  } else {
    // Solo: list days to request off
    doc.setFont("helvetica", "bold");
    doc.setFontSize(10);
    doc.text("Days to Request Off:", margin, yPos);
    yPos += 12;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    for (const d of ptoDatesArr) {
      const dt = new Date(d + "T00:00:00");
      const dateStr = dt.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
      doc.text(`  ${dateStr}`, margin, yPos);
      yPos += 10;
      if (yPos > pageH - margin - 20) {
        doc.addPage("letter", "landscape");
        yPos = margin + 12;
      }
    }
    if (floatingDatesArr.length) {
      yPos += 4;
      doc.setFont("helvetica", "bold");
      doc.text("Floating Holidays:", margin, yPos);
      yPos += 12;
      doc.setFont("helvetica", "normal");
      for (const d of floatingDatesArr) {
        const dt = new Date(d + "T00:00:00");
        const dateStr = dt.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
        doc.text(`  ${dateStr}`, margin, yPos);
        yPos += 10;
        if (yPos > pageH - margin - 20) {
          doc.addPage("letter", "landscape");
          yPos = margin + 12;
        }
      }
    }
  }

  const filename = `PTO-Calendar-${year}.pdf`;

  // iOS Safari does not support programmatic downloads via <a download> clicks.
  // Detect iOS and open the PDF in a new tab so the user can share/save it.
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (isIOS) {
    const blob = doc.output("blob");
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
  } else {
    doc.save(filename);
  }
}

function drawMonth(doc, x, y, w, h, year, monthIdx, ptoSet, floatingSet, holidaySet, blockDates) {
  const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
  const firstDay = new Date(year, monthIdx, 1);
  const startDow = (firstDay.getDay() + 6) % 7; // Mon=0

  // Month border
  doc.setDrawColor(180);
  doc.setLineWidth(0.5);
  doc.rect(x, y, w, h);

  // Month name
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9);
  doc.setTextColor(0);
  doc.text(MONTH_NAMES[monthIdx], x + w / 2, y + 12, { align: "center" });

  // Day-of-week headers
  const headerY = y + 22;
  const dayW = w / 7;
  const dayH = (h - 30) / 6; // 6 possible rows
  const daysStartY = headerY + 10;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(6);
  doc.setTextColor(120);
  for (let i = 0; i < 7; i++) {
    doc.text(DOW_SHORT[i], x + i * dayW + dayW / 2, headerY, { align: "center" });
  }

  // Days
  doc.setFont("helvetica", "normal");
  doc.setFontSize(7);

  let col = startDow;
  let row = 0;

  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, monthIdx, d);
    const key = isoDate(date);
    const dow = (date.getDay() + 6) % 7;
    const isWeekend = dow >= 5;

    const cx = x + col * dayW;
    const cy = daysStartY + row * dayH;

    // Determine day type for B&W styling
    const isPto = ptoSet.has(key);
    const isFloating = floatingSet.has(key);
    const isHoliday = holidaySet.has(key);
    const isInBlock = blockDates.has(key);

    // Draw cell background
    if (isPto) {
      // PTO: black fill, white text
      doc.setFillColor(40, 40, 40);
      doc.rect(cx + 0.5, cy, dayW - 1, dayH - 1, "F");
      doc.setTextColor(255);
    } else if (isFloating) {
      // Floating: dark gray fill, white text
      doc.setFillColor(80, 80, 80);
      doc.rect(cx + 0.5, cy, dayW - 1, dayH - 1, "F");
      doc.setTextColor(255);
    } else if (isHoliday) {
      // Holiday: medium gray fill
      doc.setFillColor(140, 140, 140);
      doc.rect(cx + 0.5, cy, dayW - 1, dayH - 1, "F");
      doc.setTextColor(255);
    } else if (isWeekend) {
      // Weekend: light gray fill
      doc.setFillColor(220, 220, 220);
      doc.rect(cx + 0.5, cy, dayW - 1, dayH - 1, "F");
      doc.setTextColor(60);
    } else {
      doc.setTextColor(0);
    }

    // Draw outline for vacation block days
    if (isInBlock && !isPto && !isFloating && !isHoliday) {
      doc.setDrawColor(60);
      doc.setLineWidth(1);
      doc.rect(cx + 0.5, cy, dayW - 1, dayH - 1);
      doc.setLineWidth(0.5);
      doc.setDrawColor(180);
    }

    // Day number
    const numStr = String(d);
    doc.setFont("helvetica", isPto || isFloating || isHoliday ? "bold" : "normal");
    doc.setFontSize(7);
    doc.text(numStr, cx + dayW / 2, cy + dayH / 2 + 1, { align: "center" });

    // Type indicator letter (small, below/beside the number)
    if (isPto || isFloating || isHoliday) {
      doc.setFontSize(4.5);
      const label = isPto ? "P" : isFloating ? "F" : "H";
      doc.text(label, cx + dayW - 2.5, cy + 5, { align: "right" });
    }

    // Reset text color
    doc.setTextColor(0);

    col++;
    if (col >= 7) {
      col = 0;
      row++;
    }
  }
}

function drawLegend(doc, x, y, pageW, hasFloating) {
  const margin = x;
  doc.setDrawColor(200);
  doc.setLineWidth(0.5);
  doc.line(margin, y - 4, pageW - margin, y - 4);

  const items = [
    { label: "Weekend", fillColor: [220, 220, 220], textColor: [60, 60, 60] },
    { label: "Holiday (H)", fillColor: [140, 140, 140], textColor: [255, 255, 255] },
    { label: "PTO (P)", fillColor: [40, 40, 40], textColor: [255, 255, 255] },
  ];
  if (hasFloating) {
    items.push({ label: "Floating (F)", fillColor: [80, 80, 80], textColor: [255, 255, 255] });
  }

  const swatchSize = 10;
  const itemGap = 16;
  const totalW = items.reduce((sum, item) => {
    return sum + swatchSize + 4 + item.label.length * 4.5 + itemGap;
  }, -itemGap);
  let lx = (pageW - totalW) / 2;

  doc.setFontSize(7);
  for (const item of items) {
    // Swatch
    doc.setFillColor(...item.fillColor);
    doc.rect(lx, y, swatchSize, swatchSize, "F");
    doc.setDrawColor(160);
    doc.rect(lx, y, swatchSize, swatchSize);

    // Label
    doc.setFont("helvetica", "normal");
    doc.setTextColor(60);
    doc.text(item.label, lx + swatchSize + 4, y + 7.5);

    lx += swatchSize + 4 + item.label.length * 4.5 + itemGap;
  }

  // Footer text
  doc.setFontSize(6);
  doc.setTextColor(150);
  doc.text("Generated by PTO Vacation Optimizer", pageW / 2, y + 22, { align: "center" });
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
  initModeToggle();
  initPyodide();
});

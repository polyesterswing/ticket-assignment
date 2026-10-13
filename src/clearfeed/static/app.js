// UI state and API calls. Loaded before Alpine, which picks up app() from x-data.

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

// Calls the JSON API. Errors are thrown as the API's {code, message}.
async function api(method, path, body, signal) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  signal?.throwIfAborted(); // the catch above also swallows aborts
  if (!response.ok) {
    throw data?.error ?? { code: `HTTP_${response.status}`, message: response.statusText };
  }
  return data;
}

function addDays(isoDate, days) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// Thrown by fetch when its request is aborted.
function isAbort(e) {
  return e?.name === "AbortError";
}

function app() {
  // Aborted when the selected company changes, so responses for the old
  // company never land in the page. Kept outside the reactive state.
  let companyRequests = new AbortController();

  return {
    DAYS,
    timezones: Intl.supportedValuesOf("timeZone"),
    tab: "agents",
    error: null, // page-level load error

    companies: [],
    companyId: null,
    agents: [],
    agentId: null,

    // Agents tab
    timezoneInput: "",
    timezoneError: null,
    timezoneSaved: false,
    shifts: [],
    shiftForm: null,
    shiftError: null,

    // Required hours tab
    windows: null, // null until loaded for the selected company
    windowsError: null,
    windowsSaved: false,

    // Coverage tab
    weekOf: "",
    coverage: null,

    // Assignment log tab
    log: [],
    logCursor: null,
    logFilters: { ticket_id: "", outcome: "" },
    expandedLogId: null,
    testTicketId: "",
    testResult: null,
    testError: null,

    get company() {
      return this.companies.find((c) => c.id === this.companyId);
    },
    get agent() {
      return this.agents.find((a) => a.id === this.agentId);
    },
    get base() {
      return `/companies/${this.companyId}`;
    },

    async init() {
      this.resetShiftForm();
      await this.run(async () => {
        this.companies = await api("GET", "/companies");
        if (this.companies.length) await this.selectCompany(this.companies[0].id);
      });
      this.$watch("tab", () => this.loadTab());
    },

    // Runs a load and shows failures in the page-level alert.
    async run(load) {
      try {
        this.error = null;
        await load();
      } catch (e) {
        if (!isAbort(e)) this.error = e.message ?? String(e);
      }
    },

    // Calls the API for the selected company.
    request(method, path, body) {
      return api(method, path, body, companyRequests.signal);
    },

    async selectCompany(id) {
      companyRequests.abort();
      companyRequests = new AbortController();
      this.companyId = Number(id);
      this.agents = [];
      this.agentId = null;
      this.shifts = [];
      this.windows = null;
      this.coverage = null;
      this.weekOf = "";
      this.log = [];
      this.logCursor = null;
      this.expandedLogId = null;
      this.testResult = null;
      this.testError = null;
      await this.run(async () => {
        this.agents = await this.request("GET", `${this.base}/agents`);
        if (this.agents.length) await this.selectAgent(this.agents[0].id);
        await this.loadTab();
      });
    },

    async loadTab() {
      await this.run(async () => {
        if (this.tab === "hours") await this.loadWindows();
        if (this.tab === "coverage") await this.loadCoverage();
        if (this.tab === "log") await this.loadLog(true);
      });
    },

    agentName(id) {
      return this.agents.find((a) => a.id === id)?.name ?? `Agent ${id}`;
    },

    formatTime(iso) {
      if (!iso) return "";
      return new Intl.DateTimeFormat(undefined, {
        timeZone: this.company.timezone,
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(iso));
    },

    // --- Agents and shifts ---

    async selectAgent(id) {
      this.agentId = id;
      this.timezoneInput = this.agent.timezone;
      this.timezoneError = null;
      this.timezoneSaved = false;
      this.resetShiftForm();
      await this.run(() => this.loadShifts());
    },

    async loadShifts() {
      this.shifts = await this.request("GET", `${this.base}/agents/${this.agentId}/shifts`);
    },

    async saveTimezone() {
      try {
        const updated = await this.request("PATCH", `${this.base}/agents/${this.agentId}`, {
          timezone: this.timezoneInput,
        });
        this.agents = this.agents.map((a) => (a.id === updated.id ? updated : a));
        this.timezoneError = null;
        this.timezoneSaved = true;
      } catch (e) {
        if (isAbort(e)) return;
        this.timezoneError = e.message;
        this.timezoneSaved = false;
      }
    },

    resetShiftForm() {
      this.shiftForm = { id: null, day: "MON", start: "09:00", end: "17:00" };
      this.shiftError = null;
    },

    editShift(shift) {
      this.shiftForm = { ...shift };
      this.shiftError = null;
    },

    async saveShift() {
      const { id, day, start, end } = this.shiftForm;
      const path = `${this.base}/agents/${this.agentId}/shifts`;
      try {
        if (id) await this.request("PUT", `${path}/${id}`, { day, start, end });
        else await this.request("POST", path, { day, start, end });
        this.resetShiftForm();
        await this.loadShifts();
      } catch (e) {
        if (isAbort(e)) return;
        this.shiftError = e.message;
      }
    },

    async deleteShift(shift) {
      if (!confirm(`Delete ${shift.day} ${shift.start}-${shift.end}?`)) return;
      await this.run(async () => {
        await this.request("DELETE", `${this.base}/agents/${this.agentId}/shifts/${shift.id}`);
        if (this.shiftForm.id === shift.id) this.resetShiftForm();
        await this.loadShifts();
      });
    },

    isOvernight(shift) {
      return shift.end !== "24:00" && shift.end <= shift.start;
    },

    // --- Required hours ---

    async loadWindows() {
      this.windows = (await this.request("GET", `${this.base}/required-hours`)).windows;
      this.windowsError = null;
      this.windowsSaved = false;
    },

    addWindow() {
      this.windows.push({ day: "MON", start: "09:00", end: "17:00" });
      this.windowsSaved = false;
    },

    removeWindow(index) {
      this.windows.splice(index, 1);
      this.windowsSaved = false;
    },

    async saveWindows() {
      try {
        const saved = await this.request("PUT", `${this.base}/required-hours`, { windows: this.windows });
        this.windows = saved.windows;
        this.windowsError = null;
        this.windowsSaved = true;
      } catch (e) {
        if (isAbort(e)) return;
        this.windowsError = e.message;
        this.windowsSaved = false;
      }
    },

    // --- Coverage ---

    async loadCoverage() {
      const query = this.weekOf ? `?week_of=${this.weekOf}` : "";
      this.coverage = await this.request("GET", `${this.base}/coverage${query}`);
      this.weekOf = this.coverage.week_start;
    },

    async moveWeek(weeks) {
      this.weekOf = addDays(this.coverage.week_start, 7 * weeks);
      await this.run(() => this.loadCoverage());
    },

    async currentWeek() {
      this.weekOf = "";
      await this.run(() => this.loadCoverage());
    },

    // --- Assignment log ---

    async loadLog(reset) {
      const params = new URLSearchParams({ limit: "25" });
      if (this.logFilters.ticket_id) params.set("ticket_id", this.logFilters.ticket_id);
      if (this.logFilters.outcome) params.set("outcome", this.logFilters.outcome);
      if (!reset && this.logCursor) params.set("cursor", this.logCursor);

      const page = await this.request("GET", `${this.base}/assignment-log?${params}`);
      this.log = reset ? page.items : [...this.log, ...page.items];
      this.logCursor = page.next_cursor;
    },

    toggleLog(id) {
      this.expandedLogId = this.expandedLogId === id ? null : id;
    },

    // Does what the ticketing system would: assign or complete a ticket.
    async sendTestTicket(action) {
      try {
        const ticketId = encodeURIComponent(this.testTicketId.trim());
        this.testResult = await this.request("POST", `${this.base}/tickets/${ticketId}/${action}`);
        this.testError = null;
        await this.loadLog(true);
      } catch (e) {
        if (isAbort(e)) return;
        this.testError = e.message;
        this.testResult = null;
      }
    },
  };
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const WEEKDAYS = [
  "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
];

export function cronToEnglish(expression) {
  try {
    return describe(parseCron(expression));
  } catch {
    return null;
  }
}

function parseCron(expression) {
  if (typeof expression !== "string") {
    throw new Error("expression must be a string");
  }
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) {
    throw new Error("expected 5 fields: min hour dom month dow");
  }
  const [min, hour, dom, month, dow] = fields;
  return {
    min, hour, dom, month, dow,
    pMin: parseField(min),
    pHour: parseField(hour),
    pDom: parseField(dom),
    pMonth: parseField(month),
    pDow: parseField(dow),
  };
}

function parseField(field) {
  if (field === "*") return [{ type: "all" }];
  return field.split(",").map(parsePart);
}

function parsePart(part) {
  if (part.includes("/")) {
    const [base, step] = part.split("/");
    if (base === "*") return { type: "step_all", step: Number(step) };
    if (base.includes("-")) {
      const [start, end] = base.split("-").map(Number);
      return { type: "step_range", start, end, step: Number(step) };
    }
  }
  if (part.includes("-")) {
    const [start, end] = part.split("-").map(Number);
    return { type: "range", start, end };
  }
  return { type: "value", value: Number(part) };
}

function describe(cron) {
  const segments = [
    timePhrase(cron),
    dayPhrase(cron),
    monthPhrase(cron),
    weekdayPhrase(cron),
  ].filter(Boolean);
  return `Runs ${segments.join(", ")}.`;
}

function timePhrase({ min, hour, pMin, pHour }) {
  if (min === "*" && hour === "*") return "every minute";
  if (hour === "*" && isStepAll(pMin)) {
    return `every ${pMin[0].step} minutes`;
  }
  if (hour === "*") return `every hour at minute ${render(pMin)}`;
  if (isStepAll(pHour)) {
    return `every ${pHour[0].step} hours at minute ${render(pMin)}`;
  }
  if (min === "*") return `every minute during hour ${render(pHour)}`;
  return `at ${pad2(render(pHour))}:${pad2(render(pMin))}`;
}

function dayPhrase({ dom, pDom }) {
  if (dom === "*") return "every day";
  return `on day ${render(pDom)}`;
}

function monthPhrase({ month, dom, dow, pMonth }) {
  if (month === "*") {
    return dom !== "*" && dow === "*" ? "every month" : "";
  }
  return `in ${render(pMonth, "month")}`;
}

function weekdayPhrase({ dow, pDow }) {
  if (dow === "*") return "";
  return `on ${render(pDow, "dow")}`;
}

function render(parsed, type) {
  return joinParts(parsed.map((p) => renderPart(p, type)));
}

function renderPart(part, type) {
  const value = (n) => mapValue(n, type);
  switch (part.type) {
    case "all": return "every";
    case "value": return String(value(part.value));
    case "range": return `${value(part.start)} through ${value(part.end)}`;
    case "step_all": return `every ${part.step}`;
    case "step_range":
      return `every ${part.step} from ${value(part.start)} through ${value(part.end)}`;
    default: return "";
  }
}

function mapValue(value, type) {
  if (type === "month") return MONTHS[value - 1] ?? value;
  if (type === "dow") return WEEKDAYS[value] ?? value;
  return value;
}

function joinParts(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

function isStepAll(parsed) {
  return parsed.length === 1 && parsed[0]?.type === "step_all";
}

function pad2(value) {
  return /^\d+$/.test(value) ? value.padStart(2, "0") : value;
}

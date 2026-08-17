const KST_FORMATTER = new Intl.DateTimeFormat("sv-SE", {
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  month: "2-digit",
  timeZone: "Asia/Seoul",
  year: "numeric",
});

const trimDecimal = (value: string): string => {
  if (!value.includes(".")) {
    return value;
  }
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? "0" : trimmed;
};

export const formatDecimal = (value: string): string => {
  const normalized = trimDecimal(value);
  const negative = normalized.startsWith("-");
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [whole = "0", fraction] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return negative ? `-${body}` : body;
};

export const formatSignedDecimal = (value: string): string => {
  const formatted = formatDecimal(value);
  if (formatted === "0" || formatted.startsWith("-")) {
    return formatted;
  }
  return `+${formatted}`;
};

export const formatSignedPercent = (value: string): string => `${formatSignedDecimal(value)}%`;

export const formatKstDateTime = (value: string): string =>
  KST_FORMATTER.format(new Date(value)).replace(",", "");

export const decimalToNumber = (value: string): number => Number.parseFloat(value);

export const marketDirection = (value: string): "up" | "down" | "flat" => {
  const numeric = decimalToNumber(value);
  if (numeric > 0) {
    return "up";
  }
  return numeric < 0 ? "down" : "flat";
};

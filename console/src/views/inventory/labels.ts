// What the person reads. The identifiers stay those of the API (ADR-0005); the words are Spanish.
export const CATEGORY_LABELS: Record<string, string> = {
  personal_data: "Dato personal",
  "special_category.health": "Categoría especial · salud",
  "special_category.other": "Categoría especial · otra",
  official_identifier: "Identificador oficial",
  financial_data: "Dato financiero",
  contact_data: "Dato de contacto",
  location_data: "Dato de localización",
  technical_credential: "Credencial técnica",
  no_personal_data: "Sin dato personal",
};

export const DELTA_LABELS: Record<string, string> = {
  appeared: "Apareció",
  disappeared: "Desapareció",
  anomalous_growth: "Crecimiento anómalo",
};

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`;
}

export function when(value: string | null | undefined): string {
  if (!value) {
    return "nunca";
  }
  const moment = new Date(value);
  return Number.isNaN(moment.getTime())
    ? value
    : moment.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
}

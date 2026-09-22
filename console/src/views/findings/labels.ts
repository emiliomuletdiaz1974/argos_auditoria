// What the person reads about a finding. The states are those of the API (ADR-0005).
export const STATUS_LABELS: Record<string, string> = {
  open: "Abierto",
  in_remediation: "En remediación",
  pending_verification: "Pendiente de verificación",
  closed_compliant: "Cerrado conforme",
  reopened: "Reabierto",
  risk_accepted: "Riesgo aceptado",
};

// The button that moves a finding to each state a person may choose.
export const ACTION_LABELS: Record<string, string> = {
  in_remediation: "Pasar a remediación",
  pending_verification: "Marcar como subsanado",
  risk_accepted: "Aceptar el riesgo",
};

export const SEVERITY_LABELS: Record<string, string> = {
  critical: "Crítica",
  high: "Alta",
  medium: "Media",
  low: "Baja",
};

export const HISTORY_LABELS: Record<string, string> = {
  "finding.open": "Abierto",
  "finding.recur": "Volvió a aparecer",
};

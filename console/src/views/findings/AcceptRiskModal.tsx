// ARG-076 · accepting a risk is a signed decision, not a way to make a finding go away: it needs a
// reason someone else can judge and a date on which it stops holding.
import { useId, useState } from "react";

export const MIN_REASON = 20;

export interface RiskAcceptance {
  note: string;
  risk_expiry: string;
}

interface Props {
  open: boolean;
  onAccept: (acceptance: RiskAcceptance) => void;
  onCancel: () => void;
}

export function AcceptRiskModal({ open, onAccept, onCancel }: Props) {
  const title = useId();
  const [note, setNote] = useState("");
  const [expiry, setExpiry] = useState("");
  if (!open) {
    return null;
  }
  const reason = note.trim();
  const short = reason.length > 0 && reason.length < MIN_REASON;
  const ready = reason.length >= MIN_REASON && expiry !== "";
  return (
    <div className="modal-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby={title} className="modal panel">
        <h2 id={title}>Aceptar el riesgo</h2>
        <p>
          La aceptación queda en el diario y en el expediente de la campaña, con tu nombre, la justificación y la
          fecha de caducidad. Al caducar, el hallazgo se reabre solo.
        </p>
        <label className="field">
          Justificación
          <textarea value={note} rows={4} onChange={(event) => setNote(event.target.value)} />
        </label>
        {short ? <p className="muted">La justificación necesita al menos {MIN_REASON} caracteres.</p> : null}
        <label className="field">
          Caduca el
          <input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
        </label>
        <div className="actions">
          <button type="button" onClick={onCancel}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!ready}
            onClick={() => onAccept({ note: reason, risk_expiry: expiry })}
          >
            Aceptar el riesgo
          </button>
        </div>
      </div>
    </div>
  );
}

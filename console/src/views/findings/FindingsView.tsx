// ARG-076 · the findings: the triage board, and each finding in its own screen.
import "./findings.css";

import { FindingDetail } from "./FindingDetail";
import { FINDING_PREFIX, FindingsBoard } from "./FindingsBoard";

export function FindingsView({ path }: { path: string }) {
  if (path.startsWith(FINDING_PREFIX) && path.length > FINDING_PREFIX.length) {
    return <FindingDetail findingId={path.slice(FINDING_PREFIX.length)} />;
  }
  return <FindingsBoard />;
}

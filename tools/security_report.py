"""F09-15 · the report of the access battery, for the security dossier.

    uv run python tools/security_report.py [--results dist/security/access-battery.json]
        [--out docs/seguridad/bateria-accesos.md]

`tests/security/test_access_battery.py` writes what it tried and what the deployed API answered;
this turns it into a Markdown page with the date, the commit, the totals by category, every
failure and every combination tried. The page is generated, never edited by hand.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "dist" / "security" / "access-battery.json"
OUT = REPO / "docs" / "seguridad" / "bateria-accesos.md"
CATEGORIES = {
    "matrix": "Matriz rol × permiso con tokens reales",
    "second factor": "Segundo factor",
    "tokens": "Tokens indebidos",
    "separation of duties": "Separación de deberes",
    "surface": "Superficie de la API y la consola",
    "internal services": "Servicios internos",
    "public services": "Servicios públicos",
    "security log": "Registro de seguridad",
}


def _commit() -> str:
    done = subprocess.run(  # noqa: S603 - fixed command
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "desconocido"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render(data: dict[str, Any], commit: str) -> str:
    results: list[dict[str, Any]] = data["results"]
    started = dt.datetime.fromisoformat(data["started"])
    total, good = Counter(), Counter()
    for result in results:
        total[result["category"]] += 1
        good[result["category"]] += bool(result["ok"])
    lines = [
        "# Batería de accesos indebidos",
        "",
        f"**Generado:** {started:%Y-%m-%d %H:%M} UTC · **Commit:** `{commit}` · "
        f"**API atacada:** {data['api']} · **Confidencialidad:** `client`",
        "",
        "Informe generado por `tests/security/test_access_battery.py` y `tools/security_report.py`"
        " (F09-15). La batería ataca el contenedor `api` desplegado con tokens reales del realm,"
        " como lo haría alguien dentro de la red, y comprueba después el estado: una denegación"
        " que dejó efecto no es una denegación. No se edita a mano.",
        "",
        "## Resumen",
        "",
        "| Categoría | Pruebas | Correctas | Fallidas |",
        "|---|---|---|---|",
    ]
    for category in total:
        lines.append(
            f"| {category} | {total[category]} | {good[category]} |"
            f" {total[category] - good[category]} |"
        )
    failures = [r for r in results if not r["ok"]]
    lines += ["", "## Fallos", ""]
    if failures:
        lines += ["| Categoría | Caso | Esperado | Obtenido |", "|---|---|---|---|"]
        lines += [
            f"| {r['category']} | {_cell(r['case'])} | {_cell(r['expected'])} | {_cell(r['got'])} |"
            for r in failures
        ]
    else:
        lines.append("Ningún fallo: cada intento indebido fue rechazado y no dejó efecto.")
    lines += ["", "## Combinaciones probadas", ""]
    for category in total:
        lines += [f"### {CATEGORIES.get(category, category)}", ""]
        lines += ["| Caso | Esperado | Obtenido | Resultado |", "|---|---|---|---|"]
        lines += [
            f"| {_cell(r['case'])} | {_cell(r['expected'])} | {_cell(r['got'])} |"
            f" {'correcto' if r['ok'] else '**fallo**'} |"
            for r in results
            if r["category"] == category
        ]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    data = json.loads(args.results.read_text(encoding="utf-8"))
    args.out.write_text(render(data, _commit()), encoding="utf-8", newline="\n")
    failed = sum(not r["ok"] for r in data["results"])
    print(f"{len(data['results'])} checks, {failed} failed: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

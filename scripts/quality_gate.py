#!/usr/bin/env python3
"""Quality Gate PayFlex : classe chaque indicateur en OK / WARNING / CRITICAL.

Usage :
  python scripts/quality_gate.py coverage --file reports/coverage.xml
  python scripts/quality_gate.py perf     --file reports/perf-summary.json
  python scripts/quality_gate.py secrets  --file reports/gitleaks-report.json

Code de sortie : 0 = OK ou WARNING (le pipeline continue)
                 1 = CRITICAL (le pipeline s'arrete : Fail Fast)
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPORT_DIR = Path("reports")

# ---------- Seuils (tableau du sujet) ----------
COVERAGE_WARN = 80.0      # < 80 %  -> warning
COVERAGE_CRIT = 70.0      # < 70 %  -> critique
P95_WARN_MS = 200.0       # p95 >= 200 ms -> warning
P95_CRIT_MS = 500.0       # p95 > 500 ms  -> critique
ERROR_WARN = 0.01         # erreurs >= 1 % -> warning
ERROR_CRIT = 0.02         # erreurs > 2 %  -> critique
LEAKS_MAX_TOLERATED = 0   # aucune fuite toleree

OK, WARNING, CRITICAL = "OK", "WARNING", "CRITICAL"
ICON = {OK: "✅", WARNING: "⚠️", CRITICAL: "❌"}


def result(gate, status, message, metrics, details=None, action=""):
    return {
        "gate": gate,
        "status": status,
        "message": message,
        "metrics": metrics,
        "details": details or [],
        "action": action,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------- Controle 1 : couverture de code ----------
def check_coverage(path):
    gate = "Couverture de code"
    if not Path(path).exists():
        return result(gate, CRITICAL, f"Rapport de couverture introuvable : {path}", {},
                      action="Verifier que les tests unitaires ont bien genere coverage.xml.")
    pct = float(ET.parse(path).getroot().attrib["line-rate"]) * 100
    metrics = {"Couverture": f"{pct:.1f} %", "Seuil warning": f"{COVERAGE_WARN:.0f} %",
               "Seuil critique": f"{COVERAGE_CRIT:.0f} %"}
    if pct < COVERAGE_CRIT:
        return result(gate, CRITICAL, f"Couverture de {pct:.1f} % inferieure au seuil critique de {COVERAGE_CRIT:.0f} %",
                      metrics, action="Ajouter des tests unitaires avant de redeployer.")
    if pct < COVERAGE_WARN:
        return result(gate, WARNING, f"Attention, couverture a {pct:.1f} % (objectif : {COVERAGE_WARN:.0f} %)",
                      metrics, action="Completer les tests unitaires.")
    return result(gate, OK, f"Couverture de {pct:.1f} % (objectif : {COVERAGE_WARN:.0f} %)", metrics)


# ---------- Controle 2 : performance (k6) ----------
def check_perf(path):
    gate = "Performance (k6)"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        metrics = data["metrics"]

        def values(name):
            m = metrics[name]
            return m.get("values", m)

        p95 = float(values("http_req_duration")["p(95)"])
        failed = values("http_req_failed")
        err = float(failed.get("rate", failed.get("value", 0.0)))
    except (OSError, KeyError, ValueError):
        return result(gate, CRITICAL, "Resultats k6 absents ou illisibles : test de charge non execute", {},
                      action="Consulter les logs de l'etape k6.")

    table = {"Latence p95": f"{p95:.0f} ms", "Taux d'erreur": f"{err * 100:.2f} %",
             "Seuils": f"warning p95 >= {P95_WARN_MS:.0f} ms ; critique p95 > {P95_CRIT_MS:.0f} ms ou erreurs > {ERROR_CRIT * 100:.0f} %"}

    causes = []
    if p95 > P95_CRIT_MS:
        causes.append(f"latence p95 de {p95:.0f} ms > {P95_CRIT_MS:.0f} ms")
    if err > ERROR_CRIT:
        causes.append(f"taux d'erreur de {err * 100:.2f} % > {ERROR_CRIT * 100:.0f} %")
    if causes:
        return result(gate, CRITICAL, "Performance degradee : " + " ; ".join(causes), table,
                      action="Rechercher la regression de performance (dernier commit, ressources, requetes lentes).")

    if p95 >= P95_WARN_MS or err >= ERROR_WARN:
        return result(gate, WARNING, f"Performance a surveiller : p95 = {p95:.0f} ms, erreurs = {err * 100:.2f} %",
                      table, action="Surveiller la tendance, optimiser si elle se confirme.")
    return result(gate, OK, f"Performance conforme : p95 = {p95:.0f} ms, erreurs = {err * 100:.2f} %", table)


# ---------- Controle 3 : confidentialite (Gitleaks) ----------
def check_secrets(path):
    gate = "Confidentialite (Gitleaks)"
    if not Path(path).exists():
        return result(gate, CRITICAL, f"Rapport Gitleaks introuvable : {path} (scan non execute)", {},
                      action="Verifier l'etape de scan Gitleaks.")
    text = Path(path).read_text(encoding="utf-8").strip()
    leaks = json.loads(text) if text else []
    n = len(leaks)
    rate = max(0.0, (1 - n / max(LEAKS_MAX_TOLERATED, 1)) * 100)
    metrics = {"Fuites detectees": n, "Seuil maximal tolere": LEAKS_MAX_TOLERATED,
               "Taux de confidentialite": f"{rate:.0f} %"}
    if n > LEAKS_MAX_TOLERATED:
        details = [f"{l.get('RuleID', '?')} dans {l.get('File', '?')} (ligne {l.get('StartLine', '?')})" for l in leaks]
        return result(gate, CRITICAL,
                      f"Fuite de donnees sensibles detectee : {n} fuite(s), taux de confidentialite de {rate:.0f} % (exige : 100 %)",
                      metrics, details,
                      "Retirer le secret du code, le REVOQUER / le renouveler, puis relancer le pipeline.")
    return result(gate, OK, f"Taux de confidentialite de {rate:.0f} % : aucune fuite detectee", metrics)


# ---------- Publication des resultats ----------
def to_markdown(res):
    lines = [f"### {ICON[res['status']]} {res['gate']} : {res['status']}", "", res["message"], ""]
    if res["metrics"]:
        lines += ["| Indicateur | Valeur |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in res["metrics"].items()]
        lines.append("")
    if res["details"]:
        lines += [f"- {d}" for d in res["details"]] + [""]
    return "\n".join(lines)


def incident_report(res):
    repo = os.getenv("GITHUB_REPOSITORY", "execution locale")
    run_id = os.getenv("GITHUB_RUN_ID")
    run_url = (f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}"
               if run_id else "n/a (execution locale)")
    metrics = "\n".join(f"| {k} | {v} |" for k, v in res["metrics"].items())
    details = "\n".join(f"- {d}" for d in res["details"]) or "- (aucun detail supplementaire)"
    return f"""# Rapport d'incident - Pipeline interrompu (erreur critique)

| Champ | Valeur |
|---|---|
| Date (UTC) | {res['time']} |
| Depot | {repo} |
| Branche | {os.getenv('GITHUB_REF_NAME', 'n/a')} |
| Commit | {os.getenv('GITHUB_SHA', 'n/a')} |
| Execution | {run_url} |
| Controle en echec | {res['gate']} |

## Cause exacte
{res['message']}

## Mesures
| Indicateur | Valeur |
|---|---|
{metrics}

## Details
{details}

## Consequence
Le deploiement est annule : les etapes suivantes ne sont pas executees (Fail Fast).

## Action recommandee
{res['action']}
"""


def publish(res):
    status = res["status"]
    print(f"[{status}] {res['gate']} : {res['message']}")
    for d in res["details"]:
        print(f"    - {d}")

    # Annotations visibles dans l'interface GitHub Actions
    if status == WARNING:
        print(f"::warning title={res['gate']}::{res['message']}")
    elif status == CRITICAL:
        print(f"::error title={res['gate']}::{res['message']}")

    # Rapport JSON cumulatif
    REPORT_DIR.mkdir(exist_ok=True)
    jpath = REPORT_DIR / "quality-report.json"
    history = json.loads(jpath.read_text(encoding="utf-8")) if jpath.exists() else []
    history.append(res)
    jpath.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")

    # Resume affiche sur la page de l'execution GitHub Actions
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(to_markdown(res) + "\n")

    # Rapport d'incident en cas d'erreur critique
    if status == CRITICAL:
        (REPORT_DIR / "incident-report.md").write_text(incident_report(res), encoding="utf-8")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("\n" + incident_report(res) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Quality Gate PayFlex")
    parser.add_argument("check", choices=["coverage", "perf", "secrets"])
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    checks = {"coverage": check_coverage, "perf": check_perf, "secrets": check_secrets}
    res = checks[args.check](args.file)
    publish(res)
    sys.exit(1 if res["status"] == CRITICAL else 0)


if __name__ == "__main__":
    main()
#!/usr/bin/env bash
set -Eeuo pipefail

# SongStudio Haupt-Test-Runner
# Ziel: deterministische Testausfuehrung ohne externe Provider-/Suno-Aufrufe
# mit professioneller, konzentrierter Terminal-Ausgabe und optionalem Quality-Gate.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_ROOT/documentation/test-audit-logs"
RUNTIME_DIR="$PROJECT_ROOT/.pytest-runtime"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/test-run-$TIMESTAMP.log"
JUNIT_FILE="$LOG_DIR/test-run-$TIMESTAMP.junit.xml"
REPORT_FILE="$LOG_DIR/test-run-$TIMESTAMP.summary.txt"
PYTEST_TARGETS=("tests")
PYTEST_EXTRA_ARGS=()
VERBOSE=0
FAIL_FAST=0
SHOW_LOG_ON_SUCCESS=0
SHOW_WARNINGS=0
KEEP_XML=0
STRICT=0
SUMMARY_ONLY=0
NO_XFAIL=0
MAX_WARNINGS="${TEST_RUNNER_MAX_WARNINGS:-}"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD="\033[1m"
  DIM="\033[2m"
  RED="\033[31m"
  GREEN="\033[32m"
  YELLOW="\033[33m"
  BLUE="\033[34m"
  CYAN="\033[36m"
  MAGENTA="\033[35m"
  RESET="\033[0m"
else
  BOLD=""
  DIM=""
  RED=""
  GREEN=""
  YELLOW=""
  BLUE=""
  CYAN=""
  MAGENTA=""
  RESET=""
fi

print_usage() {
  cat <<USAGE
SongStudio Test Runner

Nutzung:
  ./run_tests.sh                         Alle Tests mit professioneller Kompaktausgabe ausfuehren
  ./run_tests.sh --summary-only          Nur Gesamtbewertung, Kennzahlen und Artefakte anzeigen
  ./run_tests.sh --warnings              Warnungsgruppen ausgeben
  ./run_tests.sh --strict                Quality-Gate: Warnungen, XFail, XPass, Skip als Fehler werten
  ./run_tests.sh --no-xfail              Nur XFail/XPass als Fehler werten
  ./run_tests.sh --max-warnings 20       Fehler, wenn mehr als 20 Warnungen entstehen
  ./run_tests.sh --verbose               Vollstaendige pytest-Ausgabe live anzeigen
  ./run_tests.sh --fail-fast             Beim ersten Fehler stoppen
  ./run_tests.sh -k "srt"                 Nur Tests mit passendem pytest-Ausdruck ausfuehren
  ./run_tests.sh --file tests/test_x.py   Einzelne Testdatei oder einzelnen Testpfad ausfuehren
  ./run_tests.sh --show-log              Logpfad bei Erfolg deutlich anzeigen

Optionen:
  -k, --keyword <expr>       pytest -k Ausdruck
  -m, --marker <expr>        pytest -m Marker-Ausdruck
  -f, --file <path>          Testdatei/Testpfad statt gesamtem tests/-Ordner
  -v, --verbose              Live-Ausgabe und detailliertere pytest-Ausgabe
  --fail-fast                Entspricht pytest -x
  --summary-only             Keine Testdatei-Tabelle ausgeben
  --show-log                 Logdatei bei Erfolg deutlich anzeigen
  --warnings                 Pytest-Warnungsdetails nicht unterdruecken und Gruppen anzeigen
  --strict                   Strenges Gate: Fail bei Warnungen, XFail, XPass oder Skip
  --no-xfail                 Fail bei XFail oder XPass
  --max-warnings <n>         Fail, wenn Warnungen groesser als n sind
  --keep-xml                 JUnit-XML nach dem Lauf behalten
  -h, --help                 Hilfe anzeigen

Umgebung:
  TEST_RUNNER_PYTHON=/pfad/python        Python-Binary explizit setzen
  TEST_RUNNER_TIMEOUT_SECONDS=600        Optionaler Timeout, wenn 'timeout' installiert ist
  TEST_RUNNER_MAX_WARNINGS=20            Standardwert fuer --max-warnings
  NO_COLOR=1                             Farbausgabe deaktivieren
USAGE
}

is_uint() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      print_usage
      exit 0
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    --fail-fast)
      FAIL_FAST=1
      shift
      ;;
    --summary-only)
      SUMMARY_ONLY=1
      shift
      ;;
    --show-log)
      SHOW_LOG_ON_SUCCESS=1
      shift
      ;;
    --warnings)
      SHOW_WARNINGS=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --no-xfail)
      NO_XFAIL=1
      shift
      ;;
    --max-warnings)
      [[ $# -ge 2 ]] || { echo "Fehler: $1 benoetigt einen Wert." >&2; exit 2; }
      is_uint "$2" || { echo "Fehler: --max-warnings erwartet eine Zahl." >&2; exit 2; }
      MAX_WARNINGS="$2"
      shift 2
      ;;
    --keep-xml)
      KEEP_XML=1
      shift
      ;;
    -k|--keyword)
      [[ $# -ge 2 ]] || { echo "Fehler: $1 benoetigt einen Wert." >&2; exit 2; }
      PYTEST_EXTRA_ARGS+=("-k" "$2")
      shift 2
      ;;
    -m|--marker)
      [[ $# -ge 2 ]] || { echo "Fehler: $1 benoetigt einen Wert." >&2; exit 2; }
      PYTEST_EXTRA_ARGS+=("-m" "$2")
      shift 2
      ;;
    -f|--file|--target)
      [[ $# -ge 2 ]] || { echo "Fehler: $1 benoetigt einen Wert." >&2; exit 2; }
      PYTEST_TARGETS=("$2")
      shift 2
      ;;
    --)
      shift
      PYTEST_EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      echo "Unbekannte Option: $1" >&2
      echo "Nutze ./run_tests.sh --help fuer Hilfe." >&2
      exit 2
      ;;
  esac
done

if [[ -n "$MAX_WARNINGS" ]] && ! is_uint "$MAX_WARNINGS"; then
  echo "Fehler: TEST_RUNNER_MAX_WARNINGS muss eine Zahl sein." >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$RUNTIME_DIR"
cd "$PROJECT_ROOT"

PYTHON_BIN="${TEST_RUNNER_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "Python wurde nicht gefunden." >&2
    exit 127
  fi
fi

if [[ ! -x "$PYTHON_BIN" && "$PYTHON_BIN" != "python" && "$PYTHON_BIN" != "python3" ]]; then
  echo "Python ist nicht ausfuehrbar: $PYTHON_BIN" >&2
  exit 127
fi

# Harte Test-Defaults gegen unbeabsichtigte Live-/Provider-Aufrufe.
export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-test-secret-for-songstudio-tests-only}"
export SUNO_API_KEY="${SUNO_API_KEY:-test-suno-key}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-test-openai-key}"
export GROQ_API_KEY="${GROQ_API_KEY:-test-groq-key}"
export MISTRAL_API_KEY="${MISTRAL_API_KEY:-test-mistral-key}"
export VOXTRAL_API_KEY="${VOXTRAL_API_KEY:-test-voxtral-key}"
export REPLICATE_API_TOKEN="${REPLICATE_API_TOKEN:-test-replicate-token}"
export ALLOW_REGISTRATION="${ALLOW_REGISTRATION:-true}"
export SUNO_STARTUP_RECOVERY_ENABLED="${SUNO_STARTUP_RECOVERY_ENABLED:-false}"
export TASK_WATCHDOG_ENABLED="${TASK_WATCHDOG_ENABLED:-false}"
export STARTUP_LIBRARY_REPAIR_ENABLED="${STARTUP_LIBRARY_REPAIR_ENABLED:-false}"
export LIBRARY_CONTENT_POLLING_ENABLED="${LIBRARY_CONTENT_POLLING_ENABLED:-false}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-0}"
export SUNO_TEST_STORAGE_ROOT="${SUNO_TEST_STORAGE_ROOT:-$RUNTIME_DIR/storage}"

if ! "$PYTHON_BIN" -m pytest --version >/dev/null 2>&1; then
  echo -e "${RED}pytest ist in dieser Python-Umgebung nicht verfuegbar.${RESET}" >&2
  echo "Python: $PYTHON_BIN" >&2
  echo "Installiere die Projektabhaengigkeiten aus requirements.txt und starte erneut." >&2
  exit 127
fi

PYTHON_VERSION="$("$PYTHON_BIN" --version 2>&1)"
PYTEST_VERSION="$("$PYTHON_BIN" -m pytest --version 2>&1 | head -n 1)"
PYTEST_ARGS=("-q" "--tb=short" "-ra" "--junitxml" "$JUNIT_FILE")

if [[ "$SHOW_WARNINGS" -eq 0 ]]; then
  PYTEST_ARGS+=("--disable-warnings")
fi
if [[ "$VERBOSE" -eq 1 ]]; then
  PYTEST_ARGS=("-vv" "--tb=long" "-ra" "--junitxml" "$JUNIT_FILE")
  [[ "$SHOW_WARNINGS" -eq 0 ]] && PYTEST_ARGS+=("--disable-warnings")
fi
if [[ "$FAIL_FAST" -eq 1 ]]; then
  PYTEST_ARGS+=("-x")
fi
PYTEST_ARGS+=("${PYTEST_TARGETS[@]}" "${PYTEST_EXTRA_ARGS[@]}")

RUN_CMD=("$PYTHON_BIN" "-m" "pytest" "${PYTEST_ARGS[@]}")
if [[ -n "${TEST_RUNNER_TIMEOUT_SECONDS:-}" ]] && command -v timeout >/dev/null 2>&1; then
  RUN_CMD=("timeout" "${TEST_RUNNER_TIMEOUT_SECONDS}" "${RUN_CMD[@]}")
fi

hr() { printf '%b\n' "${DIM}────────────────────────────────────────────────────────────${RESET}"; }
kv() { printf '  %b%-20s%b %s\n' "$CYAN" "$1" "$RESET" "$2"; }
section() { printf '\n%b\n' "${BOLD}$1${RESET}"; }

format_targets() {
  printf '%s ' "${PYTEST_TARGETS[@]}" "${PYTEST_EXTRA_ARGS[@]:-}" | sed 's/[[:space:]]*$//'
}

create_summary_report() {
  "$PYTHON_BIN" - "$JUNIT_FILE" "$LOG_FILE" "$REPORT_FILE" <<'PY'
import collections
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

junit_path = pathlib.Path(sys.argv[1])
log_path = pathlib.Path(sys.argv[2])
report_path = pathlib.Path(sys.argv[3])
log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""

summary_line = ""
for line in log_text.splitlines():
    if re.search(r"\d+ (passed|failed|errors?|skipped|xfailed|xpassed|warnings?)", line) and " in " in line:
        summary_line = line.strip()

warning_count = 0
m = re.search(r"(?:^|, )([0-9]+) warnings?", summary_line)
if m:
    warning_count = int(m.group(1))
else:
    warning_count = len(re.findall(r"(?im)warning", log_text))

items = []
if junit_path.exists():
    root = ET.parse(junit_path).getroot()
    testcases = root.findall(".//testcase")
    for case in testcases:
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        file_attr = case.attrib.get("file", "")
        time_value = float(case.attrib.get("time", "0") or 0)
        if file_attr:
            file_name = file_attr
        elif classname:
            candidate = classname.replace(".", "/") + ".py"
            if pathlib.Path(candidate).exists():
                file_name = candidate
            else:
                parts = classname.split(".")
                parent_candidate = "/".join(parts[:-1]) + ".py" if len(parts) > 1 else candidate
                file_name = parent_candidate if pathlib.Path(parent_candidate).exists() else candidate
        else:
            file_name = "unknown"
        status = "passed"
        detail = ""
        if case.find("failure") is not None:
            status = "failed"
            detail = (case.find("failure").attrib.get("message", "") or "").strip()
        elif case.find("error") is not None:
            status = "error"
            detail = (case.find("error").attrib.get("message", "") or "").strip()
        elif case.find("skipped") is not None:
            skipped = case.find("skipped")
            msg = (skipped.attrib.get("message", "") or "").strip()
            detail = msg
            skip_type = (skipped.attrib.get("type", "") or "").lower()
            if "xfail" in msg.lower() or "xfailed" in msg.lower() or "xfail" in skip_type:
                status = "xfailed"
            else:
                status = "skipped"
        items.append((file_name, classname, name, status, time_value, detail))

counts = collections.Counter(status for *_pre, status, _time, _detail in items)
by_file = collections.defaultdict(lambda: collections.Counter())
file_time = collections.defaultdict(float)
failures = []
xfails = []
for file_name, classname, name, status, time_value, detail in items:
    by_file[file_name][status] += 1
    by_file[file_name]["total"] += 1
    file_time[file_name] += time_value
    full_name = f"{classname}::{name}" if classname else name
    if status in {"failed", "error"}:
        failures.append((file_name, full_name, status, detail))
    if status == "xfailed":
        xfails.append((file_name, full_name, detail))

total = len(items)
passed = counts.get("passed", 0)
failed = counts.get("failed", 0)
errors = counts.get("error", 0)
skipped = counts.get("skipped", 0)
xfailed = counts.get("xfailed", 0)
xpassed = counts.get("xpassed", 0)

warning_records = []
# Eintrag: (anzahl, warning_type, source_path, message, trigger_context)
# Pytest gibt Warnungen teilweise verdichtet aus:
#   tests/test_x.py: 16 warnings
#   /venv/.../schema.py:3623: DeprecationWarning: message
# Dadurch muss der Zaehler der Test-Kontexte auf die folgende konkrete Warnquelle abgebildet werden.
pending_contexts = []
inside_warning_summary = False
for raw_line in log_text.splitlines():
    stripped = raw_line.strip()
    if stripped.startswith("warnings summary") or " warnings summary " in stripped:
        inside_warning_summary = True
        continue
    if not inside_warning_summary:
        continue
    if stripped.startswith("-- Docs:") or stripped.startswith("short test summary"):
        break
    if not stripped:
        continue

    m = re.match(r"^(?P<context>[^:]+?\.py):\s*(?P<count>\d+)\s+warnings?$", stripped)
    if m:
        pending_contexts.append((m.group("context"), int(m.group("count"))))
        continue
    m = re.match(r"^(?P<context>[^:]+?\.py::[^:]+)$", stripped)
    if m:
        pending_contexts.append((m.group("context"), 1))
        continue

    m = re.match(r"^(?P<path>[^\s:][^:]*?):(?P<line>\d+):\s*(?P<type>[A-Za-z_][A-Za-z0-9_]*Warning):\s*(?P<msg>.*)$", stripped)
    if not m:
        m = re.match(r"^(?P<path>/[^:]+):(?P<line>\d+):\s*(?P<type>[A-Za-z_][A-Za-z0-9_]*Warning):\s*(?P<msg>.*)$", stripped)
    if m:
        warning_type = m.group("type")
        source_path = m.group("path")
        message = m.group("msg")
        if pending_contexts:
            for context, count in pending_contexts:
                warning_records.append((count, warning_type, source_path, message, context))
            pending_contexts = []
        else:
            warning_records.append((1, warning_type, source_path, message, source_path))

warning_type_groups = collections.Counter()
warning_path_groups = collections.Counter()
warning_message_groups = collections.Counter()
warning_trigger_groups = collections.Counter()
for count, warning_type, path, msg, context in warning_records:
    normalized_path = path
    if "/site-packages/" in normalized_path:
        normalized_path = "site-packages/" + normalized_path.split("/site-packages/", 1)[1].split("/", 1)[0]
    elif normalized_path.startswith("/"):
        parts = pathlib.Path(normalized_path).parts
        normalized_path = "/".join(parts[-3:]) if len(parts) >= 3 else normalized_path
    normalized_context = context.split("::", 1)[0]
    normalized_msg = re.sub(r"\s+", " ", msg).strip()[:160]
    warning_type_groups[warning_type] += count
    warning_path_groups[(warning_type, normalized_path)] += count
    warning_message_groups[(warning_type, normalized_msg)] += count
    warning_trigger_groups[(warning_type, normalized_context)] += count

lines = []
lines.append("SUMMARY=" + (summary_line or "keine pytest-Zusammenfassung gefunden"))
lines.append(f"TOTAL={total}")
lines.append(f"PASSED={passed}")
lines.append(f"FAILED={failed}")
lines.append(f"ERRORS={errors}")
lines.append(f"SKIPPED={skipped}")
lines.append(f"XFAILED={xfailed}")
lines.append(f"XPASSED={xpassed}")
lines.append(f"WARNINGS={warning_count}")
lines.append("")
lines.append("TEST_FILES")
for file_name in sorted(by_file):
    c = by_file[file_name]
    status_parts = []
    for key, label in [
        ("passed", "passed"),
        ("failed", "failed"),
        ("error", "errors"),
        ("xfailed", "xfailed"),
        ("skipped", "skipped"),
        ("xpassed", "xpassed"),
    ]:
        if c.get(key, 0):
            status_parts.append(f"{c[key]} {label}")
    lines.append(f"{file_name}|{c['total']}|{file_time[file_name]:.2f}|{', '.join(status_parts) if status_parts else 'keine Details'}")
lines.append("")
lines.append("FAILURES")
for file_name, full_name, status, detail in failures[:20]:
    clean_detail = re.sub(r"\s+", " ", detail).strip()
    lines.append(f"{status.upper()}|{file_name}|{full_name}|{clean_detail[:220]}")
lines.append("")
lines.append("XFAILS")
for file_name, full_name, detail in xfails[:20]:
    clean_detail = re.sub(r"\s+", " ", detail).strip()
    lines.append(f"{file_name}|{full_name}|{clean_detail[:220]}")
lines.append("")
lines.append("WARNING_TYPES")
for warning_type, count in warning_type_groups.most_common(12):
    lines.append(f"{count}|{warning_type}")
lines.append("")
lines.append("WARNING_PATHS")
for (warning_type, path), count in warning_path_groups.most_common(12):
    lines.append(f"{count}|{warning_type}|{path}")
lines.append("")
lines.append("WARNING_TESTS")
for (warning_type, context), count in warning_trigger_groups.most_common(12):
    lines.append(f"{count}|{warning_type}|{context}")
lines.append("")
lines.append("WARNING_MESSAGES")
for (warning_type, msg), count in warning_message_groups.most_common(8):
    lines.append(f"{count}|{warning_type}|{msg}")

report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

get_report_value() {
  local key="$1"
  grep -E "^${key}=" "$REPORT_FILE" 2>/dev/null | head -n 1 | cut -d= -f2- || true
}

num_value() {
  local value="${1:-0}"
  [[ "$value" =~ ^[0-9]+$ ]] && printf '%s' "$value" || printf '0'
}

print_file_table() {
  awk -F'|' '
    BEGIN { seen=0 }
    /^TEST_FILES$/ { seen=1; next }
    /^$/ && seen==1 { exit }
    seen==1 {
      printf "  %-48s %4s Tests  %6ss  %s\n", $1, $2, $3, $4
    }
  ' "$REPORT_FILE"
}

print_failures() {
  awk -F'|' '
    BEGIN { seen=0; count=0 }
    /^FAILURES$/ { seen=1; next }
    /^$/ && seen==1 { exit }
    seen==1 {
      count++
      printf "  [%s] %s\n      %s\n      %s\n", $1, $2, $3, $4
    }
    END { if (count == 0) print "  keine Fehlerdetails aus JUnit extrahiert" }
  ' "$REPORT_FILE"
}

print_xfails() {
  awk -F'|' '
    BEGIN { seen=0; count=0 }
    /^XFAILS$/ { seen=1; next }
    /^$/ && seen==1 { exit }
    seen==1 {
      count++
      printf "  %s\n      %s\n", $1, $2
      if ($3 != "") printf "      Grund: %s\n", $3
    }
    END { if (count == 0) print "  keine" }
  ' "$REPORT_FILE"
}

print_warning_groups() {
  local mode="$1"
  case "$mode" in
    types)
      awk -F'|' '
        BEGIN { seen=0; count=0 }
        /^WARNING_TYPES$/ { seen=1; next }
        /^$/ && seen==1 { exit }
        seen==1 { count++; printf "  %-5s %s\n", $1, $2 }
        END { if (count == 0) print "  keine gruppierten Warnungen vorhanden" }
      ' "$REPORT_FILE"
      ;;
    paths)
      awk -F'|' '
        BEGIN { seen=0; count=0 }
        /^WARNING_PATHS$/ { seen=1; next }
        /^$/ && seen==1 { exit }
        seen==1 { count++; printf "  %-5s %-24s %s\n", $1, $2, $3 }
        END { if (count == 0) print "  keine gruppierten Warnpfade vorhanden" }
      ' "$REPORT_FILE"
      ;;
    tests)
      awk -F'|' '
        BEGIN { seen=0; count=0 }
        /^WARNING_TESTS$/ { seen=1; next }
        /^$/ && seen==1 { exit }
        seen==1 { count++; printf "  %-5s %-24s %s\n", $1, $2, $3 }
        END { if (count == 0) print "  keine gruppierten Warn-Testkontexte vorhanden" }
      ' "$REPORT_FILE"
      ;;
    messages)
      awk -F'|' '
        BEGIN { seen=0; count=0 }
        /^WARNING_MESSAGES$/ { seen=1; next }
        /^$/ && seen==1 { exit }
        seen==1 { count++; printf "  %-5s %-24s %s\n", $1, $2, $3 }
        END { if (count == 0) print "  keine gruppierten Warnmeldungen vorhanden" }
      ' "$REPORT_FILE"
      ;;
  esac
}

printf '%b\n' "${BOLD}${BLUE}SongStudio Test Runner${RESET}"
hr
kv "Projekt" "$PROJECT_ROOT"
kv "Python" "$PYTHON_VERSION"
kv "Pytest" "$PYTEST_VERSION"
kv "Ziel" "$(format_targets)"
kv "Modus" "$([[ "$VERBOSE" -eq 1 ]] && echo "verbose" || ([[ "$SUMMARY_ONLY" -eq 1 ]] && echo "summary-only" || echo "professionell-kompakt"))"
kv "Quality-Gate" "$([[ "$STRICT" -eq 1 ]] && echo "strict" || ([[ "$NO_XFAIL" -eq 1 || -n "$MAX_WARNINGS" ]] && echo "angepasst" || echo "normal"))"
kv "Live-Schutz" "aktiv: Provider-/Suno-Keys auf Testwerte, Startup-Jobs deaktiviert"
kv "Test-Storage" "$SUNO_TEST_STORAGE_ROOT"
kv "Log" "$LOG_FILE"
hr
printf '%b\n' "${BOLD}Starte automatisierte Tests ...${RESET}"

START_SECONDS=$SECONDS
set +e
if [[ "$VERBOSE" -eq 1 ]]; then
  "${RUN_CMD[@]}" 2>&1 | tee "$LOG_FILE"
  EXIT_CODE=${PIPESTATUS[0]}
else
  "${RUN_CMD[@]}" >"$LOG_FILE" 2>&1
  EXIT_CODE=$?
fi
set -e
DURATION=$((SECONDS - START_SECONDS))

if [[ -f "$JUNIT_FILE" ]]; then
  create_summary_report || true
else
  printf 'SUMMARY=keine JUnit-Auswertung vorhanden\nTOTAL=0\nPASSED=0\nFAILED=0\nERRORS=0\nSKIPPED=0\nXFAILED=0\nXPASSED=0\nWARNINGS=0\n\nTEST_FILES\n\nFAILURES\n\nXFAILS\n\nWARNING_TYPES\n\nWARNING_PATHS\n\nWARNING_MESSAGES\n' > "$REPORT_FILE"
fi

SUMMARY_LINE="$(get_report_value SUMMARY)"
TOTAL="$(num_value "$(get_report_value TOTAL)")"
PASSED="$(num_value "$(get_report_value PASSED)")"
FAILED="$(num_value "$(get_report_value FAILED)")"
ERRORS="$(num_value "$(get_report_value ERRORS)")"
SKIPPED="$(num_value "$(get_report_value SKIPPED)")"
XFAILED="$(num_value "$(get_report_value XFAILED)")"
XPASSED="$(num_value "$(get_report_value XPASSED)")"
WARNING_COUNT="$(num_value "$(get_report_value WARNINGS)")"

GATE_EXIT_CODE="$EXIT_CODE"
GATE_FINDINGS=()
if [[ "$STRICT" -eq 1 ]]; then
  [[ "$WARNING_COUNT" -gt 0 ]] && GATE_FINDINGS+=("Warnungen > 0")
  [[ "$XFAILED" -gt 0 ]] && GATE_FINDINGS+=("XFail > 0")
  [[ "$XPASSED" -gt 0 ]] && GATE_FINDINGS+=("XPass > 0")
  [[ "$SKIPPED" -gt 0 ]] && GATE_FINDINGS+=("Skipped > 0")
fi
if [[ "$NO_XFAIL" -eq 1 ]]; then
  [[ "$XFAILED" -gt 0 ]] && GATE_FINDINGS+=("XFail > 0")
  [[ "$XPASSED" -gt 0 ]] && GATE_FINDINGS+=("XPass > 0")
fi
if [[ -n "$MAX_WARNINGS" && "$WARNING_COUNT" -gt "$MAX_WARNINGS" ]]; then
  GATE_FINDINGS+=("Warnungen ${WARNING_COUNT} > Limit ${MAX_WARNINGS}")
fi
if [[ "$EXIT_CODE" -eq 0 && "${#GATE_FINDINGS[@]}" -gt 0 ]]; then
  GATE_EXIT_CODE=1
fi

QUALITY_STATUS="BESTANDEN"
QUALITY_RATING="stabil"
QUALITY_COLOR="$GREEN"
if [[ "$EXIT_CODE" -ne 0 ]]; then
  QUALITY_STATUS="FEHLGESCHLAGEN"
  QUALITY_RATING="blockierender Testfehler"
  QUALITY_COLOR="$RED"
elif [[ "$GATE_EXIT_CODE" -ne 0 ]]; then
  QUALITY_STATUS="QUALITY-GATE FEHLGESCHLAGEN"
  QUALITY_RATING="Tests fachlich OK, aber Gate-Regeln verletzt"
  QUALITY_COLOR="$YELLOW"
elif [[ "$WARNING_COUNT" -gt 0 || "$XFAILED" -gt 0 || "$SKIPPED" -gt 0 ]]; then
  QUALITY_STATUS="BESTANDEN MIT HINWEISEN"
  QUALITY_RATING="OK mit technischen Altlasten"
  QUALITY_COLOR="$YELLOW"
fi

hr
if [[ "$EXIT_CODE" -eq 0 && "$GATE_EXIT_CODE" -eq 0 ]]; then
  printf '%b\n' "${GREEN}${BOLD}OK: Testlauf erfolgreich.${RESET}"
elif [[ "$EXIT_CODE" -eq 0 && "$GATE_EXIT_CODE" -ne 0 ]]; then
  printf '%b\n' "${YELLOW}${BOLD}ACHTUNG: Tests bestanden, Quality-Gate fehlgeschlagen.${RESET}"
else
  printf '%b\n' "${RED}${BOLD}FEHLER: Testlauf fehlgeschlagen.${RESET}"
fi
kv "Dauer" "${DURATION}s"
kv "Gesamt" "${TOTAL} Tests"
kv "Passed" "$PASSED"
kv "Failed" "$FAILED"
kv "Errors" "$ERRORS"
kv "XFailed" "$XFAILED"
kv "Skipped" "$SKIPPED"
kv "XPassed" "$XPASSED"
kv "Warnungen" "$WARNING_COUNT"
kv "Pytest" "$SUMMARY_LINE"

section "Qualitaetsbewertung"
kv "Status" "$QUALITY_STATUS"
kv "Bewertung" "$QUALITY_RATING"
kv "Gate" "$([[ "$STRICT" -eq 1 ]] && echo "strict" || ([[ "$NO_XFAIL" -eq 1 || -n "$MAX_WARNINGS" ]] && echo "angepasst" || echo "normal"))"
if [[ "${#GATE_FINDINGS[@]}" -gt 0 ]]; then
  GATE_FINDINGS_TEXT="$(printf '%s\n' "${GATE_FINDINGS[@]}" | paste -sd ',' - | sed 's/,/, /g')"
  printf '  %b%-20s%b %s\n' "$CYAN" "Gate-Verletzungen" "$RESET" "$GATE_FINDINGS_TEXT"
fi

if [[ "$SUMMARY_ONLY" -eq 0 ]]; then
  section "Testdateien"
  print_file_table
fi

if [[ "$SUMMARY_ONLY" -eq 0 && "$XFAILED" -gt 0 ]]; then
  section "Erwartete XFail-Marker"
  print_xfails
fi

if [[ "$WARNING_COUNT" -gt 0 ]]; then
  section "Warnungsuebersicht"
  if [[ "$SHOW_WARNINGS" -eq 1 ]]; then
    printf '  %b\n' "Nach Typ:"
    print_warning_groups types
    printf '\n  %b\n' "Nach Quelle:"
    print_warning_groups paths
    printf '\n  %b\n' "Nach ausloesender Testdatei:"
    print_warning_groups tests
    printf '\n  %b\n' "Haeufigste Meldungen:"
    print_warning_groups messages
  else
    printf '  %s\n' "Details wurden fuer kompakte Ausgabe unterdrueckt. Nutze --warnings fuer Warnungsgruppen."
  fi
fi

if [[ "$EXIT_CODE" -ne 0 ]]; then
  section "Fehlerdiagnose"
  print_failures
  printf '\n%b\n' "${BOLD}Letzte relevante Logzeilen:${RESET}"
  tail -n 80 "$LOG_FILE" | sed 's/^/  /'
  printf '\n%b\n' "${YELLOW}Vollstaendiges Log: $LOG_FILE${RESET}"
else
  section "Artefakte"
  printf '  Log-Datei          %s\n' "$LOG_FILE"
  printf '  Kurzbericht        %s\n' "$REPORT_FILE"
  if [[ "$KEEP_XML" -eq 1 ]]; then
    printf '  JUnit-XML          %s\n' "$JUNIT_FILE"
  else
    rm -f "$JUNIT_FILE"
  fi
  if [[ "$SHOW_LOG_ON_SUCCESS" -eq 1 ]]; then
    printf '\n%b\n' "${DIM}Vollstaendiges Log:${RESET}"
    sed 's/^/  /' "$LOG_FILE"
  fi
fi
hr
exit "$GATE_EXIT_CODE"

"""Planning profile launcher (deploy/planner): prepares and checks a Hermes home, then runs Hermes.

The planning profile plans and validates; it never operates. Its Hermes home always carries the existing,
verified restriction of the project's MCP server to the planning tools (``tools.include``, resources/prompts off)
and Tool Search off, built with the capture runner's own ``restrict_mcp_text``/``disable_tool_search_text``.
Every start re-checks that restriction and refuses to run Hermes otherwise; Hermes always gets
``--toolsets tfg-mission-control`` (no terminal, file, web or other built-in tool, no other MCP server).

    hermes_home.py login                     the operator's own provider login (hermes auth add <provider> --no-browser)
    hermes_home.py run [HERMES ARGS...]      e.g. run -z "PROMPT"  (no args: interactive session)
    hermes_home.py status                    configuration check, login present or not, drafts and finalizations
    hermes_home.py check                     configuration check only (exit 1 if not planning-safe)
    hermes_home.py prepare-trial HOME        base home for the capture runner's single real test (it adds the filter)
    hermes_home.py prepare-test-home HOME URL   TEST DOUBLE home: an OpenAI-compatible fake provider at URL

Configuration files are written only into a home that has none; nothing is ever overwritten.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # run as a script from the project root

from observability.hermes_capture_run import (  # noqa: E402
    MCP_SERVER, PLANNING_TOOLS, TRIAL_SERVER_ARGS, VERIFIED_HERMES_COMMIT, disable_tool_search_text,
    restrict_mcp_text, tools_filter)

TEMPLATE = Path(__file__).with_name("hermes-config.base.yaml")
HERMES_BIN = Path(os.environ.get("TFG_HERMES_BIN", "/opt/hermes/agent/.venv/bin/hermes"))
HERMES_AGENT = Path(os.environ.get("TFG_HERMES_AGENT", "/opt/hermes/agent"))
SERVER_COMMAND = "/opt/tfg/.venv/bin/python"
STORE = Path(__file__).resolve().parents[2] / "missions" / "generated"
TEST_DOUBLE_MODEL = "tfg-test-double"


def planning_config(base: bytes) -> bytes:
    return disable_tool_search_text(restrict_mcp_text(base, PLANNING_TOOLS))


def config_problems(raw: bytes | None) -> list[str]:
    """Why a config is NOT planning-safe; [] when it is."""
    if raw is None:
        return ["config.yaml absent"]
    try:
        config = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return ["config.yaml does not parse"]
    if not isinstance(config, dict):
        return ["config.yaml is not a mapping"]
    problems = []
    servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    entry = servers.get(MCP_SERVER) if isinstance(servers.get(MCP_SERVER), dict) else {}
    if entry.get("command") != SERVER_COMMAND or entry.get("args") != TRIAL_SERVER_ARGS or "url" in entry:
        problems.append(f"mcp_servers.{MCP_SERVER} is not this image's stdio project server")
    if entry.get("enabled", True) is not True or entry.get("lazy"):
        problems.append(f"mcp_servers.{MCP_SERVER} disabled or lazy")
    if entry.get("tools") != tools_filter(PLANNING_TOOLS):
        problems.append(f"mcp_servers.{MCP_SERVER}.tools is not exactly include {list(PLANNING_TOOLS)}")
    others = sorted(n for n, s in servers.items() if n != MCP_SERVER and not (isinstance(s, dict)
                                                                              and s.get("enabled") is False))
    if others:
        problems.append(f"other enabled MCP servers: {others}")
    search = ((config.get("tools") or {}).get("tool_search") or {}) if isinstance(config.get("tools"), dict) else {}
    if not isinstance(search, dict) or search.get("enabled") != "off":
        problems.append('tools.tool_search.enabled is not "off"')
    if config.get("hooks"):
        problems.append("hooks configured")
    plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    if plugins.get("enabled"):
        problems.append("plugins enabled")
    return problems


def _read(home: Path) -> bytes | None:
    path = home / "config.yaml"
    return path.read_bytes() if path.is_file() else None


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:  # never overwrite
        handle.write(data)
    os.chmod(path, 0o600)


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "/hermes/planning"))


def ensure_planning_home(home: Path) -> list[str]:
    if _read(home) is None:
        _write_new(home / "config.yaml", planning_config(TEMPLATE.read_bytes()))
        print(f"[PLANIFICACIÓN] configuración inicial creada en {home}/config.yaml", file=sys.stderr)
    return config_problems(_read(home))


def _model(raw: bytes | None) -> tuple[str, str]:
    config = (yaml.safe_load(raw) or {}) if raw else {}
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    return str(model.get("provider")), str(model.get("default"))


def run(args: list[str]) -> int:
    if any(a in ("-t", "--toolsets") or a.startswith("--toolsets=") for a in args):
        print("refused: the planning profile fixes --toolsets to the project's MCP server", file=sys.stderr)
        return 2
    home = _home()
    problems = ensure_planning_home(home)
    if problems:
        print("refused: HERMES_HOME is not planning-safe: " + "; ".join(problems), file=sys.stderr)
        return 2
    provider, model = _model(_read(home))
    print(f"[PLANIFICACIÓN] Hermes {VERIFIED_HERMES_COMMIT[:8]} · proveedor {provider} · modelo {model}\n"
          f"  herramientas: {', '.join(PLANNING_TOOLS)} (MCP {MCP_SERVER}); sin terminal, web, simulación ni vehículos\n"
          f"  borradores y misiones: /opt/tfg/missions/generated (anfitrión: TFG_PLANNING_STORE); sesiones: {home}\n"
          "  Ctrl+C cancela. Una finalización sin finalization.json NO está terminada: consulta `status`.",
          file=sys.stderr)
    env = {**os.environ, "HERMES_HOME": str(home)}
    os.execve(str(HERMES_BIN), [str(HERMES_BIN), *args, "--toolsets", MCP_SERVER], env)
    return 0  # not reached


def status() -> int:
    home = _home()
    raw = _read(home)
    problems = config_problems(raw)
    provider, model = _model(raw)
    print(f"Hermes home: {home} · configuración: {'PLANNING_SAFE' if not problems else 'NOT_SAFE: ' + '; '.join(problems)}")
    print(f"Proveedor/modelo configurados: {provider} / {model}")
    print(f"Credenciales del proveedor (auth.json): {'PRESENT' if (home / 'auth.json').is_file() else 'ABSENT'} "
          "(contenido nunca mostrado)")
    drafts = sorted((STORE / "drafts").glob("*/draft.json")) if (STORE / "drafts").is_dir() else []
    print(f"Almacén: {STORE} · borradores: {len(drafts)}")
    for draft in drafts:
        directory = draft.parent
        try:
            body = json.loads(draft.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"  {directory.name}: draft.json ilegible")
            continue
        print(f"  {directory.name}: mission_id {body.get('mission_id')} · vehículo {body.get('vehicle_id')}")
        for snapshot in sorted(p for p in directory.iterdir() if p.is_dir()):
            record = snapshot / "finalization.json"
            if not record.is_file():
                print(f"    finalización {snapshot.name}: INCOMPLETA (sin finalization.json; no es un resultado)")
                continue
            try:
                final = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                print(f"    finalización {snapshot.name}: finalization.json ilegible")
                continue
            validation = (final.get("validation") or {}) if isinstance(final, dict) else {}
            export = validation.get("qgc_export") or {}
            print(f"    finalización {snapshot.name}: completa · validación {validation.get('mission_status')}/"
                  f"{validation.get('execution_status')} · exportación .plan {export.get('status', 'no registrada')}"
                  + (f" ({'; '.join(export.get('reasons') or [])})" if export.get("reasons") else ""))
    return 0 if not problems else 1


def prepare_trial(home: Path) -> int:
    if _read(home) is None:
        _write_new(home / "config.yaml", TEMPLATE.read_bytes())
    link = home / "hermes-agent"
    if not link.exists():
        link.symlink_to(HERMES_AGENT)  # the capture runner checks the verified sources at <home>/hermes-agent
    print(f"trial home {home}: base config (the capture runner adds and removes the tools filter itself); "
          f"log in once with `hermes auth` using HERMES_HOME={home}")
    return 0


def prepare_test_home(home: Path, url: str) -> int:
    if home.exists() and any(home.iterdir()):
        print(f"refused: {home} is not empty", file=sys.stderr)
        return 2
    base = TEMPLATE.read_text(encoding="utf-8")
    double = base.replace("  provider: nous\n  default: poolside/laguna-s-2.1:free\n",
                          f"  provider: custom\n  base_url: {url}\n  default: {TEST_DOUBLE_MODEL}\n")
    if double == base:
        print("refused: template model block not found", file=sys.stderr)
        return 2
    header = "# TEST DOUBLE home: fake OpenAI-compatible provider, never a real model.\n"
    _write_new(home / "config.yaml", planning_config((header + double).encode("utf-8")))
    print(f"TEST DOUBLE home {home}: provider custom at {url}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command == "run":
        return run(rest)
    if command == "login" and not rest:
        # `hermes auth add` runs no agent and no tool, so it needs only the home's own provider: the trial home
        # deliberately keeps the base config (the capture runner adds the tools filter), and must be usable here.
        home = _home()
        if _read(home) is None:
            ensure_planning_home(home)
        provider, _ = _model(_read(home))
        if provider in ("None", ""):
            print(f"refused: {home}/config.yaml names no model.provider", file=sys.stderr)
            return 2
        env = {**os.environ, "HERMES_HOME": str(home)}
        os.execve(str(HERMES_BIN), [str(HERMES_BIN), "auth", "add", provider, "--no-browser"], env)
    if command == "status":
        return status()
    if command == "check":
        problems = ensure_planning_home(_home())
        print("PLANNING_SAFE" if not problems else "NOT_SAFE: " + "; ".join(problems))
        return 0 if not problems else 1
    if command == "prepare-trial" and len(rest) == 1:
        return prepare_trial(Path(rest[0]))
    if command == "prepare-test-home" and len(rest) == 2:
        return prepare_test_home(Path(rest[0]), rest[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

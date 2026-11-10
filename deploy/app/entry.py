"""Entry of the offline application image (deploy/app/Dockerfile ENTRYPOINT).

Runs what ``python3`` would run (``-m MODULE ...``, ``-c CODE ...`` or ``SCRIPT ...``) and handles a Ctrl+C that
reaches Python before the program can (typically while its modules are still loading): a short message and exit
code 130 instead of a traceback. Programs that handle KeyboardInterrupt themselves (the scenario flow keeps its
durable records and suggests --resume) keep doing so; their exit codes pass through unchanged.
"""
import os
import runpy
import sys


def main(argv: list[str]) -> int:
    sys.path[0] = os.getcwd()  # as with python3 -m / -c: imports resolve from the working directory (/opt/tfg)
    try:
        if len(argv) > 1 and argv[0] == "-m":
            sys.argv = [argv[1], *argv[2:]]
            runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        elif len(argv) > 1 and argv[0] == "-c":
            sys.argv = ["-c", *argv[2:]]
            exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__"})
        elif argv and not argv[0].startswith("-"):
            sys.argv = list(argv)
            sys.path[0] = os.path.dirname(os.path.abspath(argv[0]))
            runpy.run_path(argv[0], run_name="__main__")
        else:
            print("usage: -m MODULE [ARGS...] | -c CODE [ARGS...] | SCRIPT [ARGS...]", file=sys.stderr)
            return 2
    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl+C) before the program could handle it. Anything it had already written under "
              "/work stays as it is; check that directory before reusing it.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

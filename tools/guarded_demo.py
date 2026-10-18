"""Legacy parallel demo is disabled under the single-flight project policy.

The old shell demo arms/takes off BOTH drones. A single reservation cannot make
that a single-vehicle execution. Keep this entry point explicitly fail-closed.
"""
import argparse


def verify_child():
    return False


def run_demo():
    print("BLOCKED: the legacy two-drone demo flies both vehicles concurrently. "
          "Use an explicitly authorized single-vehicle mission executor/preflight.")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-child", action="store_true")
    args = parser.parse_args()
    return 1 if args.verify_child else run_demo()


if __name__ == "__main__":
    raise SystemExit(main())

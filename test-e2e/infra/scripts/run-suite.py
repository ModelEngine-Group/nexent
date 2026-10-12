"""Repository entrypoint; no installation, deployment or tests without explicit flags."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bootstrap":
        from bootstrap_runtime import main
        raise SystemExit(main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "onboard":
        from onboard_local import main
        raise SystemExit(main(sys.argv[2:]))
    from launch_runtime import selected_python
    try:
        runtime = selected_python(sys.argv[1:], Path(sys.executable))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
    if runtime is not None:
        raise SystemExit(subprocess.call([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]], env=os.environ.copy()))
    from suite import main
    raise SystemExit(main())

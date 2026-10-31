import re
import sys

INJECT = (
    "    rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list && \\\n"
    '    echo "deb [trusted=yes] http://host.docker.internal:18080 /" > /etc/apt/sources.list && \\\n'
)

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Inject before every "apt-get update" (multi-stage Dockerfiles have several apt layers)
    pattern = re.compile(r"( *)apt-get update")
    count = 0
    while True:
        m = pattern.search(content)
        if not m:
            break
        indent = m.group(1)
        injection = INJECT.replace("    ", indent, 2)
        content = content[: m.start()] + injection + content[m.start():]
        # skip past this update to avoid infinite loop
        content = content[m.start() + len(injection) + len("apt-get update"):]
        # need to re-search from beginning but we've consumed; simpler: track
        # Actually rebuild approach below
    break

# Simpler correct approach: process line by line
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("apt-get update"):
            indent = line[: len(line) - len(stripped)]
            out.append(indent + "rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list && \\\n")
            out.append(indent + 'echo "deb [trusted=yes] http://host.docker.internal:18080 /" > /etc/apt/sources.list && \\\n')
        # add --allow-unauthenticated to install lines right after our update
        out.append(line)
        if stripped.startswith("apt-get update"):
            pass
    content = "".join(out)
    content = content.replace(
        "apt-get install -y --no-install-recommends",
        "apt-get install -y --no-install-recommends --allow-unauthenticated",
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"patched {path}")

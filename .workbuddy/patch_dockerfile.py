import re

p = r"C:/code/nexent/deploy/images/dockerfiles/main/Dockerfile"
with open(p, encoding="utf-8") as f:
    content = f.read()

# Insert local-apt-source override right before the FIRST "apt-get update"
inject = (
    "    rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list && \\\n"
    '    echo "deb [trusted=yes] http://host.docker.internal:18080 /" > /etc/apt/sources.list && \\\n'
)
pattern = re.compile(r"( *)apt-get update")
m = pattern.search(content)
assert m, "apt-get update not found"

indent = m.group(1)
insertion = inject.replace("    ", indent, 2)
content = content[: m.start()] + insertion + content[m.start():]

# Allow unauthenticated install for the first install command after that update
content = content.replace(
    "apt-get install -y --no-install-recommends",
    "apt-get install -y --no-install-recommends --allow-unauthenticated",
    1,
)

with open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print("patched OK")

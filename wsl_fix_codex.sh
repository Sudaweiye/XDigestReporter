#!/usr/bin/env bash
set -e
mkdir -p ~/.local/bin
python3 - <<'PY'
from pathlib import Path
p = Path.home() / '.bashrc'
text = p.read_text(encoding='utf-8', errors='ignore') if p.exists() else ''
out = []
for ln in text.splitlines():
    if 'Hermes Agent ? ensure ~/.local/bin is on PATH' in ln:
        continue
    if ln.strip() == 'export PATH="$HOME/.local/bin:$PATH"':
        continue
    if 'export PATH=C:\\Users\\Lenovo/.local/bin:' in ln:
        continue
    out.append(ln)
out.append('# Hermes Agent ? ensure ~/.local/bin is on PATH')
out.append('export PATH="$HOME/.local/bin:$PATH"')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
PY
printf '%s\n' '#!/usr/bin/env bash' 'exec /home/lenovo/.hermes/node/bin/codex "$@"' > ~/.local/bin/codex
chmod +x ~/.local/bin/codex
export PATH="$HOME/.local/bin:$PATH"
which -a codex || true
~/.local/bin/codex --version

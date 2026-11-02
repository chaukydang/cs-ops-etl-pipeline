#!/bin/bash
# Copy the dashboard (app code + sample data + requirements) into a folder that can be
# pushed as its own small repository, e.g. for Streamlit Community Cloud.
#   scripts/export_demo_app.sh ../cs-ops-dashboard-demo
set -euo pipefail
dest="${1:?usage: export_demo_app.sh <destination folder>}"
here="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$dest"
cp -r "$here/app/." "$dest/"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +
cat > "$dest/README.md" <<'EOF'
# CS operations dashboard (demo)

Streamlit dashboard on synthetic sample data. It is the dashboard of the cs-ops ETL pipeline,
running in demo mode (no database).

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
EOF
echo "Exported to $dest. Entry point for Streamlit Cloud: streamlit_app.py"

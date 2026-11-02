"""Streamlit entry point for the whole repository.

On Streamlit Community Cloud the default main file is `streamlit_app.py` at the
repository root, so this repository can be added as it is. It starts the
dashboard in `app/`, which runs on the bundled sample data unless DB_HOST is set.
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "app" / "streamlit_app.py"), run_name="__main__")

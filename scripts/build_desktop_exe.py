from __future__ import annotations

from pathlib import Path
import shutil

import PyInstaller.__main__


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    spec_path = project_root / "xhs_desktop.spec"
    dist_dir = project_root / "dist"
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--clean",
            str(spec_path),
        ]
    )

    dist_dir.mkdir(parents=True, exist_ok=True)
    for filename in ["config.toml.example", "USAGE.md", "README.md"]:
        source = project_root / filename
        if source.exists():
            shutil.copy2(source, dist_dir / filename)


if __name__ == "__main__":
    main()

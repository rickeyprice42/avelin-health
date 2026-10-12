"""Package the shared collectors; never maintain a second parser implementation."""
from pathlib import Path
import shutil

def build():
    root = Path(__file__).resolve().parent
    destination = root / "extension" / "collectors"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("kuper", "fixprice", "slata", "nutrition"):
        shutil.copyfile(root / f"{name}_bookmarklet.js", destination / f"{name}_bookmarklet.js")
    return root / "extension"

if __name__ == "__main__": print(build())

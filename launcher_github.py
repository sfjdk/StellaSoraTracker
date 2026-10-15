import os

os.environ.setdefault(
    "STELLASORA_UPDATE_MANIFEST_GITHUB",
    "https://raw.githubusercontent.com/sfjdk/StellaSoraTracker/main/app_update_github.json",
)

from stellasora_toolkit.gui import main


if __name__ == "__main__":
    raise SystemExit(main())

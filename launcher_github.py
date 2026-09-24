import os

os.environ["STELLASORA_UPDATE_SOURCE"] = "github"

from stellasora_toolkit.gui import main


if __name__ == "__main__":
    raise SystemExit(main())

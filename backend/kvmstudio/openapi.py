"""Print the OpenAPI schema, used to generate the typed frontend client."""

from __future__ import annotations

import json
import sys

from .app import create_app
from .config import Config
from .libvirt_conn import LibvirtConnection


def main() -> None:
    # The connection is never opened: building the schema does not touch libvirt.
    app = create_app(Config(), LibvirtConnection("test:///default"), token="", mode="web")
    json.dump(app.openapi(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

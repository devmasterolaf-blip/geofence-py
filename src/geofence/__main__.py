"""Allow ``python -m geofence``."""

import sys

from .cli import main

sys.exit(main())

"""Central place for UI constants (sizes, fonts, colors, spacing) shared across app/ui.

resources/styles/main.qss remains the source of truth for QSS-driven styling
(colors, fonts, border-radius, padding on stylesheet-selected widgets); this
package covers values that must be set programmatically in Python.
"""

from .colors import *  # noqa: F401,F403
from .fonts import *  # noqa: F401,F403
from .sizes import *  # noqa: F401,F403
from .spacing import *  # noqa: F401,F403

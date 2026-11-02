"""Central place for UI constants (sizes, fonts, colors, spacing) shared across app/ui.

resources/styles/main.qss remains the source of truth for QSS-driven styling
(colors, fonts, border-radius, padding on stylesheet-selected widgets); this
package covers values that must be set programmatically in Python.
"""

from .colors import *
from .fonts import *
from .sizes import *
from .spacing import *

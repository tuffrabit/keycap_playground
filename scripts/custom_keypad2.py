#!/usr/bin/env python3
"""
custom_keypad.py - Generate sculpted Riskeycap-style keycaps for a custom 4x5
macro pad or gamepad.

This script builds on top of scripts/keycap.py to render individual keycaps or
an entire keypad worth of caps in one go.  It is intentionally small and easy
to edit:

* DEFAULT_LAYOUT defines the legend for each key.
* ROW_PROFILES defines the per-row sculpting (height, dish tilt, etc.).

Basic usage:

    # Render every key in DEFAULT_LAYOUT
    python3 scripts/custom_keypad.py --out ./output

    # List the keys the script knows about
    python3 scripts/custom_keypad.py --list

    # Render only a few keys by name
    python3 scripts/custom_keypad.py --out ./output R1C1 R2C3

    # Render a full set of blank (no legend) caps
    python3 scripts/custom_keypad.py --out ./blank_caps --blank

    # Force re-render (skip the "file already exists" check)
    python3 scripts/custom_keypad.py --out ./output --force

Output is .stl by default so it works with any slicer and any OpenSCAD version.
If you upgrade to OpenSCAD 2022 or newer the script will automatically enable
``--enable=fast-csg`` to speed up rendering.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from subprocess import getstatusoutput

# The existing full-keyboard scripts require colorama.  Make this script work
# even if colorama is not installed by providing harmless fallbacks.
try:
    from colorama import Fore, Back, Style
    from colorama import init as color_init
    color_init()
except ImportError:
    class _Style:
        BRIGHT = ""
        RESET_ALL = ""
    class _Fore:
        pass
    class _Back:
        pass
    Fore = _Fore()
    Back = _Back()
    Style = _Style()

# Import the Keycap helper from the same directory.
sys.path.insert(0, str(Path(__file__).parent))
from keycap import Keycap

# ---------------------------------------------------------------------------
# User-configurable settings
# ---------------------------------------------------------------------------

# Path to your OpenSCAD binary.  On Linux this is usually /usr/bin/openscad.
#OPENSCAD_PATH = Path("/usr/bin/openscad")
OPENSCAD_PATH = Path("openscad-nightly")

# Path to colorscad.sh.  Leave this pointing at a non-existent file unless you
# actually want multi-material legends rendered as a separate STL.
COLORSCAD_PATH = Path("/nonexistent/colorscad.sh")

# Standard MX key unit spacing and the gap between adjacent caps.
KEY_UNIT = 19.05
BETWEENSPACE = 0.8

# Output file type.  "stl" is the safest default; change to "3mf" if you prefer.
FILE_TYPE = "stl"

# Default 4x5 layout.  Each row is a list of key definitions.  A key definition
# is just a dict of keyword arguments; the only required key is ``name``.  Any
# Keycap attribute can be overridden here, for example:
#
#     {"name": "enter", "legends": ["Enter"], "font_sizes": [3.5],
#      "trans": [[0, 0, 0]]}
#
# Set ``homing_dot: True`` to add a tactile homing bar to a key.
DEFAULT_LAYOUT = [
    # Row 1 (top)
    [
        {"name": "R1C1", "legends": ["1"]},
        {"name": "R1C2", "legends": ["2"]},
        {"name": "R1C3", "legends": ["3"]},
        {"name": "R1C4", "legends": ["4"]},
        {"name": "R1C5", "legends": ["5"]},
    ],
    # Row 2
    [
        {"name": "R2C1", "legends": ["Q"]},
        {"name": "R2C2", "legends": ["W"]},
        {"name": "R2C3", "legends": ["E"]},
        {"name": "R2C4", "legends": ["R"]},
        {"name": "R2C5", "legends": ["T"]},
    ],
    # Row 3 (home row) - homing dots on the index-finger columns
    [
        {"name": "R3C1", "legends": ["A"], "homing_dot": True},
        {"name": "R3C2", "legends": ["S"]},
        {"name": "R3C3", "legends": ["D"]},
        {"name": "R3C4", "legends": ["F"]},
        {"name": "R3C5", "legends": ["G"], "homing_dot": True},
    ],
    # Row 4 (bottom) - same profile as row 2, rotated 180 degrees when installed
    [
        {"name": "R4C1", "legends": ["Z"]},
        {"name": "R4C2", "legends": ["X"]},
        {"name": "R4C3", "legends": ["C"]},
        {"name": "R4C4", "legends": ["V"]},
        {"name": "R4C5", "legends": ["B"]},
    ],
]

# Per-row sculpting profiles.  The keycap engine is run in "globals" mode (not
# the built-in riskeycap module) so that each row can have its own height and
# dish tilt.  Row 1 is tallest and tilted so the back is highest; row 3 is the
# shortest and flat; rows 2 and 4 share the same profile (row 4 is rotated 180
# degrees when installed on the gamepad).
#
# DISH_TILT_FLAT is enabled below, so DISH_TILT shears the whole keycap instead
# of bending it: every side (and the bottom) stays dead flat for FDM printing.
# In this mode key_height is the *maximum* height of the cap (at the back
# edge).  The values below reproduce the heights the old curved-tilt settings
# produced (14/8.8/8.2mm bent -> ~12.9/8.1/8.1mm measured); the slight bump
# past the nominal value compensates for what the spherical dish carves off
# the raised back corner.
#
# key_rotation lays the flat FRONT face of the cap on the build plate.  The
# required angle is 90 + atan(3 / (key_height + 3*tan(dish_tilt))) degrees
# (the front face's taper), so it is set per row.  Use a negative angle (e.g.
# [-102.2, 0, 0]) to print on the back face instead.
#
# You can add any Keycap attribute here per row, e.g. key_height, dish_tilt,
# dish_z, dish_depth, key_top_difference, corner_radius, etc.  Per-key settings
# in DEFAULT_LAYOUT override these row defaults.
ROW_PROFILES = {
    1: {"key_height": 12.4, "dish_tilt": 9, "dish_z": -0.4, "dish_depth": 0.4,
        "key_rotation": [102.2, 0, 0],
        "description": "tallest, positive tilt raises the back (+Y)"},
    2: {"key_height": 9.6, "dish_tilt": 6, "dish_z": -0.2, "dish_depth": 0.4,
        "key_rotation": [108.9, 0, 0],
        "description": "medium, slight back tilt"},
    3: {"key_height": 8, "dish_tilt": 0, "dish_z": 0.0, "dish_depth": 0.4,
        "key_rotation": [110.1, 0, 0],
        "description": "short, flat"},
    4: {"key_height": 8.45, "dish_tilt": 6, "dish_z": -0.2,
        "key_rotation": [108.9, 0, 0],
        "description": "same as row 2 (rotated when installed)"},
}

# ---------------------------------------------------------------------------
# Helper functions and keycap base class
# ---------------------------------------------------------------------------

def detect_openscad_args(openscad_path):
    """
    Only enable fast-csg when running OpenSCAD 2022 or newer.  Older versions
    will error out if the flag is passed.
    """
    retcode, output = getstatusoutput(f"{openscad_path} --version")
    if retcode != 0:
        print("WARNING: Could not detect OpenSCAD version; disabling fast-csg.")
        return ""
    try:
        version_str = output.split()[2]
        year = int(version_str.split(".")[0])
        if year >= 2022:
            return "--enable=fast-csg"
    except (IndexError, ValueError):
        pass
    return ""


class custom_keypad_base(Keycap):
    """
    Base keycap tuned for a sculpted, Riskeycap-style profile printed on its face.

    * 1U square caps
    * DISH_TILT_FLAT: dish_tilt shears the cap instead of bending it, so the
      front/back/side faces (and the bottom) are all dead flat; the cap is
      rotated to print on its flat FRONT face for smooth tops and strong stems
    * Wall thickness = 2.25 perimeters at 0.45 mm extrusion width
    * Uniform wall thickness for clean legends
    * Uses globals mode so per-row height and dish_tilt can be applied
    """
    def __init__(self, **kwargs):
        homing_dot = kwargs.pop("homing_dot", False)
        super().__init__(
            **kwargs,
            openscad_path=OPENSCAD_PATH,
            colorscad_path=COLORSCAD_PATH,
            output_path=Path(kwargs.get("output_path", ".")),
        )
        # Override the hard-coded fast-csg flag from Keycap.__init__ based on
        # the actually installed OpenSCAD version.
        self.openscad_args = detect_openscad_args(self.openscad_path)
        self.render = ["keycap", "stem"]
        self.file_type = FILE_TYPE
        # We use globals mode (empty profile) so that per-row key_height and
        # dish_tilt actually reach the keycap engine.  The defaults below are
        # chosen to replicate a Riskeycap-like shape.
        self.key_profile = ""
        self.key_length = KEY_UNIT - BETWEENSPACE
        self.key_width = KEY_UNIT - BETWEENSPACE
        self.key_height = 8.2
        self.key_top_difference = 6
        self.key_top_y = 0
        # Print on the flat FRONT face.  The exact angle depends on the row's
        # height+tilt so ROW_PROFILES overrides this per row.  Use a negative
        # angle (e.g. [-102.5, 0, 0]) if you'd rather print on the back face,
        # or [0, 102.5, -90]-style values to print on a side flank.
        self.key_rotation = [110.1, 0, 0]
        self.wall_thickness = 0.45 * 2.25
        self.uniform_wall_thickness = True
        self.dish_type = "sphere"
        self.dish_depth = 1.5
        self.dish_z = 0
        self.dish_thickness = 0.9
        # Flat tilt: dish_tilt is applied as a shear of the whole keycap so the
        # top keeps its tilt and height but no face is curved.  (The old
        # dish_tilt_curve bent the cap like a banana, which curved the front
        # face and left nothing flat to print on.)
        self.dish_tilt_curve = False
        self.dish_tilt_flat = True
        self.dish_corner_fn = 40
        # More layers make the tilt smoother and much more visible.  Ten is a
        # good compromise between render time and sculpting quality.
        self.polygon_layers = 10
        self.polygon_layer_rotation = 0
        self.polygon_edges = 4
        self.polygon_curve = 0
        self.corner_radius = 0.5
        self.corner_radius_curve = 0.75
        self.stem_type = "box_cherry"
        self.stem_walls_inset = 0
        self.stem_top_thickness = 0.65
        self.stem_inside_tolerance = 0.175
        self.stem_side_supports = [0, 0, 0, 0]
        self.stem_locations = [[0, 0, 0]]
        self.stem_sides_wall_thickness = 0.8
        # Single centered legend, aligned with the layer lines when side-printed.
        self.fonts = ["Gotham Rounded:style=Bold"]
        self.font_sizes = [4.5]
        self.trans = [[2.6, 0, 0]]
        self.rotation = [[0, -20, 0]]
        self.scale = [[1, 1, 3]]
        if homing_dot:
            self.homing_dot_length = 3
            self.homing_dot_width = 1
            self.homing_dot_x = 0
            self.homing_dot_y = -3
            self.homing_dot_z = -0.45
        self.postinit(**kwargs)


def build_keycaps(layout=DEFAULT_LAYOUT, row_profiles=ROW_PROFILES):
    """Turn a layout table into a list of Keycap objects."""
    keycaps = []
    for row_index, row in enumerate(layout, start=1):
        row_defaults = {
            k: v for k, v in row_profiles.get(row_index, {}).items()
            if k != "description"
        }
        for keydef in row:
            kwargs = dict(row_defaults)
            kwargs.update(keydef)
            name = kwargs.pop("name")
            keycaps.append(custom_keypad_base(name=name, **kwargs))
    return keycaps


def print_keycaps(keycaps):
    names = ", ".join(k.name for k in keycaps)
    print(Style.BRIGHT + "Available keycaps:" + Style.RESET_ALL)
    print(names)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=("Render sculpted Riskeycap-style keycaps for a custom "
                     "4x5 gamepad/macro pad."))
    parser.add_argument(
        "--out",
        default=".",
        help="Output directory for rendered files (default: current dir).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-render even if the output file already exists.")
    parser.add_argument(
        "--blank",
        action="store_true",
        help="Render all selected keycaps without legends. Use a separate --out directory if you already have legend versions there.")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available keycap names and exit.")
    parser.add_argument(
        "names",
        nargs="*",
        help="Render only these keycap names (case-insensitive).")
    args = parser.parse_args()

    keycaps = build_keycaps()

    if args.list:
        print_keycaps(keycaps)
        sys.exit(0)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    selected = keycaps
    if args.names:
        wanted = {n.lower() for n in args.names}
        selected = [k for k in keycaps if k.name.lower() in wanted]
        if not selected:
            print(f"No matching keycaps found for: {args.names}")
            sys.exit(1)

    for keycap in selected:
        if args.blank:
            keycap.legends = [""]
        keycap.output_path = out
        filepath = out / f"{keycap.name}.{keycap.file_type}"
        if not args.force and filepath.exists():
            print(f"{filepath} exists; skipping...")
            continue
        print(Style.BRIGHT + f"Rendering {filepath}..." + Style.RESET_ALL)
        retcode, output = getstatusoutput(str(keycap))
        if retcode != 0:
            print(f"ERROR rendering {keycap.name}:\n{output}")
        else:
            print(f"{filepath} rendered successfully")


if __name__ == "__main__":
    main()

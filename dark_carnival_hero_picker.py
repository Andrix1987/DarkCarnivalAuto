#!/usr/bin/env python3
# Dark Carnival hero picker (Dota 2) -- local "Practice vs Bots -> Single" only.
#
# Reads the TICKETS panel, counts each ticket (icon color + embedded digit templates),
# picks the target ticket by SELECTION_RULE, maps it to a hero, and prints the decision.
# With --run it also clicks Play x2 and selects the hero (needs per-hero grid coords).
# It stops at hero selection and does NOT play the match. LOCAL bots-only lobby.
#
# After launch you get --delay seconds (default 5) to Alt+Tab to the Dota EVENT PAGE so
# the screenshot captures the game. Run Dota in Borderless/Windowed mode.
#
# Modes: (no flag)=dry-run  --run=click  --calibrate=save calibration.png  --nopause  --delay N
# Console output is also written to picker_log.txt. Requires: mss opencv-python numpy pyautogui

import argparse
import base64
import json
import os
import sys
import threading
import time


class _Tee:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s); st.flush()
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


_IMPORT_ERROR = None
try:
    import numpy as np
    import cv2
    import mss
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.4
except ImportError as e:
    _IMPORT_ERROR = e

# OCR is OPTIONAL: used only as a fallback when a badge digit has no template yet
# (e.g. the first time a 0/4/7/9 appears). Everything works without it for the
# built-in digits and any multi-digit combination of them.
_OCR_OK = False
try:
    import pytesseract
    import shutil as _shutil
    if _shutil.which("tesseract") is None:
        for _p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                   r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break
    _OCR_OK = True
except Exception:
    pytesseract = None


class _Stopped(Exception):
    pass


STOP = threading.Event()


def isleep(seconds):
    """Sleep in small chunks; raise _Stopped as soon as STOP is set."""
    end = time.time() + seconds
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return
        if STOP.is_set():
            raise _Stopped()
        time.sleep(min(0.25, remaining))


def move_cursor(x, y):
    """Move the mouse without clicking (bypasses pyautogui failsafe)."""
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    except Exception:
        try:
            pyautogui.moveTo(x, y)
        except Exception:
            pass

# ======================================================================================
#  CONFIG  (calibrated for 1920x1080 from calibration.png)
# ======================================================================================

SCREEN_W, SCREEN_H = 1920, 1080

BTN_PLAY        = (1697, 1035)   # green "PLAY" on the event page
BTN_SELECT_HERO = (1476, 828)    # "SELECT <HERO>" on the hero grid
FOCUS_CLICK     = (700, 755)     # empty spot in the hero-select panel; click it to focus the search

# Cyan "required/selected hero" outline on the pick screen (screen 3).
OUTLINE_HSV_LOW  = (82, 120, 80)
OUTLINE_HSV_HIGH = (100, 255, 255)
HERO_GRID_REGION = (120, 200, 1320, 700)   # x1,y1,x2,y2 search area for the outline
HERO_SELECT_WAIT = 20                        # (unused now) old fixed wait after ACCEPT

# Detect the hero-select screen instead of waiting a fixed time.
PICK_PREVIEW_REGION  = (1365, 215, 1490, 470)  # right preview box: uniform on the pick screen
PICK_PREVIEW_STD_MAX = 8.0                      # preview box std below this => uniform (pick)
PICK_GRID_MEAN_MIN   = 25                       # grid region must have content (not black)
PICK_GRID_STD_MIN    = 8
PICK_MIN_WAIT        = 4                        # always wait at least this after accept
PICK_TIMEOUT         = 90                       # max seconds to wait for the grid

# "ACCEPT / PRINYAT" ready-check popup that appears after Play x2.
BTN_ACCEPT      = (957, 512)                 # center of the green ACCEPT button
ACCEPT_REGION   = (640, 360, 1280, 640)      # central area with the green ready-check glow
ACCEPT_GREEN_LOW  = (35, 70, 60)
ACCEPT_GREEN_HIGH = (90, 255, 255)
ACCEPT_MIN_FRAC = 0.08                       # >= this green fraction => popup is up
ACCEPT_TIMEOUT  = 120                        # max seconds to wait for the popup

# Pick-ready detection: the "NAUGAD" (random) button appears when the hero grid is ready.
NAUGAD_SEARCH_HALF = (788, 384, 884, 446)    # search region in the half-size (960x540) frame
NAUGAD_MATCH_MIN   = 0.6                      # template match score above this => button present
PICK_WAIT_TIMEOUT  = 150                      # max seconds to wait for NAUGAD / re-accept
NAUGAD_TEMPLATE_B64 = "iVBORw0KGgoAAAANSUhEUgAAADQAAAAkCAAAAADjxUasAAADIklEQVQ4EZXBa0iddRzA8e/v/zxn6lHntI7O83+2JJqty6ajFyOLblI5Gmul1Ro29eAsyoqKQaza2BZ7EWyUFFGCxwu6FxWOCMJR6yK0JKapeZnOtE0IWnSiBjOpfu2FB55HTwM/H7GgpKakJCIWLYySkpLKnxMiFrVXsQzOaSMWtXksg9NvxKI2j2Vw+o1ERW0uy+AMGImK2lxScKpN5zxLOQNGLBrNZan7q7rZ/vEnLOF8b8Si0VUsVhLr6wIeK2s/zSLOoBGLRlcRtPrJf94rdzPO9ZDXkNE8S4AzaMSi0RwCHmh8eZCSQWragA2HW7rxc4aMWLQwh4DPLz0/xWU7esOTFL2VVY6fO2TEooU5BDTHt59r/gvw0s7XrvvwiUb8nGEjFi1cSUBtK7fXHz8ObHs4/hU1bfi5w0Y8ZXU2AXVxiid23Nmpj/d1bBq/VNuKn/uDEU8pWElAXZwHo+9mH3H2/NYQ/qWrpg0/Z8SIpxRkExBrgbXrTzya3r65r7pTa1vxc0eMeEpBFgGxFop3dwxVhjso/XeIujh+7qgRTynIIiDWwn1fzlMZ7uDFo1AXx88ZM+IpBZkEdFZr6eg8VeF2bj0FLTH83DEjnpKfSUB5/RsXLv5OVbidnV2bXjj2KX7uuBFPyc8kKPul7KYZHgm3sea5uaMJAtwzRjwlP8xiNzw7+ebOUGvjTW+PsIh7xoin5Gew1B1Pr+H8+ydZwp0w4in56aSyy7SSgjtpxFMiGSwiSpIoQe6kEU+JpJNUkejbNjVyS9FHN6/rbvhg7+Sp4b1NF7l7Y+RVktyzRjwlkkZShTt223djz2Qd+XvPsfK2fQe5/qGBHnb1NBwiKXTWiEUjaSRVrJ0tPpGo/XW8d3PlOz/tP0D9z2Wv8NqhfQdJCk0ZsWhkBUlbEt9unS658Me9r2+8q4kD+3NjvRuG04s+e+rwHAtCPxqxaGQFSdfNza5P3PgFZaNl3yS452SRTEeu3drHNcNfsyA0bcSikRBXtLuZUtPPAnfGiEWvDrEMoRkjUTQvg2VwZ4xYRblM+R8KCD4iYlGuTBEC5D9Rm/zPoesJewAAAABJRU5ErkJggg=="

# Server-error dialog (e.g. "disconnected from server") -- its OK button is
# centered horizontally but can appear at different heights.
OK_TEMPLATE_B64 = "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"
OK_MATCH_MIN = 0.80

# Transient pop-ups handled WITHOUT leaving the flow: party invite -> Decline,
# item drop -> Accept. Templates are scaled to 1920x1080; matched multi-scale.
DECLINE_TEMPLATE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAOQAAAAsCAAAAABQh0uIAAALE0lEQVRoBd3BC5CdZWHG8f/zvt+3Z3chG5IAoYRUbhZKoBLAiAIxhjvIxRSS3TAFppWWap1ataMzUp22Mx2x2qhQGOrQi2M76lDlEgMbEcEL9xQsgTSRiwZISIDcdzd7zve+T89uNmED5rJHGGb8/fQNthG/hYyKOPBDXdZepIAQu2JAjGIQv57ZNfHrmLeQwOQ+9XQUVQSEDGKYGSYwIEZYmCYxwmIbs43YHTNCmBHirWNkyP3q7iwbEZBoMjsIDGIHIyN2MDsTe80MEW8xI0zuV3dn2QiI31xgDzI7k3hrGQO5X90dRSMKjPjNmD0QOzNvOQG5T90dRSPy2yz3qbujaETAtEDsiRHDDGJPLLB4c6V+dXcUjQiYFojRcuANjBhmEHtgBBa7YsZKQOpXd0fRCLRIJtStUCiTk2KwGWGGCWEwe01iJ8aMEGOVkdWv7o6iEWhRDsVWZQrlTJASCowwpkkCjBGY3TPBENiZMa0yyKFP3R1FIwCmBRW1Rgr7t29dbym44RAZYYwtITB7w7YCIHZiWmZAVr+6O0ISYMZIgImTTzmkDPQ99/PngqLMdsZNQmLv2BgFXscGiWE2LYh96qmFeoERZkxyKmtV+/EnT/GLGzsPblvzwH0xV22Aikas7MI5EzOhkkMgl1WsVKhybNuaCypi0NaQo0MkZwTY0S7qtQpwTI1xg46JJjHMtCL2qafGYCkDZkxiquL498zad8Uja1PRNWPGmt6HBqt2IJWDMYCNLZoKKkhlpRBywMkx5HoIqoosR6twSkQJ26FUH6JJBNltVQYxwrSg7FNPm+pRYMbGMeTquJ7OJfesKetum3L8+Wtvfq4KgMrBqMGakyAXTjErtVUyuY1GsEg1DYqmrCG4EWOloNyIJalI/TWwAqRxA6mwEduYVpR96injYBCYMQryAWecuvzbL1Cm3K7aJ6c+fOOUCYDbBuOWNV37rV+XNWnyqy8pq2OqYj2s2zIQcp58WGPt2kYYrB04fvVGqdh//PpXxo/fvKEKyu1T+1+ZeEBfCUReXTPpgNVra5hRzJi19aknKokWFK5OmFfetyilWBWxyrOv6P/EnCPkYFXpV/f+3rtWPrL60NMOevB+V53HzyyU9OwtqZpwzu8cUN+08u6NVXnBkY/8z0DU7BN+8vCME5c8mGGf6e9++sdnv7MKwoUfu+e973poyWBVmm1Ma+rqCaYlIXvW5StvXZarWC+Ruv5J/zD1kJze27FkS3r+iTNnLl/4/LnnPr9oWZUmnnfqCy9MPOaZf6Rz/gmrHi/eNfHh29e2XzX9zvv6Upx/2q13nXP+4u8qtE0//8Al//m+g7e2fyD/IJfPPDpnVm/vYFVkxDDTipTVI4tWOOuMK578xtqQwNSsBe3f+lm7q2smffmluCX94SnLb4tzjlzcO5A19eJDFj9+9OXPfKX2gQufu2NF52EXTbr1p/mKk2776UDO899/a+/5Zy++Q+Vx5x1ef/yf9+2sj/v79NeD5UD/vNmLf7AJiGKYaUVldYMEmDEKzrP+6BfffL4tp7KKuHNB/FZvbvMXD7zmxSLlS09bvnDaOc/fuayucNS8xr+tmfbxFddO/sw+C5apNnjyZetuXHXVu+++d7Py/Pffctf5Z/Xe3nnUuQetPfSxr0a3dy6orh4o4dLTH/u/Vza/tDWKbUwLktUNYogRwwwCjNjGiCYjhhkBBfVTLnvpe0vLVJWO9dp+X8p/+2Ij6NpJf/fLIvRfevqry48Yf9f9fYgTrnzuujztr5Z+6cjPbfhYYYXwha7Prrpqxppn6iEcM/WbC+ect+i2aRdPfmjtvIf/JaZa51eqP6sKmHPWls2NzWvuX5XBpkXZmgcSYHaw2C0jmsSx3R1395JTEC5PvXL9p2JVsWDi36xUbHTPZOu41bc+EZza3z/ngf/gD/5y6XVHf/ylT5e5bPhLEz+75uoTNqzLQQdM/K9Fc85atOzidz76/QM/8vDNgq7rG1fRdOkZv3w2Hz3l0TvWgG3E2BgQtuYBAsxYBU04+/Rl314ZnKnaxn/qHfd9nbJiwaTPrMlSz/tefurQg3/04/5GescHD/3eg8VxH132lamfX/fJHNo2Tb5m/OdX/cXx9y4dwGeddMuiC858yscuvevZ4z/6+A1A1/XVh2mae/rCHw0cd8l+N/0v2LTIaC4gwIxRDDkdc/l+D9z5ihL5kFnnvHzTCmqVF0y65gVC6j7tqduP+uDL310ay/d86MV/Xdc57U9XXHvgZyZ8/VFnn3PRK19e/+cn/vd9fSFdeeZ3Fl50YSOv6F3BsR974mtA1/XVhwF3z15478YJHzn0hsdENq2S5tIaI9K4084uH16+YaA2edrJL/feo0Kp+uoBn3tWbY1LZj15hz50zOLert+fPuXu29Vxwh8v/8K+77tk3fdfilPOb7/tJ31Xz7hz8YYyXD77loUXzGmsWLQsFcd87LEbMV03NP7EDu6ZveTxrYfP7P/35WBaFjSXIUaYsTCgvN+Mkw4ZXNvfeXB48Wc/Boqtuu6gTz9ThjB35rKFz5114Su3dc6LDy1e7c6ZPU9+ta9j3nRWxyM2P3TnFl/17t4frle8YtZ3Fl485+mFS8jFsZ/4+dcw+95UXeGQ4mWzt6yrdW164KevYskgM3aKmgsWZqzsQCqtw07cv6usr1/57C8yUG7eZ96Eb69uEycfteqxl6dOn7CU96x6dGWgNm3G84sHVc48dN+6Vzw4OFicffgDT29N4ZSjHnr8pJN+/qirIk354K96MR1XppsdUjjlaMUwsPzJTbYlWqSoSzEgbMZImCqUivvXBtYOhjKDcg5VmZQKQ1vKJNRZbrIDObTVG7XQP67e0Uh2rU4skxuxTBU5Fg1HK+WOqjJqa1DLVZka0SrKAQeDQDYtCKUuJYGEGSNZqhzJjSjnUBUlkOvtdSmXOEJDwc6SisHclhUrMG1bHasyOKMiYRcpE6JTDNk5dVaVcogVJSHJKTqTimDENmY0AUbslkrNzQkkzOuINzKIHSwsY4MQCDLbSCAySopVANFkwIFGMdjZsCAYmSZhOcgGZyGxnSWajMwwM1oAbIkm0yRGMU2CUnNzBQHM64g3MmIHuwgJMobojALUy5CToRCWsI1QUjRgwIRMDhio2osBAoQqxEoEHFKockwlI6q2jBhmwOY1AgQYMcSA2IkBQal5qTKBNxLbmV9HkSoVYINTLEIC2rZWsaDJRpItZ1HkFAHTlKNzUY8YYSSwA1lYwS6qEOtFBgzEgX0aiB1sXiNAvMY0idEMCErNa2Qj3khsZ3YhKGMMCplhKRQpg0CoKQdXhZMCTabJUqoNFAYpOwjjYMtAUFJ2zBIYKPr3rVuA2Ma8RuyBMMPa1b2lME3idUST2TUDAjNKlkWTkSAEO1uAMKNY7CWLFgnMkDxO8zcVNiBaZUCAAQMCDDJB2Ea8raouXbaxsGkSrTFNAgwYEGC2kXnbVV2av7GwEUa0xDSJIWaYwIAZJt405nXEXqi6NH9jYfObMCDMdmKIabIl3m5Vl3o2FJjdM01iFwwIyEAAxBBj0yTxprHZWWAvVF3q2VDa7JppErthQIABAWKIMWAQQ8SbwAbEa8ReqLrUvSlidsk0id0xIMCAADHEGDCIIeJNYAPiNWIvVON1YaoyYhQhBbZLNiCECEC2DUIIiaYMEmB2ZkYRGLEbFqMZEKMYxCgGxJ658buabucAmO0kQIwwWYAA0WRshGgSQwwIyCD2loUBsStmmBhhthEjzDAxwsKA2IlRefD/A/VEZ4FGNphkAAAAAElFTkSuQmCC"
DROP_TEMPLATE_B64 = "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"
POPUP_MATCH_MIN = 0.62
POPUP_SCALES = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15)

# End-game -> back-to-event navigation (after hero select).
CONTINUE_BTN     = (957, 908)                # "CONTINUE / PRODOLZHIT" on the end screen
DOTA_LOGO        = (285, 30)                 # Dota logo top-left (back to dashboard)
BTN_OPEN_EVENT   = (952, 926)                # "OPEN EVENT" on the dashboard
POSTGAME_WAIT    = 300                       # wait this long after hero-select before checking
ENDGAME_STRIP    = (300, 1010, 1620, 1055)   # bottom strip that turns black at match end
ENDGAME_DARK_MAX = 35                        # strip mean brightness below this => black bar
ENDGAME_TIMEOUT  = 1200                      # max seconds to poll for the black bar

# After hero select: verify the match actually started (strategy / 600-gold screen).
# Gold "600" panel on the strategy/planning screen: yellow pixels there => match started.
GOLD_REGION   = (846, 576, 962, 599)
GOLD_HSV_LOW  = (18, 90, 150)
GOLD_HSV_HIGH = (38, 255, 255)
GOLD_MIN_FRAC = 0.05
ARROW_BACK      = (30, 29)                     # very top-left icon (near the corner)
DISCONNECT_BTN  = (1697, 974)                 # "DISCONNECT" widget (event page, bottom-right)
LEAVE_YES       = (855, 597)                  # "YES, LEAVE THE GAME" dialog button

# TICKETS panel grid (icon centers), left-to-right, top-to-bottom.
TICKET_GRID = dict(x0=73, y0=383, dx=49, dy=60, cols=4)
BADGE_DY = 24                    # number badge is this many px below the icon center

# Ticket order -> hero. Cells 0..10 count; the last two panel tickets are ignored.
# pick_xy = hero portrait coord in the pick grid (fill in later for --run).
TICKETS = [
    dict(cell=0,  hero="Wisp",                  pick_xy=None),
    dict(cell=1,  hero="Rubick",              pick_xy=None),
    dict(cell=2,  hero="Oracle",              pick_xy=None),
    dict(cell=3,  hero="Doom",                pick_xy=None),
    dict(cell=4,  hero="Wraith King",         pick_xy=None),
    dict(cell=5,  hero="Jakiro",              pick_xy=None),
    dict(cell=6,  hero="Sven",                pick_xy=None),
    dict(cell=7,  hero="Abaddon",             pick_xy=None),
    dict(cell=8,  hero="Keeper of the Light", pick_xy=None),
    dict(cell=9,  hero="Chaos Knight",        pick_xy=None),
    dict(cell=10, hero="Muerta",              pick_xy=None),
]

# Rule among tickets that HAVE a count: "max_count" | "min_count" | "first_in_order"
SELECTION_RULE = "min_count"

# Embedded digit templates (18x24 bitmaps) for reading the badge numbers -- no OCR needed.
DIGIT_TEMPLATES_RAW = {
    "1": "000000111111111111000000111111111111000000111111111111111111000000111111111111000000111111111111000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111000000000000111111",
    "2": "111111111111111000111111111111111000111111111111111000000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111000000000000001111000000000000001111000000000001111111000000000001111111000000000001111111000000011111110000000000011111110000000000011111110000000111111110000000000111111110000000000111111110000000000111111111111111111111111111111111111111111111111111111",
    "3": "111111111111111000111111111111111000111111111111111000000000000001111000000000000001111000000000000001111000000000000001111000000000000001111000000000000001111000000011111110000000000011111110000000000011111110000000000000001111111000000000001111111000000000001111111000000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111111111111111111000111111111111111000111111111111111000",
    "5": "111111111111111111111111111111111111111111111111111111111111110000000000111111110000000000111111110000000000111111110000000000111111110000000000111111110000000000111111111111111000111111111111111000111111111111111000000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111000000000001111111111111111111111000111111111111111000111111111111111000",
    "6": "000000000111111000000000000111111000000000000111111000000000111000000000000000111000000000000000111000000000000111111000000000000111111000000000000111111000000000000111111111111000000111111111111000000111111111111000111111000000111111111111000000111111111111000000111111111111000000000111111111000000000111111111000000000111000111000000111111000111000000111111000111000000111111000111111111111000000111111111111000000111111111111000",
    "8": "111111111111111000111111111111111000111111111111111000111100000001111111111100000001111111111100000001111111111100000001111111111100000001111111111100000001111111000011111111111000000011111111111000000011111111111000111111110001111111111111110001111111111111110001111111111100000000000111111100000000000111111100000000000111111100000001111111111100000001111111111100000001111111111111111111111000111111111111111000111111111111111000",
    "9": "000111111111111000000111111111111000000111111111111000111111000000111111111111000000111111111111000000111111111111000000000111111111000000000111111111000000000111000111111000111111000111111000111111000111111000111111000000111111111111000000111111111111000000111111111111000000000000111000000000000000111000000000000000111000000000000111000000000000000111000000000000000111000000000111111000000000000111111000000000000111111000000000",
}
DIGIT_MIN_WHITE = 12       # (kept for compatibility)
SAT_PRESENT_MIN = 108      # icon mean-saturation >= this => colored (ticket present)
DIGIT_MAX_DIST = 0.14      # template match worse than this => try OCR / unknown
DEFAULT_DELAY = 5.0

# Per-digit segmentation: a real digit stroke is a tall-enough, big-enough blob.
# Reading one glyph at a time handles MULTI-DIGIT counts (10, 12, 25 ...) and
# ignores stray specks / hero-art bleeding into the badge box.
DIGIT_MIN_AREA   = 6
DIGIT_MIN_HEIGHT = 7
BADGE_BOX = (-14, -12, 15, 11)   # dx1,dy1,dx2,dy2 around (cx, cy+BADGE_DY)
LEARNED_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "learned_digits.json")

# Diagnostic files (log, debug captures, calibration) go into a misc subfolder
# ("\u043f\u0440\u043e\u0447\u0435\u0435" = "prochee") so the main folder holds only the program.
MISC_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "\u043f\u0440\u043e\u0447\u0435\u0435")


def _misc_path(name):
    try:
        os.makedirs(MISC_DIR, exist_ok=True)
        return os.path.join(MISC_DIR, name)
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

# ======================================================================================
#  ENGINE
# ======================================================================================


def _str_to_tpl(s):
    return np.array([1 if ch == "1" else 0 for ch in s], dtype=np.uint8).reshape(24, 18)


def _load_learned():
    try:
        with open(LEARNED_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): v for k, v in data.items()
                if isinstance(v, str) and len(v) == 432}
    except Exception:
        return {}


def _save_learned(learned):
    try:
        with open(LEARNED_PATH, "w", encoding="utf-8") as fh:
            json.dump(learned, fh)
    except Exception:
        pass


def _build_templates():
    out = {}
    for d, s in DIGIT_TEMPLATES_RAW.items():
        out[d] = _str_to_tpl(s)
    for d, s in _load_learned().items():
        if d not in out:
            out[d] = _str_to_tpl(s)
    return out


_TPL = None


def grab_screen():
    with mss.mss() as sct:
        img = np.array(sct.grab(sct.monitors[1]))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def save_png(path, img):
    """Write a PNG even when the path contains non-ASCII chars (e.g. a folder under
    "Документы"). cv2.imwrite fails silently on such paths on Windows, so we encode
    in memory and write the bytes with Python's Unicode-safe open()."""
    try:
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            return False
        with open(path, "wb") as fh:
            fh.write(buf.tobytes())
        return True
    except Exception:
        return False


def countdown_to_capture(delay):
    if not delay or delay <= 0:
        return
    print("[i] Alt+Tab to the Dota EVENT PAGE now (tickets panel visible).")
    for i in range(int(round(delay)), 0, -1):
        print("    capturing screen in %d..." % i)
        time.sleep(1)


def cell_center(idx):
    g = TICKET_GRID
    r, c = divmod(idx, g["cols"])
    return (g["x0"] + c * g["dx"], g["y0"] + r * g["dy"])


def _digit_glyphs(img, cx, cy):
    """Segment the badge into individual digit glyphs, left-to-right (18x24 binary
    each); [] if empty. Per-digit reading handles MULTI-DIGIT counts (10, 12, 25 ...)."""
    dx1, dy1, dx2, dy2 = BADGE_BOX
    reg = img[cy + BADGE_DY + dy1:cy + BADGE_DY + dy2, cx + dx1:cx + dx2]
    if reg.size == 0:
        return []
    gray = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    blobs = []
    for j in range(1, n):
        if int(stats[j, cv2.CC_STAT_AREA]) < DIGIT_MIN_AREA:
            continue
        if int(stats[j, cv2.CC_STAT_HEIGHT]) < DIGIT_MIN_HEIGHT:
            continue
        blobs.append((int(stats[j, cv2.CC_STAT_LEFT]), j))
    blobs.sort()
    glyphs = []
    for _, j in blobs:
        mask = np.where(lbl == j, np.uint8(255), np.uint8(0))
        ys, xs = np.where(mask > 0)
        g = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        g = cv2.resize(g, (18, 24), interpolation=cv2.INTER_NEAREST)
        glyphs.append((g // 255).astype(np.uint8))
    return glyphs


def icon_saturation(img, cx, cy):
    patch = img[cy - 12:cy + 12, cx - 12:cx + 12]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


def _match_digit(gl):
    best, best_dist = None, 1e9
    for d, t in _TPL.items():
        dist = float(np.mean(np.abs(gl.astype(int) - t.astype(int))))
        if dist < best_dist:
            best_dist, best = dist, d
    return best, best_dist


def _ocr_digit(gl):
    """Fallback OCR for a single glyph. Uses the LSTM engine (--oem 1) across several
    page-seg modes and returns the majority digit only if at least two modes agree
    (so a shaky read never silently becomes a wrong, auto-learned digit)."""
    if not _OCR_OK:
        return None
    try:
        big = cv2.resize(gl * 255, (180, 240), interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=0)
        inv = 255 - big
        votes = []
        for psm in (8, 13, 10, 7, 6):
            txt = pytesseract.image_to_string(
                inv, config="--psm %d --oem 1 -c tessedit_char_whitelist=0123456789" % psm)
            ds = "".join(ch for ch in txt if ch.isdigit())
            if ds:
                votes.append(ds[0])
        if not votes:
            return None
        best = max(set(votes), key=votes.count)
        return best if votes.count(best) >= 2 else None
    except Exception:
        return None


def read_count(img, cx, cy):
    """Ticket count. 0 if absent (grey icon / empty badge). Each digit is read by
    exact template match first, with OCR fallback for any digit we have no template
    for -- auto-saved so it is exact next time. None only if a COLORED ticket shows
    a digit we cannot read at all."""
    glyphs = _digit_glyphs(img, cx, cy)
    if not glyphs:
        return 0
    present = icon_saturation(img, cx, cy) >= SAT_PRESENT_MIN
    digits = ""
    learned = None
    for gl in glyphs:
        d, dist = _match_digit(gl)
        if dist <= DIGIT_MAX_DIST:
            digits += d
            continue
        if not present:
            continue
        od = _ocr_digit(gl)
        if od is None:
            return None
        digits += od
        if od not in _TPL:
            if learned is None:
                learned = _load_learned()
            _TPL[od] = gl.copy()
            learned[od] = "".join(str(int(v)) for v in gl.flatten())
    if learned is not None:
        _save_learned(learned)
    if not digits:
        return 0 if not present else None
    return int(digits)


def read_all(img):
    rows = []
    for t in TICKETS:
        cx, cy = cell_center(t["cell"])
        rows.append({**t, "xy": (cx, cy), "count": read_count(img, cx, cy)})
    return rows


def choose(rows):
    counted = [r for r in rows if r["count"] is not None]
    if not counted:
        return None
    if SELECTION_RULE == "max_count":
        return max(counted, key=lambda r: r["count"])
    if SELECTION_RULE == "min_count":
        return min(counted, key=lambda r: r["count"])
    return counted[0]   # first_in_order


def click(xy, label=""):
    print("    click", xy, " ", label)
    pyautogui.moveTo(xy[0], xy[1], duration=0.25)
    pyautogui.click()


def find_highlighted_hero(img):
    """Find the cyan-outlined hero on the pick screen. Returns ((x,y), n_pixels) or (None, n)."""
    x1, y1, x2, y2 = HERO_GRID_REGION
    sub = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(OUTLINE_HSV_LOW), np.array(OUTLINE_HSV_HIGH))
    ys, xs = np.where(mask > 0)
    n = int(len(xs))
    if n < 50:
        return None, n
    cx = int(np.median(xs)) + x1
    cy = int(np.median(ys)) + y1
    return (cx, cy), n


def accept_present(img):
    x1, y1, x2, y2 = ACCEPT_REGION
    sub = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(ACCEPT_GREEN_LOW), np.array(ACCEPT_GREEN_HIGH))
    return float((mask > 0).mean())


def wait_and_accept():
    print("    waiting for the ACCEPT (PRINYAT) popup (no timeout -- waits as long as needed)...")
    while True:
        if STOP.is_set():
            raise _Stopped()
        img = grab_screen()
        check_error_dialog(img)
        dismiss_popups(img)
        frac = accept_present(img)
        if frac >= ACCEPT_MIN_FRAC:
            print("    ACCEPT popup detected (green=%.3f) -> clicking PRINYAT" % frac)
            try:
                save_png(_misc_path("accept_capture.png"), img)
            except Exception:
                pass
            click(BTN_ACCEPT, "accept")
            time.sleep(1.0)
            return True
        time.sleep(1)


def post_game_and_return():
    """After hero select: wait out the match, detect the end screen by the black bottom
    bar, click CONTINUE, then go back to the event page via the Dota logo."""
    print("[post] waiting %ds before looking for the end screen..." % POSTGAME_WAIT)
    isleep(POSTGAME_WAIT)
    print("[post] polling for the black end-game bar (no timeout -- waits as long as needed)...")
    x1, y1, x2, y2 = ENDGAME_STRIP
    while True:
        if STOP.is_set():
            raise _Stopped()
        img = grab_screen()
        check_error_dialog(img)
        dismiss_popups(img)
        strip = img[y1:y2, x1:x2]
        bright = float(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).mean()) if strip.size else 255.0
        if bright < ENDGAME_DARK_MAX:
            print("[post] black bar detected (brightness=%.1f)." % bright)
            break
        time.sleep(2)
    print("[post] waiting 15s, then CONTINUE...")
    isleep(15)
    click(CONTINUE_BTN, "continue")
    isleep(10)
    _between_steps()
    click(DOTA_LOGO, "dota logo")
    time.sleep(2)
    _between_steps()
    click(BTN_OPEN_EVENT, "open event")
    print("[post] back on the event page.")


def pick_screen_present(img):
    """True when the hero-select grid is up: right preview box is uniform AND the grid
    region has content (rules out the event page and a black loading screen)."""
    px1, py1, px2, py2 = PICK_PREVIEW_REGION
    pv = cv2.cvtColor(img[py1:py2, px1:px2], cv2.COLOR_BGR2GRAY)
    if pv.size == 0 or float(pv.std()) >= PICK_PREVIEW_STD_MAX:
        return False
    gx1, gy1, gx2, gy2 = HERO_GRID_REGION
    gg = cv2.cvtColor(img[gy1:gy2, gx1:gx2], cv2.COLOR_BGR2GRAY)
    return float(gg.mean()) > PICK_GRID_MEAN_MIN and float(gg.std()) > PICK_GRID_STD_MIN


def wait_for_pick_screen():
    print("    waiting for the hero grid to appear (up to %ds)..." % PICK_TIMEOUT)
    time.sleep(PICK_MIN_WAIT)
    t0 = time.time()
    while time.time() - t0 < PICK_TIMEOUT:
        if pick_screen_present(grab_screen()):
            print("    hero grid detected.")
            time.sleep(0.5)
            return True
        time.sleep(1)
    print("[!] hero grid not detected within %ds; proceeding anyway." % PICK_TIMEOUT)
    return False


_NAUGAD_TPL = None


def _naugad_tpl():
    global _NAUGAD_TPL
    if _NAUGAD_TPL is None:
        arr = np.frombuffer(base64.b64decode(NAUGAD_TEMPLATE_B64), np.uint8)
        _NAUGAD_TPL = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return _NAUGAD_TPL


def naugad_present(img):
    if img.shape[1] == 1920:
        img = cv2.resize(img, (960, 540))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x1, y1, x2, y2 = NAUGAD_SEARCH_HALF
    reg = g[y1:y2, x1:x2]
    tpl = _naugad_tpl()
    if reg.shape[0] < tpl.shape[0] or reg.shape[1] < tpl.shape[1]:
        return False
    res = cv2.matchTemplate(reg, tpl, cv2.TM_CCOEFF_NORMED)
    return float(res.max()) >= NAUGAD_MATCH_MIN


_OK_TPL = None


def _ok_tpl():
    global _OK_TPL
    if _OK_TPL is None:
        arr = np.frombuffer(base64.b64decode(OK_TEMPLATE_B64), np.uint8)
        _OK_TPL = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return _OK_TPL


class _ErrorDialog(Exception):
    pass


def error_ok_button(img):
    """If the server-error dialog is up, return (x, y) of its OK button, else None.
    The dialog is centered horizontally but can appear at different heights, so we
    template-match down the central vertical strip -- the button is found at any Y."""
    tpl = _ok_tpl()
    th, tw = tpl.shape
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    cx = w // 2
    x1 = max(0, cx - tw // 2 - 60)
    x2 = min(w, cx + tw // 2 + 60)
    strip = g[:, x1:x2]
    if strip.shape[0] < th or strip.shape[1] < tw:
        return None
    res = cv2.matchTemplate(strip, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, mloc = cv2.minMaxLoc(res)
    if mx < OK_MATCH_MIN:
        return None
    return (x1 + mloc[0] + tw // 2, mloc[1] + th // 2)


def check_error_dialog(img):
    """If the error dialog's OK button is on screen (at ANY stage), click it and raise
    _ErrorDialog so the caller aborts; the loop then leaves the game and restarts."""
    loc = error_ok_button(img)
    if loc is not None:
        print("[!] Server-error dialog detected at %s -> clicking OK, then leaving/restarting." % (loc,))
        click(loc, "error OK")
        time.sleep(1.5)
        raise _ErrorDialog()


_DECLINE_TPL = None
_DROP_TPL = None


def _decline_tpl():
    global _DECLINE_TPL
    if _DECLINE_TPL is None:
        _DECLINE_TPL = cv2.imdecode(
            np.frombuffer(base64.b64decode(DECLINE_TEMPLATE_B64), np.uint8), cv2.IMREAD_GRAYSCALE)
    return _DECLINE_TPL


def _drop_tpl():
    global _DROP_TPL
    if _DROP_TPL is None:
        _DROP_TPL = cv2.imdecode(
            np.frombuffer(base64.b64decode(DROP_TEMPLATE_B64), np.uint8), cv2.IMREAD_GRAYSCALE)
    return _DROP_TPL


def _match_button(img, tpl):
    """Multi-scale template match of a button in the central area -> (score, (x, y))."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    cx = w // 2
    x1, y1, x2, y2 = max(0, cx - 360), 150, min(w, cx + 360), 960
    sub = g[y1:y2, x1:x2]
    best = (0.0, None)
    for sc in POPUP_SCALES:
        t = cv2.resize(tpl, (max(1, int(tpl.shape[1] * sc)), max(1, int(tpl.shape[0] * sc))))
        if sub.shape[0] < t.shape[0] or sub.shape[1] < t.shape[1]:
            continue
        res = cv2.matchTemplate(sub, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, (x1 + ml[0] + t.shape[1] // 2, y1 + ml[1] + t.shape[0] // 2))
    return best


def party_invite_decline(img):
    """Return the Decline-button (x, y) if a party invite is up, else None."""
    score, loc = _match_button(img, _decline_tpl())
    return loc if score >= POPUP_MATCH_MIN else None


def drop_accept(img):
    """Return the Accept-button (x, y) if an item-drop window is up, else None."""
    score, loc = _match_button(img, _drop_tpl())
    return loc if score >= POPUP_MATCH_MIN else None


def dismiss_popups(img):
    """Close transient pop-ups on this frame: party invite -> Decline, item drop ->
    Accept. Does NOT abort the current step; returns True if it clicked something."""
    loc = party_invite_decline(img)
    if loc is not None:
        print("[popup] party invite -> Decline at %s" % (loc,))
        click(loc, "decline party invite")
        time.sleep(1.0)
        return True
    loc = drop_accept(img)
    if loc is not None:
        print("[popup] item drop -> Accept at %s" % (loc,))
        click(loc, "accept drop")
        time.sleep(1.0)
        return True
    return False


def _between_steps():
    """Run between two sequential actions: handle the server-error dialog (which leaves
    and restarts) and clear any transient pop-ups (invite/drop), so the NEXT action
    lands correctly and the current step resumes where it left off."""
    for _ in range(4):
        img = grab_screen()
        check_error_dialog(img)          # may raise _ErrorDialog
        if not dismiss_popups(img):
            break
        time.sleep(0.4)


def wait_pick_or_reaccept():
    """After the first ACCEPT: wait until the NAUGAD button shows (pick screen ready).
    If the ACCEPT popup re-appears (re-queue), click it again and keep waiting."""
    print("    after accept: waiting for NAUGAD (pick ready) or a re-ACCEPT (up to %ds)..." % PICK_WAIT_TIMEOUT)
    t0 = time.time()
    while time.time() - t0 < PICK_WAIT_TIMEOUT:
        if STOP.is_set():
            raise _Stopped()
        img = grab_screen()
        check_error_dialog(img)
        dismiss_popups(img)
        if naugad_present(img):
            print("    NAUGAD detected -> hero grid is ready.")
            time.sleep(0.5)
            return True
        if accept_present(img) >= ACCEPT_MIN_FRAC:
            print("    ACCEPT popup re-appeared -> clicking it again.")
            click(BTN_ACCEPT, "re-accept")
            time.sleep(2)
        time.sleep(1)
    print("[!] Neither NAUGAD nor re-ACCEPT within timeout; proceeding anyway.")
    return False


def focus_dota_window():
    """Force the Dota 2 window to the foreground (Windows) so typed keys reach it.
    Uses AttachThreadInput to bypass the foreground-lock, like a real user click."""
    try:
        import ctypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        hwnd = u.FindWindowW(None, "Dota 2")
        if not hwnd:
            print("    [focus] Dota 2 window not found by title.")
            return False
        fg = u.GetForegroundWindow()
        cur = k.GetCurrentThreadId()
        fg_thr = u.GetWindowThreadProcessId(fg, None)
        tgt_thr = u.GetWindowThreadProcessId(hwnd, None)
        for t in {fg_thr, tgt_thr}:
            if t:
                u.AttachThreadInput(cur, t, True)
        u.ShowWindow(hwnd, 9)          # SW_RESTORE
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetActiveWindow(hwnd)
        u.SetFocus(hwnd)
        for t in {fg_thr, tgt_thr}:
            if t:
                u.AttachThreadInput(cur, t, False)
        return True
    except Exception as e:
        print("    [focus] could not activate Dota window: %s" % e)
        return False


# --- layout-independent text input (SendInput with KEYEVENTF_UNICODE) ---
import ctypes as _ct
_PUL = _ct.POINTER(_ct.c_ulong)


class _KBD(_ct.Structure):
    _fields_ = [("wVk", _ct.c_ushort), ("wScan", _ct.c_ushort),
                ("dwFlags", _ct.c_ulong), ("time", _ct.c_ulong), ("dwExtraInfo", _PUL)]


class _MOU(_ct.Structure):
    _fields_ = [("dx", _ct.c_long), ("dy", _ct.c_long), ("mouseData", _ct.c_ulong),
                ("dwFlags", _ct.c_ulong), ("time", _ct.c_ulong), ("dwExtraInfo", _PUL)]


class _HW(_ct.Structure):
    _fields_ = [("uMsg", _ct.c_ulong), ("wParamL", _ct.c_short), ("wParamH", _ct.c_ushort)]


class _II(_ct.Union):
    _fields_ = [("ki", _KBD), ("mi", _MOU), ("hi", _HW)]


class _INPUT(_ct.Structure):
    _fields_ = [("type", _ct.c_ulong), ("ii", _II)]


def type_text_unicode(text, delay=0.06):
    """Type text as Unicode via SendInput -- independent of the keyboard layout."""
    for ch in text:
        extra = _ct.c_ulong(0)
        for up in (0, 0x0002):                      # key down, then key up
            ii = _II()
            ii.ki = _KBD(0, ord(ch), 0x0004 | up, 0, _ct.pointer(extra))  # KEYEVENTF_UNICODE
            inp = _INPUT(1, ii)
            _ct.windll.user32.SendInput(1, _ct.byref(inp), _ct.sizeof(inp))
        time.sleep(delay)


def strategy_screen_present(img):
    """True if the strategy/planning screen is up -- detects the yellow gold ("600") panel."""
    x1, y1, x2, y2 = GOLD_REGION
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    frac = float((cv2.inRange(hsv, np.array(GOLD_HSV_LOW), np.array(GOLD_HSV_HIGH)) > 0).mean())
    print("[check] gold-panel yellow fraction=%.3f (threshold %.2f)" % (frac, GOLD_MIN_FRAC))
    return frac > GOLD_MIN_FRAC


def recover_leave_game():
    """Match did not start: back arrow -> Disconnect -> (5s) -> Disconnect -> Yes, leave."""
    click(ARROW_BACK, "back arrow")
    time.sleep(1.0)
    click(DISCONNECT_BTN, "disconnect")
    isleep(5)
    click(DISCONNECT_BTN, "leave (open confirm)")
    time.sleep(1.0)
    click(LEAVE_YES, "yes, leave")
    isleep(6)                                   # let the dashboard load
    click(DOTA_LOGO, "dota logo")               # make sure we are on the dashboard
    time.sleep(2)
    click(BTN_OPEN_EVENT, "open event")         # return to the event page for the next cycle
    print("[recover] left the game and returned to the event page; the cycle will restart.")


def recover_after_error():
    """After the server-error dialog (OK already clicked): just leave the game, go to
    the dashboard via the Dota logo, then reopen the event page. This is the SHORT
    tail of recover_leave_game -- the server already disconnected us, so the full
    back-arrow / confirm sequence is not needed."""
    click(DISCONNECT_BTN, "disconnect")
    isleep(6)                                   # let the dashboard load
    click(DOTA_LOGO, "dota logo")               # go to the dashboard
    time.sleep(2)
    click(BTN_OPEN_EVENT, "open event")         # back to the event page for the next cycle
    print("[recover] dismissed the error and returned to the event page.")


def do_clicks(target):
    print("[run] starting in 3s (mouse to top-left corner = cancel)...")
    time.sleep(3)
    click(BTN_PLAY, "play 1"); time.sleep(0.6)
    click(BTN_PLAY, "play 2")
    wait_and_accept()
    wait_pick_or_reaccept()

    # Type the hero name into the in-game hero search: this greys out the others and
    # puts the cyan outline on the matching hero.
    name = target["hero"]
    # bring Dota to the foreground, then type as Unicode (layout-independent) --
    # otherwise the keys go to the wrong window or fail on a non-Latin layout
    move_cursor(1912, 1070)   # park cursor off the grid FIRST (so it never covers the outline)
    time.sleep(0.3)
    focus_dota_window()
    time.sleep(0.6)
    print("[HERO] typing hero name into the search: %s" % name)
    type_text_unicode(name)
    time.sleep(1.2)

    img = grab_screen()
    check_error_dialog(img)
    dismiss_popups(img)
    try:
        save_png(_misc_path("pick_capture.png"), img)
    except Exception:
        pass

    loc, n = find_highlighted_hero(img)
    print("    cyan outline pixels: %d" % n)
    if loc is None:
        print("[!] No highlighted hero found after typing '%s' -> leaving the game "
              "and restarting the cycle (see the misc folder / pick_capture.png)." % name)
        recover_leave_game()
        return
    print("    clicking highlighted hero '%s' at %s" % (name, loc))
    click(loc, "highlighted hero"); time.sleep(0.5)
    click(BTN_SELECT_HERO, "select")
    print("[done] selected %s." % name)
    isleep(5)
    img = grab_screen()
    check_error_dialog(img)
    dismiss_popups(img)
    if strategy_screen_present(img):
        print("[check] strategy screen (600 gold) detected -> continue.")
        post_game_and_return()
    else:
        print("[check] strategy screen NOT detected -> leaving the game, then restart.")
        recover_leave_game()


def report(rows, target):
    print("\n  ticket panel (rule = %s):" % SELECTION_RULE)
    for r in rows:
        mark = "  <== pick" if target is not None and r["cell"] == target["cell"] else ""
        cnt = r["count"] if r["count"] is not None else "?"
        print("    %-22s count=%s%s" % (r["hero"], cnt, mark))
    if target is None:
        print("\n[!] No readable ticket counts. Was the event page in front?")
    else:
        print("\n[DECISION] hero = %s (count=%s)" % (target["hero"], target["count"]))


def automation_loop(set_status):
    """Repeat the full cycle until STOP: read tickets -> play -> accept -> pick -> back to event."""
    global _TPL
    _TPL = _build_templates()
    while not STOP.is_set():
        try:
            set_status("\u0427\u0438\u0442\u0430\u044e \u0431\u0438\u043b\u0435\u0442\u044b...")
            img = grab_screen()
            check_error_dialog(img)
            dismiss_popups(img)
            rows = read_all(img)
            target = choose(rows)
            report(rows, target)
            if target is None:
                set_status("\u0411\u0438\u043b\u0435\u0442\u044b \u043d\u0435 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u044b \u2014 \u0436\u0434\u0443 5\u0441")
                isleep(5)
                continue
            set_status("\u0413\u0435\u0440\u043e\u0439: %s \u2014 \u0438\u0433\u0440\u0430\u044e \u043c\u0430\u0442\u0447" % target["hero"])
            do_clicks(target)
            set_status("\u0426\u0438\u043a\u043b \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d, \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0447\u0435\u0440\u0435\u0437 5\u0441")
            isleep(5)
        except _ErrorDialog:
            set_status("\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 \u2014 \u0432\u044b\u0445\u043e\u0436\u0443 \u0438 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u043a\u0430\u044e")
            recover_after_error()
            isleep(3)


def launch_gui():
    import tkinter as tk

    BG = "#1b1e2b"; ACCENT = "#e0a516"; SUB = "#8890a6"; TXT = "#cfd3e2"
    GREEN = "#2f9e57"; GREEN_A = "#37b566"; RED = "#c0392b"; RED_A = "#d0473a"

    root = tk.Tk()
    root.title("Dark Carnival Auto")
    root.configure(bg=BG)
    root.geometry("460x250")
    root.resizable(False, False)

    tk.Label(root, text="Dark Carnival Auto", font=("Segoe UI Semibold", 18),
             fg=ACCENT, bg=BG).pack(pady=(28, 6))

    status = tk.StringVar(value="\u041e\u0442\u043a\u0440\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u0441\u043e\u0431\u044b\u0442\u0438\u044f Dota \u0438 \u043d\u0430\u0436\u043c\u0438 \xab\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c\xbb.")
    tk.Label(root, textvariable=status, wraplength=420, justify="center",
             font=("Segoe UI", 10), fg=TXT, bg=BG).pack(pady=16, padx=18)

    btn = tk.Button(root, text="\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c", width=20, height=2, bd=0,
                    font=("Segoe UI Semibold", 12), fg="white",
                    bg=GREEN, activebackground=GREEN_A, activeforeground="white",
                    relief="flat", cursor="hand2")
    btn.pack(pady=6)

    state = dict(thread=None)

    def set_status(msg):
        try:
            root.after(0, status.set, msg)
        except Exception:
            pass

    def reset_btn():
        btn.config(text="\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c", bg=GREEN, activebackground=GREEN_A)
        state["thread"] = None

    def worker():
        for i in range(5, 0, -1):
            if STOP.is_set():
                break
            set_status("\u0421\u0442\u0430\u0440\u0442 \u0447\u0435\u0440\u0435\u0437 %d  \u2014  \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0441\u044c \u043d\u0430 \u0441\u043e\u0431\u044b\u0442\u0438\u0435 Dota" % i)
            time.sleep(1)
        try:
            automation_loop(set_status)
        except _Stopped:
            set_status("\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            set_status("\u041e\u0448\u0438\u0431\u043a\u0430: %s" % e)
        root.after(0, reset_btn)

    def on_click():
        if state["thread"] is None:
            STOP.clear()
            btn.config(text="\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c", bg=RED, activebackground=RED_A)
            t = threading.Thread(target=worker, daemon=True)
            state["thread"] = t
            t.start()
        else:
            STOP.set()
            set_status("\u041e\u0441\u0442\u0430\u043d\u0430\u0432\u043b\u0438\u0432\u0430\u044e \u043f\u043e\u0441\u043b\u0435 \u0442\u0435\u043a\u0443\u0449\u0435\u0433\u043e \u0448\u0430\u0433\u0430...")

    def on_close():
        STOP.set()
        try:
            root.destroy()
        except Exception:
            pass
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    btn.config(command=on_click)
    root.mainloop()


def main():
    global _TPL
    _TPL = _build_templates()
    ap = argparse.ArgumentParser(description="Dark Carnival hero picker (local bots).")
    ap.add_argument("--run", action="store_true", help="actually click (otherwise dry-run)")
    ap.add_argument("--calibrate", action="store_true", help="save calibration.png and exit")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="seconds before capture")
    ap.add_argument("--nopause", action="store_true", help="do not wait for Enter at the end")
    ap.add_argument("--gui", action="store_true", help="launch the start/stop GUI")
    args = ap.parse_args()

    if args.gui:
        launch_gui()
        return

    countdown_to_capture(args.delay)
    img = grab_screen()
    print("[i] Captured %dx%d." % (img.shape[1], img.shape[0]))
    if img.shape[1] != SCREEN_W or img.shape[0] != SCREEN_H:
        print("[i] Resolution != %dx%d -> coordinates likely need adjusting." % (SCREEN_W, SCREEN_H))

    if args.calibrate:
        out = _misc_path("calibration.png")
        save_png(out, img)
        print("[calibrate] Saved:", out)
        return

    rows = read_all(img)
    target = choose(rows)
    report(rows, target)
    if args.run and target is not None:
        do_clicks(target)


def _pause():
    try:
        input("\nPress Enter to close this window...")
    except EOFError:
        pass


if __name__ == "__main__":
    _here = os.path.dirname(os.path.abspath(__file__))
    _logf = None
    try:
        _logf = open(_misc_path("picker_log.txt"), "w", encoding="utf-8", errors="replace")
        sys.stdout = _Tee(sys.__stdout__, _logf)
        sys.stderr = _Tee(sys.__stderr__, _logf)
    except Exception:
        pass
    try:
        print("[start] dark_carnival_hero_picker.py; python", sys.version.split()[0])
        if _IMPORT_ERROR is not None:
            print("[!] Missing library:", _IMPORT_ERROR.name)
            print("    Install: pip install mss opencv-python numpy pyautogui")
        else:
            main()
    except Exception:
        import traceback
        print("\n[ERROR] crashed:\n")
        traceback.print_exc()
    finally:
        try:
            if _logf:
                _logf.flush()
        except Exception:
            pass
        if "--nopause" not in sys.argv:
            _pause()

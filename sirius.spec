# Ative a venv e rode:
#.\venv\Scripts\python.exe build.py

# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

BASE_DIR      = Path(os.environ.get('SIRIUS_BUILD_ROOT', Path.cwd()))
ICON_PATH_STR = os.environ.get('SIRIUS_BUILD_ICON')
if not ICON_PATH_STR:
    potential_icon = BASE_DIR / 'face.ico'
    if potential_icon.exists():
        ICON_PATH_STR = str(potential_icon)

# ── Collect all submodules for packages with dynamic imports ─────────
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

_pkg_binaries, _pkg_datas, _pkg_hiddenimports = collect_all('packaging')

block_cipher = None

a = Analysis(
    [str(BASE_DIR / 'main.py')],
    pathex=[str(BASE_DIR)],
    binaries=[] + _pkg_binaries,
    datas=[] + collect_data_files('qtawesome') + _pkg_datas,
    hiddenimports=[
        # ── Google Gemini SDK ────────────────────────────────────
        'google.genai',
        'google.genai.types',
        'google.generativeai',
        # ── Google APIs (auth, calendar, gmail) ─────────────────
        'google_auth_oauthlib',
        'oauthlib',
        'requests_oauthlib',
        'googleapiclient',
        'googleapiclient.discovery',
        'google.auth',
        'google.auth.transport.requests',
        'google.oauth2',
        'google.oauth2.credentials',
        # ── Audio ───────────────────────────────────────────────
        'sounddevice',
        'numpy',
        # ── Computer Vision ─────────────────────────────────────
        'cv2',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'mss',
        # ── Web / HTTP ──────────────────────────────────────────
        'requests',
        'bs4',
        'duckduckgo_search',
        # ── Browser automation ──────────────────────────────────
        'playwright.async_api',
        'playwright._impl._connection',
        'playwright._impl._browser',
        'playwright._impl._browser_context',
        'playwright._impl._page',
        # ── GUI automation ──────────────────────────────────────
        'pyautogui',
        'pyperclip',
        'pygetwindow',
        # ── System / Windows ────────────────────────────────────
        'psutil',
        'win32gui',
        'win32process',
        'comtypes',
        'comtypes.client',
        'pycaw',
        'win10toast',
        # ── Media ───────────────────────────────────────────────
        'youtube_transcript_api',
        'send2trash',
        # ── Notifications ───────────────────────────────────────
        # 'plyer',  # only used in dynamically generated scripts, not a direct import
        # ── UI Framework ────────────────────────────────────────
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        # ── Icons (qtawesome) ───────────────────────────────────
        'qtawesome',
        'qtpy',
        # ── Project modules (explicit for safety) ───────────────
    ]
    + collect_submodules('google.genai')
    + collect_submodules('google.generativeai')
    + collect_submodules('googleapiclient')
    + collect_submodules('google_auth_oauthlib')
    + collect_submodules('oauthlib')
    + collect_submodules('requests_oauthlib')
    + collect_submodules('google.auth')
    + collect_submodules('google.oauth2')
    + collect_submodules('comtypes')
    + _pkg_hiddenimports,
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'sympy',
        'tensorflow',
        'torch',
        'tkinter',
        'PyQt5',
        'PySide2',
        'PySide6',
        'notebook',
        'jupyter_client',
        'ipython',
        'setuptools',
        'pip',
        'packaging',
        'wheel',
        'sphinx',
        'twisted',
        'zmq',
        'IPython',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SIRIUS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH_STR,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SIRIUS',
)

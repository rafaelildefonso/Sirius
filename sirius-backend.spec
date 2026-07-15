# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for SIRIUS backend (headless, no PyQt6).
# Build: pyinstaller -y sirius-backend.spec
#

import os
import sys
from pathlib import Path

BASE_DIR = Path(os.environ.get('SIRIUS_BUILD_ROOT', Path.cwd()))

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

_pkg_binaries, _pkg_datas, _pkg_hiddenimports = collect_all('packaging')
_fw_datas = collect_data_files('faster_whisper')

block_cipher = None

# Collect runtime data files (configs, memory, .env, dashboard static assets)
def _collect_runtime_data():
    datas = []
    for dirname in ("config", "memory"):
        src = BASE_DIR / dirname
        if src.is_dir():
            for f in src.rglob("*"):
                if f.is_file() and not f.name.startswith("__"):
                    dst = str(f.relative_to(BASE_DIR))
                    datas.append((str(f), dst))
    dashboard_static = BASE_DIR / "dashboard" / "static"
    if dashboard_static.is_dir():
        for f in dashboard_static.rglob("*"):
            if f.is_file() and not f.name.startswith("__"):
                dst = str(f.relative_to(BASE_DIR))
                datas.append((str(f), dst))
    for fname in (".env",):
        fp = BASE_DIR / fname
        if fp.exists():
            datas.append((str(fp), fname))
    return datas

a = Analysis(
    [str(BASE_DIR / 'sirius_backend_launcher.py')],
    pathex=[str(BASE_DIR)],
    binaries=[] + _pkg_binaries,
    datas=[] + _pkg_datas + _fw_datas + _collect_runtime_data(),
    hiddenimports=[
        # ── Entry point modules ─────────────────────────────────
        'main',
        # ── Persistence layer (DB, repository, models, etc.) ────
        'persistence',
        'persistence.database',
        'persistence.repository',
        'persistence.models',
        'persistence.classifier',
        'persistence.extractor',
        'persistence.retriever',
        'persistence.context_builder',
        'persistence.embedding',
        'persistence.scheduler',
        'persistence.backup',
        # ── Encryption ─────────────────────────────────────────
        'cryptography',
        'cryptography.fernet',
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
        'websockets',
        'fastapi',
        'uvicorn',
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
        # ── Dashboard / Remote ────────────────────────────────────
        'qrcode',
        'dashboard.server',
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
        'PyQt6',
        'PySide2',
        'PySide6',
        'qtawesome',
        'qtpy',
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
    name='sirius-backend',
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
    icon=None,
)

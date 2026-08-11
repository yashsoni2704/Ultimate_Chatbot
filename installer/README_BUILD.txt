============================================================
  DocMind — How to Build the Installer
  (Read this once. Takes 2 minutes.)
============================================================

WHAT YOU GET
------------
  DocMind_Setup.exe — a single file you can share with anyone.
  When they run it, it installs DocMind completely automatically.


ONE-TIME SETUP (do this only once)
------------------------------------
  1. Download Inno Setup 6 (free, 5 MB):
     https://jrsoftware.org/isdl.php
     → Click "Download Inno Setup 6"
     → Run the installer, click Next → Next → Install

  2. (Optional) Place your own icon at:
     installer\assets\DocMind.ico
     If you skip this, the build script uses a default Windows icon.


EVERY TIME YOU WANT A NEW .EXE
--------------------------------
  1. Make your code changes (edit app.py, static files, etc.)

  2. Double-click:
     installer\build_installer.bat

  3. Wait 30-60 seconds.

  4. Your installer is at:
     installer\Output\DocMind_Setup.exe

  5. Share that file. Done.


WHAT THE INSTALLER DOES WHEN USER RUNS IT
------------------------------------------
  Step 1  — Welcome screen (user clicks Next)
  Step 2  — System check: scans for Python, MongoDB, Ollama
  Step 3  — Shows what will be installed vs already present
  Step 4  — User chooses install folder (default: C:\DocMind)
  Step 5  — Downloads and silently installs:
              • Python 3.11.9   (if not installed, ~25 MB)
              • MongoDB 8.0     (if not installed, ~500 MB)
              • Ollama           (if not installed, ~60 MB)
  Step 6  — Copies all app files to C:\DocMind
  Step 7  — Runs install_helper.bat which:
              • Creates Python virtual environment (env\)
              • Installs all pip packages from requirements.txt
                  (Flask, LangChain, Docling, torch, etc.)
              • Installs Playwright Chromium browser
              • Starts Ollama service
              • Downloads bge-m3 embedding model  (~670 MB)
              • Downloads llama3.1 LLM model      (~4.7 GB)
              • Creates uploads/, vector_store/, logs/ folders
              • Generates .env with secure SECRET_KEY
  Step 8  — Creates Desktop shortcut + Start Menu entry
  Step 9  — Finish screen with "Launch DocMind" checkbox

  Total download for end user: ~6 GB
  Total install time: 20-45 minutes (mostly model downloads)


HOW USER LAUNCHES THE APP AFTER INSTALL
-----------------------------------------
  Double-click Desktop icon "DocMind"
    → Starts Qdrant, Chat server, Admin server
    → Opens browser at http://localhost:5000

  Admin panel: http://localhost:5001/admin


FOLDER STRUCTURE AFTER INSTALL (on user's PC)
-----------------------------------------------
  C:\DocMind\
  ├── app.py              (chat server)
  ├── admin_app.py        (admin panel)
  ├── config.py
  ├── watcher.py
  ├── qdrant.exe          (vector database)
  ├── launcher.bat        (what the shortcut runs)
  ├── install_helper.bat
  ├── requirements.txt
  ├── .env                (auto-generated, has SECRET_KEY)
  ├── .env.example
  ├── env\                (Python virtual environment)
  ├── uploads\            (user-uploaded documents)
  ├── vector_store\       (Qdrant data)
  ├── logs\               (app logs)
  ├── utils\
  ├── db\
  ├── static\
  ├── templates\
  └── scripts\


IF SOMETHING GOES WRONG DURING INSTALL
----------------------------------------
  Check the log file at:
    C:\DocMind\install_log.txt

  This file records every step — you can see exactly what failed.


IF YOU CHANGE requirements.txt (new package added)
----------------------------------------------------
  No changes needed to .iss file.
  Just rebuild:  double-click build_installer.bat


IF YOU WANT TO CHANGE APP NAME / VERSION
------------------------------------------
  Open installer\DocMind_Setup.iss in any text editor.
  At the top, change these lines:
    #define AppName     "DocMind"
    #define AppVersion  "1.0.0"
  Then rebuild.


IF YOU WANT TO CHANGE DEFAULT INSTALL PATH
-------------------------------------------
  Open installer\DocMind_Setup.iss
  Change this line:
    #define DefaultDirName "C:\DocMind"
  Then rebuild.
  Also update the same path in:
    installer\assets\launcher.bat  (line: set "INSTALL_DIR=C:\DocMind")


UNINSTALL
----------
  Control Panel → Programs → DocMind → Uninstall
  This removes all app files, venv, logs, uploads, vector store.
  It does NOT uninstall Python, MongoDB, or Ollama
  (since those may be used by other apps on the system).

============================================================

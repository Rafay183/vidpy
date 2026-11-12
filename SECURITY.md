# Security Policy

## Supported versions

Only the latest release on PyPI (`vidpy-ray`) receives security fixes.

## How vidpy protects you

* `vidpy studio` listens on **127.0.0.1 only** by default, so nobody else on your network can reach it. `--host 0.0.0.0` exposes the full editor (including import-from-path and file downloads from your workspace) to your network — only use it on a network you trust.
* Files are served only from your workspace folder and from media you explicitly imported.
* The **Custom FFmpeg Filter** effect passes text straight to FFmpeg. Only open `.vidpy.json` projects from people you trust, the same way you would treat a script.
* Uploaded media is stored in your workspace (`~/vidpy-studio` by default); nothing is sent to the internet.

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's **Security → Report a vulnerability** (private advisory) on https://github.com/rafay183/vidpy. You'll get a response as soon as possible, and credit in the release notes if you wish.

#!/usr/bin/env python3
"""
Simple FTP/FTPS deploy test.

Reads connection settings from environment variables:
  FTP_HOST / FTP_SERVER / SFTP_SERVER
  FTP_USER / FTP_USERNAME / SFTP_USERNAME
  FTP_PASS / FTP_PASSWORD / SFTP_PASSWORD
  FTP_PORT (default 21)
  FTP_PROTOCOL (ftp|ftps). SFTP is not supported by this script.
  FTP_REMOTE_DIR (remote target directory)

Creates FTP_REMOTE_DIR if needed, uploads deploy-test.txt with a timestamp,
and lists the target directory.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from ftplib import FTP, FTP_TLS, error_perm


def getenv(*keys: str, default: str | None = None) -> str | None:
    for k in keys:
        v = os.getenv(k)
        if v:
            return v
    return default


def ensure_dirs(ftp: FTP, path: str) -> None:
    parts = [p for p in path.strip("/").split("/") if p]
    cwd = ""
    for p in parts:
        cwd = f"{cwd}/{p}" if cwd else p
        try:
            ftp.mkd(cwd)
        except error_perm as e:
            # 550 already exists, ignore
            if not str(e).startswith("550"):
                raise


def main() -> int:
    host = getenv("FTP_HOST", "FTP_SERVER", "SFTP_SERVER")
    user = getenv("FTP_USER", "FTP_USERNAME", "SFTP_USERNAME")
    pwd = getenv("FTP_PASS", "FTP_PASSWORD", "SFTP_PASSWORD")
    port_s = getenv("FTP_PORT", default="21")
    proto = getenv("FTP_PROTOCOL", default="ftps" if port_s == "21" else "ftp")
    remote_dir = getenv("FTP_REMOTE_DIR", "SFTP_REMOTE_DIR") or ""

    if not (host and user and pwd and remote_dir):
        print(
            "Missing required env vars: FTP_HOST/USER/PASS and FTP_REMOTE_DIR",
            file=sys.stderr,
        )
        return 2

    if proto and proto.lower() == "sftp":
        print(
            "This debug script does not support SFTP. Set FTP_PROTOCOL=ftps or use port 21.",
            file=sys.stderr,
        )
        return 2

    port = int(port_s or 21)
    print(f"Protocol: {proto} | Host: {host} | Port: {port} | Remote dir: {remote_dir}")

    if proto and proto.lower() == "ftps":
        ftp = FTP_TLS()
    else:
        ftp = FTP()

    try:
        ftp.connect(host, port, timeout=30)
        ftp.login(user=user, passwd=pwd)
        if isinstance(ftp, FTP_TLS):
            ftp.prot_p()  # Secure data connection

        # Ensure path is relative to login root
        rel = remote_dir.lstrip("/")
        ensure_dirs(ftp, rel)
        ftp.cwd(rel)

        # Upload test file
        content = f"Deployed at {time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        data = content.encode()
        from io import BytesIO

        ftp.storbinary("STOR deploy-test.txt", BytesIO(data))

        # List files
        print("Remote directory listing:")
        ftp.retrlines("LIST")
        ftp.quit()
        return 0
    except Exception as e:
        print("ERROR during FTP deploy test:", e, file=sys.stderr)
        traceback.print_exc()
        try:
            ftp.close()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

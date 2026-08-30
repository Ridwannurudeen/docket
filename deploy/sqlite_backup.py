#!/usr/bin/env python3

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_backup(source: Path | str, target: Path | str) -> None:
    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    partial_path = Path(f"{target_path}.partial")
    if target_path.exists() or target_path.is_symlink():
        raise FileExistsError(f"backup target already exists: {target_path}")

    descriptor = os.open(
        partial_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        os.close(descriptor)
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise

    published = False
    try:
        source_uri = f"{source_path.as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
            with closing(sqlite3.connect(partial_path)) as destination_connection:
                source_connection.backup(destination_connection)
                quick_check = destination_connection.execute(
                    "PRAGMA quick_check"
                ).fetchall()
                if quick_check != [("ok",)]:
                    raise RuntimeError(f"backup quick_check failed: {quick_check!r}")
        os.chmod(partial_path, 0o600)
        _fsync_file(partial_path)
        os.replace(partial_path, target_path)
        published = True
        _fsync_directory(target_path.parent)
    except BaseException:
        partial_path.unlink(missing_ok=True)
        if published:
            target_path.unlink(missing_ok=True)
            _fsync_directory(target_path.parent)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and durably publish a verified online SQLite backup."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    create_backup(arguments.source, arguments.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

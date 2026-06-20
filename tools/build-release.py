#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "wp-media-sync"
RELEASE_FILES = [
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/check-wp-cli.sh",
    "scripts/wp-media-sync.py",
    "references/media-sync-rules.md",
    ".env.example",
]
RELEASE_ASSETS = [
    "install.sh",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build clean GitHub Releases artifacts for wp-media-sync.")
    parser.add_argument("--dist", default="dist", help="Output directory, default: dist")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_release_files(stage_dir: Path) -> None:
    for relative in RELEASE_FILES:
        source = PROJECT_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"Missing release file: {relative}")
        target = stage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def add_zip_file(zip_handle: zipfile.ZipFile, source: Path, archive_name: Path) -> None:
    st = source.stat()
    info = zipfile.ZipInfo(str(archive_name).replace(os.sep, "/"))
    info.date_time = (2026, 1, 1, 0, 0, 0)
    info.external_attr = (stat.S_IMODE(st.st_mode) & 0xFFFF) << 16
    zip_handle.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


def build_zip(stage_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w") as zip_handle:
        for source in sorted(stage_dir.rglob("*")):
            if source.is_file():
                archive_name = Path(SKILL_NAME) / source.relative_to(stage_dir)
                add_zip_file(zip_handle, source, archive_name)


def build_tar(stage_dir: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w:gz") as tar_handle:
        for source in sorted(stage_dir.rglob("*")):
            archive_name = Path(SKILL_NAME) / source.relative_to(stage_dir)
            tar_handle.add(source, arcname=str(archive_name), recursive=False)


def main() -> int:
    args = parse_args()
    dist_dir = (PROJECT_ROOT / args.dist).resolve()
    stage_dir = dist_dir / SKILL_NAME

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    stage_dir.mkdir(parents=True)

    copy_release_files(stage_dir)

    zip_path = dist_dir / f"{SKILL_NAME}.zip"
    tar_path = dist_dir / f"{SKILL_NAME}.tar.gz"
    build_zip(stage_dir, zip_path)
    build_tar(stage_dir, tar_path)

    asset_paths = []
    for relative in RELEASE_ASSETS:
        source = PROJECT_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"Missing release asset: {relative}")
        target = dist_dir / Path(relative).name
        shutil.copy2(source, target)
        asset_paths.append(target)

    sums_path = dist_dir / "SHA256SUMS"
    sum_lines = [
        f"{sha256(zip_path)}  {zip_path.name}",
        f"{sha256(tar_path)}  {tar_path.name}",
    ]
    for asset_path in asset_paths:
        sum_lines.append(f"{sha256(asset_path)}  {asset_path.name}")
    sums_path.write_text(
        "\n".join(sum_lines)
        + "\n",
        encoding="utf-8",
    )

    print(f"Built clean release artifacts in {dist_dir}")
    print(f"- {zip_path.name}")
    print(f"- {tar_path.name}")
    for asset_path in asset_paths:
        print(f"- {asset_path.name}")
    print(f"- {sums_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

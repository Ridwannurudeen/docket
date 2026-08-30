#!/usr/bin/env python3

import argparse
import base64
import csv
import email.parser
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = 1
BUILD_LOCK_PATH = "deploy/build-requirements.txt"
RUNTIME_LOCK_PATH = "deploy/runtime-requirements.txt"
PROVENANCE_FILENAME = "docket-provenance.json"
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class BundleError(RuntimeError):
    pass


def _sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hashed_record_value(contents: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise BundleError(f"release manifest contains duplicate key: {key}")
        value[key] = item
    return value


def _read_json(contents: bytes, label: str) -> object:
    try:
        return json.loads(contents, object_pairs_hook=_json_object)
    except (BundleError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"{label} is not valid JSON: {exc}") from exc


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict:
    if type(value) is not dict:
        raise BundleError(f"{label} must be a JSON object")
    actual = set(value)
    if actual != expected:
        raise BundleError(
            f"{label} keys differ: expected {sorted(expected)}, got {sorted(actual)}"
        )
    return value


def _require_hash(value: object, label: str) -> str:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise BundleError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _require_commit(value: object, label: str) -> str:
    if type(value) is not str or COMMIT_PATTERN.fullmatch(value) is None:
        raise BundleError(f"{label} must be 40 lowercase hexadecimal characters")
    return value


def _deploy_files(deploy_root: Path) -> dict[str, Path]:
    if not deploy_root.is_dir() or deploy_root.is_symlink():
        raise BundleError(f"deploy directory is missing or invalid: {deploy_root}")
    files: dict[str, Path] = {}
    for path in sorted(deploy_root.rglob("*")):
        relative = path.relative_to(deploy_root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise BundleError(f"deploy assets must not be symbolic links: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BundleError(f"deploy asset is not a regular file: {relative}")
        files[f"deploy/{relative.as_posix()}"] = path
    return files


def _require_secure_path(path: Path, owner: int) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise BundleError(f"secure release bundle path is missing: {path}") from exc
    if stat.S_ISLNK(details.st_mode):
        raise BundleError(
            f"secure release bundle paths must not be symbolic links: {path}"
        )
    if details.st_uid != owner:
        raise BundleError(
            f"secure release bundle owner mismatch for {path}: "
            f"got {details.st_uid}, expected {owner}"
        )
    if stat.S_IMODE(details.st_mode) & 0o022:
        raise BundleError(f"secure release bundle path is group/world writable: {path}")


def _require_secure_bundle_base(
    manifest_path: Path, deploy_root: Path, owner: int
) -> Path:
    bundle_root = manifest_path.parent
    if deploy_root.parent != bundle_root or deploy_root.name != "deploy":
        raise BundleError(
            "secure verification requires the manifest and deploy directory in one bundle"
        )
    for path in (bundle_root, deploy_root, manifest_path):
        _require_secure_path(path, owner)
    for ancestor in bundle_root.parents:
        details = ancestor.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise BundleError(
                f"secure release bundle ancestors must not be symbolic links: {ancestor}"
            )
        mode = stat.S_IMODE(details.st_mode)
        safe_sticky_directory = (
            stat.S_ISDIR(details.st_mode)
            and details.st_uid == 0
            and bool(mode & stat.S_ISVTX)
        )
        if details.st_uid not in {0, owner}:
            raise BundleError(
                f"secure release bundle ancestor has an unsafe owner: {ancestor}"
            )
        if mode & 0o022 and not safe_sticky_directory:
            raise BundleError(
                f"secure release bundle ancestor is group/world writable: {ancestor}"
            )
    return bundle_root


def _require_secure_bundle_tree(
    bundle_root: Path,
    manifest_path: Path,
    wheel_path: Path,
    deploy_root: Path,
    deploy_files: dict[str, Path],
    owner: int,
) -> None:
    paths = {bundle_root, manifest_path, wheel_path, deploy_root}
    paths.update(
        path for path in deploy_root.rglob("*") if "__pycache__" not in path.parts
    )
    paths.update(deploy_files.values())
    for path in sorted(paths):
        if path.suffix == ".pyc":
            continue
        _require_secure_path(path, owner)


def _validate_asset_path(value: object) -> str:
    if type(value) is not str or "\n" in value or "\r" in value or "\\" in value:
        raise BundleError("deploy asset paths must be normalized POSIX paths")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != "deploy"
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise BundleError(f"invalid deploy asset path: {value}")
    return value


def _read_manifest(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise BundleError(f"release manifest is missing or invalid: {path}")
    manifest = _require_exact_keys(
        _read_json(path.read_bytes(), "release manifest"),
        {
            "deploy_assets",
            "runtime_lock",
            "schema_version",
            "source_commit",
            "wheel",
        },
        "release manifest",
    )
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise BundleError(
            f"unsupported release manifest schema: {manifest['schema_version']}"
        )
    manifest["source_commit"] = _require_commit(
        manifest["source_commit"], "source commit"
    )

    wheel = _require_exact_keys(
        manifest["wheel"], {"filename", "sha256"}, "wheel binding"
    )
    filename = wheel["filename"]
    if (
        type(filename) is not str
        or not filename.endswith(".whl")
        or Path(filename).name != filename
        or any(character in filename for character in "\r\n/\\")
    ):
        raise BundleError("wheel filename must be a single .whl basename")
    wheel["sha256"] = _require_hash(wheel["sha256"], "wheel SHA-256")

    runtime_lock = _require_exact_keys(
        manifest["runtime_lock"], {"path", "sha256"}, "runtime lock binding"
    )
    if runtime_lock["path"] != RUNTIME_LOCK_PATH:
        raise BundleError(f"runtime lock path must be {RUNTIME_LOCK_PATH}")
    runtime_lock["sha256"] = _require_hash(
        runtime_lock["sha256"], "runtime lock SHA-256"
    )

    if type(manifest["deploy_assets"]) is not dict or not manifest["deploy_assets"]:
        raise BundleError("deploy asset bindings must be a non-empty JSON object")
    assets: dict[str, str] = {}
    for raw_path, raw_hash in manifest["deploy_assets"].items():
        path_value = _validate_asset_path(raw_path)
        assets[path_value] = _require_hash(
            raw_hash, f"deploy asset SHA-256 for {path_value}"
        )
    manifest["deploy_assets"] = assets
    return manifest


def _verify_wheel(path: Path, source_commit: str) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise BundleError("wheel contains duplicate archive paths")
            metadata_paths = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            record_paths = [
                name for name in names if name.endswith(".dist-info/RECORD")
            ]
            provenance_paths = [
                name
                for name in names
                if name.endswith(f".dist-info/{PROVENANCE_FILENAME}")
            ]
            if len(metadata_paths) != 1 or len(record_paths) != 1:
                raise BundleError("wheel must contain exactly one METADATA and RECORD")
            if len(provenance_paths) != 1:
                raise BundleError(
                    "wheel must contain exactly one embedded provenance member"
                )
            dist_info = metadata_paths[0].rsplit("/", 1)[0]
            if (
                record_paths[0].rsplit("/", 1)[0] != dist_info
                or provenance_paths[0].rsplit("/", 1)[0] != dist_info
            ):
                raise BundleError("wheel dist-info members do not share one directory")

            metadata = email.parser.BytesParser().parsebytes(
                archive.read(metadata_paths[0])
            )
            package_name = metadata.get("Name", "")
            package_version = metadata.get("Version", "")
            if package_name.lower() != "docket" or not package_version:
                raise BundleError("wheel metadata must name docket and carry a version")

            provenance = _require_exact_keys(
                _read_json(archive.read(provenance_paths[0]), "embedded provenance"),
                {"source_commit"},
                "embedded provenance",
            )
            embedded_commit = _require_commit(
                provenance["source_commit"], "embedded source commit"
            )
            if embedded_commit != source_commit:
                raise BundleError(
                    "embedded source commit does not match the release manifest"
                )

            try:
                record_text = archive.read(record_paths[0]).decode("utf-8")
                rows = list(csv.reader(io.StringIO(record_text, newline="")))
            except (UnicodeDecodeError, csv.Error) as exc:
                raise BundleError(f"wheel RECORD is invalid: {exc}") from exc
            if any(len(row) != 3 for row in rows):
                raise BundleError("wheel RECORD rows must have three columns")
            record: dict[str, tuple[str, str]] = {}
            for name, digest, size in rows:
                if name in record:
                    raise BundleError(f"wheel RECORD repeats path: {name}")
                record[name] = (digest, size)
            wheel_files = {info.filename for info in infos if not info.is_dir()}
            if set(record) != wheel_files:
                raise BundleError("wheel RECORD inventory does not match the archive")
            for name in sorted(wheel_files):
                digest, size = record[name]
                if name == record_paths[0]:
                    if digest or size:
                        raise BundleError(
                            "wheel RECORD must leave its own hash and size empty"
                        )
                    continue
                contents = archive.read(name)
                if digest != _hashed_record_value(contents) or size != str(
                    len(contents)
                ):
                    raise BundleError(f"wheel RECORD digest or size mismatch: {name}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleError(f"wheel archive is invalid: {exc}") from exc
    return package_name, package_version


def verify_bundle(
    manifest_path: Path, deploy_root: Path, secure_owner: int | None = None
) -> dict[str, str]:
    manifest_path = manifest_path.absolute()
    deploy_root = deploy_root.absolute()
    bundle_root = None
    if secure_owner is not None:
        bundle_root = _require_secure_bundle_base(
            manifest_path, deploy_root, secure_owner
        )
    manifest = _read_manifest(manifest_path)
    source_commit = manifest["source_commit"]

    wheel_path = manifest_path.parent / manifest["wheel"]["filename"]
    if not wheel_path.is_file() or wheel_path.is_symlink():
        raise BundleError(f"wheel is missing or invalid: {wheel_path}")
    wheel_sha = _sha256_file(wheel_path)
    if wheel_sha != manifest["wheel"]["sha256"]:
        raise BundleError(
            f"wheel SHA-256 mismatch: got {wheel_sha}, expected {manifest['wheel']['sha256']}"
        )

    runtime_lock = deploy_root / "runtime-requirements.txt"
    if not runtime_lock.is_file() or runtime_lock.is_symlink():
        raise BundleError(f"runtime lock is missing or invalid: {runtime_lock}")
    runtime_lock_sha = _sha256_file(runtime_lock)
    if runtime_lock_sha != manifest["runtime_lock"]["sha256"]:
        raise BundleError(
            "runtime lock SHA-256 mismatch: "
            f"got {runtime_lock_sha}, expected {manifest['runtime_lock']['sha256']}"
        )

    deploy_files = _deploy_files(deploy_root)
    if secure_owner is not None:
        _require_secure_bundle_tree(
            bundle_root,
            manifest_path,
            wheel_path,
            deploy_root,
            deploy_files,
            secure_owner,
        )
    expected_assets = set(manifest["deploy_assets"])
    actual_assets = set(deploy_files)
    if expected_assets != actual_assets:
        missing = sorted(expected_assets - actual_assets)
        unexpected = sorted(actual_assets - expected_assets)
        raise BundleError(
            f"deploy asset inventory mismatch: missing={missing}, unexpected={unexpected}"
        )
    for asset in sorted(actual_assets):
        actual = _sha256_file(deploy_files[asset])
        expected = manifest["deploy_assets"][asset]
        if actual != expected:
            raise BundleError(
                f"deploy asset SHA-256 mismatch for {asset}: got {actual}, expected {expected}"
            )

    package_name, package_version = _verify_wheel(wheel_path, source_commit)
    return {
        "manifest_sha256": _sha256_file(manifest_path),
        "package_name": package_name,
        "package_version": package_version,
        "runtime_lock_path": str(runtime_lock),
        "runtime_lock_sha256": runtime_lock_sha,
        "source_commit": source_commit,
        "wheel_path": str(wheel_path),
        "wheel_sha256": wheel_sha,
    }


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError(
            f"git {' '.join(arguments)} failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _extract_git_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir()
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise BundleError(f"git archive contains an unsafe path: {member.name}")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise BundleError(
                    f"git archive member is not a regular file: {member.name}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise BundleError(
                    f"git archive member could not be read: {member.name}"
                )
            with source, target.open("xb") as destination_file:
                shutil.copyfileobj(source, destination_file)
            target.chmod(member.mode & 0o777)


def _write_provenance_wheel(source: Path, target: Path, source_commit: str) -> None:
    temporary = target.with_name(f".{target.name}.partial")
    provenance = (
        json.dumps(
            {"source_commit": source_commit},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(source) as original:
            infos = original.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise BundleError("built wheel contains duplicate archive paths")
            record_infos = [
                info for info in infos if info.filename.endswith(".dist-info/RECORD")
            ]
            if len(record_infos) != 1:
                raise BundleError("built wheel must contain exactly one RECORD")
            record_info = record_infos[0]
            dist_info = record_info.filename.rsplit("/", 1)[0]
            provenance_path = f"{dist_info}/{PROVENANCE_FILENAME}"
            if provenance_path in names:
                raise BundleError(
                    "built wheel already contains an embedded provenance member"
                )

            record_rows: list[tuple[str, str, str]] = []
            with zipfile.ZipFile(temporary, "x") as rewritten:
                for info in infos:
                    if info.filename == record_info.filename:
                        continue
                    contents = original.read(info.filename)
                    rewritten.writestr(info, contents)
                    if not info.is_dir():
                        record_rows.append(
                            (
                                info.filename,
                                _hashed_record_value(contents),
                                str(len(contents)),
                            )
                        )

                provenance_info = zipfile.ZipInfo(
                    provenance_path, date_time=(1980, 1, 1, 0, 0, 0)
                )
                provenance_info.compress_type = zipfile.ZIP_DEFLATED
                provenance_info.external_attr = (stat.S_IFREG | 0o644) << 16
                rewritten.writestr(provenance_info, provenance)
                record_rows.append(
                    (
                        provenance_path,
                        _hashed_record_value(provenance),
                        str(len(provenance)),
                    )
                )

                record_stream = io.StringIO(newline="")
                writer = csv.writer(record_stream, lineterminator="\n")
                writer.writerows(sorted(record_rows))
                writer.writerow((record_info.filename, "", ""))
                rewritten.writestr(
                    record_info, record_stream.getvalue().encode("utf-8")
                )
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _build_bundle(output: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    top_level = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    if top_level != repo:
        raise BundleError(f"builder is not inside the repository root: {repo}")
    status_output = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status_output:
        raise BundleError(
            "working tree is not clean; commit or remove all changes before building"
        )
    source_commit = _require_commit(
        _git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip(), "Git HEAD"
    )

    output = output.expanduser().resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise BundleError("release bundle output must be outside the repository")
    if output.exists() or output.is_symlink():
        raise BundleError(f"release bundle output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="docket-release-build-") as temporary_name:
        temporary_root = Path(temporary_name)
        archive_path = temporary_root / "source.tar"
        archive_result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                source_commit,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if archive_result.returncode != 0:
            raise BundleError(
                f"git archive failed with exit {archive_result.returncode}: "
                f"{archive_result.stderr.strip()}"
            )
        source_root = temporary_root / "source"
        _extract_git_archive(archive_path, source_root)
        runtime_lock = source_root / RUNTIME_LOCK_PATH
        if not runtime_lock.is_file():
            raise BundleError(f"committed runtime lock is missing: {RUNTIME_LOCK_PATH}")
        build_lock = source_root / BUILD_LOCK_PATH
        if not build_lock.is_file():
            raise BundleError(f"committed build lock is missing: {BUILD_LOCK_PATH}")

        builder_venv = temporary_root / "builder-venv"
        venv_result = subprocess.run(
            [sys.executable, "-m", "venv", str(builder_venv)],
            check=False,
        )
        if venv_result.returncode != 0:
            raise BundleError(
                "temporary builder environment creation failed with exit "
                f"{venv_result.returncode}"
            )
        builder_python = builder_venv / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        install_result = subprocess.run(
            [
                str(builder_python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--require-hashes",
                "--only-binary=:all:",
                "-r",
                str(build_lock),
            ],
            check=False,
        )
        if install_result.returncode != 0:
            raise BundleError(
                "hash-locked builder dependency installation failed with exit "
                f"{install_result.returncode}"
            )

        raw_dist = temporary_root / "dist"
        raw_dist.mkdir()
        build_result = subprocess.run(
            [
                str(builder_python),
                "-m",
                "build",
                "--no-isolation",
                "--wheel",
                "--outdir",
                str(raw_dist),
                str(source_root),
            ],
            cwd=source_root,
            check=False,
        )
        if build_result.returncode != 0:
            raise BundleError(
                f"locked wheel build failed with exit {build_result.returncode}"
            )
        wheels = list(raw_dist.glob("*.whl"))
        if len(wheels) != 1:
            raise BundleError(
                f"wheel build produced {len(wheels)} wheel files, expected one"
            )

        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))
        )
        try:
            shutil.copytree(source_root / "deploy", staging / "deploy")
            final_wheel = staging / wheels[0].name
            _write_provenance_wheel(wheels[0], final_wheel, source_commit)
            deploy_files = _deploy_files(staging / "deploy")
            deploy_assets = {
                name: _sha256_file(path) for name, path in deploy_files.items()
            }
            runtime_lock_sha = _sha256_file(staging / RUNTIME_LOCK_PATH)
            manifest = {
                "deploy_assets": deploy_assets,
                "runtime_lock": {
                    "path": RUNTIME_LOCK_PATH,
                    "sha256": runtime_lock_sha,
                },
                "schema_version": SCHEMA_VERSION,
                "source_commit": source_commit,
                "wheel": {
                    "filename": final_wheel.name,
                    "sha256": _sha256_file(final_wheel),
                },
            }
            manifest_path = staging / "release-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            verify_bundle(manifest_path, staging / "deploy")
            os.replace(staging, output)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return output / "release-manifest.json"


def _print_verification(verified: dict[str, str]) -> None:
    for key in (
        "source_commit",
        "wheel_path",
        "wheel_sha256",
        "package_name",
        "package_version",
        "runtime_lock_path",
        "runtime_lock_sha256",
        "manifest_sha256",
    ):
        value = verified[key]
        if "\n" in value or "\r" in value:
            raise BundleError(f"verified {key} cannot be represented safely")
        print(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify an integrity-bound Docket release bundle."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("deploy", type=Path)
    verify.add_argument("--secure-owner", type=int)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "build":
            manifest = _build_bundle(arguments.output)
            print(manifest)
        else:
            _print_verification(
                verify_bundle(
                    arguments.manifest,
                    arguments.deploy,
                    secure_owner=arguments.secure_owner,
                )
            )
    except (BundleError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"release bundle error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

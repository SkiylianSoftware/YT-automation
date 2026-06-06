"""Project entrypoints with automatic dependecy management."""

from __future__ import annotations

import nox

requirements = "requirements.txt"
requirements_base = "requirements-base.txt"
requirements_google = "requirements-google.txt"
format_dirs = ["noxfile.py", "src", "tests"]

nox.options.sessions = []

# Code execution


def _ensure_whisper(session: nox.Session) -> None:
    """Install pywhispercpp to a persistent shared directory (one-time build).

    All whisper-dependent sessions share this single install target at
    ``~/.cache/yt-automation/whisper-site/`` instead of each rebuilding
    from git into their own venv.
    """
    from pathlib import Path

    whisper_site = Path.home() / ".cache" / "yt-automation" / "whisper-site"

    if not list(whisper_site.glob("_pywhispercpp*.so*")):
        whisper_site.mkdir(parents=True, exist_ok=True)
        session.log("Building pywhispercpp with Vulkan GPU support ...")
        session.install("-r", requirements_base)
        session.run(
            "python3", "-m", "pip", "install",
            "--target", str(whisper_site),
            "git+https://github.com/absadiki/pywhispercpp",
            env={"GGML_VULKAN": "1"},
        )
        session.log("pywhispercpp installed to %s", whisper_site)
    else:
        session.log(f"pywhispercpp already built at {whisper_site}")
        # Always install runtime deps into the session venv (it's fresh each
        # time), even when pywhispercpp itself is cached in the shared dir.
        session.install("-r", requirements_base)


def _run(session: nox.Session, *args: str) -> None:
    """Run a command using the session's venv python."""
    session.run("python3", "-m", "src.main", *args)


@nox.session(name="silence-removal")
def silence_removal(session: nox.Session) -> None:
    """Run silence removal (Vulkan GPU build if glslc available, else CPU)."""
    _ensure_whisper(session)
    session.log("Running silence-removal ...")
    _run(session, "silence-removal", *session.posargs)


@nox.session(name="transcribe")
def transcribe(session: nox.Session) -> None:
    """Transcribe a video/audio file to SRT captions (GPU accelerated)."""
    _ensure_whisper(session)
    session.log("Running transcribe ...")
    _run(session, "transcribe", *session.posargs)


@nox.session(name="background-music")
def background_music(session: nox.Session) -> None:
    """Run background music insertion (no Whisper/GPU deps)."""
    session.install("-r", requirements_base)
    session.log("Running background-music ...")
    _run(session, "background-music", *session.posargs)


@nox.session(name="playlist-automation")
def playlist_automation(session: nox.Session) -> None:
    """Run playlist automation (needs Google API deps)."""
    session.install("-r", requirements_base)
    session.install("-r", requirements_google)
    session.log("Running playlist-automation ...")
    _run(session, "playlist-automation", *session.posargs)

@nox.session(name="legacy-updater")
def legacy_updater(session: nox.Session) -> None:
    """Run bulk legacy title updates (needs Google API deps)."""
    session.install("-r", requirements_base)
    session.install("-r", requirements_google)
    session.log("Running legacy-updater ...")
    _run(session, "legacy-updater", *session.posargs)


@nox.session()
def run(session: nox.Session) -> None:
    """Run the main script entrypoint (installs all deps)."""
    session.install("-r", requirements)
    session.log("Running ...")
    _run(session, *session.posargs)


@nox.session()
def dev(session: nox.Session) -> None:
    """Install dependecies and drop into a dev shell."""
    session.install("-r", requirements)
    session.run("python3")


@nox.session
def docs(session: nox.Session) -> None:
    """Build and serve the docs."""
    session.install("mkdocs")
    session.install("mkdocs-dracula-theme")
    session.run("mkdocs", "build", "-f", "docs/mkdocs.yml")
    session.run("mkdocs", "serve", "-f", "docs/mkdocs.yml")


# Linting and formatting


def install_apt_packages(session: nox.Session, *pkg_args: str) -> None:
    """Install packages with apt. requires sudo access."""
    session.run("sudo", "apt-get", "update", "-qq", external=True)
    session.run("sudo", "apt-get", "install", "-y", *pkg_args, "-qq", external=True)


def install_npm_packages(session: nox.Session, *pkg_args: str) -> None:
    """Install packages from npm."""
    session.run("npm", "install", "--silent", *pkg_args, external=True)


@nox.session(tags=["format", "check"])
def black(session: nox.Session) -> None:
    """Format python acording to PEP."""
    session.install("black")
    session.run("black", *format_dirs)


@nox.session(tags=["format", "check"])
def isort(session: nox.Session) -> None:
    """Sort python imports correctly."""
    session.install("isort")
    session.run("isort", "--profile", "black", *format_dirs)


@nox.session(tags=["docs"])
def format_docs(session: nox.Session):
    """Format mkdocs with prettier."""
    install_apt_packages(session, "nodejs", "npm")
    install_npm_packages(session, "--save-dev", "prettier")

    session.run("npx", "prettier", "--write", "docs/**/*.md", external=True)


@nox.session(tags=["lint", "check"])
def flake(session: nox.Session) -> None:
    """Lint python and docstrings according to PEP."""
    session.install("flake8")
    session.install("flake8-docstrings")
    session.run(
        "flake8",
        *format_dirs,
        "--max-line-length",
        "88",
        "--extend-ignore",
        "E203,W503",
        "--ignore",
        "D100,D101",
        "--exclude",
        "tests/*",
    )


@nox.session(tags=["lint", "check"])
def mypy(session: nox.Session) -> None:
    """Run python type checking with mypy."""
    import pathlib

    mypy_dirs = []
    for directory in format_dirs:
        if pathlib.Path(directory).is_dir():
            mypy_dirs.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", requirements_base)
    session.run("mypy", *mypy_dirs, "--ignore-missing-imports")


@nox.session(tags=["docs"])
def lint_docs(session: nox.Session):
    """Lint the docs according to markdownlint."""
    install_apt_packages(session, "nodejs", "npm")
    install_npm_packages(session, "markdownlint-cli")

    session.run("npx", "markdownlint", "docs/**/*.md", external=True)


# Cleanup


@nox.session
def clean(session: nox.Session) -> None:
    """Remove all created files."""
    import os
    import shutil

    def delete(directory: str) -> None:
        shutil.rmtree(directory, ignore_errors=True)

    def delete_file(file):
        try:
            os.remove(file)
        except FileNotFoundError:
            print(f"{file} doesn't seem to exist, skipping.")
        except Exception as e:
            print(f"Unknown error {e}")

    delete("__pycache__")
    delete("src/__pycache__")
    delete(".mypy_cache")
    delete(".pytest_cache")
    delete(".nox")
    delete("node_modules")
    delete("site")

    delete_file(".coverage")
    delete_file("application.log")
    delete_file("package.json")
    delete_file("package-lock.json")


# Test execution


@nox.session(tags=["test", "check"])
def test(session: nox.Session) -> None:
    """Run pytest (core tests only, no whisper/GPU deps needed)."""
    session.install("pytest")
    session.install("pytest-mock")
    session.install("coverage")
    session.install("-r", requirements_base)

    session.run(
        "coverage",
        "run",
        "-m",
        "pytest",
        "tests",
        "--import-mode=importlib",
        "--durations=10",
        "-v",
    )
    session.run("coverage", "report", "-m")
    session.run("coverage", "html")

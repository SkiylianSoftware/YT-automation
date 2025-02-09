"""Project entrypoints with automatic dependecy management."""

import nox

requirements = "requirements.txt"
format_dirs = ["noxfile.py", "src", "tests"]

nox.options.sessions = ["run"]

# Code execution


@nox.session
def run(session: nox.session) -> None:
    """Run the main script entrypoint."""
    session.install("-r", requirements)
    session.run("python3", "-m", "src.main", *session.posargs, external=True)


@nox.session
def dev(session: nox.session) -> None:
    """Install dependecies and drop into a dev shell."""
    session.install("-r", requirements)
    session.run("python3")


@nox.session
def docs(session: nox.session) -> None:
    """Build and serve the docs."""
    session.install("mkdocs")
    session.install("mkdocs-dracula-theme")
    session.run("mkdocs", "build", "-f", "docs/mkdocs.yml")
    session.run("mkdocs", "serve", "-f", "docs/mkdocs.yml")


# Linting and formatting


def install_apt_packages(session: nox.session, *pkg_args: str) -> None:
    """Install apt packages (sudo pswd required)."""
    session.run("sudo", "apt-get", "update", "-qq", external=True)
    session.run("sudo", "apt-get", "install", "-y", *pkg_args, "-qq", external=True)


def install_npm_packages(session: nox.session, *pkg_args: str) -> None:
    """Install npm packages."""
    session.run("npm", "install", "--silent", *pkg_args, external=True)


@nox.session(tags=["format", "check"])
def black(session: nox.session) -> None:
    """Format python acording to PEP."""
    session.install("black")
    session.run("black", *format_dirs)


@nox.session(tags=["format", "check"])
def isort(session: nox.session) -> None:
    """Sort python imports correctly."""
    session.install("isort")
    session.run("isort", "--profile", "black", *format_dirs)


@nox.session(tags=["docs"])
def format_docs(session: nox.session):
    """Format mkdocs with prettier."""
    install_apt_packages(session, "nodejs", "npm")
    install_npm_packages(session, "--save-dev", "prettier")

    session.run("npx", "prettier", "--write", "docs/**/*.md", external=True)


@nox.session(tags=["lint", "check"])
def flake(session: nox.session) -> None:
    """Lint python nd docstrings according to PEP."""
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
def mypy(session: nox.session) -> None:
    """Run python type checking with mypy."""
    import pathlib

    mypy_dirs = []
    for directory in format_dirs:
        if pathlib.Path(directory).is_dir():
            mypy_dirs.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", requirements)
    session.run("mypy", *mypy_dirs, "--ignore-missing-imports")


@nox.session(tags=["docs"])
def lint_docs(session: nox.session) -> None:
    """Lint the docs according to markdownlint."""
    install_apt_packages(session, "nodejs", "npm")
    install_npm_packages(session, "markdownlint-cli")

    session.run("npx", "markdownlint", "docs/**/*.md", external=True)


# Cleanup


@nox.session
def clean(session: nox.session) -> None:
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
def test(session: nox.session) -> None:
    """Run pytest."""
    session.install("pytest")
    session.install("pytest-mock")
    session.install("coverage")
    session.install("-r", requirements)

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

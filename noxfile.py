import nox

requirements = "requirements.txt"
format_dirs = ["noxfile.py", "src", "tests"]

nox.options.sessions = ["run"]

# Code execution


@nox.session
def run(session: nox.session) -> None:
    session.install("-r", requirements)
    session.run("python3", "-m", "src.main", *session.posargs, external=True)


@nox.session
def dev(session: nox.session) -> None:
    session.install("-r", requirements)
    session.run("python3")


# Linting and formatting


@nox.session(tags=["format", "check"])
def black(session: nox.session) -> None:
    session.install("black")
    session.run("black", *format_dirs)


@nox.session(tags=["format", "check"])
def isort(session: nox.session) -> None:
    session.install("isort")
    session.run("isort", "--profile", "black", *format_dirs)


@nox.session(tags=["lint", "check"])
def flake(session: nox.session) -> None:
    session.install("flake8")
    session.run(
        "flake8", *format_dirs, "--max-line-length", "88", "--extend-ignore", "E203"
    )


@nox.session(tags=["lint", "check"])
def mypy(session: nox.session) -> None:
    import pathlib

    mypy_dirs = []
    for directory in format_dirs:
        if pathlib.Path(directory).is_dir():
            mypy_dirs.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", requirements)
    session.run("mypy", *mypy_dirs, "--ignore-missing-imports")


# Cleanup


@nox.session
def clean(session: nox.session) -> None:
    """Cleanly remove all created files"""
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

    delete_file(".coverage")
    delete_file("application.log")


# Test execution


@nox.session(tags=["test", "check"])
def test(session: nox.session) -> None:
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

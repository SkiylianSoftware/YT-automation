import nox

requirements = "requirements.txt"

format_dirs = ["noxfile.py", "src", "tests"]

# Code execution


@nox.session
def run(session: nox.session) -> None:
    session.install("-r", requirements)
    session.run("python3", "-m", "src.main", external=True)


# Linting and formatting


@nox.session(tags=["format", "lint"])
def black(session: nox.session) -> None:
    session.install("black")
    session.run("black", *format_dirs)


@nox.session
def clean(session: nox.session) -> None:
    """Cleanly remove all created files"""
    import shutil

    def delete(directory: str) -> None:
        shutil.rmtree(directory, ignore_errors=True)

    delete("__pycache__")
    delete("src/__pycache__")
    delete(".mypy_cache")
    delete(".pytest_cache")
    delete(".nox")


@nox.session(tags=["lint"])
def flake(session: nox.session) -> None:
    session.install("flake8")
    session.run(
        "flake8", *format_dirs, "--max-line-length", "88", "--extend-ignore", "E203"
    )


@nox.session(tags=["format", "lint"])
def isort(session: nox.session) -> None:
    session.install("isort")
    session.run("isort", "--profile", "black", *format_dirs)


@nox.session(tags=["lint"])
def mymy(session: nox.session) -> None:
    import pathlib

    mypy_dirs = []
    for directory in format_dirs:
        if pathlib.Path(directory).is_dir():
            mypy_dirs.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", requirements)
    session.run("mypy", *mypy_dirs, "--ignore-missing-imports")


# Test execution


@nox.session(tags=["test"])
def tests(session: nox.session) -> None:
    session.install("pytest")
    session.install("-r", requirements)

    # TODO: Remember how to run pytests

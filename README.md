# YT-automation
Scripts I use for youtube automation.

### What's included
- Playlist Automation - Automatically add videos to their respective playlists based on video and playlist title. 

## Setup

You will first need to follow the [pyyoutube](https://github.com/sns-sdks/python-youtube) usage [instructions](https://sns-sdks.lkhardy.cn/python-youtube/getting_started/), as we leverage the library to authenticate to and perform actions against the YouTube api.
create a file `.env.client` 

## Usage

This project makes use of [nox](https://nox.thea.codes/en/stable/index.html) to manage dependencies. We distribute a few nox sessions that you can execute to perform tasks.

### Program execution

Program execution is the default entrypoint provided by nox. Running `nox` will install dependencies and run the program.
This behavious is also replicated by running `nox -s run`.
Different program functions will require you to pass arguments to the program, which is achieved with `nox -- {args}`. It is reccomended to first run `nox -- help` to see the program help text.

To open a development shell with dependencies installed, you can run `nox -s dev`.

### Project Utils

We provide an entrypoint to format the project with `nox -s black`, and an entrypoint to sort imports with `nox -s isort`. To save executing both, you can instead run `nox -t format` to run the suite of formatting tools.

We additionally provide entrypoints to lint the project: `nox -s flake` to check python formatting against PEP, and `nox -s mypy` to validate typing. `nox -t lint` will run all of the linting tools.

A standard linting pass for a developer would probably look like `nox -t format lint`.

### Testing

Running `nox -s test` will execute the PyTest tests with `coverage` enabled, and provide a coverage report to stdout.

### Cleanup

Running `nox -s clean` will remove all files created directly by the program or it's development environments.

# 
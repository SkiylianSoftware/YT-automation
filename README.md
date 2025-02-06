# YT-automation
Scripts I use for youtube automation.

### What's included
- Playlist Automation - Automatically add videos to their respective playlists based on video and playlist title. 
- Calendar Automation - Automatically put released and upcoming videos in two google calendars based on publish date.

## Setup

**[Note]** You *must* use a chromium based broswer for OAuth (annoyingly). Google doesn't seem to like using Firefox.

### YouTube integration
You will first need to follow the [pyyoutube](https://github.com/sns-sdks/python-youtube) usage [instructions](https://sns-sdks.lkhardy.cn/python-youtube/getting_started/), as we leverage the library to authenticate to and perform actions against the YouTube api.

Next, create a file `.env.youtube`, and populate it with the client credentials generated when creating OAuth:
```
client_id=$client_id
client_secret=$client_secret
```

The first time you run any scripts that utilise the YouTube API, you will be asked to authenticate to the application. Follow the instructions in your terminal, upon completion the access credentials will be persisted in your `env.youtube` file.

### Calendar integration
You will need to follow the [instructions](https://developers.google.com/calendar/api/quickstart/python) to create an OAuth application that can interact with Google calendar. You can reuse the same application as created above for pyyoutube, however, this will need a second set of OAuth credentials, which you should download as a .json

Next, create a file `.env.calendar`, and populate it with the contents of the created OAuth credentials. (You can simply copy the file here and rename it to `.env.calendar`)

The first time you run any scripts that utilise the Calendar API, you will be asked to authenticate the the application. Follow the instructions provided.

## Usage

This project makes use of [nox](https://nox.thea.codes/en/stable/index.html) to manage dependencies. We distribute a few nox sessions that you can execute to perform tasks.

To automatically move videos to playlists, run `nox -- playlist-automation`.
    run `nox -- playlist-automation --help` for further help.

To automatically populate a google calendar with scheduled and past uploads, run `nox -- calendar-automation`
    run `nox -- calendar-automation --help` for further help.

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

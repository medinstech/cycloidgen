"""Whether a newer version exists, and how to get it onto this machine.

A tool that is installed once and used for months is a tool that quietly falls
behind, and here that is not only a missing feature.  The numbers this produces
come out of models that change between releases - see the changelog, and see
:mod:`cycloidgen.notice` for what they already do not claim.  Somebody sizing a
gearbox against a build from two versions ago has no way of knowing that the
stiffness figure in front of them was revised, and no reason to suspect it.  The
version check is how that person finds out.

Everything network-shaped is here and nothing here imports Qt, so the comparison,
the parsing and the asset choice can be tested without a display and without a
connection.  :mod:`cycloidgen.ui.updates` is the half that asks the user.

Three rules the rest of the application leans on:

* **Nothing happens unasked.**  No request on import, none from the command
  line, and none from the window until the user has answered the question once.
  ``CYCLOIDGEN_NO_UPDATE_CHECK`` turns the whole thing off for a distribution
  packager whose users update through them and not through us.
* **The route depends on how this copy was installed.**  A frozen Windows build
  has an installer that can be fetched and run; a wheel has ``pip install -U``;
  an AppImage is a file the user put somewhere themselves and is not ours to
  replace.  :func:`route` answers it, and the dialog says only what is true of
  the copy in front of it.
* **A failure is reported and never fatal.**  No network, a corporate proxy, a
  rate limit and a rewritten API are one thing to somebody standing in front of
  a design: the check did not happen.  Nothing in here may take the application
  down, and nothing in here may pretend it succeeded.

What is *not* claimed: there is no signature on any of this.  The download is
GitHub over TLS and the file is checked against the length GitHub published for
it, which catches a truncated transfer and nothing else.  The Windows installer
is unsigned - the release notes have said so since the first one - so SmartScreen
warns whether the user downloaded it in a browser or the application did.  The
dialog says that rather than implying a verification that has not happened.
"""
from __future__ import annotations

import json
import os
import platform
import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

__all__ = [
    "API_URL",
    "ENV_VAR",
    "RELEASES_URL",
    "REPOSITORY",
    "Asset",
    "Cancelled",
    "Release",
    "UpdateError",
    "disabled",
    "download",
    "frozen",
    "instruction",
    "is_newer",
    "latest",
    "launch",
    "release_from_payload",
    "route",
    "staging_directory",
    "version_key",
]

#: Set this to anything non-empty and no check is made, by any path, including
#: the one the user explicitly asks for from the menu.  It exists for the same
#: reason ``CYCLOIDGEN_SETTINGS`` does: whoever ships this copy may have a better
#: answer than we do about how it gets updated.
ENV_VAR = "CYCLOIDGEN_NO_UPDATE_CHECK"

#: The one place the repository is named for the API's benefit.  It is the same
#: repository ``cycloidgen.ui.branding`` publishes as a link and the same one
#: ``pyproject.toml`` declares as the homepage; ``tests/test_update.py`` holds
#: the three together, because a repository that moves and leaves this behind
#: gives every installed copy a permanent, silent 404.
REPOSITORY = "medinstech/cycloidgen"

#: Deliberately ``/releases/latest`` and not ``/releases``: that endpoint skips
#: drafts and pre-releases by itself, so an ``rc`` published for testing is never
#: offered to somebody running a stable build.  Nothing here has to filter it.
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"

#: Where a person is sent when the application cannot do the install itself.
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"

#: Ten seconds for the question, and long enough for the answer to arrive over
#: a bad hotel connection.  It is a background check: it may fail, and failing
#: quickly is better than a window that will not close because a socket is open.
TIMEOUT = 10.0

#: Read in 256 kB bites.  The installer is around 230 MB, so this is a thousand
#: progress ticks - enough that the bar moves, few enough that emitting them is
#: not the expensive part.
_CHUNK = 256 * 1024


class UpdateError(RuntimeError):
    """The check or the download did not happen, with a reason a person can read.

    Every message this carries is written to be shown as-is in a dialog: it says
    what failed rather than what raised, because "could not reach GitHub" is
    actionable to the reader and ``URLError(ConnectionRefusedError(61))`` is not.
    """


class Cancelled(Exception):
    """The user pressed Cancel.  Not an error, and not reported as one."""


# ----------------------------------------------------------------- versions --

#: The same shape ``tests/test_version.py`` holds the project's own version to,
#: because the thing being compared against is a tag this project published.
#: Anything else - a date, a four-part version, a tag from a fork - is refused
#: rather than guessed at, and a refusal here reads as "no update", which is the
#: safe direction to be wrong in.
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")

#: Alpha below beta below release candidate below the release itself.  Three is
#: the final release, so a version with no suffix sorts above every pre-release
#: of the same number: 7.8.0rc1 comes before 7.8.0, which is the whole point.
_STAGE = {"a": 0, "b": 1, "rc": 2}
_FINAL = 3


def version_key(text: str) -> tuple[int, int, int, int, int] | None:
    """Sortable form of a version string, or ``None`` if it is not one.

    A leading ``v`` is accepted because that is how the tags are spelled, and
    the tag is what the API reports.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION.match(text.strip().removeprefix("v").removeprefix("V"))
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.group(1, 2, 3))
    stage, number = match.group(4), match.group(5)
    return (major, minor, patch, _STAGE.get(stage, _FINAL), int(number or 0))


def is_newer(candidate: str, current: str = __version__) -> bool:
    """Is ``candidate`` a version worth offering to somebody running ``current``?

    False whenever the question cannot be answered - an unparseable tag, a
    version equal to this one, a release older than this one.  A user running a
    build newer than the published release is a developer, and telling them to
    downgrade would be worse than saying nothing.
    """
    new, have = version_key(candidate), version_key(current)
    if new is None or have is None:
        return False
    return new > have


# ------------------------------------------------------------------ releases --

@dataclass(frozen=True)
class Asset:
    """One file attached to a release."""

    name: str
    url: str
    size: int


@dataclass(frozen=True)
class Release:
    """What GitHub says the newest published release is."""

    version: str
    page: str
    notes: str
    assets: tuple[Asset, ...] = ()

    def is_newer_than(self, current: str = __version__) -> bool:
        return is_newer(self.version, current)

    def asset_for(self, system: str | None = None,
                  machine: str | None = None) -> Asset | None:
        """The file this platform would install, if the release carries one.

        Matched on the suffix rather than on a name built from the version,
        because the name is a packaging decision and this has to keep working
        when it changes.  ``cycloidgen.spec``, ``packaging/cycloidgen.nsi``,
        ``packaging/appimage.sh`` and ``packaging/macos.sh`` between them decide
        what is actually published; the endings are the stable part.
        """
        system = (system or platform.system()).lower()
        machine = (machine or platform.machine()).lower()
        if system == "windows":
            wanted, want_machine = (".exe",), None
        elif system == "linux":
            # x86-64 is the only architecture the AppImage is built for, and an
            # AppImage for the wrong one is an executable that will not start.
            wanted, want_machine = (".appimage",), ("x86_64", "amd64")
        elif system == "darwin":
            # Likewise: the disk image is Apple silicon, and an Intel Mac is
            # told to use pip - which is what the release notes say too.
            wanted, want_machine = (".dmg",), ("arm64", "aarch64")
        else:
            return None
        if want_machine is not None and machine not in want_machine:
            return None
        for asset in self.assets:
            if asset.name.lower().endswith(wanted):
                return asset
        return None


def release_from_payload(payload: object) -> Release:
    """Turn GitHub's JSON into a :class:`Release`, or say why it cannot.

    Written defensively on purpose.  This is the one place in the application
    that parses something a remote service sends, the shape is not ours, and the
    failure mode of assuming it - a ``KeyError`` out of a background thread
    during start-up - is the kind of crash nobody can report usefully.
    """
    if not isinstance(payload, dict):
        raise UpdateError("GitHub's answer was not a release")
    tag = payload.get("tag_name") or payload.get("name") or ""
    if version_key(tag) is None:
        raise UpdateError(f"GitHub reported a release this build cannot read: {tag!r}")

    assets = []
    for item in payload.get("assets") or ():
        if not isinstance(item, dict):
            continue
        name, url = item.get("name"), item.get("browser_download_url")
        if not name or not url:
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        assets.append(Asset(str(name), str(url), size))

    return Release(
        version=str(tag).removeprefix("v").removeprefix("V"),
        page=str(payload.get("html_url") or RELEASES_URL),
        notes=str(payload.get("body") or "").strip(),
        assets=tuple(assets),
    )


# ------------------------------------------------------------------- fetching --

def disabled() -> bool:
    """Has this copy been told not to check?"""
    return bool(os.environ.get(ENV_VAR, "").strip())


def _context() -> ssl.SSLContext:
    """A verifying TLS context, with certificates the frozen build can find.

    ``ssl.create_default_context`` loads the platform store, which is the right
    answer on Windows and on a normal Linux install.  A PyInstaller bundle on
    macOS is the case it does not cover: OpenSSL looks in the paths it was
    compiled with, those belong to the machine the bundle was *built* on, and the
    result is a verification failure on a connection that is perfectly fine.
    certifi ships the same CA list as a file, so where it is available it is
    used - and where it is not, the platform store is still tried rather than
    verification being turned off.  An update fetched over an unverified
    connection is worse than no update.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _request(url: str) -> urllib.request.Request:
    # GitHub answers 403 to a request with no User-Agent, which arrives here as
    # "forbidden" and reads like a rate limit.  The API version header pins the
    # response shape: without it a future default could change the field names
    # under an installed copy that can never be updated to match.
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"cycloidgen/{__version__}",
    })


def _http_message(error: urllib.error.HTTPError) -> str:
    if error.code in (403, 429):
        return ("GitHub is rate-limiting this address; the check will work again "
                "in an hour")
    if error.code == 404:
        return "GitHub has no published release for this project yet"
    return f"GitHub answered {error.code} {error.reason}"


def latest(*, url: str = API_URL, timeout: float = TIMEOUT) -> Release:
    """Ask GitHub what the newest published release is.

    Raises :class:`UpdateError` for everything that can go wrong, with a message
    fit to put in front of a person.
    """
    if disabled():
        raise UpdateError(f"update checks are turned off by {ENV_VAR}")
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout,
                                    context=_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateError(_http_message(exc)) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"could not reach GitHub: {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise UpdateError(f"could not reach GitHub: {exc}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateError("GitHub's answer was not the release information") from exc
    return release_from_payload(payload)


# ---------------------------------------------------------------- downloading --

def staging_directory() -> Path:
    """Where a downloaded installer is put.

    The system temporary directory, in a folder of our own: an installer is a
    file that has served its purpose the moment it has run, and leaving 230 MB
    in somebody's Downloads folder to be found a year later and run by accident
    is not a favour.  Whatever cleans ``%TEMP%`` will clean this.
    """
    return Path(tempfile.gettempdir()) / "cycloidgen-update"


def download(asset: Asset, directory: Path | None = None, *,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             timeout: float = TIMEOUT) -> Path:
    """Fetch ``asset`` and return the file, having checked its length.

    Written to ``name.part`` and renamed once it is whole.  A partial file under
    the real name is the one outcome that must not be possible here: it is an
    installer, it looks finished, and running it would take out the working
    install to replace it with half of one.
    """
    directory = directory or staging_directory()
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / asset.name
    partial = directory / f"{asset.name}.part"

    done = 0
    try:
        with urllib.request.urlopen(_request(asset.url), timeout=timeout,
                                    context=_context()) as response:
            # The API's `size` is what to expect; the response header is what is
            # actually coming.  They agree in practice and the header is the one
            # that describes *this* transfer, so it wins for the progress bar.
            try:
                total = int(response.headers.get("Content-Length") or asset.size)
            except (TypeError, ValueError):
                total = asset.size
            with partial.open("wb") as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise Cancelled
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except Cancelled:
        partial.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(_http_message(exc)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"the download stopped: {exc}") from exc

    if asset.size and done != asset.size:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            f"the download is {done:,} bytes and should be {asset.size:,}; "
            "it was cut short and has been discarded")

    # Windows will not rename onto an existing file, and an installer left over
    # from an abandoned attempt is exactly what is there on a second try.
    final.unlink(missing_ok=True)
    partial.replace(final)
    return final


def launch(installer: Path) -> None:
    """Start the downloaded installer and leave it running after we exit.

    Through ``os.startfile``, which is ShellExecute, and that matters: the NSIS
    script declares ``RequestExecutionLevel admin``, so the process needs to be
    elevated.  ``subprocess`` cannot do it - CreateProcess refuses a manifest it
    cannot satisfy and fails with ERROR_ELEVATION_REQUIRED - whereas ShellExecute
    raises the UAC prompt and hands the user the decision, which is where that
    decision belongs.

    The caller closes the application straight afterwards.  The installer clears
    the old install before it copies, and it cannot delete a running executable:
    it would sit on a Retry dialog waiting for us to go away.
    """
    if sys.platform != "win32":
        raise UpdateError("this build cannot install an update by itself")
    if not installer.is_file():
        raise UpdateError(f"the installer is not where it was put: {installer}")
    os.startfile(str(installer))


# ---------------------------------------------------------------------- route --

def frozen() -> bool:
    """Is this the bundled application rather than an installed package?"""
    return bool(getattr(sys, "frozen", False))


def route(system: str | None = None, *, is_frozen: bool | None = None) -> str:
    """How *this* copy gets updated: ``installer``, ``download`` or ``pip``.

    Three different answers, and offering the wrong one is worse than offering
    none: telling somebody who installed a wheel to download a 230 MB installer
    gives them two copies of the application, and telling somebody running the
    installed build to type a pip command gives them a second, shadowed one.
    """
    if is_frozen is None:
        is_frozen = frozen()
    if not is_frozen:
        return "pip"
    if (system or platform.system()).lower() == "windows":
        return "installer"
    return "download"


def instruction(kind: str | None = None) -> str:
    """One sentence telling the reader what the button in front of them will do."""
    kind = kind or route()
    if kind == "installer":
        return ("cycloidgen can download the installer and start it. The application "
                "closes while it runs, and your preferences and saved designs are "
                "kept. The installer is unsigned, so Windows SmartScreen will warn "
                "on first run: More info → Run anyway.")
    if kind == "download":
        return ("This copy is a bundled build that was placed here by hand, so it is "
                "not ours to replace. The release page has the new one.")
    # Named rather than assumed: a machine with several interpreters is exactly
    # where `pip install -U` upgrades a copy that is not the one running.
    return (f"This copy was installed with pip. Upgrade it with:\n\n"
            f"    \"{sys.executable}\" -m pip install --upgrade cycloidgen")

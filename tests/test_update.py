"""The update check: the comparison, the parsing, and what it refuses to do.

Nothing in here touches the network.  That is not a limitation of the tests, it
is the property being tested: this module is the one place in the application
that talks to a remote service, and it has to be possible to exercise every
decision it makes without one.  Anything that reaches GitHub is called with an
explicit URL or a stubbed opener; the default path is never taken.

The three failure modes worth guarding, in order of how much they would cost:

* **Offering the wrong thing.** A user running a wheel told to download a 230 MB
  installer ends up with two copies; a Mac told to fetch an AppImage ends up
  with one that will not start.  The route and the asset choice are decided from
  the platform, and they are decided here.
* **Offering a downgrade.** A version comparison that gets a pre-release the
  wrong way round tells somebody on 7.8.0 that 7.8.0rc1 is newer.
* **Failing loudly.** A rewritten API, a 403, an empty release: all of them have
  to arrive as an `UpdateError` carrying a sentence, never as a `KeyError` out
  of a background thread during start-up.
"""
from __future__ import annotations

import json
import re
import urllib.error
from pathlib import Path

import pytest

import cycloidgen
from cycloidgen import update

ROOT = Path(__file__).resolve().parent.parent


def _release(**kwargs) -> update.Release:
    fields = {"version": "9.9.9", "page": "https://example.invalid/r", "notes": ""}
    fields.update(kwargs)
    return update.Release(**fields)


# ------------------------------------------------------------------ versions --

@pytest.mark.parametrize("text", ["7.7.0", "v7.7.0", "0.0.1", "12.4.9",
                                  "7.8.0rc1", "7.8.0a3", "7.8.0b12"])
def test_the_versions_this_project_publishes_are_readable(text):
    assert update.version_key(text) is not None


@pytest.mark.parametrize("text", ["", "7.7", "7.7.0.1", "2026-08-28", "latest",
                                  "v7.7.0-hotfix", "7.7.0.post1", None, 7.7])
def test_anything_else_is_refused_rather_than_guessed_at(text):
    assert update.version_key(text) is None


def test_the_projects_own_version_is_one_of_them():
    """If this fails, an installed copy can never recognise its own release."""
    assert update.version_key(cycloidgen.__version__) is not None


@pytest.mark.parametrize("older, newer", [
    ("7.7.0", "7.7.1"),
    ("7.7.9", "7.8.0"),
    ("7.9.0", "8.0.0"),
    ("7.7.0", "7.7.0"),          # equal is not newer
    # A pre-release leads to the release, and never the other way round.  Get
    # this backwards and 7.8.0rc1 is offered as an upgrade from 7.8.0.
    ("7.8.0rc1", "7.8.0"),
    ("7.8.0a1", "7.8.0b1"),
    ("7.8.0b9", "7.8.0rc1"),
    ("7.7.0", "7.8.0rc1"),
])
def test_which_way_round_the_versions_go(older, newer):
    if older == newer:
        assert not update.is_newer(newer, older)
        return
    assert update.is_newer(newer, older)
    assert not update.is_newer(older, newer)


def test_an_unreadable_version_is_never_an_update():
    """"I do not understand this tag" has to mean "say nothing"."""
    assert not update.is_newer("main", "7.7.0")
    assert not update.is_newer("7.8.0", "some-fork-1.2")


def test_a_build_ahead_of_the_release_is_not_told_to_downgrade():
    """The developer's own tree, between a bump and the tag that follows it."""
    assert not update.is_newer("7.7.0", "7.8.0")


# ------------------------------------------------------------------ payloads --

#: Trimmed to the fields this reads, in the spelling GitHub uses.
PAYLOAD = {
    "tag_name": "v9.9.9",
    "html_url": "https://github.com/medinstech/cycloidgen/releases/tag/v9.9.9",
    "body": "## 9.9.9\n\n- something changed",
    "assets": [
        {"name": "cycloidgen_v9.9.9_Setup.exe", "size": 241172480,
         "browser_download_url": "https://example.invalid/setup.exe"},
        {"name": "cycloidgen-9.9.9-x86_64.AppImage", "size": 812345678,
         "browser_download_url": "https://example.invalid/app.AppImage"},
        {"name": "cycloidgen-9.9.9-arm64.dmg", "size": 712345678,
         "browser_download_url": "https://example.invalid/app.dmg"},
    ],
}


def test_a_release_comes_out_of_the_payload_whole():
    release = update.release_from_payload(PAYLOAD)
    assert release.version == "9.9.9"                  # the `v` is dropped
    assert release.page.endswith("/v9.9.9")
    assert "something changed" in release.notes
    assert len(release.assets) == 3
    assert release.assets[0].size == 241172480


@pytest.mark.parametrize("payload", [
    None, [], "a string", {}, {"tag_name": "nightly"}, {"tag_name": None},
])
def test_an_answer_that_is_not_a_release_raises_rather_than_crashes(payload):
    """The shape is not ours, so it is checked rather than assumed.

    A `KeyError` here would surface as a crash on a background thread during
    start-up, which is the least reportable failure this application could have.
    """
    with pytest.raises(update.UpdateError):
        update.release_from_payload(payload)


def test_a_release_with_broken_assets_keeps_the_ones_that_are_whole():
    release = update.release_from_payload({
        "tag_name": "9.9.9",
        "assets": [
            {"name": "good.exe", "browser_download_url": "https://x.invalid/a",
             "size": 5},
            {"name": "no url"},
            {"browser_download_url": "https://x.invalid/b"},
            "not a dict",
            {"name": "bad size.exe", "browser_download_url": "https://x.invalid/c",
             "size": "large"},
        ],
    })
    assert [a.name for a in release.assets] == ["good.exe", "bad size.exe"]
    assert release.assets[1].size == 0


def test_a_release_with_no_notes_still_parses():
    release = update.release_from_payload({"tag_name": "9.9.9"})
    assert release.notes == ""
    assert release.assets == ()
    assert release.page == update.RELEASES_URL


# -------------------------------------------------------------------- assets --

RELEASE = update.release_from_payload(PAYLOAD)


@pytest.mark.parametrize("system, machine, ending", [
    ("Windows", "AMD64", ".exe"),
    ("Linux", "x86_64", ".AppImage"),
    ("Darwin", "arm64", ".dmg"),
])
def test_each_platform_is_offered_the_file_built_for_it(system, machine, ending):
    asset = RELEASE.asset_for(system, machine)
    assert asset is not None and asset.name.endswith(ending)


@pytest.mark.parametrize("system, machine", [
    # No AppImage is built for arm, and no disk image for Intel - the release
    # notes send both to pip.  Offering the wrong one is worse than offering
    # nothing: it downloads for several minutes and then will not start.
    ("Linux", "aarch64"),
    ("Darwin", "x86_64"),
    ("FreeBSD", "amd64"),
])
def test_a_platform_with_no_bundle_is_offered_nothing(system, machine):
    assert RELEASE.asset_for(system, machine) is None


def test_a_release_that_published_no_assets_offers_nothing():
    assert _release().asset_for("Windows", "AMD64") is None


# --------------------------------------------------------------------- route --

@pytest.mark.parametrize("system, is_frozen, expected", [
    ("Windows", True, "installer"),
    ("Linux", True, "download"),
    ("Darwin", True, "download"),
    ("Windows", False, "pip"),
    ("Linux", False, "pip"),
])
def test_how_this_copy_would_be_updated(system, is_frozen, expected):
    assert update.route(system, is_frozen=is_frozen) == expected


@pytest.mark.parametrize("kind", ["installer", "download", "pip"])
def test_every_route_can_say_what_it_will_do(kind):
    """A sentence, not a label: this is the whole explanation the user gets."""
    text = update.instruction(kind)
    assert len(text) > 40 and text.rstrip().endswith((".", "cycloidgen"))


def test_the_pip_instruction_names_the_interpreter_that_is_running():
    """A machine with several Pythons is where a bare `pip` upgrades the wrong one."""
    import sys
    assert sys.executable in update.instruction("pip")
    assert "--upgrade cycloidgen" in update.instruction("pip")


# ------------------------------------------------------------------ the fetch --

def test_the_environment_can_turn_the_whole_thing_off(monkeypatch):
    """A distribution that updates its own packages gets to say so."""
    monkeypatch.setenv(update.ENV_VAR, "1")
    assert update.disabled()
    with pytest.raises(update.UpdateError):
        update.latest(url="https://example.invalid/never-reached")


def test_an_unset_variable_is_not_a_setting(monkeypatch):
    monkeypatch.delenv(update.ENV_VAR, raising=False)
    assert not update.disabled()
    monkeypatch.setenv(update.ENV_VAR, "")
    assert not update.disabled()


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def test_a_check_reads_the_release_off_the_wire(monkeypatch):
    seen = {}

    def opener(request, timeout=None, context=None):
        seen["url"] = request.full_url
        seen["agent"] = request.get_header("User-agent")
        return _Response(json.dumps(PAYLOAD).encode("utf-8"))

    monkeypatch.delenv(update.ENV_VAR, raising=False)
    monkeypatch.setattr(update.urllib.request, "urlopen", opener)
    release = update.latest()
    assert release.version == "9.9.9"
    assert seen["url"] == update.API_URL
    # GitHub answers 403 to a request with no User-Agent, and that arrives
    # looking exactly like a rate limit.
    assert seen["agent"] and "cycloidgen" in seen["agent"]


@pytest.mark.parametrize("code, expected", [
    (403, "rate-limiting"),
    (429, "rate-limiting"),
    (404, "no published release"),
    (500, "500"),
])
def test_an_http_failure_says_something_a_person_can_act_on(monkeypatch, code,
                                                            expected):
    def opener(request, timeout=None, context=None):
        raise urllib.error.HTTPError(request.full_url, code, "nope", {}, None)

    monkeypatch.delenv(update.ENV_VAR, raising=False)
    monkeypatch.setattr(update.urllib.request, "urlopen", opener)
    with pytest.raises(update.UpdateError) as caught:
        update.latest()
    assert expected in str(caught.value)


def test_a_download_that_404s_does_not_talk_about_releases(monkeypatch, tmp_path):
    """The same helper serves the check and the download, and the 404 differs.

    "GitHub has no published release for this project yet" is true of a check
    that cannot find one and nonsense during a download: the release is right
    there, it is the file that has gone - replaced, most likely, between the
    check and the click. A message that is wrong in one of its two callers sends
    the reader looking in the wrong place, which is worse than a status code.
    """
    def opener(request, timeout=None, context=None):
        raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)

    monkeypatch.setattr(update.urllib.request, "urlopen", opener)
    asset = update.Asset("setup.exe", "https://example.invalid/s.exe", 10)
    with pytest.raises(update.UpdateError) as caught:
        update.download(asset, tmp_path)
    said = str(caught.value)
    assert "no longer on the release" in said
    assert "no published release" not in said
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raised", [
    urllib.error.URLError("no route to host"),
    TimeoutError("timed out"),
    OSError("connection reset"),
])
def test_a_connection_that_does_not_happen_is_reported_not_raised(monkeypatch,
                                                                  raised):
    def opener(request, timeout=None, context=None):
        raise raised

    monkeypatch.delenv(update.ENV_VAR, raising=False)
    monkeypatch.setattr(update.urllib.request, "urlopen", opener)
    with pytest.raises(update.UpdateError):
        update.latest()


def test_an_answer_that_is_not_json_is_reported_the_same_way(monkeypatch):
    monkeypatch.delenv(update.ENV_VAR, raising=False)
    monkeypatch.setattr(update.urllib.request, "urlopen",
                        lambda *a, **k: _Response(b"<html>proxy login</html>"))
    with pytest.raises(update.UpdateError):
        update.latest()


# ---------------------------------------------------------------- downloading --

def _download(monkeypatch, body: bytes, size: int, tmp_path, **kwargs) -> Path:
    monkeypatch.setattr(update.urllib.request, "urlopen",
                        lambda *a, **k: _Chunks(body))
    asset = update.Asset("cycloidgen_v9.9.9_Setup.exe",
                         "https://example.invalid/setup.exe", size)
    return update.download(asset, tmp_path, **kwargs)


class _Chunks(_Response):
    """A response that hands out its body a chunk at a time, like the real one."""

    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self._at = 0
        self.headers = {"Content-Length": str(len(body))}

    def read(self, _size: int = -1) -> bytes:
        chunk = self._body[self._at:self._at + 8]
        self._at += len(chunk)
        return chunk


def test_a_download_arrives_whole_and_under_its_own_name(monkeypatch, tmp_path):
    body = b"x" * 64
    path = _download(monkeypatch, body, len(body), tmp_path)
    assert path.name == "cycloidgen_v9.9.9_Setup.exe"
    assert path.read_bytes() == body


def test_a_short_download_is_discarded_rather_than_kept(monkeypatch, tmp_path):
    """The one outcome that must not be possible.

    A partial installer under the real name looks finished, and running it takes
    out the working install to replace it with half of one.
    """
    with pytest.raises(update.UpdateError):
        _download(monkeypatch, b"x" * 40, 64, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cancelling_leaves_nothing_behind(monkeypatch, tmp_path):
    with pytest.raises(update.Cancelled):
        _download(monkeypatch, b"x" * 4096, 4096, tmp_path,
                  cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_progress_is_reported_as_it_goes(monkeypatch, tmp_path):
    ticks: list[tuple[int, int]] = []
    body = b"x" * 64
    _download(monkeypatch, body, len(body), tmp_path, progress=lambda a, b:
              ticks.append((a, b)))
    assert ticks[-1] == (64, 64)
    assert [done for done, _ in ticks] == sorted(done for done, _ in ticks)


def test_a_second_attempt_replaces_the_first(monkeypatch, tmp_path):
    """Windows will not rename onto an existing file, and an abandoned attempt
    leaves exactly that in the way."""
    body = b"x" * 64
    first = _download(monkeypatch, body, len(body), tmp_path)
    second = _download(monkeypatch, body, len(body), tmp_path)
    assert first == second and second.read_bytes() == body


def test_the_staging_directory_is_temporary():
    """An installer is spent the moment it has run.  Leaving 230 MB in somebody's
    Downloads folder to be found a year later and run by accident is not a favour."""
    import tempfile
    assert str(update.staging_directory()).startswith(tempfile.gettempdir())


def test_only_windows_can_install_in_place(monkeypatch, tmp_path):
    """Every other bundle is a file the user placed themselves."""
    monkeypatch.setattr(update.sys, "platform", "linux")
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"x")
    with pytest.raises(update.UpdateError):
        update.launch(installer)


def test_a_missing_installer_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(update.sys, "platform", "win32")
    with pytest.raises(update.UpdateError):
        update.launch(tmp_path / "not-there.exe")


# --------------------------------------------------------------- one address --

def test_the_api_and_the_help_menu_name_the_same_repository():
    """Two copies of the address, and only one of them is ever clicked.

    A repository that moves and leaves this behind gives every installed copy a
    permanent, silent 404: the Help menu still works, the check never finds
    anything, and nothing says why.
    """
    pytest.importorskip("PySide6")
    from cycloidgen.ui import branding
    linked = f"https://github.com/{update.REPOSITORY}"
    assert linked == branding.PROJECT_URL
    assert update.RELEASES_URL == branding.RELEASES_URL
    assert update.API_URL.endswith(f"/repos/{update.REPOSITORY}/releases/latest")


def test_the_repository_is_the_one_the_package_metadata_publishes():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    homepage = re.search(r'^Homepage\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert homepage is not None
    assert homepage.group(1) == f"https://github.com/{update.REPOSITORY}"

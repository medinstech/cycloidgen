# Security policy

## Supported versions

The latest release on `main`. This is a small project; there is no long-term
support branch, and a fix ships as the next version rather than as a backport.

## Reporting a vulnerability

Use GitHub's private reporting — **Security ▸ Advisories ▸ Report a
vulnerability** — or write to <sinantufekci@medinstech.com>. Please do not open a
public issue for anything that could be exploited before there is a fix.

Tell us what an attacker gets, and how you got it. A proof of concept, a design
file, or the exact input that triggers it is worth more than a description. You
will get an acknowledgement within a week; if you do not, assume the mail went
astray and try the other channel.

## What is in scope

cycloidgen is a desktop application and a library. It makes no network requests,
runs no server, and has no accounts or credentials. That leaves a small but real
surface, and it is mostly *untrusted input*:

- **Design files.** `File ▸ Open design...`, `--design`, and `GearSpec` parse
  JSON supplied by whoever sent you the file. Anything that turns a hostile
  design file into code execution, a write outside the chosen folder, or a hang
  that cannot be interrupted is in scope.
- **Export paths.** Everything is written under a folder you pick. A path in a
  design that escapes it would be in scope.
- **Bundled dependencies.** A vulnerability in the standalone Windows build
  because of a component it ships (OCCT, Qt, matplotlib and friends) is in
  scope for us to rebuild against a fixed version, even though the flaw is not
  ours.

## What is not in scope

- **The engineering numbers.** A wrong stiffness or a missed check is a serious
  bug and we want to hear about it — but it is an [issue][issues], not a
  security report. The README says plainly that these are preliminary sizing
  estimates and not a certification, and that validating against a physical
  prototype is the user's job. That is a stated limitation, not a vulnerability.
- **Denial of service by asking for something enormous.** A 200-lobe drive at a
  micron chord tolerance will take a while. That is arithmetic.
- **The SmartScreen warning on the unsigned Windows build.** Known, and on the
  roadmap.

[issues]: https://github.com/medinstech/cycloidgen/issues

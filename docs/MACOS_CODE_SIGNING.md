# Signing and notarizing the macOS app

How to turn the ad-hoc build into something a tester can double-click.

**Status (2026-08-19):** Apple Developer Program enrolled; **no certificates
created yet**. That is the only blocker — `scripts/build-desktop.sh` already
has the signing and notarization paths wired, and skips them cleanly until an
identity exists.

App identifiers, for when a form asks. Apple uses four different things called
some variation of "ID", and they are not interchangeable:

| Name | Value | What it is for |
|---|---|---|
| **Team ID** | `FPG3W3PA24` | `notarytool --team-id`; the parenthesised half of your signing identity. Apple also shows this as **App ID Prefix** on the Identifiers page. |
| **Bundle ID** | `org.pillar43.app` | What the app declares in `tauri.conf.json`; what a provisioning profile binds to; names the sandbox container. | <!-- noqa: FNREF -->
| **App Store Connect Apple ID** | `6803142217` | Identifies the app *record* for a Store submission. Not used by Developer ID or notarization at all. |
| **Account Apple ID** | your email address | What `notarytool --apple-id` authenticates as. |

The last two are the pair people conflate. Notarization wants the **email**;
passing the numeric App Store Connect ID produces an auth error that does not
say so.

Confirm the Team ID at developer.apple.com/account → **Membership**. Once your
certificate exists, your signing identity will read:

```
Developer ID Application: <your name or org> (FPG3W3PA24)
```

---

## What the three things are, and why you need all of them

People conflate these constantly, and the failure modes look identical to the
user (a scary dialog), so they are worth separating:

| | What it proves | Without it |
|---|---|---|
| **Signature** (Developer ID cert) | The bundle came from you and has not been altered | On Apple Silicon an unsigned binary will not execute at all |
| **Hardened runtime** (`--options runtime`) | The process opted into memory/library protections | Notarization refuses the submission |
| **Notarization + staple** | Apple scanned it and issued a ticket, attached to the file | Gatekeeper shows "cannot be opened because Apple cannot check it for malicious software" |

Stapling matters more than it sounds: it attaches the ticket to the `.dmg` so
Gatekeeper can verify **offline**. Notarize without stapling and a tester with
no network sees the same warning as an unnotarized build.

---

## One-time setup

### 1. Create a Developer ID Application certificate

This is the certificate for **direct distribution** (your `.dmg`). It is *not*
the same as the "Apple Distribution" certificate the App Store uses — see
`plans/MAC_APP_STORE_MIGRATION.md`.

Easiest route, if you have Xcode:

> Xcode → Settings → Accounts → select your Apple ID → **Manage Certificates…**
> → **+** → **Developer ID Application**

Without Xcode, via the portal:

1. **Keychain Access → Certificate Assistant → Request a Certificate From a
   Certificate Authority.** Enter your email, choose **Saved to disk**. This
   produces a `.certSigningRequest` file.
2. [developer.apple.com/account/resources/certificates](https://developer.apple.com/account/resources/certificates)
   → **+** → **Developer ID Application** → upload the CSR.
3. Download the resulting `.cer` and double-click it to install into your
   login keychain.

**One catch that stops people:** only the **Account Holder** role can create a
Developer ID certificate. If you are on someone else's team as an Admin or
Developer, the option is simply absent rather than erroring — which reads like
a bug and is not one.

Confirm it landed:

```bash
security find-identity -v -p codesigning
```

You want a line like:

```
1) A1B2C3... "Developer ID Application: Your Name (FPG3W3PA24)"
```

The parenthesised value is your **Team ID** — for this account, `FPG3W3PA24`.
If what comes back differs, the identity belongs to a different team and
everything below needs that value instead.

### 2. Create an app-specific password

Notarization authenticates as your Apple ID but **rejects your real password**.
An app-specific password is a separate 16-character credential scoped to one
tool, revocable on its own.

1. Sign in at [account.apple.com](https://account.apple.com) (the older
   `appleid.apple.com` redirects there).
2. **Sign-In and Security** → **App-Specific Passwords**.
3. **+** / "Generate an app-specific password", label it `pillar43-notary` — the
   label is only how you recognise it in the list later.
4. Copy the value. It looks like `abcd-efgh-ijkl-mnop`; **keep the hyphens**,
   they are part of it.

Two things that actually stop people:

- **Two-factor authentication must already be on.** App-specific passwords do
  not exist without it, and the menu item is simply *absent* rather than
  disabled with an explanation — so it reads as "Apple removed this feature"
  when it means "turn on 2FA first".
- **It is shown exactly once.** There is no way to read it back. If you lose
  it, revoke that entry and generate another; nothing is harmed by doing so as
  long as you re-run `store-credentials` afterwards.

The password authorises notarization submissions for your account, so treat it
like a key: it goes into the keychain (next step), not into a shell history, a
`.env`, or this repo.

### 3. Store the notarization credentials in the keychain

Do this once, then never handle the password again. **Run it with no
arguments** so it prompts for each value — the password is read without
echoing, which keeps it out of your shell history:

```bash
xcrun notarytool store-credentials
```

It asks for a profile name (use `pillar43-notary`), your account Apple ID (the email),
the Team ID (`FPG3W3PA24`), and the app-specific password.

The single-line form exists and is what CI uses, but on a workstation it writes
the password into your shell history in cleartext, so prefer the prompt:

```bash
xcrun notarytool store-credentials "pillar43-notary" \
  --apple-id "you@example.com" --team-id "FPG3W3PA24" --password "xxxx-xxxx-xxxx-xxxx"
```

> **If an app-specific password is ever exposed** — pasted into a chat, a
> commit, a log, a screenshot — revoke it at account.apple.com and generate
> another. It authorises notarization submissions for the whole account, and
> revoking costs nothing as long as you re-run `store-credentials` afterwards.
>
> writes session transcripts to `$NOTES_PATH/ai_learnings/sessions/`, which is
> Pillar-43's own `notes/` mount. Anything landing there is scanned, chunked,
> embedded, and retrievable by the AI sidebar — a secret pasted into a session
> does not just sit in a log, it becomes searchable content in your vault.

---

## Building a signed, notarized release

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (FPG3W3PA24)"
export NOTARY_PROFILE="pillar43-notary"

./scripts/build-desktop.sh
```

The script's seven steps: frontend → backend freeze → resources → bundle →
**sign** → disk image → **notarize + staple**.

Notarization takes minutes, not seconds. `notarytool --wait` blocks until
Apple answers; this is normal, not a hang.

Rebuild flags still work — `SKIP_WEB=1 SKIP_FREEZE=1 ./scripts/build-desktop.sh`
re-signs without re-freezing Python, which is the slow part.

### CI form

For GitHub Actions, where there is no keychain profile to reuse:

```bash
export APPLE_ID="you@example.com"
export APPLE_TEAM_ID="FPG3W3PA24"
export APPLE_APP_PASSWORD="${{ secrets.APPLE_APP_PASSWORD }}"
```

The certificate itself must be imported into a temporary keychain in the
runner — export it as a `.p12` and store the base64 as a secret.

---

## Verify before you ship

Do not infer success from a clean build. Check what a tester will actually get:

```bash
spctl -a -vvv -t install "desktop/src-tauri/target/release/bundle/macos/Pillar-43.app"
```

Expected:

```
accepted
source=Notarized Developer ID
```

Anything else — `source=Unnotarized Developer ID`, or a rejection — means the
warning still appears on their machine. Also confirm the ticket is attached:

```bash
xcrun stapler validate <path-to>.dmg
```

**The real test is a second Mac.** One that has never built this app, with the
`.dmg` downloaded through a browser so it carries the quarantine attribute.
Copying a file over via `scp` or AirDrop does not reproduce what a download
does, and that difference is exactly where "works for me" comes from.

---

## Antivirus false positives are a separate problem

Signing and notarization satisfy **Gatekeeper**, Apple's check. They do not
bind third-party antivirus.

On 2026-08-19 Norton quarantined the PyInstaller-frozen `pillar43-backend` as
`MacOS:MalwareX-gen [Spy]`, killing four consecutive builds. It was a proven
false positive — a frozen binary whose entire source was `print("hello world")`
drew the identical verdict, and the bootloaders verified bit-identical to the
official PyPI wheel — but a build that cannot complete is blocked either way.

**This is now fixed at the root: the app no longer uses PyInstaller.** It ships
a bundled CPython running the backend source, which removes the bootloader stub
and the opaque appended archive that the generic signature actually matches.
See `plans/EMBEDDED_CPYTHON_SIDECAR.md`.

Worth keeping in mind anyway, because the general point outlives this instance:

- **Signing and notarization satisfy Gatekeeper, not third-party antivirus.**
  Apple's ticket says nothing to Norton, Avast or an EDR agent. A notarized app
  can still be quarantined on a tester's machine.
- **Antivirus can break a build, not just a download.** Real-time scanning takes
  the file mid-write, and the build dies somewhere confusing —
  `codesign ... Operation not permitted`, in that case.
- **If it recurs, get a control first.** Building a trivial hello-world through
  the same toolchain took ten seconds and settled in one step what the detection
  was actually keyed on. That beats arguing from the detection name.

---

## Entitlements

`desktop/src-tauri/entitlements.plist` is **empty, deliberately.** Pillar-43 asks
for no hardened-runtime relaxations at all.

It carried three until 2026-08-21 — `allow-jit` and
`allow-unsigned-executable-memory` (on the belief that ONNX Runtime generates
and executes code) and `disable-library-validation` (for PyInstaller's ~157
`dlopen`ed libraries). All three came from analysis rather than a failing
build, because no certificate existed when they were written.

Measured once one did: with the file empty and the hardened runtime enforced,
the bundled interpreter completed a full catalog pass — 5 files, 117 chunks,
**117 real ONNX inferences**. Removing them one at a time and all together
changed nothing. Dropping PyInstaller had already retired the third argument
independently, since every `.so` in the bundle now carries the same Team ID,
which is what library validation asks for.

**Before adding one back, reproduce the failure with it absent and record what
died.** The temptation is to paste in a relaxation because something crashed
near enough to make it plausible; that is how the original three arrived. Test
against a **catalog pass**, not app launch — the embedding path is lazy, so the
process starts fine and dies later if it is going to.

Keeping it empty is worth real effort. Each relaxation widens the attack
surface of a process that reads the user's entire library, and the first two
are refused outright at App Store review.

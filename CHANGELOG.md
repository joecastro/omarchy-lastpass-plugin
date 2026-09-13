# Changelog

## 0.1.0 - Unreleased

- Add an Omarchy bar widget for opening the installed LastPass extension as a
  desktop popup.
- Support Chromium, Chrome, Brave, and Microsoft Edge, including browser
  selection, profile discovery, extension-store links, and web-vault access.
- Keep a single popup instance, move it between workspaces, dismiss it when
  another window is focused, and restore the user's focus settings afterward.
- Add a compact footer with browser, extension, and plugin information.
- Add configurable popup dimensions and optional keyboard-shortcut guidance.
- Implement the helper in typed, standard-library Python with behavioral tests,
  Ruff, mypy, pytest, QML linting, and Omarchy manifest validation.
- Keep transient runtime state in a private, user-owned directory.

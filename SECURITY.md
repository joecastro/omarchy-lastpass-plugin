# Security notes

## Scope

The plugin launches UI provided by the installed LastPass extension. It does
not call LastPass APIs, parse vault data, invoke the LastPass CLI, or access
credentials.

The helper reads:

- extension manifests, to find the popup page and browser profile;
- Hyprland window, process, workspace, pointer, and monitor metadata;
- browser executable paths from `/proc`, to distinguish Chromium-family
  windows that share the same application class;
- the default-browser setting when automatic selection is enabled.

The helper uses the Python standard library plus `hyprctl`, `uwsm-app`,
`wtype`, and `xdg-settings` to launch the selected browser and manage its
window. While the popup is open, it temporarily switches Hyprland to
click-to-focus and restores the previous focus policy when the popup closes.

The helper stores only the managed popup's transient Hyprland window address
in a mode-0700 directory under `XDG_RUNTIME_DIR`. Its `/tmp` fallback is also
user-scoped and private. State files reject symbolic-link targets and are
removed when the popup watcher exits.

## Reporting a problem

Open an issue for ordinary problems or use GitHub's private vulnerability
reporting for sensitive ones. Never include passwords, vault contents, session
tokens, or LastPass exports.

## Screen sharing

The popup may display account names and credential actions. Close it before
sharing your screen. A Hyprland `no_screen_share` rule may also be applied to
the extension window class.

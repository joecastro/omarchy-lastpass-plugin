# Prevent tiling reflow

The helper floats and positions the LastPass popup after the browser creates
it. In a tiling layout, other windows may briefly reflow before that happens.

To make the popup floating from the moment it appears, add these rules to
`~/.config/hypr/bindings.lua`:

```lua
for _, browser_class in ipairs({ "chrome", "msedge" }) do
  o.window("^" .. browser_class .. "-(hdokiejnpimakedhajhdlcegeplioahd|bbcinlkgjjkejfdpemiealijmmooekmp)__webclient-extension-toolbar\\.html-.+$", {
    float = true,
    no_screen_share = true,
  })
end
```

The rules cover Chromium, Chrome, Brave, and Edge; both known LastPass
extension IDs; and any browser profile. `no_screen_share` also keeps the popup
out of Hyprland's screen-sharing picker.

Reload Hyprland and check the configuration:

```bash
hyprctl reload
hyprctl configerrors
```

Remove the rules and reload Hyprland to undo the change.

The plugin does not install these rules automatically. Omarchy plugins have no
install or uninstall hook for compositor configuration, and silently editing a
user's Hyprland files would be difficult to reverse safely.

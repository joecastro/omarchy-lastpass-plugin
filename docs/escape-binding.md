# Optional Escape binding

The LastPass extension page may consume Escape instead of closing its
standalone window. Add this binding to `~/.config/hypr/bindings.lua` to dismiss
the LastPass popup while passing Escape through everywhere else:

```lua
hl.unbind("ESCAPE")
o.bind("ESCAPE", nil, function()
  local window = hl.get_active_window()
  local is_lastpass = window and (
    window.class:match("^chrome%-hdokiejnpimakedhajhdlcegeplioahd")
    or window.class:match("^chrome%-bbcinlkgjjkejfdpemiealijmmooekmp")
    or window.class:match("^msedge%-hdokiejnpimakedhajhdlcegeplioahd")
    or window.class:match("^msedge%-bbcinlkgjjkejfdpemiealijmmooekmp")
  )
  if is_lastpass then
    hl.dispatch(hl.dsp.exec_cmd("omarchy-shell joecastro.lastpass toggle"))
    return { ok = true }
  end

  return { ok = false }
end, { auto_consuming = true })
```

The plugin does not install this binding because community plugins should not
replace global user keybindings automatically.

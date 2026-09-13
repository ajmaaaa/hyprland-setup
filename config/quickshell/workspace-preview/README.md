# Workspace preview

Requires Quickshell 0.3.1 and Hyprland toplevel export. Run `start.sh` from the
Hyprland session; the installer configures automatic startup. Duplicate starts
are ignored.

- Active workspace in the middle, nearest existing workspace above/below.
- Right-aligned cards, smaller neighbors, lower preview dimmed by 16%.
- Labels overlay the lower left with no background or status dot.
- Slide animation, automatic dismissal 1 second after a workspace change.
- Real window captures at native source resolution, mipmapped for downscaling.
- Captures refresh at up to 8 FPS while visible and are released when hidden.
- No keyboard focus or mouse interception.

Captures include window contents and geometry, not wallpaper or desktop panels.
Very small text is limited by the thumbnail size.

```sh
quickshell ipc -p ~/.config/quickshell/workspace-preview call preview reveal
quickshell ipc -p ~/.config/quickshell/workspace-preview call preview status
quickshell kill -p ~/.config/quickshell/workspace-preview
```

To disable startup, remove the preview start command from the active Hyprland
configuration (`hyprland.lua` or `conf.d/autostart.conf`).

References:
- https://quickshell.org/docs/v0.3.1/types/Quickshell.Wayland/ScreencopyView/
- https://doc.qt.io/qt-6/qml-qtquick-item.html#layer.mipmap-prop

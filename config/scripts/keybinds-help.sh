#!/bin/bash

# █░█ ▄▀█ █░░ █░░
# █▀█ █▀█ █▄▄ █▄▄
# ==========================================
#  KEYBINDINGS CHEATSHEET (ROFI)
# ==========================================

THEME="$HOME/.config/rofi/launchers/type-7/style-4.rasi"

gen_list() {
    # APPLICATIONS
    echo "<b>  --- APPLICATIONS ---</b>"
    echo "<b>  App Launcher</b>             <span alpha='60%'>| Mod + Space</span>"
    echo "<b>  Terminal</b>                 <span alpha='60%'>| Mod + Enter</span>"
    echo "<b>  File Manager</b>             <span alpha='60%'>| Mod + f</span>"
    echo "<b>  Browser (Brave)</b>          <span alpha='60%'>| Mod + b</span>"
    echo "<b>  Browser (Zen)</b>            <span alpha='60%'>| Mod + z</span>"
    echo "<b>  Antigravity IDE</b>          <span alpha='60%'>| Mod + c</span>"
    echo "<b>  Neovim</b>                   <span alpha='60%'>| Mod + n</span>"
    echo "<b>  Music Menu</b>               <span alpha='60%'>| Mod + m</span>"
    echo "<b>  Quick Apps</b>               <span alpha='60%'>| Mod + a</span>"

    # SYSTEM
    echo " "
    echo "<b>  --- SYSTEM & UTILITIES ---</b>"
    echo "<b>  Power Menu</b>               <span alpha='60%'>| Mod + Shift + e</span>"
    echo "<b>  VPN (Proton)</b>             <span alpha='60%'>| Mod + v</span>"
    echo "<b>📽️ Projector/Monitor</b>        <span alpha='60%'>| Mod + p</span>"
    echo "<b>  Screenshot Menu</b>          <span alpha='60%'>| Mod + Shift + s</span>"
    echo "<b>  Screenshot (Region)</b>      <span alpha='60%'>| PrintScreen</span>"
    echo "<b>  Screenshot (Full)</b>        <span alpha='60%'>| Shift + PrintScreen</span>"
    echo "<b>  Toggle Wallpaper</b>         <span alpha='60%'>| Mod + Shift + w</span>"
    echo "<b>  Toggle Dark/Light</b>        <span alpha='60%'>| Mod + Shift + n</span>"
    echo "<b>  Reload Config</b>            <span alpha='60%'>| Mod + Shift + c</span>"

    # WINDOW
    echo " "
    echo "<b>  --- WINDOW & LAYOUT ---</b>"
    echo "<b>  Kill Window</b>              <span alpha='60%'>| Mod + q</span>"
    echo "<b>  Fullscreen</b>               <span alpha='60%'>| Mod + ↑</span>"
    echo "<b>  Unfullscreen</b>             <span alpha='60%'>| Mod + ↓</span>"
    echo "<b>  Move Window Left/Right</b>   <span alpha='60%'>| Mod + ← / →</span>"
    echo "<b>  Focus (Vim)</b>              <span alpha='60%'>| Mod + h / j / k / l</span>"
    echo "<b>  Floating Toggle</b>          <span alpha='60%'>| Mod + Shift + Space</span>"
    echo "<b>  True Fullscreen</b>          <span alpha='60%'>| Mod + Shift + f</span>"
    echo "<b>  Toggle Split</b>             <span alpha='60%'>| Mod + Alt + v</span>"
    echo "<b>  Scratchpad (Show)</b>        <span alpha='60%'>| Mod + Minus</span>"
    echo "<b>  Scratchpad (Move)</b>        <span alpha='60%'>| Mod + Shift + Minus</span>"
    echo "<b>  Resize Mode</b>              <span alpha='60%'>| Mod + r</span>"

    # HARDWARE
    echo " "
    echo "<b>  --- HARDWARE ---</b>"
    echo "<b>  Volume Control</b>           <span alpha='60%'>| F1 (Mute) / F2 (-) / F3 (+)</span>"
    echo "<b>  Brightness</b>               <span alpha='60%'>| F5 (Down) / F6 (Up)</span>"
    echo "<b>  Gesture (Swipe)</b>          <span alpha='60%'>| 3 Fingers Left/Right</span>"
}

gen_list | rofi -dmenu -i -markup-rows -p "Keybinds" -theme "$THEME"

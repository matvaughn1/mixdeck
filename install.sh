#!/bin/bash
# Put Mixdeck on the PATH, in the app menu and in login autostart. Safe to re-run.
set -e
R=$(cd "$(dirname "$0")" && pwd)
mkdir -p ~/.local/bin ~/.local/share/applications ~/.config/autostart
ln -sfn "$R/bin/mixdeck" ~/.local/bin/mixdeck && echo "linked ~/.local/bin/mixdeck"

desktop() {  # desktop <file> <extra args>
    cat > "$1" <<DESK
[Desktop Entry]
Type=Application
Name=Mixdeck
GenericName=Audio Mixer
Comment=PipeWire mixer with X-Touch control
Icon=$R/mixdeck/icon.svg
Exec=$HOME/.local/bin/mixdeck $2
Categories=AudioVideo;Audio;Mixer;
StartupWMClass=mixdeck
DESK
    echo "wrote $1"
}
desktop ~/.local/share/applications/mixdeck.desktop ""
desktop ~/.config/autostart/mixdeck.desktop "--hidden"
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

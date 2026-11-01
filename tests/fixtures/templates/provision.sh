#!/usr/bin/env bash
# Installs what the template corpus needs beyond the base TeX packages, without changing any
# template's fonts or packages. Debian/Ubuntu. Safe to re-run. Used by CI's corpus job.
#
#   texlive-xetex, texlive-luatex      XeLaTeX for Awesome-CV and Deedy
#   texlive-fonts-extra                Font Awesome 5, Lato/Roboto (Type 1) for AltaCV
#   texlive-fonts-extra-links          makes TeX Live's OpenType fonts (Roboto) visible to fontconfig
#   fontawesome6/7 (LPPL)              Awesome-CV / moderncv load them; TeX Live 2023 lacks both
#   Source Sans 3 (SIL OFL)            Awesome-CV's main font; from Adobe's repo
set -euo pipefail

if command -v apt-get >/dev/null; then
  SUDO=$([ "$(id -u)" = 0 ] && echo "" || echo sudo)
  $SUDO apt-get install -y --no-install-recommends \
    texlive-xetex texlive-luatex texlive-fonts-extra texlive-fonts-extra-links fontconfig
fi

TEXMFHOME=$(kpsewhich -var-value TEXMFHOME)
# fontawesome6 (Awesome-CV) and fontawesome7 (current moderncv), OpenType only: both templates
# compile with LuaLaTeX here. Branch fa6 holds version 6, main holds version 7.
for v in 6 7; do
  branch=$([ "$v" = 6 ] && echo fa6 || echo main)
  FA=https://raw.githubusercontent.com/braniii/fontawesome/$branch/fontawesome$v
  mkdir -p "$TEXMFHOME/tex/latex/fontawesome$v" "$TEXMFHOME/fonts/opentype/fontawesome$v"
  for f in "fontawesome$v.sty" "fontawesome$v-mapping.def" "fontawesome$v-generic-helper.sty" \
           "fontawesome$v-utex-helper.sty" "fontawesome$v.lua" "tufontawesome${v}free.fd" \
           "tufontawesome${v}brands.fd" "tufontawesome${v}pro.fd"; do
    curl -fsSL -o "$TEXMFHOME/tex/latex/fontawesome$v/$f" "$FA/tex/$f"
  done
  for f in "FontAwesome${v}Free-Solid-900.otf" "FontAwesome${v}Free-Regular-400.otf" \
           "FontAwesome${v}Brands-Regular-400.otf"; do
    curl -fsSL -o "$TEXMFHOME/fonts/opentype/fontawesome$v/$f" "$FA/opentype/$f"
  done
done

FONTS="${XDG_DATA_HOME:-$HOME/.local/share}/fonts/source-sans-3"
SS3=https://raw.githubusercontent.com/adobe-fonts/source-sans/release/OTF
mkdir -p "$FONTS"
for w in Regular It Bold BoldIt Light LightIt; do
  curl -fsSL -o "$FONTS/SourceSans3-$w.otf" "$SS3/SourceSans3-$w.otf"
done
fc-cache -f >/dev/null
mktexlsr "$TEXMFHOME" >/dev/null 2>&1 || true
luaotfload-tool --update >/dev/null 2>&1 || true
echo "fontawesome6: $(kpsewhich fontawesome6.sty)  fontawesome7: $(kpsewhich fontawesome7.sty)"
echo "Source Sans 3: $(fc-list | grep -c 'Source Sans 3') faces; Roboto: $(fc-list | grep -c 'Roboto') faces"

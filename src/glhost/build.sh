#!/bin/sh
# Compila o renderizador do host (bin/glhost).
set -e
cd "$(dirname "$0")"
mkdir -p ../../bin
cp ../shim/glops.h ../shim/gen_host.inc ../shim/opnames.inc ../shim/gl_hand_names.inc . 2>/dev/null || true
case "$(uname -s)" in
  Darwin)
    "${CC:-clang}" -O2 -Wno-everything host.c pngload.c -framework GLUT -framework OpenGL \
      -framework ApplicationServices -framework CoreFoundation -o ../../bin/glhost
    ;;
  Linux)
    pixbuf_flags=$(pkg-config --cflags --libs gdk-pixbuf-2.0)
    "${CC:-cc}" ${CPPFLAGS:-} ${CFLAGS:-} -O2 host.c pngload.c ${LDFLAGS:-} \
      $pixbuf_flags -lglut -lGL -lX11 -lm -o ../../bin/glhost
    ;;
  *)
    echo "glhost requires macOS or Linux (including WSL2)." >&2
    exit 1
    ;;
esac
ls -l ../../bin/glhost

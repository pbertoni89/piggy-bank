# Piggy Bank: PySide6 + QtWebEngine GUI and JupyterLab, in one image.
# Use the driver.sh wrappers rather than these commands directly:
#   ./driver.sh --docker-build-image   build the image (as your UID/GID)
#   ./driver.sh --docker-run-gui       show the GUI on the host's X server
#   ./driver.sh --docker-jupyter       JupyterLab on piggy_bank/, at http://127.0.0.1:8888
#   docker run --rm piggy-bank test    run the test suite offscreen
#
# Real data is never baked into the image: driver.sh mounts data/ at /app/data at runtime.

FROM python:3.14-slim

# Runtime libraries for Qt 6 (xcb platform plugin) and QtWebEngine (Chromium).
# The PySide6 wheels bundle Qt itself, but not these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libopengl0 libglib2.0-0 libdbus-1-3 \
        libfontconfig1 libfreetype6 fonts-dejavu-core \
        libxkbcommon0 libxkbcommon-x11-0 libxkbfile1 \
        libx11-6 libx11-xcb1 libxext6 libxrender1 libxi6 libxtst6 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxshmfence1 \
        libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxcb-xfixes0 libxcb-glx0 \
        libnss3 libnspr4 libasound2t64 libdrm2 libgbm1 libcups2t64 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Chromium's sandbox needs user namespaces, which containers usually don't grant
    QTWEBENGINE_DISABLE_SANDBOX=1 \
    # Software rendering by default: without the host GPU, Chromium's GPU init hangs the first
    # QWebEngineView forever. driver.sh's PIGGYBANK_GPU=1 passes /dev/dri and overrides both.
    QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu \
    LIBGL_ALWAYS_SOFTWARE=1 \
    QT_X11_NO_MITSHM=1

WORKDIR /app

# Dependencies, from the heaviest/most stable layer to the most volatile. Editing pyproject.toml only
# rebuilds layer C, and the BuildKit cache mount keeps pip's downloads across rebuilds anyway.

# Layer A: PyTorch (pulled by sentence_transformers), CPU-only build. The PyPI one is the CUDA build,
# which drags in GBs of nvidia-* wheels. The constraint pins it, so no later layer can swap it back.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip freeze | grep -i '^torch==' > /etc/pip-constraints.txt
ENV PIP_CONSTRAINT=/etc/pip-constraints.txt

# Layer B: other heavy, rarely changing packages
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install PySide6 superqt

# Layer C: everything else, read straight from pyproject.toml (runtime + dev + notebook extras)
COPY pyproject.toml ./
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
p = tomllib.load(open("pyproject.toml", "rb"))["project"]
extras = p["optional-dependencies"]
print("\n".join(p["dependencies"] + extras["dev"] + extras["notebook"]))
EOF
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

# Source, then an editable install: DATA_DIR is resolved relative to the source tree (/app/data/etica)
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps -e . \
    && for f in piggy_bank/ui/*.ui; do pyside6-uic "$f" -o "${f%.ui}_rc.py"; done

# Non-root user matching the host's, so load_data()'s writes into the mounted data/ keep your ownership
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" piggy && useradd -m -u "${UID}" -g "${GID}" piggy \
    && mkdir -p /app/data/etica && chown -R piggy:piggy /app \
    # Mount point of driver.sh's model-cache volume: it must already exist and be owned by piggy,
    # because a new named volume copies its ownership from the image
    # (.cache listed too, or install creates it root-owned and matplotlib can't write its cache)
    && install -d -o piggy -g piggy /home/piggy/.cache /home/piggy/.cache/huggingface
USER piggy

COPY --chmod=755 <<'EOF' /usr/local/bin/entrypoint
#!/bin/sh
set -e
case "${1:-gui}" in
  gui)    shift 2>/dev/null || true; exec piggy-bank "$@" ;;
  test)   shift; export QT_QPA_PLATFORM=offscreen; exec python -m pytest "$@" ;;
  driver) shift; exec python piggy_bank/driver.py "$@" ;;
  jupyter)
    shift
    exec jupyter lab --ip=0.0.0.0 --port=8888 --no-browser \
         --ServerApp.root_dir=/app/piggy_bank "$@" ;;
  *)      exec "$@" ;;
esac
EOF

EXPOSE 8888

ENTRYPOINT ["entrypoint"]
CMD ["gui"]

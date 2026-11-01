#!/bin/bash
dirRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dirVenv=${dirRoot}/.venv

# Container engine and image name, overridable from the environment (e.g. PIGGYBANK_ENGINE=podman)
dockerEngine="${PIGGYBANK_ENGINE:-docker}"
dockerImage="${PIGGYBANK_IMAGE:-pbertoni/pyside-jupyterlab:piggy-bank}"
jupyterPort="${PIGGYBANK_JUPYTER_PORT:-8888}"
# Named volume for the Hugging Face cache (sentence_transformers models), so they're downloaded once
# and survive the --rm containers. Remove it with: docker volume rm piggy-bank-hf-cache
hfCacheVolume="${PIGGYBANK_HF_VOLUME:-piggy-bank-hf-cache}"
hfCacheMount="${hfCacheVolume}:/home/piggy/.cache/huggingface"


function pb_docker_build_image() {
  "${dockerEngine}" build -t "${dockerImage}" \
    --build-arg UID="$(id -u)" --build-arg GID="$(id -g)" \
    "${dirRoot}"
}


# Prints 'dark', 'light' or nothing: the host desktop's colour scheme, from $PIGGYBANK_COLOR_SCHEME if
# set, else from the freedesktop settings portal (KDE, GNOME, ...). Qt in the container can't read it:
# that would need the session D-Bus mounted, which would expose the whole desktop to the container.
function pb_host_color_scheme() {
  if [[ -n "${PIGGYBANK_COLOR_SCHEME}" ]]; then
    echo "${PIGGYBANK_COLOR_SCHEME}"
    return
  fi
  command -v gdbus > /dev/null || return 0
  # Answers e.g. "(<<uint32 1>>,)": 1 = prefer dark, 2 = prefer light, 0 = no preference
  case "$(gdbus call --session --timeout 2 --dest org.freedesktop.portal.Desktop \
            --object-path /org/freedesktop/portal/desktop \
            --method org.freedesktop.portal.Settings.ReadOne \
            org.freedesktop.appearance color-scheme 2> /dev/null)" in
    *"uint32 1"*) echo dark ;;
    *"uint32 2"*) echo light ;;
  esac
}


function pb_docker_run_gui() {
  [[ -n "${DISPLAY}" ]] || { echo "DISPLAY is not set: no X server to show the GUI on"; return 4; }
  # Let the container's user (same UID as ours) talk to the X server
  if command -v xhost > /dev/null; then
    xhost "+SI:localuser:$(id -un)" > /dev/null
  else
    echo "xhost not found: if the GUI can't open the display, install xorg-x11-server-utils / x11-xserver-utils"
  fi
  mkdir -p "${dirRoot}/data/etica"
  # The image renders in software by default. PIGGYBANK_GPU=1 passes the host GPU (Mesa drivers:
  # Intel/AMD) and re-enables Chromium's GPU path. If the window never appears with it, drop it.
  local gpuArgs=()
  if [[ "${PIGGYBANK_GPU:-0}" == 1 ]]; then
    [[ -d /dev/dri ]] || { echo "PIGGYBANK_GPU=1 but /dev/dri doesn't exist on this host"; return 5; }
    gpuArgs=(--device /dev/dri -e QTWEBENGINE_CHROMIUM_FLAGS= -e LIBGL_ALWAYS_SOFTWARE=0)
    local grp gid
    for grp in video render; do
      gid="$(getent group "${grp}" | cut -d: -f3)"
      [[ -n "${gid}" ]] && gpuArgs+=(--group-add "${gid}")
    done
  fi
  local colorScheme
  colorScheme="$(pb_host_color_scheme)"
  echo "Colour scheme: ${colorScheme:-unknown, Qt default (light)}"
  # :z relabels the bind mounts for SELinux (Fedora); --shm-size because Chromium outgrows the 64 MB default
  "${dockerEngine}" run --rm -it \
    -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
    -e PIGGYBANK_COLOR_SCHEME="${colorScheme}" \
    -v "${dirRoot}/data:/app/data:z" \
    -v "${hfCacheMount}" \
    --shm-size=512m \
    "${gpuArgs[@]}" \
    "${dockerImage}" gui "${@}"
}


function pb_docker_jupyter() {
  mkdir -p "${dirRoot}/data/etica"
  # piggy_bank/ is mounted (not baked) so notebook edits land in the repo and etica.py changes are live.
  # The port is bound to localhost only: the notebooks see real bank data.
  echo "JupyterLab on http://127.0.0.1:${jupyterPort} (open the URL with ?token=... printed below)"
  "${dockerEngine}" run --rm -it \
    -p "127.0.0.1:${jupyterPort}:8888" \
    -v "${dirRoot}/piggy_bank:/app/piggy_bank:z" \
    -v "${dirRoot}/data:/app/data:z" \
    -v "${hfCacheMount}" \
    "${dockerImage}" jupyter "${@}"
}


function pb_activate_venv() {
  source "${dirVenv}/bin/activate"
}


# Creates ${dirVenv} if it isn't a venv yet, then installs the project (editable, as DATA_DIR requires)
# with all the extras in pyproject.toml. On an existing venv, pip only installs what's missing.
# torch is CPU-only, as in the Dockerfile: PyPI's torch is the CUDA build (GBs of nvidia-* wheels), and
# recent CUDA builds don't even support older GPUs (e.g. Quadro P1000, sm_61: "no kernel image is
# available"). A CUDA torch found in the venv is replaced, and the installed +cpu version is pinned in
# ${dirVenv}/pip-constraints.txt, so a dependency that wants another torch fails instead of pulling CUDA.
function pb_update_venv() {
  if [[ -f "${dirVenv}/pyvenv.cfg" && -x "${dirVenv}/bin/python" ]]; then
    echo "Updating the venv in ${dirVenv}"
  else
    echo "${dirVenv} is not a Python venv: creating it"
    python3 -m venv "${dirVenv}" || return 1
  fi
  local extras
  extras="$("${dirVenv}/bin/python" -c "import tomllib; f = open('${dirRoot}/pyproject.toml', 'rb'); \
print(','.join(tomllib.load(f)['project'].get('optional-dependencies', {})))")" || return 2
  local pip=("${dirVenv}/bin/python" -m pip)
  local constraints="${dirVenv}/pip-constraints.txt"
  "${pip[@]}" install --upgrade pip || return 3
  local cudaWheels
  cudaWheels="$("${pip[@]}" freeze | grep -E '^(torch==.*\+cu|nvidia-|cuda-|triton==)' | cut -d= -f1)"
  if [[ -n "${cudaWheels}" ]]; then
    echo "Removing the CUDA build of torch and its wheels:" ${cudaWheels}
    # shellcheck disable=SC2086
    "${pip[@]}" uninstall -y ${cudaWheels} || return 5
    rm -f "${constraints}"
  fi
  "${pip[@]}" install torch --index-url https://download.pytorch.org/whl/cpu || return 6
  "${pip[@]}" freeze | grep -i '^torch==' > "${constraints}"
  "${pip[@]}" install -c "${constraints}" -e "${dirRoot}${extras:+[${extras}]}" || return 4
}


function pb_run_designer() {
  nohup pyside6-designer "${dirRoot}"/piggy_bank/ui/*.ui &
}


function pb_build_ui() {
  pushd "${dirRoot}"/piggy_bank/ui > /dev/null || return 1
  local ui_file
  local rc_file
  for ui_file in *.ui; do
    [[ -f "${ui_file}" ]] && {
      rc_file="${ui_file%.ui}_rc.py"
      echo "Building UI for ${ui_file} -> ${rc_file}"
      pyside6-uic "${ui_file}" -o "${rc_file}" || {
        echo "Failed to build UI for ${ui_file}"
        popd > /dev/null || return 1
        return 2
      }
    }
  done
  popd > /dev/null || return 1
  echo "UI built successfully"
}


function pb_run_gui() {
  pushd "${dirRoot}" > /dev/null || return 1

  python -c "import superqt; print(f'superqt version {superqt.__version__} is installed')" || {
    echo "superqt is not installed. Please install it with 'pip install superqt'"
    popd > /dev/null || return 1
    return 3
  }

  set -x
  PYTHONPATH=. python piggy_bank/main_window.py
  local rc=${?}
  { set +x; } 2>/dev/null
  echo "UI exited with code ${rc}."
  popd > /dev/null || return 1
  return ${rc}
}


function pb_deprecated_headless() {
  pushd "${dirRoot}" > /dev/null || return 1
  PYTHONPATH=. python piggy_bank/driver.py
  local rc=${?}
  echo "Driver exited with code ${rc}."
  popd > /dev/null || return 1
  return ${rc}
}


function pb_run_tests() {
  # Build first, otherwise the widget tests are skipped
  pb_build_ui || return ${?}
  pushd "${dirRoot}" > /dev/null || return 1
  python -m pytest "${@}"
  local rc=${?}
  popd > /dev/null || return 1
  return ${rc}
}


function pb_usage() {
  echo "Usage: $0 OPTION [args...]"
  echo "Local (uses ${dirVenv}):"
  echo "  --update-venv:         Create the venv if needed, install pyproject.toml's packages (all extras)"
  echo "  --run-gui:             Run the GUI (build it first with --build-gui)"
  echo "  --build-gui:           Compile piggy_bank/ui/*.ui into *_rc.py"
  echo "  --run-designer:        Open the .ui files in Qt Designer"
  echo "  --build-run-tests:     Build the UI and run the test suite (extra args go to pytest)"
  echo "  --deprecated-headless: Run the headless driver"
  echo "Docker (no local .venv needed; set PIGGYBANK_ENGINE=podman to use podman):"
  echo "  --docker-build-image:  Build the '${dockerImage}' image"
  echo "  --docker-run-gui:      Run the GUI in a container, on the host's X display"
  echo "  --docker-jupyter:      Run JupyterLab on piggy_bank/ at http://127.0.0.1:${jupyterPort}"
  echo "  -h, --help:            Show this help message"
  exit "${1:-0}"
}


if [[ ${BASH_SOURCE[0]} == "${0}" ]]; then
  # Only the first option is read; the rest are passed to the chosen command.
  # Docker options don't source the venv, so they work on a host without one.
  option="${1}"
  shift
  case "${option}" in
    --update-venv)
      pb_update_venv ;;
    --run-gui)
      pb_activate_venv; pb_run_gui ;;
    --build-gui)
      pb_activate_venv; pb_build_ui ;;
    --run-designer)
      pb_activate_venv; pb_run_designer ;;
    --build-run-tests)
      pb_activate_venv; pb_run_tests "${@}" ;;
    --deprecated-headless)
      pb_activate_venv; pb_deprecated_headless ;;
    --docker-build-image)
      pb_docker_build_image "${@}" ;;
    --docker-run-gui)
      pb_docker_run_gui "${@}" ;;
    --docker-jupyter)
      pb_docker_jupyter "${@}" ;;
    -h|--help)
      pb_usage 0 ;;
    *)
      pb_usage 3 ;;
  esac
  exit ${?}
else
  echo "Sourced ${BASH_SOURCE[0]}: type pb_ and tabulate to discover new functions"
fi

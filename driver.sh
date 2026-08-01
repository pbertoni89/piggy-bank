#!/bin/bash
dirRoot="$(dirname "${BASH_SOURCE[0]}")"
source "$dirRoot/.venv/bin/activate"


function run_designer() {
  nohup pyside6-designer &
}


function build_ui() {
  pushd "${dirRoot}"/piggy_bank/ui > /dev/null || return 1
  local ui_file
  local rc_file
  for ui_file in *.ui; do
    [[ -f "${ui_file}" ]] && {
      rc_file="${ui_file%.ui}_rc.py"
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


function build_run_ui() {
  build_ui
  pushd "${dirRoot}" > /dev/null || return 1

  python -c "import superqt; print(f'superqt version {superqt.__version__} is installed')" || {
    echo "superqt is not installed. Please install it with 'pip install superqt'"
    popd > /dev/null || return 1
    return 3
  }

  PYTHONPATH=. python piggy_bank/main_window.py
  echo "UI exited with code ${?}."
  popd > /dev/null || return 1
}


function usage() {
  echo "Usage: $0 [-d] [-r] [-b] [-h] [-i]"
  echo "  -d: Run Qt Designer"
  echo "  -r: Build and run the UI"
  echo "  -i: Run the headless driver"
  echo "  -b: Build the UI"
  echo "  -h: Show this help message"
  exit "${1:-0}"
}


getopts "drbhi" opt
case ${opt} in
  d)
    run_designer
    ;;
  r)
    build_run_ui
    ;;
  i)
    pushd "${dirRoot}" > /dev/null || return 1
    PYTHONPATH=. python piggy_bank/driver.py
    echo "Driver exited with code ${?}."
    popd > /dev/null || return 1
    ;;
  b)
    build_ui
    ;;
  h)
    usage 0
    ;;
  *)
    usage 3
    ;;
esac

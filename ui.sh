#!/bin/bash
dirRoot="$(dirname "${BASH_SOURCE[0]}")"
source "$dirRoot/.venv/bin/activate"


function run_designer() {
  nohup pyside6-designer &
}


function build_ui() {
  pushd "${dirRoot}"/piggy_bank/src/ui > /dev/null || return 1
  pyside6-uic main_window.ui -o main_window_rc.py || {
    echo "Failed to build UI."
    popd > /dev/null || return 1
    return 2
  }
  popd > /dev/null || return 1
  echo "UI built successfully."
}


function build_run_ui() {
  build_ui
  pushd "${dirRoot}" > /dev/null || return 1

  python -c "import superqt; print(f'superqt version {superqt.__version__} is installed')" || {
    echo "superqt is not installed. Please install it with 'pip install superqt'."
    popd > /dev/null || return 1
    return 3
  }

  PYTHONPATH=. python piggy_bank/src/main_window.py
  echo "UI exited with code ${?}."
  popd > /dev/null || return 1
}


function usage() {
  echo "Usage: $0 [-d] [-r] [-b] [-h]"
  echo "  -d: Run Qt Designer"
  echo "  -r: Build and run the UI"
  echo "  -b: Build the UI"
  echo "  -h: Show this help message"
  exit "${1:-0}"
}


getopts "drbh" opt
case ${opt} in
  d)
    run_designer
    ;;
  r)
    build_run_ui
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

#!/bin/bash
dirRoot="$(dirname "${BASH_SOURCE[0]}")"
source "${dirRoot}/.venv/bin/activate"


function piggybank_run_designer() {
  nohup pyside6-designer "${dirRoot}"/piggy_bank/ui/*.ui &
}


function piggybank_build_ui() {
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


function piggybank_build_run_ui() {
  piggybank_build_ui
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
}


function piggybank_run_tests() {
  # Build first, otherwise the widget tests are skipped
  piggybank_build_ui || return ${?}
  pushd "${dirRoot}" > /dev/null || return 1
  python -m pytest "${@}"
  local rc=${?}
  popd > /dev/null || return 1
  return ${rc}
}


function piggybank_usage() {
  echo "Usage: $0 [-d] [-r] [-b] [-h] [-i] [-t [pytest args...]]"
  echo "  -d: Run Qt Designer"
  echo "  -r: Build and run the UI"
  echo "  -i: Run the headless driver"
  echo "  -b: Build the UI"
  echo "  -t: Build the UI and run the test suite (extra args go to pytest)"
  echo "  -h: Show this help message"
  exit "${1:-0}"
}


getopts "drbhit" opt
shift $((OPTIND - 1))
case ${opt} in
  d)
    piggybank_run_designer
    ;;
  r)
    piggybank_build_run_ui
    ;;
  i)
    pushd "${dirRoot}" > /dev/null || return 1
    PYTHONPATH=. python piggy_bank/driver.py
    echo "Driver exited with code ${?}."
    popd > /dev/null || return 1
    ;;
  b)
    piggybank_build_ui
    ;;
  t)
    piggybank_run_tests "${@}"
    exit ${?}
    ;;
  h)
    piggybank_usage 0
    ;;
  *)
    piggybank_usage 3
    ;;
esac

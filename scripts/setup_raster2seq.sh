#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${BAOJU_RASTER2SEQ_ROOT:-${PROJECT_ROOT}/models/Raster2Seq}"
PYTHON_BIN="${BAOJU_RASTER2SEQ_BOOTSTRAP_PYTHON:-python3.10}"
VENV="${TARGET}/.venv"
PINNED_COMMIT="a6c4e27a68d11d7a459f6e4a2601fd887227dd1a"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Raster2Seq requires Python 3.10. Install it, then rerun with BAOJU_RASTER2SEQ_BOOTSTRAP_PYTHON." >&2
  exit 1
fi

if [[ ! -d "${TARGET}/.git" ]]; then
  git clone https://github.com/Cornell-VAILab/Raster2Seq.git "${TARGET}"
fi

git -C "${TARGET}" fetch origin
git -C "${TARGET}" checkout "${PINNED_COMMIT}"
"${PYTHON_BIN}" -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip wheel setuptools
"${VENV}/bin/python" -m pip install \
  torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 \
  --index-url https://download.pytorch.org/whl/cu118
"${VENV}/bin/python" -m pip install -r "${TARGET}/requirements.txt" huggingface_hub

(
  cd "${TARGET}/models/ops"
  bash make.sh
)
(
  cd "${TARGET}/diff_ras"
  "${VENV}/bin/python" setup.py build develop
)

echo
echo "Raster2Seq installation completed. Start Baoju with:"
echo "BAOJU_RASTER2SEQ_ROOT=${TARGET} \\"
echo "BAOJU_RASTER2SEQ_PYTHON=${VENV}/bin/python \\"
echo "python -m uvicorn backend.app.main:app --reload"

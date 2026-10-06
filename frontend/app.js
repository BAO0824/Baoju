const $ = (selector) => document.querySelector(selector);
const state = {
  imageFile: null,
  imageUrl: null,
  imageSize: null,
  model: null,
  providerAvailable: false,
  selectedWallId: null,
  viewMode: "overlay",
  calibrationPicking: false,
  calibrationPoints: [],
};

const elements = {
  imageInput: $("#imageInput"),
  jsonInput: $("#jsonInput"),
  dropZone: $("#dropZone"),
  recognizeButton: $("#recognizeButton"),
  providerCard: $("#providerCard"),
  canvas: $("#floorplanCanvas"),
  emptyState: $("#emptyState"),
  sourceImage: $("#sourceImage"),
  roomLayer: $("#roomLayer"),
  wallLayer: $("#wallLayer"),
  openingLayer: $("#openingLayer"),
  calibrationLayer: $("#calibrationLayer"),
  opacityInput: $("#opacityInput"),
  canvasMeta: $("#canvasMeta"),
  toast: $("#toast"),
  saveState: $("#saveState"),
  downloadButton: $("#downloadButton"),
  modelSummary: $("#modelSummary"),
  wallInspector: $("#wallInspector"),
  wallTitle: $("#wallTitle"),
  wallLengthInput: $("#wallLengthInput"),
  wallThicknessInput: $("#wallThicknessInput"),
  lengthLabel: $("#lengthLabel"),
  issuesSection: $("#issuesSection"),
  issuesList: $("#issuesList"),
  calibrationPanel: $("#calibrationPanel"),
  calibrationHint: $("#calibrationHint"),
  pickCalibrationButton: $("#pickCalibrationButton"),
  distanceInput: $("#distanceInput"),
  applyCalibrationButton: $("#applyCalibrationButton"),
};

const svg = (tag, attributes = {}) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
};

function showToast(message, timeout = 5200) {
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => (elements.toast.hidden = true), timeout);
}

function markDirty() {
  elements.saveState.textContent = "尚未匯出變更";
}

async function loadProviderStatus() {
  try {
    const response = await fetch("/api/providers");
    if (!response.ok) throw new Error("無法讀取 provider 狀態");
    const [provider] = await response.json();
    state.providerAvailable = Boolean(provider?.available);
    elements.providerCard.className = `status-card ${state.providerAvailable ? "ready" : "unavailable"}`;
    elements.providerCard.innerHTML = state.providerAvailable
      ? `<span class="status-dot"></span><div><strong>Raster2Seq 已就緒</strong><small>${provider.model}・${provider.device}</small></div>`
      : `<span class="status-dot"></span><div><strong>AI 主機尚未就緒</strong><small>${escapeHtml(provider?.reason || "未安裝模型")}</small></div>`;
  } catch (error) {
    state.providerAvailable = false;
    elements.providerCard.className = "status-card unavailable";
    elements.providerCard.innerHTML = `<span class="status-dot"></span><div><strong>API 無法連線</strong><small>${escapeHtml(error.message)}</small></div>`;
  }
  updateRecognizeButton();
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value);
  return node.innerHTML;
}

function updateRecognizeButton() {
  elements.recognizeButton.disabled = !state.imageFile || !state.providerAvailable;
}

async function setImageFile(file) {
  if (!file?.type?.startsWith("image/")) {
    showToast("請選擇 PNG、JPG 或 WEBP 圖片。");
    return;
  }
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageFile = file;
  state.imageUrl = URL.createObjectURL(file);
  const dimensions = await readImageDimensions(state.imageUrl);
  state.imageSize = dimensions;
  state.model = null;
  state.selectedWallId = null;
  state.calibrationPoints = [];
  elements.sourceImage.setAttribute("href", state.imageUrl);
  showCanvas(dimensions.width, dimensions.height);
  elements.canvasMeta.textContent = `${file.name}・${dimensions.width} × ${dimensions.height}px`;
  elements.saveState.textContent = "圖片已載入，尚未辨識";
  elements.dropZone.querySelector("strong").textContent = file.name;
  elements.dropZone.querySelector("small").textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
  clearGeometry();
  updateRecognizeButton();
}

function readImageDimensions(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = reject;
    image.src = url;
  });
}

function showCanvas(width, height) {
  elements.emptyState.hidden = true;
  elements.canvas.hidden = false;
  elements.canvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
  elements.sourceImage.setAttribute("width", width);
  elements.sourceImage.setAttribute("height", height);
  updateViewMode();
}

function clearGeometry() {
  [elements.roomLayer, elements.wallLayer, elements.openingLayer, elements.calibrationLayer].forEach(
    (layer) => layer.replaceChildren(),
  );
  elements.modelSummary.innerHTML = ["房間", "牆", "門窗"]
    .map((label) => `<div><strong>—</strong><span>${label}</span></div>`)
    .join("");
  elements.wallInspector.hidden = true;
  elements.issuesSection.hidden = true;
  elements.calibrationPanel.hidden = true;
  elements.downloadButton.disabled = true;
}

async function recognize() {
  if (!state.imageFile || !state.providerAvailable) return;
  const form = new FormData();
  form.append("file", state.imageFile);
  elements.recognizeButton.disabled = true;
  elements.recognizeButton.textContent = "AI 辨識中…";
  try {
    const response = await fetch("/api/recognize", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail || {};
      throw new Error(detail.reason || detail.message || "辨識失敗");
    }
    loadModel(payload.model);
    showToast(`Raster2Seq 已產生 ${payload.rawPredictionCount} 個 polygons，請開始校正與檢查。`);
  } catch (error) {
    showToast(error.message, 9000);
  } finally {
    elements.recognizeButton.textContent = "執行 AI 格局辨識";
    updateRecognizeButton();
  }
}

function loadModel(model) {
  if (!model?.nodes || !model?.walls || !model?.rooms || !model?.coordinateSpace) {
    throw new Error("這不是有效的 Baoju geometry JSON。");
  }
  state.model = model;
  state.selectedWallId = null;
  state.calibrationPoints = [];
  state.calibrationPicking = false;
  showCanvas(model.coordinateSpace.width, model.coordinateSpace.height);
  elements.canvasMeta.textContent = `${model.rooms.length} 房間・${model.walls.length} 牆・${model.calibration.coordinateUnit}`;
  elements.downloadButton.disabled = false;
  elements.saveState.textContent = "模型已載入";
  renderModel();
}

function nodeMap() {
  return new Map((state.model?.nodes || []).map((node) => [node.id, node]));
}

function renderModel() {
  if (!state.model) return;
  const nodes = nodeMap();
  elements.roomLayer.replaceChildren();
  elements.wallLayer.replaceChildren();
  elements.openingLayer.replaceChildren();

  state.model.rooms.forEach((room) => {
    const points = room.nodeIds.map((id) => nodes.get(id)).filter(Boolean);
    if (points.length < 3) return;
    const polygon = svg("polygon", {
      points: points.map((point) => `${point.x},${point.y}`).join(" "),
      class: "room-shape",
      "data-room-id": room.id,
    });
    elements.roomLayer.append(polygon);
  });

  state.model.walls.forEach((wall) => {
    const start = nodes.get(wall.startNode);
    const end = nodes.get(wall.endNode);
    if (!start || !end) return;
    const line = svg("line", {
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      class: `wall-line${wall.id === state.selectedWallId ? " selected" : ""}`,
      "data-wall-id": wall.id,
    });
    line.addEventListener("click", (event) => {
      event.stopPropagation();
      selectWall(wall.id);
    });
    elements.wallLayer.append(line);
  });

  state.model.openings.forEach((opening) => {
    const wall = state.model.walls.find((candidate) => candidate.id === opening.wallId);
    if (!wall || opening.offset == null) return;
    const start = nodes.get(wall.startNode);
    const end = nodes.get(wall.endNode);
    if (!start || !end) return;
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (!length) return;
    const ux = (end.x - start.x) / length;
    const uy = (end.y - start.y) / length;
    const from = Math.max(0, opening.offset - opening.width / 2);
    const to = Math.min(length, opening.offset + opening.width / 2);
    elements.openingLayer.append(
      svg("line", {
        x1: start.x + ux * from,
        y1: start.y + uy * from,
        x2: start.x + ux * to,
        y2: start.y + uy * to,
        class: "opening-line",
        "data-opening-id": opening.id,
      }),
    );
  });

  elements.modelSummary.innerHTML = [
    [state.model.rooms.length, "房間"],
    [state.model.walls.length, "牆"],
    [state.model.openings.length, "門窗"],
  ]
    .map(([value, label]) => `<div><strong>${value}</strong><span>${label}</span></div>`)
    .join("");
  renderIssues();
  renderCalibration();
  updateInspector();
  updateViewMode();
}

function renderIssues() {
  const issues = state.model?.issues || [];
  elements.issuesSection.hidden = issues.length === 0;
  elements.issuesList.innerHTML = issues
    .map((issue) => `<div class="issue ${escapeHtml(issue.severity)}">${escapeHtml(issue.message)}</div>`)
    .join("");
}

function selectWall(wallId) {
  state.selectedWallId = wallId;
  renderModel();
}

function updateInspector() {
  const wall = state.model?.walls.find((candidate) => candidate.id === state.selectedWallId);
  elements.wallInspector.hidden = !wall;
  if (!wall) return;
  const nodes = nodeMap();
  const start = nodes.get(wall.startNode);
  const end = nodes.get(wall.endNode);
  const length = Math.hypot(end.x - start.x, end.y - start.y);
  const unit = state.model.calibration.coordinateUnit;
  elements.wallTitle.textContent = wall.id;
  elements.lengthLabel.textContent = `長度（${unit}）`;
  elements.wallLengthInput.value = Math.round(length * 100) / 100;
  elements.wallThicknessInput.value = wall.thicknessMm || "";
}

function updateWallLength() {
  const wall = state.model?.walls.find((candidate) => candidate.id === state.selectedWallId);
  const newLength = Number(elements.wallLengthInput.value);
  if (!wall || !Number.isFinite(newLength) || newLength <= 0) return;
  const nodes = nodeMap();
  const start = nodes.get(wall.startNode);
  const end = nodes.get(wall.endNode);
  const oldLength = Math.hypot(end.x - start.x, end.y - start.y);
  if (!oldLength) return;
  const ux = (end.x - start.x) / oldLength;
  const uy = (end.y - start.y) / oldLength;
  end.x = start.x + ux * newLength;
  end.y = start.y + uy * newLength;
  markDirty();
  renderModel();
}

function updateWallThickness() {
  const wall = state.model?.walls.find((candidate) => candidate.id === state.selectedWallId);
  const value = Number(elements.wallThicknessInput.value);
  if (!wall || !Number.isFinite(value) || value <= 0) return;
  wall.thicknessMm = value;
  markDirty();
}

function updateViewMode() {
  const showImage = state.viewMode !== "geometry";
  const showGeometry = state.viewMode !== "image";
  elements.sourceImage.style.display = showImage ? "block" : "none";
  elements.sourceImage.style.opacity = Number(elements.opacityInput.value) / 100;
  [elements.roomLayer, elements.wallLayer, elements.openingLayer].forEach(
    (layer) => (layer.style.display = showGeometry ? "block" : "none"),
  );
}

function canvasPoint(event) {
  const point = elements.canvas.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform(elements.canvas.getScreenCTM().inverse());
}

function addCalibrationPoint(event) {
  if (!state.calibrationPicking || !state.model || state.calibrationPoints.length >= 2) return;
  const point = canvasPoint(event);
  state.calibrationPoints.push({ x: point.x, y: point.y });
  if (state.calibrationPoints.length === 2) {
    state.calibrationPicking = false;
    elements.pickCalibrationButton.textContent = "重新選取兩點";
    elements.calibrationHint.textContent = "已選兩點，輸入這一段的真實距離。";
  }
  renderCalibrationPoints();
  updateCalibrationButton();
}

function renderCalibration() {
  const needsCalibration = state.model?.calibration?.status === "required";
  elements.calibrationPanel.hidden = !needsCalibration;
  renderCalibrationPoints();
}

function renderCalibrationPoints() {
  elements.calibrationLayer.replaceChildren();
  if (state.calibrationPoints.length === 2) {
    const [a, b] = state.calibrationPoints;
    elements.calibrationLayer.append(svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "calibration-line" }));
  }
  state.calibrationPoints.forEach((point) => {
    elements.calibrationLayer.append(svg("circle", { cx: point.x, cy: point.y, r: 4, class: "calibration-point" }));
  });
}

function beginCalibration() {
  state.calibrationPoints = [];
  state.calibrationPicking = true;
  elements.pickCalibrationButton.textContent = "請到圖上點兩點…";
  elements.calibrationHint.textContent = "請依序點選已知尺寸的兩個端點。";
  renderCalibrationPoints();
  updateCalibrationButton();
}

function updateCalibrationButton() {
  elements.applyCalibrationButton.disabled =
    state.calibrationPoints.length !== 2 || Number(elements.distanceInput.value) <= 0;
}

async function applyCalibration() {
  if (!state.model || state.calibrationPoints.length !== 2) return;
  elements.applyCalibrationButton.disabled = true;
  try {
    const response = await fetch("/api/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: state.model,
        pointA: state.calibrationPoints[0],
        pointB: state.calibrationPoints[1],
        knownDistanceMm: Number(elements.distanceInput.value),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail?.message || "比例校正失敗");
    state.model = payload;
    state.calibrationPoints = [];
    state.calibrationPicking = false;
    markDirty();
    renderModel();
    showToast("比例校正完成，格局座標已轉換成 mm。");
  } catch (error) {
    showToast(error.message);
    updateCalibrationButton();
  }
}

function downloadModel() {
  if (!state.model) return;
  const blob = new Blob([JSON.stringify(state.model, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${state.model.source?.filename?.replace(/\.[^.]+$/, "") || "baoju-project"}.baoju`;
  link.click();
  URL.revokeObjectURL(url);
  elements.saveState.textContent = "已匯出本機備份";
}

elements.imageInput.addEventListener("change", (event) => setImageFile(event.target.files[0]));
elements.jsonInput.addEventListener("change", async (event) => {
  try {
    const data = JSON.parse(await event.target.files[0].text());
    loadModel(data.model || data);
  } catch (error) {
    showToast(error.message);
  }
});
elements.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropZone.classList.add("dragging");
});
elements.dropZone.addEventListener("dragleave", () => elements.dropZone.classList.remove("dragging"));
elements.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove("dragging");
  setImageFile(event.dataTransfer.files[0]);
});
elements.recognizeButton.addEventListener("click", recognize);
elements.opacityInput.addEventListener("input", updateViewMode);
elements.downloadButton.addEventListener("click", downloadModel);
elements.wallLengthInput.addEventListener("change", updateWallLength);
elements.wallThicknessInput.addEventListener("change", updateWallThickness);
elements.canvas.addEventListener("click", addCalibrationPoint);
elements.pickCalibrationButton.addEventListener("click", beginCalibration);
elements.distanceInput.addEventListener("input", updateCalibrationButton);
elements.applyCalibrationButton.addEventListener("click", applyCalibration);
document.querySelectorAll("[data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    state.viewMode = button.dataset.view;
    document.querySelectorAll("[data-view]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    updateViewMode();
  }),
);

loadProviderStatus();

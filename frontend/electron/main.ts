import {
  app,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  screen,
  Tray,
} from "electron";
import path from "node:path";

const isDev = process.env.NODE_ENV === "development";
let mainWindow: BrowserWindow | null = null;
let overlayWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;
let overlayPinned = false;
let edgeEnteredAt = 0;
let awaySince = 0;
let overlaySettings = {
  enabled: true,
  edge: "right" as "left" | "right",
  delay: 350,
  launchAtLogin: true,
};

const preload = path.join(__dirname, "preload.js");

function loadRenderer(window: BrowserWindow, route = ""): void {
  if (isDev) {
    window.loadURL(`http://localhost:5173${route ? `/#${route}` : ""}`);
  } else {
    window.loadFile(path.join(__dirname, "../dist/index.html"), {
      hash: route,
    });
  }
}

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    title: "Orchestratr",
    width: 1380,
    height: 900,
    minWidth: 900,
    minHeight: 650,
    backgroundColor: "#F5F2EA",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  loadRenderer(win);
  win.once("ready-to-show", () => win.show());
  win.on("close", (event) => {
    if (quitting) return;
    event.preventDefault();
    win.hide();
  });
  win.on("closed", () => {
    mainWindow = null;
  });
  return win;
}

function overlayBounds(display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())) {
  const { workArea } = display;
  const width = 420;
  const height = Math.min(580, workArea.height - 32);
  return {
    width,
    height,
    x: overlaySettings.edge === "right" ? workArea.x + workArea.width - width - 12 : workArea.x + 12,
    y: Math.round(workArea.y + (workArea.height - height) / 2),
  };
}

function createOverlayWindow(): BrowserWindow {
  const win = new BrowserWindow({
    ...overlayBounds(),
    title: "Orchestratr Quick Overlay",
    frame: false,
    transparent: true,
    resizable: false,
    show: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: true,
    focusable: true,
    backgroundColor: "#00000000",
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: true,
    },
  });
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setAlwaysOnTop(true, "floating");
  loadRenderer(win, "/overlay");
  win.on("blur", () => {
    if (!overlayPinned) win.hide();
  });
  return win;
}

function showOverlay(focus = false): void {
  if (!overlayWindow || overlayWindow.isDestroyed()) overlayWindow = createOverlayWindow();
  overlayWindow.setBounds(overlayBounds(), false);
  if (focus) {
    overlayWindow.show();
    overlayWindow.focus();
  } else {
    overlayWindow.showInactive();
  }
}

function showMainWindow(route = ""): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    mainWindow = createMainWindow();
  }
  if (route) loadRenderer(mainWindow, route);
  mainWindow.show();
  mainWindow.focus();
}

function createTray(): void {
  const iconPath = isDev
    ? path.join(__dirname, "../public/orchestratr-menubar.png")
    : path.join(__dirname, "../dist/orchestratr-menubar.png");
  const icon = nativeImage.createFromPath(iconPath);
  if (process.platform === "darwin") icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.setToolTip("Orchestratr");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Orchestratr", click: () => showMainWindow() },
      { label: "Open Quick Overlay", click: () => showOverlay(true) },
      { type: "separator" },
      {
        label: "Quit Orchestratr",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => showMainWindow());
}

function monitorScreenEdge(): void {
  setInterval(() => {
    if (!overlaySettings.enabled || overlayPinned || !overlayWindow) return;
    const point = screen.getCursorScreenPoint();
    const display = screen.getDisplayNearestPoint(point);
    const area = display.bounds;
    const atEdge =
      overlaySettings.edge === "right"
        ? point.x >= area.x + area.width - 7
        : point.x <= area.x + 7;
    const inTriggerBand =
      point.y >= area.y + area.height * 0.35 &&
      point.y <= area.y + area.height * 0.65;

    if (atEdge && inTriggerBand) {
      awaySince = 0;
      if (!edgeEnteredAt) edgeEnteredAt = Date.now();
      if (Date.now() - edgeEnteredAt >= overlaySettings.delay && !overlayWindow.isVisible()) {
        showOverlay(false);
      }
      return;
    }

    edgeEnteredAt = 0;
    if (!overlayWindow.isVisible() || overlayWindow.isFocused()) return;
    const bounds = overlayWindow.getBounds();
    const inside =
      point.x >= bounds.x - 8 &&
      point.x <= bounds.x + bounds.width + 8 &&
      point.y >= bounds.y - 8 &&
      point.y <= bounds.y + bounds.height + 8;
    if (inside) {
      awaySince = 0;
    } else {
      if (!awaySince) awaySince = Date.now();
      if (Date.now() - awaySince > 450) overlayWindow.hide();
    }
  }, 100);
}

app.whenReady().then(() => {
  app.setName("Orchestratr");
  app.setLoginItemSettings({ openAtLogin: overlaySettings.launchAtLogin });
  mainWindow = createMainWindow();
  overlayWindow = createOverlayWindow();
  createTray();
  monitorScreenEdge();

  globalShortcut.register("Alt+Space", () => {
    if (overlayWindow?.isVisible()) {
      overlayWindow.hide();
    } else {
      showOverlay(true);
    }
  });

  screen.on("display-added", () => overlayWindow?.setBounds(overlayBounds()));
  screen.on("display-removed", () => overlayWindow?.setBounds(overlayBounds()));
  screen.on("display-metrics-changed", () => overlayWindow?.setBounds(overlayBounds()));

  app.on("activate", () => showMainWindow());
});

ipcMain.on("overlay:set-pinned", (_event, pinned: boolean) => {
  overlayPinned = pinned;
});

ipcMain.on("overlay:configure", (_event, settings: Partial<typeof overlaySettings>) => {
  overlaySettings = { ...overlaySettings, ...settings };
  app.setLoginItemSettings({ openAtLogin: overlaySettings.launchAtLogin });
  overlayWindow?.setBounds(overlayBounds());
  if (!overlaySettings.enabled && !overlayPinned) overlayWindow?.hide();
});

ipcMain.on("overlay:hide", () => {
  if (!overlayPinned) overlayWindow?.hide();
});

ipcMain.on("app:open-main", (_event, route?: string) => {
  overlayWindow?.hide();
  showMainWindow(route);
});

app.on("before-quit", () => {
  quitting = true;
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  // Orchestratr intentionally remains available in the menu bar.
});

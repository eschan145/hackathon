import { app, BrowserWindow } from "electron";
import path from "node:path";

// No preload/IPC bridge is used: the renderer talks directly to the
// FastAPI backend at http://127.0.0.1:8765 via fetch + WebSocket. This
// keeps things simple for a local hackathon app where the frontend and
// backend both run on the same trusted machine — there's no need to
// proxy REST/WS calls through the main process.

const isDev = process.env.NODE_ENV === "development";

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#f4f4f5",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (isDev) {
    win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("orchestratrDesktop", {
  setOverlayPinned: (pinned: boolean) => ipcRenderer.send("overlay:set-pinned", pinned),
  configureOverlay: (settings: {
    enabled: boolean;
    edge: "left" | "right";
    delay: number;
    launchAtLogin: boolean;
  }) => ipcRenderer.send("overlay:configure", settings),
  openFullApp: () => ipcRenderer.send("app:open-main"),
  hideOverlay: () => ipcRenderer.send("overlay:hide"),
});

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("orchestratrDesktop", {
  setOverlayPinned: (pinned: boolean) => ipcRenderer.send("overlay:set-pinned", pinned),
  configureOverlay: (settings: {
    enabled: boolean;
    edge: "left" | "right";
    delay: number;
    launchAtLogin: boolean;
  }) => ipcRenderer.send("overlay:configure", settings),
  openFullApp: (route?: string) => ipcRenderer.send("app:open-main", route),
  hideOverlay: () => ipcRenderer.send("overlay:hide"),
});

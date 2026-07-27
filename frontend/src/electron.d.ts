export {};

declare global {
  interface Window {
    orchestratrDesktop?: {
      setOverlayPinned: (pinned: boolean) => void;
      configureOverlay: (settings: {
        enabled: boolean;
        edge: "left" | "right";
        delay: number;
        launchAtLogin: boolean;
      }) => void;
      openFullApp: (route?: string) => void;
      hideOverlay: () => void;
    };
  }
}

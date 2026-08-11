export const startDevelopmentTools = async (): Promise<void> => {
  if (!import.meta.env.DEV || import.meta.env.VITE_DISABLE_REACT_DEVTOOLS === "1") {
    return;
  }
  const [{ init }, { scan }] = await Promise.all([import("react-grab"), import("react-scan")]);
  init();
  scan({ enabled: true, showToolbar: false });
};

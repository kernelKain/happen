import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/600.css";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing root element");
}

createRoot(root).render(<App />);

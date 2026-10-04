import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/600.css";
import { createRoot } from "react-dom/client";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing root element");
}

createRoot(root).render(
  <main>
    <h1>Happen</h1>
    <p>Know where. Know when.</p>
  </main>,
);

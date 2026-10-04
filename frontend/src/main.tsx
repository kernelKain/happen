import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/600.css";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { Landing } from "./app/landing/Landing";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing root element");
}

const layout = new URLSearchParams(window.location.search).get("layout");
const earlierPlanner = layout === "planner";

createRoot(root).render(earlierPlanner ? <App /> : <Landing />);

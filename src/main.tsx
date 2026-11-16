import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "sonner";
import "@fontsource/old-standard-tt/latin-400.css";
import "@fontsource/old-standard-tt/latin-400-italic.css";
import "@fontsource/old-standard-tt/latin-700.css";
import "@fontsource/b612/latin-400.css";
import "@fontsource/b612/latin-700.css";
import "@fontsource/b612-mono/latin-400.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/shell.css";
import "./styles/plate.css";
import "./styles/observe.css";
import "./styles/mission.css";
import "./survey.css";
import App from "./App";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <Toaster theme="dark" position="bottom-right" />
  </React.StrictMode>,
);

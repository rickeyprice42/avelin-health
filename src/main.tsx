import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import "./quality.css";
import "./trends.css";
import "./profile.css";
import "./agent.css";
import "./nutrition-estimates.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);

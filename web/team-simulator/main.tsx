import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import RoverDemo from "./RoverDemo";
import type { Hazard } from "./contracts";
import fixtures from "./fixtures.json";

const host = document.getElementById("street-simulator-root");
if (!host) throw new Error("Street simulator mount is missing.");

// These two synthetic examples are copied from the pinned teammate source.
// They are local data, not results from a model, camera, or geographic API.
createRoot(host).render(
  <StrictMode>
    <RoverDemo hazards={fixtures as Hazard[]} />
  </StrictMode>,
);

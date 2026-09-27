import { useEffect, useState } from "react";
import { Bot, CircleOff, Cpu, Radio, RotateCw } from "lucide-react";
import { request } from "./api";
import type { Hazard } from "./contracts";
import RoverDemo from "./RoverDemo";

interface Device {
  device_id: string;
  name: string;
  capabilities: string[];
  available: boolean;
  simulated: boolean;
  physical_connected: boolean;
}
interface Inventory {
  inventory: Device[];
  simulated: boolean;
  physical_connections_verified: boolean;
}

export default function Fleet({ hazards }: { hazards: Hazard[] }) {
  const [inventory, setInventory] = useState<Device[]>([]);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const result = await request<Inventory>("/relay/api/missions/inventory");
      setInventory(result.inventory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Fleet inventory unavailable");
    }
  }
  useEffect(() => { void load(); }, []);

  return (
    <>
      <div className="fleet-summary">
        <div>
          <span className="eyebrow">ROBOT AND DEVICE INVENTORY</span>
          <h2>Connected mission roles</h2>
          <p>These are declared simulation capabilities, not proof of physical connection.</p>
        </div>
        <button className="secondary" onClick={() => void load()}><RotateCw size={16} /> Refresh status</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="device-grid">
        {inventory.map((device) => (
          <article className="device-card" key={device.device_id}>
            <div className="device-icon">{device.device_id === "learm" ? <Bot /> : <Cpu />}</div>
            <span className={`device-state ${device.physical_connected ? "connected" : "disconnected"}`}>
              {device.physical_connected ? <Radio size={12} /> : <CircleOff size={12} />}
              {device.physical_connected ? "Connected" : "Not connected"}
            </span>
            <h3>{device.name}</h3>
            <p>{device.capabilities.map((item) => item.replaceAll("_", " ")).join(" · ")}</p>
            <small>{device.available ? "Available in simulation" : "Unavailable in simulation"}</small>
            {device.device_id === "learm" && (
              <div className="device-warning">
                Power alone does not establish control. No USB/serial link is detected, and the exact LeArm controller is still unknown. Physical response stays blocked.
              </div>
            )}
          </article>
        ))}
      </div>
      <RoverDemo hazards={hazards} />
    </>
  );
}


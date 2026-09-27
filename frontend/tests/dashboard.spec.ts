import { test, expect } from "@playwright/test";
const location = {
  type: "LineString",
  coordinates: [
    [-80.36, 25.76],
    [-80.35, 25.77],
  ],
};
const project = {
  id: "p1",
  title: "Miami utility corridor",
  utility: "Utility A",
  description: "Test project",
  location,
  start_date: null,
  end_date: null,
  status: null,
  source_url: null,
  metadata: { demo: true },
};
const snapshot = {
  projects: [
    project,
    {
      ...project,
      id: "p2",
      title: "Crossing water works",
      utility: "Utility B",
    },
  ],
  records: [],
  hazards: [],
  matches: [
    {
      id: "m1",
      left_id: "p1",
      left_kind: "project",
      right_id: "p2",
      right_kind: "project",
      distance_m: 0,
      distance_tier: "crossing",
      intersects: true,
      timeline_overlap: null,
      timeline_gap_days: null,
      closest_points: [
        [-80.355, 25.765],
        [-80.355, 25.765],
      ],
      metadata: {},
    },
  ],
  risk_cells: [
    {
      id: "r1",
      location: {
        type: "Polygon",
        coordinates: [
          [
            [-80.36, 25.76],
            [-80.35, 25.76],
            [-80.35, 25.77],
            [-80.36, 25.76],
          ],
        ],
      },
      score: 40,
      level: "MODERATE",
      components: {
        distance: 40,
        timeline: 0,
        hazard: 0,
        public_infrastructure: 0,
      },
      reasons: ["Utility project geometries intersect."],
      project_ids: ["p1", "p2"],
      record_ids: [],
      hazard_ids: [],
      match_ids: ["m1"],
      metadata: {},
    },
  ],
};
test.beforeEach(async ({ page }) => {
  await page.route("**/api/demo-summary", (route) =>
    route.fulfill({ json: snapshot }),
  );
  // Offline tests do not depend on an external tile or font server.
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.route("https://*.basemaps.cartocdn.com/**", (route) =>
    route.abort(),
  );
  await page.route("https://fonts.googleapis.com/**", (route) => route.abort());
  await page.route("**/relay/api/missions/inventory", (route) =>
    route.fulfill({
      json: {
        simulated: true,
        physical_connections_verified: false,
        inventory: [
          { device_id: "freenove-hexapod", name: "Freenove Hexapod", capabilities: ["second_view"], available: false, simulated: true, physical_connected: false },
          { device_id: "learm", name: "Hiwonder LeArm", capabilities: ["reviewed_response"], available: false, simulated: true, physical_connected: false },
        ],
      },
    }),
  );
});
test("renders real contracts, filters matches, preserves unknown dates and exports", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByText("API data loaded")).toBeVisible();
  await expect(
    page.getByText("Utility project geometries intersect."),
  ).toBeVisible();
  await expect(
    page.getByText("2 demo fixtures", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Project connections", exact: true }).click();
  await expect(
    page.getByText("Schedule unknown", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Relationship filter").selectOption("utility");
  await expect(page.getByText("1 matches")).toBeVisible();
  await page.getByLabel("Search matches").fill("does not exist");
  await expect(
    page.getByText("No matches found.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Evidence & sources", exact: true }).click();
  await expect(page.getByText("Unknown → Unknown").first()).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export data" }).click();
  expect((await download).suggestedFilename()).toBe(
    "grid-hazard-rover-snapshot.json",
  );
  expect(errors).toEqual([]);
});
test("JPEG submission sends verified input and handles no-hazard result", async ({
  page,
}) => {
  await page.route("**/ingest/photo", async (route) => {
    const body = route.request().postDataBuffer()!.toString();
    expect(body).toContain("-80.36");
    expect(body).toContain("25.76");
    expect(body).toMatch(/2026-09-26T.*Z/);
    await route.fulfill({
      json: {
        hazard_detected: false,
        hazard: null,
        persisted: false,
        classification: {
          hazard_type: null,
          severity: null,
          confidence: 0.9,
          description: "No visible hazard.",
        },
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Upload photo" }).click();
  await page.getByLabel("JPEG photograph").setInputFiles({
    name: "sample.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from([255, 216, 255, 217]),
  });
  await page.getByLabel("Longitude", { exact: true }).fill("-80.36");
  await page.getByLabel("Latitude", { exact: true }).fill("25.76");
  await page.getByLabel("Capture time").fill("2026-09-26T12:00");
  await page.getByRole("button", { name: "Analyze with Gemini" }).click();
  await expect(
    page.getByText("No hazard detected", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("No hazard record was saved.")).toBeVisible();
  await page.getByRole("button", { name: "Close upload" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
test("upload provider errors remain retryable and a saved hazard refreshes data", async ({
  page,
}) => {
  let snapshotReads = 0;
  await page.route("**/api/demo-summary", (route) => {
    snapshotReads++;
    return route.fulfill({ json: snapshot });
  });
  await page.route("**/ingest/photo", (route) =>
    route.fulfill({
      status: 502,
      json: { detail: "Classification provider unavailable" },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("API data loaded")).toBeVisible();
  await page.getByRole("button", { name: "Upload photo" }).click();
  await page
    .getByLabel("JPEG photograph")
    .setInputFiles({
      name: "sample.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from([255, 216, 255, 217]),
    });
  await page.getByLabel("Longitude", { exact: true }).fill("-80.36");
  await page.getByLabel("Latitude", { exact: true }).fill("25.76");
  await page.getByLabel("Capture time").fill("2026-09-26T12:00");
  await page.getByRole("button", { name: "Analyze with Gemini" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Classification provider unavailable",
  );
  const before = snapshotReads;
  await page.route("**/ingest/photo", (route) =>
    route.fulfill({
      json: {
        hazard_detected: true,
        persisted: true,
        hazard: { id: "h1" },
        classification: {
          hazard_type: "pothole",
          severity: 3,
          confidence: 0.9,
          description: "Visible road damage.",
        },
      },
    }),
  );
  await page.getByRole("button", { name: "Analyze with Gemini" }).click();
  await expect(
    page.getByText("Hazard classified", { exact: true }),
  ).toBeVisible();
  await expect.poll(() => snapshotReads).toBeGreaterThan(before);
});
test("API failure is honest and retry recovers", async ({ page }) => {
  await page.route("**/api/demo-summary", (route) =>
    route.fulfill({ status: 503, json: { detail: "Storage unavailable" } }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Storage unavailable");
  await expect(
    page.getByText("API unavailable", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/demo-summary", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.getByRole("button", { name: "Refresh dashboard" }).click();
  await expect(page.getByText("API data loaded")).toBeVisible();
});
test("mobile layout stays inside the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("API data loaded")).toBeVisible();
  for (const section of [
    "Overview",
    "Project connections",
    "Rover findings",
    "Robot fleet",
    "Call reports",
    "Evidence & sources",
  ]) {
    await page.getByRole("button", { name: section, exact: true }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({ path: "tmp/mobile.png", fullPage: true });
});
test("company token unlocks the protected AI call review queue", async ({ page }) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("fieldsight-call-access", "test-company-token"),
  );
  const call = {
    conversation_id: "conv_test_001",
    company_id: "utility-a",
    company_name: "Utility A",
    ended_at: "2026-09-27T12:00:00Z",
    duration_seconds: 72,
    analysis: {
      summary: "Caller reported flooding near an exposed cable.",
      category: "field_hazard",
      sentiment: "concerned",
      urgency: "high",
      call_successful: true,
      location_text: "NW 7th Street, Miami",
      action_items: ["Dispatch a qualified reviewer."],
    },
    recording_status: "provider_retained",
    consent_to_record: true,
    review_status: "new",
  };
  await page.route("**/api/calls", async (route) => {
    expect(route.request().headers().authorization).toBe(
      "Bearer test-company-token",
    );
    await route.fulfill({ json: [call] });
  });
  await page.route("**/api/calls/conv_test_001", (route) =>
    route.fulfill({
      json: {
        ...call,
        agent_id: "agent_fieldsight",
        agent_name: "FieldSight Operations",
        transcript: [
          { role: "agent", message: "How can I help?", time_in_call_seconds: 1 },
          {
            role: "user",
            message: "There is an exposed cable.",
            time_in_call_seconds: 9,
          },
        ],
        has_audio: true,
        audio_sha256: null,
        reviewer_note: null,
        source: "elevenlabs",
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Call reports", exact: true }).click();
  await expect(page.getByText("Company follow-up queue")).toBeVisible();
  await page.getByRole("button", { name: /Utility A/ }).click();
  await expect(page.getByText("There is an exposed cable.")).toBeVisible();
  await expect(page.getByText("NW 7th Street, Miami")).toBeVisible();
});
test("robot fleet is truthful and crawler demo advances", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Rover simulation", exact: true }).click();
  await expect(page.getByText("Hiwonder LeArm")).toBeVisible();
  await expect(page.getByText("Physical response stays blocked.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Simulated rover telemetry")).toContainText("87%");
  await expect(page.getByText("Mission ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start demo" }).click();
  await expect(page.getByText("Walking corridor", { exact: true })).toBeVisible({ timeout: 4000 });
  await page.getByRole("button", { name: "Open evidence for standing water" }).click();
  await expect(page.getByRole("dialog", { name: "Inspection evidence detail" })).toContainText("[longitude, latitude]");
  await page.getByRole("button", { name: "Close evidence" }).click();
});
test("company portal scopes the experience and returns to operations", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Company portal" }).click();
  await expect(page.getByText("Company portal preview")).toBeVisible();
  await expect(page.getByText("See what needs attention near your planned work.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Company portal" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Operations workspace" }).click();
  await expect(page.getByText("Miami-Dade workspace")).toBeVisible();
});
test("nearby hazards and risk areas collapse into an interactive list", async ({ page }) => {
  await page.unroute("**/api/demo-summary");
  await page.route("**/api/demo-summary", (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        hazards: [
          {
            id: "h-near-risk",
            hazard_type: "pothole",
            severity: 4,
            confidence: 0.93,
            description: "Road surface damage near the coordination area.",
            timestamp: "2026-09-27T12:00:00Z",
            image_url: null,
            location: { type: "Point", coordinates: [-80.355, 25.765] },
            metadata: { demo: true },
          },
        ],
      },
    }),
  );
  await page.goto("/");
  const cluster = page.locator(".map-notice-cluster");
  await expect(cluster).toContainText("2");
  await cluster.hover();
  await expect(page.locator(".leaflet-tooltip .map-cluster-list")).toContainText("2 nearby map items");
  await cluster.click();
  const popup = page.locator(".leaflet-popup .map-cluster-list");
  await expect(popup).toContainText("pothole");
  await popup.getByRole("button", { name: /pothole/i }).click();
  await expect(page.locator(".detail h2")).toHaveText("pothole");
});
test("live backend smoke and desktop screenshot", async ({ page }) => {
  test.setTimeout(120000);
  test.skip(
    !process.env.LIVE_DASHBOARD,
    "Set LIVE_DASHBOARD=1 to exercise the running backend.",
  );
  await page.unroute("**/api/demo-summary");
  await page.unroute("https://tile.openstreetmap.org/**");
  await page.unroute("https://*.basemaps.cartocdn.com/**");
  await page.unroute("https://fonts.googleapis.com/**");
  await page.goto("/");
  await expect(page.getByText("API data loaded")).toBeVisible({
    timeout: 90000,
  });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: "tmp/dashboard-live.png", fullPage: true });
});

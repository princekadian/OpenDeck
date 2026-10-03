import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ActionInfo, EditorTree } from "./api";
import { EditorApp } from "./EditorApp";

// jsdom lacks the modal dialog API.
beforeEach(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

function action(type: string, displayName: string, category: string, configSchema: object, extra: Partial<ActionInfo> = {}): ActionInfo {
  return {
    type,
    displayName,
    description: `${displayName} description`,
    category,
    icon: "key",
    status: "available",
    trustedOnly: false,
    destructive: false,
    stateful: false,
    configSchema: configSchema as ActionInfo["configSchema"],
    ...extra,
  };
}

function makeTree(): EditorTree {
  return {
    activeProfileId: "pr1",
    profiles: [
      { id: "pr1", name: "Main", description: "", iconRef: null, sortOrder: 0 },
      { id: "pr2", name: "Gaming", description: "", iconRef: null, sortOrder: 1 },
    ],
    pages: [
      { id: "pg1", profileId: "pr1", name: "Home", iconRef: null, sortOrder: 0, kind: "deck" },
      { id: "pg2", profileId: "pr1", name: "Work", iconRef: null, sortOrder: 1, kind: "deck" },
      { id: "pg3", profileId: "pr2", name: "Games", iconRef: null, sortOrder: 0, kind: "deck" },
    ],
    buttons: [
      { id: "b1", pageId: "pg1", parentId: null, kind: "action", sortOrder: 0, label: "Lock PC", description: "", iconRef: "builtin:lock", actionType: "lock_windows", actionConfig: {}, appearance: {}, enabled: true },
      { id: "b2", pageId: "pg1", parentId: null, kind: "action", sortOrder: 1, label: "YouTube", description: "", iconRef: null, actionType: "open_url", actionConfig: { url: "https://youtube.com" }, appearance: {}, enabled: true },
    ],
    categories: [
      { id: "open", label: "Open" },
      { id: "system", label: "System" },
      { id: "keyboard", label: "Keyboard" },
      { id: "workflow", label: "Workflow" },
      { id: "streaming", label: "Streaming" },
      { id: "advanced", label: "Advanced" },
    ],
    keys: [
      { name: "S", label: "S", group: "Letters" },
      { name: "G", label: "G", group: "Letters" },
      { name: "F13", label: "F13", group: "Function keys" },
    ],
    actions: [
      action("open_url", "Open website", "open", { properties: { url: { type: "string", title: "Web address", widget: "url" } }, required: ["url"] }),
      action("open_folder", "Open folder", "open", { properties: { path: { type: "string", title: "Folder", widget: "folder" } }, required: ["path"] }),
      action("lock_windows", "Lock Windows", "system", {}),
      action("shutdown", "Shutdown", "system", { properties: { confirm: { type: "boolean", title: "Ask for a second tap on the device", default: true } } }, { destructive: true }),
      action("hotkey", "Hotkey", "keyboard", {
        properties: { shortcut: { $ref: "#/$defs/Shortcut", title: "Shortcut", widget: "hotkey" } },
        required: ["shortcut"],
        $defs: { Shortcut: { type: "object", properties: { modifiers: { type: "array" }, key: { type: "string" } } } },
      }),
      action("delay", "Delay", "workflow", { properties: { milliseconds: { type: "integer", title: "Delay", default: 500, minimum: 0, maximum: 60000, unit: "ms" } } }),
      action("counter", "Counter", "workflow", {
        properties: {
          operation: { type: "string", enum: ["increment", "decrement", "reset"], default: "increment", title: "On press", labels: { increment: "Increase", decrement: "Decrease", reset: "Reset" } },
          amount: { type: "integer", default: 1, title: "By", showWhen: { operation: ["increment", "decrement"] } },
        },
      }),
      action("multi_action", "Multi Action", "workflow", {
        properties: { steps: { type: "array", title: "Actions", widget: "steps" } },
        required: ["steps"],
      }),
      action("obs_start_streaming", "OBS: Start streaming", "streaming", {}, { status: "coming_soon" }),
      action("run_command", "Run command", "advanced", { properties: { command: { type: "string", title: "Command line", widget: "code" } }, required: ["command"] }, { trustedOnly: true }),
    ],
  };
}

type Call = { method: string; url: string; body: unknown };

function mockApi(tree: EditorTree, handlers: Record<string, (body: unknown) => unknown> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
      calls.push({ method, url, body });
      const key = `${method} ${url.replace("/api/admin", "")}`;
      if (key === "GET /config") return json(tree);
      const handler = handlers[key];
      if (handler) {
        const result = handler(body);
        return result instanceof Response ? result : json(result ?? null, result === undefined ? 204 : 200);
      }
      return new Response(null, { status: 204 });
    }),
  );
  return calls;
}

function json(data: unknown, status = 200) {
  return status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

async function renderEditor() {
  render(<EditorApp />);
  await screen.findByRole("heading", { name: "Home" });
}

describe("EditorApp", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("shows profiles, the selected page and its buttons in order", async () => {
    mockApi(makeTree());
    await renderEditor();
    expect(screen.getByRole("button", { name: "Main, shown first on devices" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Default")).toBeInTheDocument();
    const tiles = screen.getAllByRole("button", { name: /position \d/ });
    expect(tiles.map((t) => t.getAttribute("aria-label"))).toEqual([
      "Lock PC, position 1. Edit",
      "YouTube, position 2. Edit",
    ]);
  });

  it("creates a button with action settings and a built-in icon", async () => {
    const calls = mockApi(makeTree(), { "POST /pages/pg1/buttons": (b) => ({ ...(b as object), id: "new", pageId: "pg1", sortOrder: 2 }) });
    await renderEditor();
    fireEvent.click(screen.getAllByRole("button", { name: /Add button/ })[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("When pressed"), { target: { value: "open_folder" } });
    fireEvent.change(within(dialog).getByLabelText("Folder"), { target: { value: "C:\\Users\\me\\Downloads" } });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Downloads" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Change" }));
    fireEvent.click(within(dialog).getByRole("option", { name: "Folder" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add button" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/pages/pg1/buttons"))).toBe(true));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/buttons"))!;
    expect(post.body).toEqual({
      kind: "action",
      parentId: null,
      label: "Downloads",
      description: "",
      iconRef: "builtin:folder",
      actionType: "open_folder",
      actionConfig: { path: "C:\\Users\\me\\Downloads" },
      enabled: true,
    });
  });

  it("shows server validation errors next to the field", async () => {
    mockApi(makeTree(), {
      "PATCH /buttons/b2": () =>
        json({ detail: { code: "INVALID_CONFIG", message: "Check the highlighted fields.", fields: { url: "Enter a web address starting with http:// or https://." } } }, 400),
    });
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "YouTube, position 2. Edit" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Web address"), { target: { value: "ftp://x" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText(/starting with http/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Web address")).toHaveAttribute("aria-invalid", "true");
  });

  it("deletes a button from its context menu after confirmation", async () => {
    const calls = mockApi(makeTree());
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Lock PC options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete button" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/buttons/b1"))).toBe(true));
  });

  it("reorders buttons with Alt + arrow keys", async () => {
    const calls = mockApi(makeTree());
    await renderEditor();
    const tile = screen.getByRole("button", { name: "Lock PC, position 1. Edit" });
    fireEvent.keyDown(tile, { key: "ArrowRight", altKey: true });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/pages/pg1/buttons-order"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/buttons-order"))!.body).toEqual({ ids: ["b2", "b1"], parentId: null });
  });

  it("toggles a button off from the menu", async () => {
    const calls = mockApi(makeTree());
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "YouTube options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Disable" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/buttons/b2/enabled"))?.body).toEqual({ enabled: false }));
  });

  it("switches page and profile", async () => {
    mockApi(makeTree());
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Work, 0 buttons" }));
    expect(await screen.findByRole("heading", { name: "Work" })).toBeInTheDocument();
    expect(screen.getByText("No buttons on this page yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Gaming" }));
    expect(await screen.findByRole("heading", { name: "Games" })).toBeInTheDocument();
  });

  it("creates a profile and opens its first page", async () => {
    const tree = makeTree();
    mockApi(tree, {
      "POST /profiles": (b) => {
        tree.profiles.push({ id: "pr3", name: (b as { name: string }).name, description: "", iconRef: null, sortOrder: 2 });
        tree.pages.push({ id: "pg9", profileId: "pr3", name: "Main", iconRef: null, sortOrder: 0, kind: "deck" });
        return tree.profiles[2];
      },
    });
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "New profile" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Profile name"), { target: { value: "Streaming" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Create profile" }));
    });
    expect(await screen.findByRole("heading", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByText("Streaming", { selector: ".crumbs__step" })).toBeInTheDocument();
  });
});

/** Home gets an "Audio" folder holding "Vol +" and a nested "Advanced" folder holding "Mixer". */
function withFolders(tree: EditorTree): EditorTree {
  const base = { description: "", actionConfig: {}, appearance: {}, enabled: true };
  tree.buttons.push(
    { ...base, id: "f1", pageId: "pg1", parentId: null, kind: "folder", sortOrder: 2, label: "Audio", iconRef: "builtin:mic", actionType: "" },
    { ...base, id: "b3", pageId: "pg1", parentId: "f1", kind: "action", sortOrder: 0, label: "Vol +", iconRef: null, actionType: "lock_windows" },
    { ...base, id: "f2", pageId: "pg1", parentId: "f1", kind: "folder", sortOrder: 1, label: "Advanced", iconRef: null, actionType: "" },
    { ...base, id: "b4", pageId: "pg1", parentId: "f2", kind: "action", sortOrder: 0, label: "Mixer", iconRef: null, actionType: "lock_windows" },
  );
  return tree;
}

describe("Folders", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("creates a folder with only a name and an icon", async () => {
    const calls = mockApi(makeTree(), { "POST /pages/pg1/buttons": (b) => ({ ...(b as object), id: "nf", pageId: "pg1", sortOrder: 2 }) });
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Add folder" }));
    const dialog = await screen.findByRole("dialog", { name: "New folder" });
    expect(within(dialog).queryByLabelText("When pressed")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Test on this PC" })).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Audio" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create folder" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ kind: "folder", label: "Audio", parentId: null });
  });

  it("opens folders with breadcrumbs, adds inside them and goes back", async () => {
    const calls = mockApi(withFolders(makeTree()), {
      "POST /pages/pg1/buttons": (b) => ({ ...(b as object), id: "n", pageId: "pg1", sortOrder: 9 }),
    });
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: /^Audio folder, 2 items/ }));
    expect(await screen.findByRole("heading", { name: "Audio" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /position \d/ }).map((t) => t.getAttribute("aria-label"))).toEqual([
      "Vol +, position 1. Edit",
      "Advanced folder, 1 item, position 2. Open",
    ]);
    fireEvent.click(screen.getByRole("button", { name: /^Advanced folder/ }));
    expect(await screen.findByRole("heading", { name: "Advanced" })).toBeInTheDocument();
    const trail = screen.getByRole("navigation", { name: "Location" });
    expect(within(trail).getAllByRole("button").map((b) => b.textContent)).toEqual(["Main", "Home", "Audio"]);

    fireEvent.click(screen.getAllByRole("button", { name: /Add button/ })[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("When pressed"), { target: { value: "lock_windows" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add button" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ kind: "action", parentId: "f2" });

    fireEvent.click(within(trail).getByRole("button", { name: "Audio" }));
    expect(await screen.findByRole("heading", { name: "Audio" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
  });

  it("reorders inside the open folder", async () => {
    const calls = mockApi(withFolders(makeTree()));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: /^Audio folder/ }));
    fireEvent.keyDown(await screen.findByRole("button", { name: "Vol +, position 1. Edit" }), { key: "ArrowRight", altKey: true });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/buttons-order"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/buttons-order"))!.body).toEqual({ ids: ["f2", "b3"], parentId: "f1" });
  });

  it("warns what a folder holds before deleting it", async () => {
    const calls = mockApi(withFolders(makeTree()));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Audio options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/contains 2 buttons and 1 nested folder/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete folder and contents" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/buttons/f1"))).toBe(true));
  });

  it("moves a button into a nested folder but never a folder into itself", async () => {
    const calls = mockApi(withFolders(makeTree()));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Audio options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to…" }));
    let select = (await screen.findByLabelText(/Move "Audio" to/)) as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.textContent?.trim());
    expect(labels).not.toContain("▸ Audio");
    expect(labels.some((l) => l?.includes("Advanced"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "Lock PC options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to…" }));
    select = (await screen.findByLabelText(/Move "Lock PC" to/)) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "pg1:f2" } });
    fireEvent.click(screen.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/buttons/b1/move"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/buttons/b1/move"))!.body).toEqual({ pageId: "pg1", parentId: "f2" });
  });

  it("keeps a folder with contents from turning into an action", async () => {
    mockApi(withFolders(makeTree()));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Audio options" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename or change icon…" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit folder" });
    expect(within(dialog).getByRole("radio", { name: /Action/ })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: /Folder/ })).toBeChecked();
  });
});

describe("Action settings", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  async function openNewButton() {
    await renderEditor();
    fireEvent.click(screen.getAllByRole("button", { name: /Add button/ })[0]);
    return screen.findByRole("dialog");
  }

  function choose(dialog: HTMLElement, type: string) {
    fireEvent.change(within(dialog).getByLabelText("When pressed"), { target: { value: type } });
  }

  it("groups actions by category and disables coming-soon ones", async () => {
    mockApi(makeTree());
    const dialog = await openNewButton();
    const select = within(dialog).getByLabelText("When pressed") as HTMLSelectElement;
    const groups = Array.from(select.querySelectorAll("optgroup")).map((g) => g.label);
    expect(groups).toEqual(["Open", "System", "Keyboard", "Workflow", "Streaming", "Advanced"]);
    const obs = within(select).getByRole("option", { name: "OBS: Start streaming (coming soon)" }) as HTMLOptionElement;
    expect(obs.disabled).toBe(true);
  });

  it("records a hotkey and saves it structurally", async () => {
    const calls = mockApi(makeTree(), { "POST /pages/pg1/buttons": (b) => ({ ...(b as object), id: "n", pageId: "pg1", sortOrder: 2 }) });
    const dialog = await openNewButton();
    choose(dialog, "hotkey");
    const recorder = within(dialog).getByRole("button", { name: "Record shortcut" });
    fireEvent.click(recorder);
    fireEvent.keyDown(recorder, { code: "ControlLeft", ctrlKey: true });
    fireEvent.keyDown(recorder, { code: "KeyS", ctrlKey: true, shiftKey: true });
    expect(within(dialog).getByText("Ctrl + Shift + S")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add button" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect((calls.find((c) => c.method === "POST")!.body as { actionConfig: unknown }).actionConfig).toEqual({
      shortcut: { modifiers: ["CTRL", "SHIFT"], key: "S" },
    });
  });

  it("fills defaults and hides fields that do not apply", async () => {
    mockApi(makeTree());
    const dialog = await openNewButton();
    choose(dialog, "delay");
    expect(within(dialog).getByLabelText("Delay")).toHaveValue(500);
    expect(within(dialog).getByText("ms")).toBeInTheDocument();
    choose(dialog, "counter");
    expect(within(dialog).getByLabelText("By")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("On press"), { target: { value: "reset" } });
    expect(within(dialog).queryByLabelText("By")).not.toBeInTheDocument();
  });

  it("builds a multi action from steps", async () => {
    const calls = mockApi(makeTree(), { "POST /pages/pg1/buttons": (b) => ({ ...(b as object), id: "n", pageId: "pg1", sortOrder: 2 }) });
    const dialog = await openNewButton();
    choose(dialog, "multi_action");
    fireEvent.click(within(dialog).getByRole("button", { name: "+ Add action" }));
    fireEvent.change(within(dialog).getByLabelText("Action", { selector: "select" }), { target: { value: "delay" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "+ Add action" }));
    const pickers = within(dialog).getAllByLabelText("Action", { selector: "select" });
    fireEvent.change(pickers[pickers.length - 1], { target: { value: "lock_windows" } });
    // Composite actions are not offered as steps.
    expect(within(pickers[0] as HTMLElement).queryByRole("option", { name: "Multi Action" })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add button" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect((calls.find((c) => c.method === "POST")!.body as { actionConfig: unknown }).actionConfig).toEqual({
      steps: [
        { actionType: "delay", actionConfig: { milliseconds: 500 } },
        { actionType: "lock_windows", actionConfig: {} },
      ],
    });
  });

  it("warns about scripts and asks before testing destructive actions", async () => {
    const calls = mockApi(makeTree(), { "POST /actions/test": () => ({ success: true, message: "ok" }) });
    const dialog = await openNewButton();
    choose(dialog, "run_command");
    expect(within(dialog).getByText(/Runs exactly what you write here/)).toBeInTheDocument();
    choose(dialog, "shutdown");
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Test on this PC" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(calls.some((c) => c.url.endsWith("/actions/test"))).toBe(false);
    confirmSpy.mockRestore();
  });
});

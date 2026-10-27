import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, type VmSummary } from "../api/client";
import { ErrorMessage } from "../components/ErrorMessage";
import { NotificationProvider } from "../components/Notifications";
import { useNotifier } from "../components/notifier";
import { TaskTrackerProvider } from "../components/TaskTracker";
import { HomeTab } from "../features/home/HomeTab";
import { LibraryActionsProvider } from "../features/library/LibraryActions";
import { LibraryPanel } from "../features/library/LibraryPanel";
import { VmActionsProvider } from "../features/vm/VmActions";
import { NetworkEditor } from "../features/network-editor/NetworkEditor";
import { PreferencesDialog } from "../features/preferences/PreferencesDialog";
import { FirstRunWizard } from "../features/first-run/FirstRunWizard";
import { IsoPicker } from "../features/iso-picker/IsoPicker";
import { GuestToolsDialog } from "../features/guest-tools/GuestToolsDialog";
import { VmSettings } from "../features/vm-settings/VmSettings";
import { PathPicker } from "../features/files/PathPicker";
import { ScanDialog } from "../features/scan/ScanDialog";
import { NewVmWizard } from "../features/wizard/NewVmWizard";
import { FullscreenBar } from "../features/console/FullscreenBar";
import { CloseDialog } from "../features/session/CloseDialog";
import { type SnapshotKind, SnapshotRequest } from "../features/snapshots/SnapshotRequest";
import { useConsole } from "../features/console/consoleRegistry";
import { useCdroms } from "../features/vm/useCdroms";
import {
  browserFullscreen,
  keyboardLockAvailable,
  setFullscreen,
  toggleFullscreen,
} from "../platform/fullscreen";
import { VmTab } from "../features/vm/VmTab";
import { storeGuestLanguage } from "../i18n";
import { diskPicker } from "../platform/folders";
import { AboutDialog } from "./AboutDialog";
import { MenuBar } from "./MenuBar";
import { StatusBar } from "./StatusBar";
import { HOME_TAB, TabBar } from "./TabBar";
import { Toolbar } from "./Toolbar";
import { useAppData } from "./useAppData";
import { useShortcuts } from "./useShortcuts";
import "./App.css";

export interface Layout {
  library: boolean;
  toolbar: boolean;
  statusBar: boolean;
}

/** Closing the desktop window quits; a browser tab is the user's to close. */
function desktopWindow(): boolean {
  return Boolean(window.pywebview?.api?.close_window);
}

export function App() {
  return (
    <NotificationProvider>
      <TaskTrackerProvider>
        <VmActionsProvider>
          <MainWindow />
        </VmActionsProvider>
      </TaskTrackerProvider>
    </NotificationProvider>
  );
}

function MainWindow() {
  const { t, i18n } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const { info, vms, knownNames, library, error, loading, libvirtLost, refresh } = useAppData();
  const [layout, setLayout] = useState<Layout>({ library: true, toolbar: true, statusBar: true });
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [networkEditorOpen, setNetworkEditorOpen] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [firstRunOpen, setFirstRunOpen] = useState(false);
  const [mediaTarget, setMediaTarget] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  // Chosen from a folder's context menu, rather than the selected node.
  const [wizardFolder, setWizardFolder] = useState<string>();
  // File > Open: the disk the wizard starts from, and the browser's listing of files.
  const [wizardDisk, setWizardDisk] = useState<string | undefined>(undefined);
  const [pickingDisk, setPickingDisk] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [guestToolsFor, setGuestToolsFor] = useState<string | null>(null);
  const [openVms, setOpenVms] = useState<string[]>([]);
  // Names given when a tab opens on a VM the list does not have yet (just created).
  const [tabNames, setTabNames] = useState<ReadonlyMap<string, string>>(new Map());
  const [activeTab, setActiveTab] = useState<string>(HOME_TAB);
  // The library follows the active tab: its VM selected, none on Home.
  const [syncedTab, setSyncedTab] = useState<string>(HOME_TAB);
  if (activeTab !== syncedTab) {
    setSyncedTab(activeTab);
    setSelectedNode(activeTab === HOME_TAB ? null : `v:${activeTab}`);
  }
  // Quitting asks first what to do with the VMs still running.
  const [quitting, setQuitting] = useState(false);
  const [snapshotFor, setSnapshotFor] = useState<{ uuid: string; kind: SnapshotKind } | null>(null);
  // VM whose console fills the screen, and the window state to put back after.
  const [fullscreenVm, setFullscreenVm] = useState<string | null>(null);
  const windowWasFullscreen = useRef(false);
  const browserNoticeShown = useRef(false);
  const kvmNoticeShown = useRef(false);

  useEffect(() => {
    if (!info) return;
    // A guest keeps the language of their own browser.
    const language = info.role === "guest" ? i18n.language : info.ui.language;
    void i18n.changeLanguage(language);
    document.documentElement.lang = language;
    document.documentElement.dataset.mode = info.mode;
    if (info.ui.theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = info.ui.theme;
  }, [info, i18n]);

  // Checked at each start: a kernel update can leave KVM unusable until a reboot.
  useEffect(() => {
    const kvm = info?.kvm;
    if (!kvm?.problem || info?.role === "guest" || kvmNoticeShown.current) return;
    kvmNoticeShown.current = true;
    notifyError(
      t("kvm.title"),
      new ApiError(0, `kvm.${kvm.problem}`, `${kvm.module}, kernel ${kvm.kernel}`),
    );
  }, [info, notifyError, t]);

  // A VM can be missing from the list for a moment (renamed, defined elsewhere):
  // its tab keeps the last known name, and the list is fetched again.
  const missingTab = vms !== null && openVms.some((uuid) => !vms.some((vm) => vm.uuid === uuid));
  useEffect(() => {
    if (missingTab) refresh();
  }, [missingTab, refresh]);

  // The desktop window hands its close button to the page, for that question.
  useEffect(() => {
    const api = window.pywebview?.api;
    if (!api?.guard_close) return;
    void api.guard_close(true);
    const onClose = () => {
      void api.close_answered?.();
      setQuitting(true);
    };
    window.addEventListener("kvmstudio:close", onClose);
    return () => window.removeEventListener("kvmstudio:close", onClose);
  }, [info]);

  // The assistant opens by itself until a VM location is chosen.
  useEffect(() => {
    let cancelled = false;
    api
      .setup()
      .then((s) => !cancelled && s.needed && setFirstRunOpen(true))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // A guest of LAN sharing manages VMs, not the host (F-102).
  const guest = info?.role === "guest";
  const logout = () => {
    api
      .logout()
      .catch(() => undefined)
      .finally(() => window.location.reload());
  };

  const toggle = (key: keyof Layout) => setLayout((l) => ({ ...l, [key]: !l[key] }));

  const openVm = (uuid: string, name?: string) => {
    if (name) setTabNames((names) => new Map(names).set(uuid, name));
    setOpenVms((tabs) => (tabs.includes(uuid) ? tabs : [...tabs, uuid]));
    setActiveTab(uuid);
  };

  const closeTab = (uuid: string) => {
    const index = openVms.indexOf(uuid);
    const rest = openVms.filter((id) => id !== uuid);
    setOpenVms(rest);
    if (activeTab === uuid) setActiveTab(rest[Math.min(index, rest.length - 1)] ?? HOME_TAB);
  };

  const vmByUuid = new Map((vms ?? []).map((vm) => [vm.uuid, vm]));
  const tabs = openVms.map((uuid) => ({
    id: uuid,
    label: vmByUuid.get(uuid)?.name ?? knownNames.get(uuid) ?? tabNames.get(uuid) ?? "",
  }));
  // Menu and toolbar act on the VM of the active tab, else on the library selection.
  const selectedVm = selectedNode?.startsWith("v:") ? selectedNode.slice(2) : "";
  const currentVm = vmByUuid.get(activeTab !== HOME_TAB ? activeTab : selectedVm) ?? null;
  const { drives, reload: reloadDrives } = useCdroms(currentVm);
  const vmConsole = useConsole(currentVm?.uuid);
  const allTabs = [HOME_TAB, ...openVms];
  const cycleTab = (delta: number) => {
    const at = allTabs.indexOf(activeTab);
    setActiveTab(allTabs[(at + delta + allTabs.length) % allTabs.length] ?? HOME_TAB);
  };
  // Leaving the VM tab, or the VM stopping, ends the console full screen.
  const consoleFullscreen =
    fullscreenVm !== null &&
    activeTab === fullscreenVm &&
    ["running", "paused"].includes(vmByUuid.get(fullscreenVm)?.state ?? "")
      ? fullscreenVm
      : null;
  const exitConsoleFullscreen = useCallback(() => setFullscreenVm(null), []);
  const closeSnapshot = useCallback(() => setSnapshotFor(null), []);
  // The window goes back to how it was once the console full screen ends.
  const wasConsoleFullscreen = useRef(false);
  useEffect(() => {
    if (wasConsoleFullscreen.current && !consoleFullscreen) {
      void setFullscreen(windowWasFullscreen.current);
    }
    wasConsoleFullscreen.current = consoleFullscreen !== null;
  }, [consoleFullscreen]);
  const consoleFullscreenFor = vmConsole && activeTab !== HOME_TAB ? activeTab : null;
  const toggleConsoleFullscreen = () => {
    if (consoleFullscreen) {
      exitConsoleFullscreen();
      return;
    }
    if (!consoleFullscreenFor) return;
    setFullscreenVm(consoleFullscreenFor);
    void setFullscreen(true).then((before) => {
      windowWasFullscreen.current = before;
    });
    if (browserFullscreen() && !browserNoticeShown.current) {
      browserNoticeShown.current = true;
      notify(
        t("console.fullscreenBrowserTitle"),
        t(
          keyboardLockAvailable() ? "console.fullscreenBrowserLocked" : "console.fullscreenBrowser",
        ),
      );
    }
  };
  // In a browser, Escape (imposed) leaves full screen: follow it.
  useEffect(() => {
    if (!consoleFullscreen || !browserFullscreen()) return;
    const onChange = () => {
      if (!document.fullscreenElement) setFullscreenVm(null);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [consoleFullscreen]);

  const startFromDisk = (path: string) => {
    setWizardDisk(path);
    setWizardOpen(true);
  };
  const openDisk = () => {
    const native = diskPicker();
    if (native) void native(library?.root ?? null).then((path) => path && startFromDisk(path));
    else setPickingDisk(true);
  };

  useShortcuts({
    newVm: () => setWizardOpen(true),
    closeTab: () => activeTab !== HOME_TAB && closeTab(activeTab),
    nextTab: () => cycleTab(1),
    previousTab: () => cycleTab(-1),
    preferences: () => !guest && setPreferencesOpen(true),
    settings: () => currentVm && setSettingsFor(currentVm.uuid),
    grab: () => vmConsole?.grab(),
    consoleFullscreen: toggleConsoleFullscreen,
    appFullscreen: toggleFullscreen,
  });
  const setMedia = (target: string, path: string | null) => {
    if (!currentVm) return;
    api
      .changeMedia(currentVm.uuid, target, path)
      .then(reloadDrives)
      .catch((err: unknown) => notifyError(t("iso.changeFailed", { name: currentVm.name }), err));
  };

  if (error?.code === "auth.invalid_token") {
    return (
      <div className="session-error">
        <ErrorMessage error={error} />
      </div>
    );
  }

  return (
    <LibraryActionsProvider
      library={library}
      onNewVm={(folder) => {
        setWizardFolder(folder);
        setWizardOpen(true);
      }}
      onSnapshots={(vm) => setSnapshotFor({ uuid: vm.uuid, kind: "manager" })}
    >
      <div className="app">
        <MenuBar
          layout={layout}
          onToggle={toggle}
          onAbout={() => setAboutOpen(true)}
          onNetworkEditor={guest ? undefined : () => setNetworkEditorOpen(true)}
          onPreferences={guest ? undefined : () => setPreferencesOpen(true)}
          onFirstRun={guest ? undefined : () => setFirstRunOpen(true)}
          onLogout={guest ? logout : undefined}
          guestLanguage={
            guest
              ? {
                  current: i18n.language,
                  onChange: (language) => {
                    storeGuestLanguage(language);
                    void i18n.changeLanguage(language);
                    document.documentElement.lang = language;
                  },
                }
              : undefined
          }
          onNewVm={() => setWizardOpen(true)}
          onOpenDisk={openDisk}
          onScan={guest ? undefined : () => setScanOpen(true)}
          onSettings={() => currentVm && setSettingsFor(currentVm.uuid)}
          onSnapshot={
            currentVm ? (kind) => setSnapshotFor({ uuid: currentVm.uuid, kind }) : undefined
          }
          onGuestTools={() => currentVm && setGuestToolsFor(currentVm.uuid)}
          vmConsole={vmConsole}
          onFullscreen={consoleFullscreenFor ? toggleConsoleFullscreen : undefined}
          onAppFullscreen={toggleFullscreen}
          onGoHome={() => setActiveTab(HOME_TAB)}
          onCloseTab={activeTab !== HOME_TAB ? () => closeTab(activeTab) : undefined}
          onNextTab={allTabs.length > 1 ? () => cycleTab(1) : undefined}
          onPreviousTab={allTabs.length > 1 ? () => cycleTab(-1) : undefined}
          tabs={[{ id: HOME_TAB, label: t("home.tab") }, ...tabs]}
          activeTab={activeTab}
          onActivateTab={setActiveTab}
          onQuit={info?.mode === "desktop" && desktopWindow() ? () => setQuitting(true) : undefined}
          drives={drives}
          onChangeMedia={setMediaTarget}
          onEject={(target) => setMedia(target, null)}
          vm={currentVm}
        />
        {layout.toolbar && (
          <Toolbar
            libraryVisible={layout.library}
            onToggleLibrary={() => toggle("library")}
            vm={currentVm}
            vmConsole={vmConsole}
            onFullscreen={consoleFullscreenFor ? toggleConsoleFullscreen : undefined}
            onSnapshot={
              currentVm ? (kind) => setSnapshotFor({ uuid: currentVm.uuid, kind }) : undefined
            }
          />
        )}
        <div className="app-body">
          {layout.library && (
            <LibraryPanel
              vms={vms}
              library={library}
              loading={loading}
              error={error}
              selected={selectedNode}
              onSelect={setSelectedNode}
              onOpen={(uuid) => openVm(uuid, vmByUuid.get(uuid)?.name)}
              onSettings={setSettingsFor}
              onRefresh={refresh}
              onClose={() => toggle("library")}
            />
          )}
          <main className="workspace">
            <TabBar tabs={tabs} active={activeTab} onActivate={setActiveTab} onClose={closeTab} />
            <div className="workspace-content" hidden={activeTab !== HOME_TAB}>
              <HomeTab onNewVm={() => setWizardOpen(true)} />
            </div>
            {/* VM tabs stay mounted so their console keeps its connection. */}
            {openVms.map((uuid) => (
              <div
                key={uuid}
                className={
                  uuid === consoleFullscreen
                    ? "workspace-content workspace-fullscreen"
                    : "workspace-content"
                }
                hidden={activeTab !== uuid}
              >
                <VmTab vm={vmByUuid.get(uuid)} onSettings={() => setSettingsFor(uuid)} />
              </div>
            ))}
          </main>
        </div>
        {layout.statusBar && (
          <StatusBar
            info={info}
            vms={vms}
            libvirtLost={libvirtLost}
            vmConsole={activeTab !== HOME_TAB ? vmConsole : null}
          />
        )}
        {consoleFullscreen && (
          <FullscreenBar
            vm={vmByUuid.get(consoleFullscreen) as VmSummary}
            vmConsole={vmConsole}
            onExit={exitConsoleFullscreen}
          />
        )}
        <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} version={info?.version} />
        {networkEditorOpen && <NetworkEditor onClose={() => setNetworkEditorOpen(false)} />}
        {settingsFor && vmByUuid.get(settingsFor) && (
          <VmSettings
            vm={vmByUuid.get(settingsFor) as VmSummary}
            onClose={() => setSettingsFor(null)}
          />
        )}
        {guestToolsFor && vmByUuid.get(guestToolsFor) && (
          <GuestToolsDialog
            vm={vmByUuid.get(guestToolsFor) as VmSummary}
            onClose={() => setGuestToolsFor(null)}
          />
        )}
        {wizardOpen && (
          <NewVmWizard
            library={library}
            vms={vms ?? []}
            initialFolder={
              wizardFolder ?? (selectedNode?.startsWith("f:") ? selectedNode.slice(2) : "")
            }
            initialDisk={wizardDisk}
            onCreated={(uuid, name) => {
              refresh();
              openVm(uuid, name);
            }}
            onClose={() => {
              setWizardOpen(false);
              setWizardDisk(undefined);
              setWizardFolder(undefined);
            }}
          />
        )}
        {scanOpen && (
          <ScanDialog start={library?.root ?? null} onClose={() => setScanOpen(false)} />
        )}
        {pickingDisk && (
          <PathPicker
            kind="disk"
            title={t("files.openDisk")}
            start={library?.root ?? null}
            onChoose={(path) => {
              setPickingDisk(false);
              startFromDisk(path);
            }}
            onClose={() => setPickingDisk(false)}
          />
        )}
        {mediaTarget && currentVm && (
          <IsoPicker
            title={t("iso.titleFor", { name: currentVm.name, target: mediaTarget })}
            onPick={(path) => {
              setMedia(mediaTarget, path);
              setMediaTarget(null);
            }}
            onClose={() => setMediaTarget(null)}
          />
        )}
        {preferencesOpen && (
          <PreferencesDialog
            onClose={() => setPreferencesOpen(false)}
            onSaved={refresh}
            onScan={() => {
              setPreferencesOpen(false);
              setScanOpen(true);
            }}
          />
        )}
        {snapshotFor && vmByUuid.get(snapshotFor.uuid) && (
          <SnapshotRequest
            vm={vmByUuid.get(snapshotFor.uuid) as VmSummary}
            kind={snapshotFor.kind}
            onClose={closeSnapshot}
          />
        )}
        {quitting && (
          <CloseDialog
            reason="quit"
            onCancel={() => setQuitting(false)}
            onProceed={() => void window.pywebview?.api?.close_window?.()}
          />
        )}
        {firstRunOpen && (
          <FirstRunWizard onClose={() => setFirstRunOpen(false)} onSaved={refresh} />
        )}
      </div>
    </LibraryActionsProvider>
  );
}

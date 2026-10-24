import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { ErrorMessage } from "../components/ErrorMessage";
import { NotificationProvider } from "../components/Notifications";
import { useNotifier } from "../components/notifier";
import { HomeTab } from "../features/home/HomeTab";
import { LibraryActionsProvider } from "../features/library/LibraryActions";
import { LibraryPanel } from "../features/library/LibraryPanel";
import { VmActionsProvider } from "../features/vm/VmActions";
import { NetworkEditor } from "../features/network-editor/NetworkEditor";
import { PreferencesDialog } from "../features/preferences/PreferencesDialog";
import { IsoPicker } from "../features/iso-picker/IsoPicker";
import { NewVmWizard } from "../features/wizard/NewVmWizard";
import { useCdroms } from "../features/vm/useCdroms";
import { VmTab } from "../features/vm/VmTab";
import { AboutDialog } from "./AboutDialog";
import { MenuBar } from "./MenuBar";
import { StatusBar } from "./StatusBar";
import { HOME_TAB, TabBar } from "./TabBar";
import { Toolbar } from "./Toolbar";
import { useAppData } from "./useAppData";
import "./App.css";

export interface Layout {
  library: boolean;
  toolbar: boolean;
  statusBar: boolean;
}

export function App() {
  return (
    <NotificationProvider>
      <VmActionsProvider>
        <MainWindow />
      </VmActionsProvider>
    </NotificationProvider>
  );
}

function MainWindow() {
  const { t, i18n } = useTranslation();
  const { notifyError } = useNotifier();
  const { info, vms, library, error, loading, libvirtLost, refresh } = useAppData();
  const [layout, setLayout] = useState<Layout>({ library: true, toolbar: true, statusBar: true });
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [networkEditorOpen, setNetworkEditorOpen] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [mediaTarget, setMediaTarget] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [openVms, setOpenVms] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<string>(HOME_TAB);

  useEffect(() => {
    if (!info) return;
    void i18n.changeLanguage(info.ui.language);
    document.documentElement.lang = info.ui.language;
    document.documentElement.dataset.mode = info.mode;
    if (info.ui.theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = info.ui.theme;
  }, [info, i18n]);

  const toggle = (key: keyof Layout) => setLayout((l) => ({ ...l, [key]: !l[key] }));

  const openVm = (uuid: string) => {
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
  const tabs = openVms.map((uuid) => ({ id: uuid, label: vmByUuid.get(uuid)?.name ?? uuid }));
  // Menu and toolbar act on the VM of the active tab, else on the library selection.
  const selectedVm = selectedNode?.startsWith("v:") ? selectedNode.slice(2) : "";
  const currentVm = vmByUuid.get(activeTab !== HOME_TAB ? activeTab : selectedVm) ?? null;
  const { drives, reload: reloadDrives } = useCdroms(currentVm);
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
    <LibraryActionsProvider library={library}>
      <div className="app">
        <MenuBar
          layout={layout}
          onToggle={toggle}
          onAbout={() => setAboutOpen(true)}
          onNetworkEditor={() => setNetworkEditorOpen(true)}
          onPreferences={() => setPreferencesOpen(true)}
          onNewVm={() => setWizardOpen(true)}
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
              onOpen={openVm}
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
              <div key={uuid} className="workspace-content" hidden={activeTab !== uuid}>
                <VmTab vm={vmByUuid.get(uuid)} />
              </div>
            ))}
          </main>
        </div>
        {layout.statusBar && <StatusBar info={info} vms={vms} libvirtLost={libvirtLost} />}
        <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} version={info?.version} />
        {networkEditorOpen && <NetworkEditor onClose={() => setNetworkEditorOpen(false)} />}
        {wizardOpen && (
          <NewVmWizard
            library={library}
            vms={vms ?? []}
            initialFolder={selectedNode?.startsWith("f:") ? selectedNode.slice(2) : ""}
            onCreated={(uuid) => {
              refresh();
              openVm(uuid);
            }}
            onClose={() => setWizardOpen(false)}
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
          <PreferencesDialog onClose={() => setPreferencesOpen(false)} onSaved={refresh} />
        )}
      </div>
    </LibraryActionsProvider>
  );
}

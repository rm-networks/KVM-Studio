import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorMessage } from "../components/ErrorMessage";
import { HomeTab } from "../features/home/HomeTab";
import { LibraryPanel } from "../features/library/LibraryPanel";
import { AboutDialog } from "./AboutDialog";
import { MenuBar } from "./MenuBar";
import { StatusBar } from "./StatusBar";
import { TabBar } from "./TabBar";
import { Toolbar } from "./Toolbar";
import { useAppData } from "./useAppData";
import "./App.css";

export interface Layout {
  library: boolean;
  toolbar: boolean;
  statusBar: boolean;
}

export function App() {
  const { i18n } = useTranslation();
  const { info, vms, error, loading, refresh } = useAppData();
  const [layout, setLayout] = useState<Layout>({ library: true, toolbar: true, statusBar: true });
  const [selectedVm, setSelectedVm] = useState<string | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);

  useEffect(() => {
    if (!info) return;
    void i18n.changeLanguage(info.ui.language);
    document.documentElement.lang = info.ui.language;
    if (info.ui.theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = info.ui.theme;
  }, [info, i18n]);

  if (error?.code === "auth.invalid_token") {
    return (
      <div className="session-error">
        <ErrorMessage error={error} />
      </div>
    );
  }

  const toggle = (key: keyof Layout) => setLayout((l) => ({ ...l, [key]: !l[key] }));

  return (
    <div className="app">
      <MenuBar layout={layout} onToggle={toggle} onAbout={() => setAboutOpen(true)} />
      {layout.toolbar && (
        <Toolbar libraryVisible={layout.library} onToggleLibrary={() => toggle("library")} />
      )}
      <div className="app-body">
        {layout.library && (
          <LibraryPanel
            vms={vms}
            loading={loading}
            error={error}
            selected={selectedVm}
            onSelect={setSelectedVm}
            onRefresh={refresh}
            onClose={() => toggle("library")}
          />
        )}
        <main className="workspace">
          <TabBar />
          <div className="workspace-content">
            <HomeTab />
          </div>
        </main>
      </div>
      {layout.statusBar && <StatusBar info={info} vms={vms} />}
      <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} version={info?.version} />
    </div>
  );
}

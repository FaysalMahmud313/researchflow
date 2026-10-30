import { lazy, Suspense, useEffect, useState } from 'react';
import { TopNav } from './components/TopNav';
import { Sidebar } from './components/Sidebar';
import { Spinner, Toasts } from './components/ui';
import { useApp, useRoute } from './lib/app';
import { AuthPage } from './pages/AuthPage';
import { OverviewPage } from './pages/OverviewPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { ProjectPage } from './pages/ProjectPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotificationsPage } from './pages/NotificationsPage';
import { CodeResultsPage, ExperimentsPage, FilesPage, PapersPage, ReferencesPage, TasksPage } from './pages/LibraryPages';

// The writing workspace pulls in the full CodeMirror editor; load it on demand.
const WorkspacePage = lazy(() => import('./workspace/WorkspacePage'));

export function App() {
  const { user, loading } = useApp();
  const route = useRoute();
  const [menuOpen, setMenuOpen] = useState(false);
  // Verification and reset links (#/auth/...) open the auth screens even when signed in.
  const [authLink, setAuthLink] = useState(() => window.location.hash.startsWith('#/auth/'));
  useEffect(() => {
    const onHash = () => setAuthLink(window.location.hash.startsWith('#/auth/'));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        <Spinner size={20} />
      </div>
    );
  }
  if (!user || authLink) {
    return (
      <>
        <AuthPage />
        <Toasts />
      </>
    );
  }

  const inWorkspace = route.name === 'workspace';
  let page: JSX.Element;
  if (route.name === 'workspace') {
    page = (
      <Suspense fallback={<div className="flex h-full items-center justify-center"><Spinner size={20} /></div>}>
        <WorkspacePage key={route.manuscriptId} manuscriptId={route.manuscriptId} initialFileId={route.fileId} />
      </Suspense>
    );
  } else if (route.name === 'project') {
    page = <ProjectPage key={route.projectId} projectId={route.projectId} tab={route.tab} />;
  } else {
    const pages: Record<string, JSX.Element> = {
      overview: <OverviewPage />,
      mine: <ProjectsPage key="mine" mode="mine" />,
      shared: <ProjectsPage key="shared" mode="shared" />,
      papers: <PapersPage />,
      files: <FilesPage />,
      code: <CodeResultsPage />,
      references: <ReferencesPage />,
      experiments: <ExperimentsPage />,
      tasks: <TasksPage />,
      notifications: <NotificationsPage />,
      settings: <SettingsPage />,
    };
    page = pages[route.section];
  }

  return (
    <div className="flex h-full flex-col">
      <TopNav compact={inWorkspace} onMenu={() => setMenuOpen((o) => !o)} />
      <div className="flex min-h-0 flex-1">
        {/* The writing workspace uses the full width; the sidebar stays one click away via the menu button. */}
        {(!inWorkspace || menuOpen) && <Sidebar route={route} open={menuOpen} onNavigate={() => setMenuOpen(false)} />}
        {menuOpen && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
        <main className="min-h-0 min-w-0 flex-1">{page}</main>
      </div>
      <Toasts />
    </div>
  );
}

import { Suspense, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Rail } from '@/components/navigation/Rail';
import { TopBar } from '@/components/navigation/TopBar';
import { MobileNav } from '@/components/navigation/MobileNav';
import { Footer } from '@/components/navigation/Footer';
import { CompareTray } from '@/components/navigation/CompareTray';
import { CommandPalette } from '@/components/search/CommandPalette';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import { Toaster } from '@/components/common/Toaster';
import { ErrorBoundary } from '@/components/common/ErrorState';
import { PageSkeleton } from './PageSkeleton';

export function AppShell() {
  const loc = useLocation();
  useEffect(() => {
    if (!loc.hash) window.scrollTo({ top: 0 });
  }, [loc.pathname, loc.hash]);
  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Rail />
      <div className="shell-main">
        <TopBar />
        <main id="main" tabIndex={-1} style={{ flex: 1, display: 'flex', flexDirection: 'column', outline: 'none' }}>
          <ErrorBoundary label="This page">
            <Suspense fallback={<PageSkeleton />}>
              <div key={loc.pathname} className="page-enter" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <Outlet />
              </div>
            </Suspense>
          </ErrorBoundary>
        </main>
        <Footer />
      </div>
      <MobileNav />
      <CompareTray />
      <CommandPalette />
      <EvidenceDrawer />
      <Toaster />
    </div>
  );
}

import { Suspense, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Rail } from '@/components/navigation/Rail';
import { TopBar } from '@/components/navigation/TopBar';
import { MobileNav } from '@/components/navigation/MobileNav';
import { Footer } from '@/components/navigation/Footer';
import { CompareTray, useCompareTrayVisible } from '@/components/navigation/CompareTray';
import { CommandPalette } from '@/components/search/CommandPalette';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import { Toaster } from '@/components/common/Toaster';
import { RevealRegion } from '@/components/common/RevealRegion';
import { ErrorBoundary } from '@/components/common/ErrorState';
import { PageSkeleton } from './PageSkeleton';

export function AppShell() {
  const loc = useLocation();
  const tray = useCompareTrayVisible();
  // moving between conversations is not a page change: the chat workspace (history, scroll, focus) stays mounted
  const revealKey = loc.pathname.startsWith('/chat') ? '/chat' : loc.pathname;
  useEffect(() => {
    if (!loc.hash) window.scrollTo({ top: 0 });
  }, [revealKey, loc.hash]);
  return (
    <div className="shell" data-tray={tray || undefined}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Rail />
      <div className="shell-main">
        <TopBar />
        <main id="main" tabIndex={-1} style={{ flex: 1, display: 'flex', flexDirection: 'column', outline: 'none' }}>
          <ErrorBoundary label="This page">
            <Suspense fallback={<PageSkeleton />}>
              <RevealRegion key={revealKey} className="page-enter" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <Outlet />
              </RevealRegion>
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

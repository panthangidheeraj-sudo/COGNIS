import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Search } from 'lucide-react';
import { useUi } from '@/stores/ui';
import { modKeyLabel } from '@/hooks/useHotkey';
import { CognisLogo } from '@/components/common/Motif';
import { StatusCenter } from './StatusCenter';
import { ThemeToggle } from './ThemeToggle';
import { DensityToggle } from './DensityToggle';

export function TopBar() {
  const openPalette = useUi((s) => s.openPalette);
  const [scrolled, setScrolled] = useState(false);
  const onHome = useLocation().pathname === '/';
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  return (
    <header className={`topbar ${scrolled ? 'is-scrolled' : ''}`}>
      <Link to="/" className="topbar-logo" aria-label="COGNIS home">
        <CognisLogo />
      </Link>
      <button className={`search-trigger ${onHome && !scrolled ? 'search-trigger--hidden' : ''}`} onClick={() => openPalette()} aria-label="Search companies, research and data sheets">
        <Search aria-hidden />
        <span className="st-label">Search companies, research, sheets…</span>
        <span className="kbd" aria-hidden>
          {modKeyLabel} K
        </span>
      </button>
      <span className="spacer" />
      <StatusCenter />
      <DensityToggle />
      <ThemeToggle />
    </header>
  );
}

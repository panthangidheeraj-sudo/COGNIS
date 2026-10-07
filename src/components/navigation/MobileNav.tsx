import { useState } from 'react';
import { NavLink, Link, useLocation } from 'react-router-dom';
import { Ellipsis } from 'lucide-react';
import { Modal } from '@/components/common/Overlay';
import { PRIMARY_NAV, SECONDARY_NAV } from './navItems';

/** Bottom navigation for phones: 4 primary destinations + More. */
export function MobileNav() {
  const [more, setMore] = useState(false);
  const loc = useLocation();
  const main = PRIMARY_NAV.slice(0, 4);
  const rest = [...PRIMARY_NAV.slice(4), ...SECONDARY_NAV];
  const moreActive = rest.some((r) => loc.pathname.startsWith(r.to));
  return (
    <>
      <nav className="mobile-nav" aria-label="Primary">
        {main.map(({ to, label, icon: Icon, ...r }) => (
          <NavLink key={to} to={to} end={'end' in r}>
            <Icon aria-hidden />
            {label}
          </NavLink>
        ))}
        <button className={moreActive ? 'active' : ''} onClick={() => setMore(true)} aria-haspopup="dialog">
          <Ellipsis aria-hidden />
          More
        </button>
      </nav>
      <Modal open={more} onClose={() => setMore(false)} title="More">
        <div className="more-grid">
          {rest.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} onClick={() => setMore(false)}>
              <Icon aria-hidden />
              {label}
            </Link>
          ))}
        </div>
      </Modal>
    </>
  );
}

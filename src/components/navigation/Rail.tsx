import { NavLink, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api';
import { CognisLogo } from '@/components/common/Motif';
import { PRIMARY_NAV, SECONDARY_NAV } from './navItems';

/** Compact desktop/tablet rail. */
export function Rail() {
  const { data: watch } = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist.get, staleTime: 60_000 });
  return (
    <nav className="rail" aria-label="Primary">
      <Link to="/" className="rail-logo" aria-label="COGNIS home">
        <CognisLogo compact />
      </Link>
      <div className="rail-nav">
        {PRIMARY_NAV.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink key={to} to={to} end={'end' in rest} className="rail-link">
            <Icon aria-hidden />
            <span className="rail-label">{label}</span>
            {to === '/watchlist' && watch && watch.changedCount > 0 && (
              <span className="rail-badge" aria-label={`${watch.changedCount} companies changed`}>
                {watch.changedCount}
              </span>
            )}
          </NavLink>
        ))}
      </div>
      <div className="rail-foot">
        {SECONDARY_NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className="rail-link">
            <Icon aria-hidden />
            <span className="rail-label">{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

import { Columns3, Compass, House, Library, Radar, Table2, Telescope, Settings2, CircleHelp } from 'lucide-react';

export const PRIMARY_NAV = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/discover', label: 'Discover', icon: Compass },
  { to: '/research', label: 'Research', icon: Telescope },
  { to: '/library', label: 'Library', icon: Library },
  { to: '/sheets', label: 'Data Sheets', icon: Table2 },
  { to: '/compare', label: 'Compare', icon: Columns3 },
  { to: '/watchlist', label: 'Watchlist', icon: Radar },
] as const;

export const SECONDARY_NAV = [
  { to: '/settings', label: 'Settings', icon: Settings2 },
  { to: '/about', label: 'About', icon: CircleHelp },
] as const;

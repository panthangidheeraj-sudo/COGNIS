import { lazy } from 'react';
import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { AppShell } from './layout/AppShell';

// Route-level code splitting: heavy pages (charts, 3D) load on demand.
const Home = lazy(() => import('@/pages/Home/HomePage'));
const Discover = lazy(() => import('@/pages/Discover/DiscoverPage'));
const Research = lazy(() => import('@/pages/Research/ResearchPage'));
const Company = lazy(() => import('@/pages/Company/CompanyPage'));
const Library = lazy(() => import('@/pages/Library/LibraryPage'));
const Artifact = lazy(() => import('@/pages/Artifact/ArtifactPage'));
const SheetsIndex = lazy(() => import('@/pages/DataSheets/SheetsIndexPage'));
const Sheet = lazy(() => import('@/pages/DataSheets/SheetPage'));
const Compare = lazy(() => import('@/pages/Compare/ComparePage'));
const Watchlist = lazy(() => import('@/pages/Watchlist/WatchlistPage'));
const Settings = lazy(() => import('@/pages/Settings/SettingsPage'));
const About = lazy(() => import('@/pages/Settings/AboutPage'));
const NotFound = lazy(() => import('@/pages/NotFoundPage'));

function CompanyResearchRedirect() {
  const { orgNumber } = useParams();
  return <Navigate to={`/research?org=${orgNumber}`} replace />;
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/discover', element: <Discover /> },
      { path: '/research', element: <Research /> },
      { path: '/company/:orgNumber', element: <Company /> },
      { path: '/company/:orgNumber/research', element: <CompanyResearchRedirect /> },
      { path: '/library', element: <Library /> },
      { path: '/library/:artifactId', element: <Artifact /> },
      { path: '/sheets', element: <SheetsIndex /> },
      { path: '/sheets/:sheetId', element: <Sheet /> },
      { path: '/compare', element: <Compare /> },
      { path: '/watchlist', element: <Watchlist /> },
      { path: '/settings', element: <Settings /> },
      { path: '/about', element: <About /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

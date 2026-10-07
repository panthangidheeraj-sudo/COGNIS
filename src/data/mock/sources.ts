/**
 * MOCK BACKEND — source catalog.
 * Source names are real public Norwegian sources, used only as labels.
 * All company data in the mock backend is fictional demo data.
 */
import type { Source } from '@/types';

export const SOURCES: Record<string, Source> = {
  brreg: {
    id: 'brreg',
    name: 'Brønnøysundregistrene',
    originalTitle: 'Enhetsregisteret',
    kind: 'registry',
    tier: 'primary',
    official: true,
    url: 'https://www.brreg.no/',
    domain: 'brreg.no',
  },
  accounts: {
    id: 'accounts',
    name: 'Regnskapsregisteret',
    originalTitle: 'Regnskapsregisteret — årsregnskap',
    kind: 'financial',
    tier: 'primary',
    official: true,
    url: 'https://www.brreg.no/',
    domain: 'brreg.no',
  },
  roles: {
    id: 'roles',
    name: 'Brønnøysundregistrene — roles',
    originalTitle: 'Enhetsregisteret — roller',
    kind: 'people',
    tier: 'primary',
    official: true,
    url: 'https://www.brreg.no/',
    domain: 'brreg.no',
  },
  announcements: {
    id: 'announcements',
    name: 'Brønnøysundregistrene — announcements',
    originalTitle: 'Kunngjøringer',
    kind: 'activity',
    tier: 'primary',
    official: true,
    url: 'https://www.brreg.no/',
    domain: 'brreg.no',
  },
  nav: {
    id: 'nav',
    name: 'arbeidsplassen.nav.no',
    originalTitle: 'Arbeidsplassen — NAV',
    kind: 'jobs',
    tier: 'primary',
    official: true,
    url: 'https://arbeidsplassen.nav.no/',
    domain: 'arbeidsplassen.nav.no',
  },
  doffin: {
    id: 'doffin',
    name: 'Doffin',
    originalTitle: 'Doffin — offentlige anskaffelser',
    kind: 'regulatory',
    tier: 'primary',
    official: true,
    url: 'https://www.doffin.no/',
    domain: 'doffin.no',
  },
  linkedin: {
    id: 'linkedin',
    name: 'LinkedIn',
    kind: 'people',
    tier: 'secondary',
    official: false,
    url: 'https://www.linkedin.com/',
    domain: 'linkedin.com',
  },
  proff: {
    id: 'proff',
    name: 'Proff.no',
    kind: 'financial',
    tier: 'secondary',
    official: false,
    url: 'https://www.proff.no/',
    domain: 'proff.no',
  },
  websearch: {
    id: 'websearch',
    name: 'Web search',
    kind: 'web',
    tier: 'discovery',
    official: false,
  },
};

export function websiteSource(orgNumber: string, domain: string): Source {
  return {
    id: `web-${orgNumber}`,
    name: `Official website (${domain})`,
    kind: 'website',
    tier: 'primary',
    official: true,
    url: `https://${domain}/`,
    domain,
  };
}

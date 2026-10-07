import { useState } from 'react';
import { MapPin } from 'lucide-react';
import type { CompanyLocation, CompanyProfile, Person } from '@/types';
import { FactValue } from '@/components/evidence/FactValue';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { Modal } from '@/components/common/Overlay';
import { EmptyState } from '@/components/common/EmptyState';
import { CompanyNetwork } from '@/components/network/CompanyNetwork';
import { NorwayMap } from '@/components/maps/NorwayMap';
import { SectionState } from '../SectionState';
import { formatDate } from '@/utils/format';

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('');
}

export function PeopleSection({ profile, showNetwork = true }: { profile: CompanyProfile; showNetwork?: boolean }) {
  const [person, setPerson] = useState<Person | null>(null);
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const people = profile.people.people;
  const groups: { id: string; label: string; list: Person[] }[] = [
    { id: 'exec', label: 'Executive', list: people.filter((p) => p.roleGroup === 'executive' && p.current) },
    { id: 'board', label: 'Board', list: people.filter((p) => p.roleGroup === 'board' && p.current) },
    { id: 'founder', label: 'Founders (verified)', list: people.filter((p) => p.roleGroup === 'founder') },
    { id: 'other', label: 'Other roles', list: people.filter((p) => p.roleGroup === 'other' && p.current) },
    { id: 'hist', label: 'Historical', list: people.filter((p) => !p.current) },
  ].filter((g) => g.list.length);

  return (
    <div className="stack" style={{ gap: 22 }}>
      <SectionState meta={profile.people} sourceIndex={profile.sourceIndex} />
      {!people.length && profile.people.status !== 'pending' && <EmptyState compact title="No registered roles found." />}
      {groups.map((g) => (
        <section key={g.id} aria-labelledby={`pg-${g.id}`} data-search-block={`people-${g.id}`}>
          <div className="block-head">
            <h3 id={`pg-${g.id}`}>{g.label}</h3>
            <span className="t-micro">{g.list.length}</span>
          </div>
          <div className="people-grid">
            {g.list.map((p) => (
              <button key={p.id} className="person" onClick={() => setPerson(p)} aria-label={`${p.name}, ${p.role}. Show details.`}>
                <span className="person-avatar" aria-hidden>
                  {initials(p.name)}
                </span>
                <span className="stack" style={{ gap: 2, minWidth: 0, flex: 1, textAlign: 'left' }}>
                  <span className="person-name truncate">{p.name}</span>
                  <span className="t-sm t-soft truncate">{p.role}</span>
                  <span className="t-xs t-muted">
                    {p.since ? `Since ${formatDate(p.since)}` : 'Start date not recorded'}
                    {p.until ? ` · until ${formatDate(p.until)}` : ''}
                  </span>
                </span>
                <span className={`pill pill--sm ${p.current ? 'pill--ok' : ''}`}>{p.current ? 'Current' : 'Historical'}</span>
              </button>
            ))}
          </div>
        </section>
      ))}

      {showNetwork && people.length > 0 && (
        <section className="card" aria-labelledby="net-h" data-search-block="network">
          <div className="card-head">
            <h3 id="net-h">Company network</h3>
            <span className="t-xs t-muted">Every connection has registry or public evidence · click a node</span>
          </div>
          <CompanyNetwork name={profile.company.legalName} relationships={profile.relationships} onSelect={(r) => openEv({ title: `${r.label}: ${r.entity.name}`, value: r.entity.orgNumber ? `${r.entity.name} (${r.entity.orgNumber})` : r.entity.name, evidence: r.evidence })} />
        </section>
      )}

      <Modal open={!!person} onClose={() => setPerson(null)} title={person?.name ?? ''}>
        {person && (
          <div className="stack" style={{ gap: 16 }}>
            <dl className="kv">
              <dt>Current role</dt>
              <dd>
                <FactValue fact={person.fact} sourceIndex={profile.sourceIndex} context={profile.company.legalName} /> <span className="t-soft">· {person.role}</span>
              </dd>
              <dt>Effective from</dt>
              <dd>{person.since ? formatDate(person.since) : 'Not recorded'}</dd>
              {person.until && (
                <>
                  <dt>Until</dt>
                  <dd>{formatDate(person.until)}</dd>
                </>
              )}
              <dt>State</dt>
              <dd>{person.current ? 'Current' : 'Historical'}</dd>
            </dl>
            <div className="stack" style={{ gap: 8 }}>
              <span className="t-micro">Other company relationships</span>
              {person.otherRoles?.length ? (
                person.otherRoles.map((r) => (
                  <button key={r.companyName} className="row-btn" onClick={() => openEv({ title: `${person.name} — ${r.role}`, value: r.companyName, evidence: r.evidence })}>
                    <span className="stack" style={{ gap: 0, flex: 1, textAlign: 'left' }}>
                      <span>{r.companyName}</span>
                      <span className="t-xs t-muted">
                        {r.role} · {r.current ? 'Current' : 'Historical'}
                      </span>
                    </span>
                    <span className="t-xs t-accent">Evidence</span>
                  </button>
                ))
              ) : (
                <p className="t-sm t-muted">No other verified roles found in the registry.</p>
              )}
            </div>
            <p className="t-xs t-muted">Only role information from public registries is shown. COGNIS does not collect personal contact details or photos.</p>
          </div>
        )}
      </Modal>
    </div>
  );
}

const KIND_LABEL: Record<CompanyLocation['kind'], string> = {
  registered_address: 'Registered address',
  headquarters: 'Headquarters (verified)',
  operating: 'Operating location',
  postal: 'Postal address',
};

export function LocationsSection({ profile, mapHeight = 380 }: { profile: CompanyProfile; mapHeight?: number }) {
  const locs = profile.locations.locations;
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const onlyRegistered = locs.every((l) => l.kind === 'registered_address');
  return (
    <div className="loc">
      <div className="loc-map card" style={{ padding: 12 }} data-search-block="locations-map">
        <NorwayMap locations={locs} height={mapHeight} onSelect={(l) => openEv(l.fact)} />
      </div>
      <div className="stack" style={{ gap: 10 }} data-search-block="locations-list">
        <SectionState meta={profile.locations} sourceIndex={profile.sourceIndex} />
        {onlyRegistered && <div className="state-banner">No verified location data beyond the registered address.</div>}
        {locs.map((l) => (
          <div key={l.id} className="loc-item">
            <MapPin aria-hidden className={l.verified ? 't-accent' : 't-muted'} />
            <div className="stack" style={{ gap: 2, minWidth: 0, flex: 1 }}>
              <span className="row-wrap" style={{ gap: 6 }}>
                <strong style={{ fontWeight: 500 }}>{l.municipality}</strong>
                <span className="pill pill--sm">{KIND_LABEL[l.kind]}</span>
                {!l.verified && <span className="pill pill--sm pill--warn">Not verified</span>}
              </span>
              <FactValue fact={l.fact} sourceIndex={profile.sourceIndex} context={profile.company.legalName} className="t-sm" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

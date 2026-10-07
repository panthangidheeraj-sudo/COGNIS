import { useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowRightLeft, ArrowUp, History, Lightbulb } from 'lucide-react';
import type { Change, CompanyProfile } from '@/types';
import { Popover } from '@/components/common/Popover';
import { useOpenEvidence } from '@/components/evidence/useEvidence';
import { VerificationLine, evidenceAsFact } from '@/components/evidence/SourceBadge';
import { formatDate, formatRelative } from '@/utils/format';
import { CHANGE_CATEGORY_LABEL, CHANGE_ORDER } from '@/utils/status';
import { cn } from '@/utils/cn';

interface ChipGroup {
  key: string;
  headline: string;
  changes: Change[];
  direction?: 'up' | 'down';
}

/** Orders material changes by decision relevance and folds repeated additions ("2 new locations"). */
export function groupMaterialChanges(changes: Change[]): ChipGroup[] {
  const material = changes
    .filter((c) => c.material)
    .sort((a, b) => CHANGE_ORDER.indexOf(a.category) - CHANGE_ORDER.indexOf(b.category) || b.detectedAt.localeCompare(a.detectedAt));
  const out: ChipGroup[] = [];
  for (const c of material) {
    const foldable = (c.category === 'location' || c.category === 'address') && c.kind === 'added';
    const existing = foldable ? out.find((g) => g.key === `fold-${c.category}`) : undefined;
    if (existing) {
      existing.changes.push(c);
      existing.headline = `${existing.changes.length} new locations`;
      continue;
    }
    out.push({ key: foldable ? `fold-${c.category}` : c.id, headline: c.headline ?? c.label, changes: [c], direction: c.direction });
  }
  return out;
}

const DirIcon = ({ g }: { g: ChipGroup }) =>
  g.direction === 'up' ? <ArrowUp aria-hidden /> : g.direction === 'down' ? <ArrowDown aria-hidden /> : <ArrowRightLeft aria-hidden />;

/**
 * "What changed?" — only backend-verified, material changes since the
 * previous research, in decision order. When nothing material was detected
 * it says so, without implying that nothing changed in the real world.
 */
export function WhatChanged({ profile, onAllChanges, onExplain }: { profile: CompanyProfile; onAllChanges: () => void; onExplain: (c: Change) => void }) {
  const ch = profile.changes;
  const groups = useMemo(() => groupMaterialChanges(ch.changes), [ch.changes]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const anchors = useRef<Record<string, HTMLButtonElement | null>>({});
  const openEv = useOpenEvidence(profile.sourceIndex, profile.company.legalName);
  const since = ch.since ? `since the ${ch.baselineLabel ?? 'previous research'} on ${formatDate(ch.since)}` : 'since the previous research';
  const minor = ch.changes.filter((c) => !c.material).length;
  const active = groups.find((g) => g.key === openKey);

  return (
    <section className="wc" aria-labelledby="wc-h">
      <div className="wc-lead">
        <History aria-hidden />
        <h2 id="wc-h">What changed?</h2>
      </div>
      {ch.status === 'pending' ? (
        <p className="wc-empty">Change tracking starts after the first research. Only registry data is available for this company.</p>
      ) : groups.length === 0 ? (
        <p className="wc-empty">
          No verified material changes were detected {since}. {minor ? `${minor} minor update${minor === 1 ? ' was' : 's were'} recorded. ` : ''}
          <span className="t-muted">This covers the sources checked, not every possible change.</span>
        </p>
      ) : (
        <>
          <span className="wc-since">{capitalize(since)}</span>
          <ul className="wc-chips">
            {groups.map((g) => (
              <li key={g.key}>
                <button
                  ref={(el) => {
                    anchors.current[g.key] = el;
                  }}
                  className={cn('wc-chip', g.direction === 'up' && 'is-up', g.direction === 'down' && 'is-down')}
                  onClick={() => setOpenKey(openKey === g.key ? null : g.key)}
                  aria-haspopup="dialog"
                  aria-expanded={openKey === g.key}
                >
                  <DirIcon g={g} />
                  {g.headline}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <button className="link-btn wc-all" onClick={onAllChanges}>
        All changes <ArrowRight aria-hidden />
      </button>

      {active && (
        <Popover anchor={anchors.current[active.key] ?? null} open onClose={() => setOpenKey(null)} label={active.headline} width={340}>
          <div className="stack" style={{ gap: 12 }}>
            <span className="t-micro">{CHANGE_CATEGORY_LABEL[active.changes[0].category]}</span>
            {active.changes.map((c) => (
              <div key={c.id} className="stack" style={{ gap: 6 }}>
                <strong style={{ fontWeight: 500 }}>{c.label}</strong>
                <span className="change-vals">
                  {c.previous && <span className="change-prev">{c.previous}</span>}
                  {c.previous && <span className="change-arrow">→</span>}
                  {c.current && <span className="change-cur">{c.current}</span>}
                </span>
                <span className="t-xs t-muted">
                  Detected {formatRelative(c.detectedAt)} · {[...new Set(c.evidence.map((e) => profile.sourceIndex[e.sourceId]?.name ?? e.sourceId))].join(', ')}
                </span>
                <VerificationLine fact={evidenceAsFact(c.evidence)} sourceIndex={profile.sourceIndex} />
                <div className="row-wrap" style={{ gap: 6 }}>
                  <button
                    className="btn btn--sm"
                    onClick={() => {
                      setOpenKey(null);
                      openEv({ title: c.label, value: c.previous ? `${c.previous} → ${c.current}` : c.current, evidence: c.evidence });
                    }}
                  >
                    Evidence
                  </button>
                  {c.explainable && (
                    <button
                      className="btn btn--sm"
                      onClick={() => {
                        setOpenKey(null);
                        onExplain(c);
                      }}
                    >
                      <Lightbulb aria-hidden /> Explain this change
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Popover>
      )}
    </section>
  );
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

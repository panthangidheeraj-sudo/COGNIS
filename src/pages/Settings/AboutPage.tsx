import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Ban,
  Banknote,
  BriefcaseBusiness,
  Building2,
  CircleAlert,
  CircleDashed,
  Compass,
  Earth,
  FileCheck2,
  Fingerprint,
  Landmark,
  Library,
  Lock,
  MapPin,
  Quote,
  Route,
  ScanSearch,
  Search,
  Shield,
  ShieldCheck,
  Telescope,
  Users,
} from 'lucide-react';
import { API_MODE } from '@/api/http';
import { useGlobe } from '@/stores/ui';
import { useReducedMotion } from '@/hooks/useMediaQuery';
import { useScrollStory } from '@/hooks/useScrollStory';
import { GlobeStage } from '@/components/globe/GlobeStage';
import { Motif } from '@/components/common/Motif';
import { cn } from '@/utils/cn';
import './about.css';

/**
 * About COGNIS as a scroll story. Each act is a tall section whose stage pins while the visual
 * progresses with scroll (`--p`, see useScrollStory); acts hand over to one another with short
 * cross-fades. Reduced motion shows the same content as a calm, static page.
 * Everything stated here describes what the product actually does — no figures, no invented data.
 */
const CHAPTERS = [
  { id: 'cognis', num: '01', title: 'COGNIS' },
  { id: 'find', num: '02', title: 'Find' },
  { id: 'understand', num: '03', title: 'Understand' },
  { id: 'verify', num: '04', title: 'Verify' },
  { id: 'evidence', num: '05', title: 'Evidence' },
  { id: 'workflow', num: '06', title: 'Research' },
  { id: 'precision', num: '07', title: 'Precision' },
];
/** Chapter → element to scroll to (two chapters share the Earth act). */
const ANCHOR: Record<string, string> = { cognis: 'act-earth', find: 'act-earth', understand: 'act-understand', verify: 'act-verify', evidence: 'act-evidence', workflow: 'act-workflow', precision: 'act-precision' };

const NORWAY = { id: 'about-norway', lat: 64.5, lon: 12 };

export default function AboutPage() {
  const reduced = useReducedMotion();
  const root = useRef<HTMLDivElement>(null);
  const active = useScrollStory(root, !reduced);

  // Act 1 → 2: the Earth turns towards Norway, where COGNIS researches companies.
  const setFocus = useGlobe((g) => g.setFocus);
  useEffect(() => {
    setFocus(!reduced && active === 1 ? NORWAY : null);
  }, [active, reduced, setFocus]);
  useEffect(() => () => setFocus(null), [setFocus]);

  const jump = (id: string) => {
    const el = document.getElementById(ANCHOR[id]);
    if (!el) return;
    const second = id === 'find';
    const y = el.getBoundingClientRect().top + window.scrollY + (second ? el.offsetHeight * 0.55 : 0);
    window.scrollTo({ top: y, behavior: reduced ? 'auto' : 'smooth' });
  };

  return (
    <div ref={root} className={cn('story', reduced && 'story--static')}>
      <nav className="story-index" aria-label="About chapters">
        <ol>
          {CHAPTERS.map((c, i) => (
            <li key={c.id}>
              <button className={cn(i === active && 'is-active')} aria-current={i === active ? 'step' : undefined} onClick={() => jump(c.id)}>
                <span className="t-mono">{c.num}</span>
                <span className="story-index-label">{c.title}</span>
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {/* ---------------- 01 + 02: identity, then Find (one Earth stage) ---------------- */}
      <section id="act-earth" className="act act--earth" data-act data-chapters={2} aria-label="COGNIS and Find">
        <div className="pin">
          <div className="act-visual earth-visual" aria-hidden>
            <GlobeStage className="story-globe" />
          </div>
          <div className="act-copy">
            <Copy className="copy--a" num="01" kicker="COGNIS" title={<>Company intelligence, <em className="t-serif">built from evidence.</em></>} lead>
              COGNIS finds Norwegian companies, explains them through public sources, and shows the evidence behind every fact it publishes.
              <span className="story-scroll-hint" aria-hidden>
                Scroll to follow a research run <ArrowRight />
              </span>
            </Copy>
            <Copy className="copy--b" num="02" kicker="Find" title={<>Find the <em className="t-serif">right</em> companies.</>}>
              Search by name, organization number, industry or place — or describe what you need in plain language. COGNIS turns the description into filters it can actually apply to Enhetsregisteret, and
              shows its interpretation so you can correct it.
              <Points
                items={[
                  [Search, 'Natural-language discovery, with the interpretation shown as editable filters'],
                  [Fingerprint, 'One company, one organization number: exact identity before any research'],
                  [Earth, 'Results placed on the globe only where a location is verified'],
                ]}
              />
            </Copy>
          </div>
        </div>
      </section>

      {/* ---------------- 03: Understand ---------------- */}
      <section id="act-understand" className="act act--understand" data-act aria-labelledby="h-understand">
        <div className="pin">
          <div className="act-copy">
            <Copy id="h-understand" num="03" kicker="Understand" title={<>A dossier, <em className="t-serif">assembled</em> — not guessed.</>}>
              One research run builds a company profile from the official registers and the company's own verified website. Financials stay in the currency they were filed in. Whatever cannot be established
              stays visibly empty.
            </Copy>
          </div>
          <div className="act-visual dossier" aria-hidden>
            {[
              [Building2, 'Identity', 'Enhetsregisteret', 'Legal name, form, status, industry, registered address'],
              [Banknote, 'Financials', 'Regnskapsregisteret', 'Filed annual accounts, by reporting period, in their own currency'],
              [Users, 'People', 'Roles register', 'General manager, chair and board as registered'],
              [MapPin, 'Locations', 'Registered establishments', 'Headquarters and sub-units, mapped where verified'],
              [BriefcaseBusiness, 'Website & hiring', 'Identity-verified website', 'Company description, careers pages and current openings'],
              [Activity, 'Activity & changes', 'Saved research', 'Filings, events and what changed since the last run'],
            ].map(([Icon, title, source, text], i) => {
              const I = Icon as typeof Building2;
              return (
                <div key={title as string} className="dossier-layer" style={{ '--i': i } as CSSProperties}>
                  <span className="dossier-icon">
                    <I />
                  </span>
                  <span className="dossier-text">
                    <strong>{title as string}</strong>
                    <span className="t-xs t-muted">{text as string}</span>
                  </span>
                  <span className="dossier-src t-mono">{source as string}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ---------------- 04: Verify ---------------- */}
      <section id="act-verify" className="act act--verify" data-act aria-labelledby="h-verify">
        <div className="pin">
          <div className="act-visual rings" aria-hidden>
            <svg className="rings-svg" viewBox="0 0 400 400">
              <circle className="ring ring--outer" cx="200" cy="200" r="182" />
              <circle className="ring ring--mid" cx="200" cy="200" r="128" />
              <circle className="ring ring--inner" cx="200" cy="200" r="74" />
              <circle className="ring-node" cx="200" cy="200" r="9" />
              <path className="ring-ray" d="M212 192 L 318 122" />
              <circle className="ring-tip" cx="326" cy="117" r="6" />
            </svg>
            <ul className="labels">
              {[
                [ShieldCheck, 'ok', 'Verified by 2 primary sources'],
                [Shield, 'ok', 'Verified by 1 primary source'],
                [Quote, 'info', 'Secondary-source evidence'],
                [CircleAlert, 'warn', 'Potential conflict'],
                [CircleDashed, 'muted', 'Not available'],
              ].map(([Icon, tone, text], i) => {
                const I = Icon as typeof Shield;
                return (
                  <li key={text as string} className={`label label--${tone}`} style={{ '--i': i } as CSSProperties}>
                    <I /> {text as string}
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="act-copy">
            <Copy id="h-verify" num="04" kicker="Verify" title={<>Every fact shows <em className="t-serif">its evidence.</em></>}>
              Each published value links to its source, reporting period, retrieval date and — where available — the exact excerpt. Facts are labelled by the quality of their evidence, never by a confidence
              percentage. When sources disagree, both values stay visible with the reason.
            </Copy>
          </div>
        </div>
      </section>

      {/* ---------------- 05: Evidence architecture ---------------- */}
      <section id="act-evidence" className="act act--evidence" data-act aria-labelledby="h-evidence">
        <div className="pin">
          <div className="act-copy">
            <Copy id="h-evidence" num="05" kicker="Evidence" title={<>Sources have <em className="t-serif">rank.</em></>}>
              Official registers outrank everything. A company website counts only after its identity is checked against the register. Licensed sources are used only with a licence. Web search can suggest
              where to look — but nothing it returns is ever published as a fact.
            </Copy>
          </div>
          <div className="act-visual tiers" aria-hidden>
            {[
              [Landmark, 'Official registers', 'Primary', 'Enhetsregisteret · Regnskapsregisteret · roles · establishments · group structure'],
              [ShieldCheck, 'Company-owned, identity-verified', 'Primary when verified', 'The company website, careers pages and linked job boards'],
              [Lock, 'Licensed secondary', 'Secondary', 'Used only when a licence key is configured'],
              [Telescope, 'Discovery only', 'Never evidence', 'Web search finds candidates; their snippets are never published'],
            ].map(([Icon, title, rank, text], i) => {
              const I = Icon as typeof Landmark;
              return (
                <div key={title as string} className={cn('tier', i === 3 && 'tier--discovery')} style={{ '--i': i } as CSSProperties}>
                  <span className="tier-icon">
                    <I />
                  </span>
                  <span className="tier-text">
                    <strong>{title as string}</strong>
                    <span className="t-xs t-muted">{text as string}</span>
                  </span>
                  <span className="tier-rank t-mono">{rank as string}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ---------------- 06: Research workflow ---------------- */}
      <section id="act-workflow" className="act act--workflow" data-act aria-labelledby="h-workflow">
        <div className="pin">
          <div className="act-copy">
            <Copy id="h-workflow" num="06" kicker="Research" title={<>A research run <em className="t-serif">you can audit.</em></>}>
              The language model plans and reads. Deterministic rules decide what is published: a fact needs a source, a retrieval time, an exact excerpt and an extraction method — or it is not shown.
            </Copy>
          </div>
          <ol className="act-visual flow" aria-label="Research steps">
            {[
              [Fingerprint, 'Resolve identity', 'Match the exact company by organization number'],
              [Route, 'Plan', 'A bounded plan across the permitted sources'],
              [ScanSearch, 'Retrieve', 'Official registers and the verified website; robots.txt and access blocks respected'],
              [Quote, 'Extract', 'Structured register fields; website text only when its quote is found verbatim'],
              [FileCheck2, 'Publication gate', 'Source, time, excerpt and method — or the fact is withheld'],
              [Compass, 'Synthesize', 'A summary whose every number must appear in the verified facts'],
              [Library, 'Save & monitor', 'A living artifact in your Library; changes detected on the next run'],
            ].map(([Icon, title, text], i) => {
              const I = Icon as typeof Route;
              return (
                <li key={title as string} className="flow-step" style={{ '--i': i } as CSSProperties}>
                  <span className="flow-dot">
                    <I />
                  </span>
                  <span className="flow-text">
                    <strong>{title as string}</strong>
                    <span className="t-xs t-muted">{text as string}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {/* ---------------- 07: Positioning ---------------- */}
      <section id="act-precision" className="act act--precision" data-act aria-labelledby="h-precision">
        <div className="final">
          <Motif size={64} className="final-motif" />
          <span className="eyebrow">07 · Precision</span>
          <h2 id="h-precision" className="final-title">
            Precision over recall. <em className="t-serif">Evidence over guesswork.</em>
          </h2>
          <p className="final-lead">
            When something cannot be verified, COGNIS says so — <span className="t-nowrap">“Not available”</span>, <span className="t-nowrap">“Source blocked”</span> or <span className="t-nowrap">“Ambiguous”</span> — instead of
            filling the gap.
          </p>
          <div className="final-actions">
            <Link to="/research" className="btn btn--primary btn--lg">
              Start research <ArrowRight aria-hidden />
            </Link>
            <Link to="/discover" className="btn btn--lg">
              Discover companies
            </Link>
          </div>
          <div className="final-notes">
            <section>
              <h3>Freshness</h3>
              <p>
                Each fact carries its own verification date. Saved research stays as it was until you update it; when the backend detects newer filings or changed sources, the artifact shows “Fresh research
                available”. Older versions remain viewable and comparable.
              </p>
            </section>
            <section>
              <h3>Data limitations</h3>
              <p>
                Some sources block automated access, some companies publish little, and registries can lag. Absence of evidence in the searched sources is not proof of absence. Financial amounts are shown in the
                currency they were filed in and are never converted.
              </p>
            </section>
            <section>
              <h3>What COGNIS will not do</h3>
              <p>
                <Ban className="inline-icon" aria-hidden /> No scores, rankings or confidence percentages. No collection from private profiles or sites that block automated access. No facts from search snippets.
              </p>
            </section>
          </div>
          {API_MODE === 'mock' && <p className="notice notice--info">This build runs on the mock backend. All companies, people and figures are fictional demo data.</p>}
          <p className="t-xs t-muted final-meta">
            Version 0.1.0 · Builderr Signalpost Hackathon ·{' '}
            <Link to="/settings" className="link-btn" style={{ fontSize: 12 }}>
              System status
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}

function Copy({ id, num, kicker, title, children, className, lead }: { id?: string; num: string; kicker: string; title: ReactNode; children: ReactNode; className?: string; lead?: boolean }) {
  return (
    <div className={cn('copy', className)}>
      <span className="copy-kicker">
        <span className="t-mono">{num}</span>
        <span className="copy-rule" />
        {kicker}
      </span>
      {lead ? (
        <h1 id={id} className="copy-title copy-title--lead">
          {title}
        </h1>
      ) : (
        <h2 id={id} className="copy-title">
          {title}
        </h2>
      )}
      <div className="copy-body">{children}</div>
    </div>
  );
}

function Points({ items }: { items: [typeof Search, string][] }) {
  return (
    <ul className="copy-points">
      {items.map(([I, text]) => (
        <li key={text}>
          <I aria-hidden /> {text}
        </li>
      ))}
    </ul>
  );
}

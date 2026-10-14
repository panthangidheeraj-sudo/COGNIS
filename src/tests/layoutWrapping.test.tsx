/**
 * Research layout and long text.
 *
 * jsdom does no layout, so the guarantees are pinned two ways: the stylesheet rules that keep panels apart and let text wrap (any change that
 * brings back a bare `1fr` track or a no-wrap fact fails here), and the components that decide when a value wraps and which parts stay visible.
 * The real geometry was also measured in a browser at 1440, 1280, 1100, 900 and 700 px (no overlap, no sideways scroll).
 */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from './utils';
// @ts-expect-error -- this project has no @types/node; vitest runs in Node, so the module exists at runtime (the Vitest CSS pipeline would hand back empty text for ?raw imports)
import { readFileSync } from 'node:fs';
import { FactValue, LONG_FACT_CHARS, isLongFactText } from '@/components/evidence/FactValue';
import { StepRow } from '@/components/research/ResearchPlan';
import type { Fact, ResearchStep } from '@/types';

/* ------------------------------------------------------------------ css helpers -- */
const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8') as string;
const researchCss = read('../pages/Research/research.css');
const appCss = read('../styles/app.css');
const componentsCss = read('../styles/components.css');
const sectionsCss = read('../styles/sections.css');
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\>]/g, '\\$&');

/** Declarations of the first rule whose selector list contains `selector`, searching from `from`. */
function rule(css: string, selector: string, from = 0): Record<string, string> {
  const text = strip(css).slice(from);
  const re = new RegExp(`(?:^|[}\\s,])${esc(selector)}\\s*(?:,[^{}]*)?\\{([^}]*)\\}`);
  const m = re.exec(text);
  if (!m) throw new Error(`rule not found: ${selector}`);
  const out: Record<string, string> = {};
  for (const d of m[1].split(';')) {
    const i = d.indexOf(':');
    if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim().replace(/\s+/g, ' ');
  }
  return out;
}
const mediaStart = (css: string, query: string) => strip(css).indexOf(`@media (${query})`);

/** Every `grid-template-columns` declaration in a stylesheet, with the selector it belongs to. */
function gridColumns(css: string): { selector: string; value: string }[] {
  const out: { selector: string; value: string }[] = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  const text = strip(css);
  while ((m = re.exec(text))) {
    const d = /grid-template-columns:\s*([^;]+);/.exec(m[2]);
    if (d) out.push({ selector: m[1].trim().split('\n').pop()!.trim(), value: d[1].trim().replace(/\s+/g, ' ') });
  }
  return out;
}

/* --------------------------------------------------------------- panel overlap -- */
describe('Research columns stay separate', () => {
  it('the three columns are bounded tracks and the middle one can shrink', () => {
    const grid = rule(researchCss, '.rs-grid');
    expect(grid['grid-template-columns']).toBe('minmax(240px, 280px) minmax(0, 1fr) minmax(280px, 340px)');
    expect(grid.gap).toBeDefined();
  });

  it('grid children and columns may be narrower than their content', () => {
    expect(rule(researchCss, '.rs-grid > *')['min-width']).toBe('0');
    const col = rule(researchCss, '.rs-col');
    expect(col['min-width']).toBe('0');
    // an implicit `auto` track grows to the widest unbreakable word and pushes the panel over its neighbour
    expect(col['grid-template-columns']).toBe('minmax(0, 1fr)');
  });

  it('a panel wraps long words inside itself', () => {
    const panel = rule(researchCss, '.rs-panel');
    expect(panel['min-width']).toBe('0');
    expect(panel['max-width']).toBe('100%');
    expect(panel['overflow-wrap']).toBe('anywhere');
  });

  it('the narrower desktop layout keeps a bounded plan column next to a shrinkable synthesis column', () => {
    const at = mediaStart(researchCss, 'max-width: 1240px');
    expect(at).toBeGreaterThan(0);
    expect(rule(researchCss, '.rs-grid', at)['grid-template-columns']).toBe('minmax(220px, 260px) minmax(0, 1fr)');
  });

  it('no Research or key-value grid uses a bare 1fr track (it can never shrink below its content)', () => {
    for (const css of [researchCss, componentsCss, sectionsCss]) {
      for (const { selector, value } of gridColumns(css)) {
        if (!/^\.(rs-|kv\b|about-kv|sact|step)/.test(selector.replace(/^[^.]*/, ''))) continue;
        const tokens = value.replace(/minmax\([^)]*\)/g, '').replace(/repeat\([^)]*\)/g, '').split(' ');
        expect(tokens.filter((t) => t === '1fr'), `${selector}: ${value}`).toEqual([]);
      }
    }
  });

  it('fact rows and key-value rows give the value column minmax(0, 1fr)', () => {
    expect(rule(researchCss, '.rs-facts li')['grid-template-columns']).toBe('150px minmax(0, 1fr)');
    expect(rule(componentsCss, '.kv')['grid-template-columns']).toBe('minmax(110px, 38%) minmax(0, 1fr)');
    expect(rule(sectionsCss, '.about-kv')['grid-template-columns']).toBe('170px minmax(0, 1fr)');
  });
});

/* --------------------------------------------------------------- text wrapping -- */
describe('Long text wraps inside its container', () => {
  it('a long fact value wraps, and the citation count never shrinks away', () => {
    expect(rule(appCss, '.fact')['max-width']).toBe('100%');
    expect(rule(appCss, '.fact-btn')['max-width']).toBe('100%');
    const wrap = rule(appCss, '.fact--wrap .fact-btn');
    expect(wrap['white-space']).toBe('normal');
    expect(wrap['overflow-wrap']).toBe('anywhere');
    expect(rule(appCss, '.fact-count')['flex']).toBe('none');
  });

  it('descriptions and key-value cells wrap long words', () => {
    expect(rule(sectionsCss, '.about-text')['overflow-wrap']).toBe('anywhere');
    expect(rule(componentsCss, '.kv dd')['overflow-wrap']).toBe('anywhere');
  });

  it('a source name in the plan wraps instead of being cut off', () => {
    expect(rule(researchCss, '.step-source')['overflow-wrap']).toBe('anywhere');
    expect(rule(researchCss, '.step-label')['overflow-wrap']).toBe('anywhere');
  });
});

const LONG =
  'Akers Energy Holdings is an independent exploration and production company with operatorship of several fields https://www.example.com/a/very/long/unbroken/url/path/that/never/ends/abcdefghijklmnopqrstuvwxyz0123456789';
const source = { id: 's1', name: 'Regnskapsregisteret', kind: 'financial' as const, tier: 'primary' as const, official: true };
const fact = (value: string, over: Partial<Fact> = {}): Fact => ({
  id: 'f1',
  field: 'overview.description',
  label: 'Description',
  status: 'verified',
  value,
  evidenceState: 'verified',
  evidence: [
    { id: 'e1', sourceId: 's1', retrievedAt: '2026-10-03T10:00:00Z', excerpt: value },
    { id: 'e2', sourceId: 's2', retrievedAt: '2026-10-03T10:00:00Z', excerpt: value },
  ],
  ...over,
});

describe('FactValue with long values', () => {
  it('marks only long values for wrapping; short numbers and names keep their one-line form', () => {
    expect(isLongFactText('x'.repeat(LONG_FACT_CHARS))).toBe(false);
    expect(isLongFactText('x'.repeat(LONG_FACT_CHARS + 1))).toBe(true);
    const { container } = renderWithProviders(
      <>
        <FactValue fact={fact('Ingrid Solberg')} sourceIndex={{ s1: source }} />
        <FactValue fact={fact(LONG)} sourceIndex={{ s1: source }} />
      </>,
    );
    const [short, long] = Array.from(container.querySelectorAll('.fact'));
    expect(short).not.toHaveClass('fact--wrap');
    expect(long).toHaveClass('fact--wrap');
  });

  it('shows the whole value — nothing is cut off — and keeps the citation count and evidence button', () => {
    renderWithProviders(<FactValue fact={fact(LONG)} sourceIndex={{ s1: source }} />);
    const btn = screen.getByRole('button', { name: new RegExp(LONG.slice(0, 20)) });
    expect(btn).toHaveTextContent(LONG);
    expect(within(btn).getByLabelText('2 sources')).toBeInTheDocument(); // the citation marker stays inside the clickable control
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog');
  });

  it('prose values (descriptions) keep wrapping through their own class', () => {
    const { container } = renderWithProviders(<FactValue fact={fact('Short text')} sourceIndex={{}} className="fact--prose" />);
    expect(container.querySelector('.fact')).toHaveClass('fact--prose');
  });
});

describe('Research plan rows with long source names', () => {
  it('renders the full label and source name', () => {
    const step: ResearchStep = {
      id: 's-registry',
      key: 'registry',
      label: 'Verify_identity_against_the_official_register_without_any_spaces_in_this_label',
      sourceKind: 'registry',
      optional: false,
      status: 'done',
      sourceName: 'Brønnøysundregistrene_Enhetsregisteret_https://data.brreg.no/enhetsregisteret/api/enheter',
      factCount: 7,
      evidenceCount: 7,
      durationMs: 900,
    };
    const { container } = renderWithProviders(
      <ol>
        <StepRow step={step} />
      </ol>,
    );
    expect(screen.getByText(step.label)).toBeInTheDocument();
    const name = screen.getByText(step.sourceName!);
    expect(name).toHaveClass('step-source');
    expect(name).not.toHaveClass('truncate'); // truncation would hide part of a source name
    expect(container.querySelector('.truncate')).toBeNull();
  });
});

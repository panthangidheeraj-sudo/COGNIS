/**
 * MOCK BACKEND — recorded research event scripts.
 * In mock mode these play back like a live SSE stream so the UI can be built
 * against the exact event contract. The UI never invents progress itself.
 */
import type { ResearchEvent, ResearchMode, ResearchPlan, ResearchRunSummary, ResearchStep, StartResearchInput } from '@/types';
import { answerFromProfile } from './answers';
import { fullProfile, specsByOrg } from './store';

const STEP_DEFS: Record<string, { label: string; sourceKind: ResearchStep['sourceKind']; optional: boolean }> = {
  identity: { label: 'Verify identity', sourceKind: 'registry', optional: false },
  filing: { label: 'Latest annual filing', sourceKind: 'financial', optional: false },
  leadership: { label: 'Leadership', sourceKind: 'people', optional: false },
  locations: { label: 'Locations', sourceKind: 'registry', optional: true },
  website: { label: 'Company website', sourceKind: 'website', optional: true },
  hiring: { label: 'Hiring', sourceKind: 'jobs', optional: true },
  activity: { label: 'Recent public activity', sourceKind: 'activity', optional: true },
  secondary: { label: 'Secondary sources', sourceKind: 'people', optional: true },
  news: { label: 'Web & news discovery', sourceKind: 'web', optional: true },
};

export function planFor(mode: ResearchMode, stepKeys?: string[]): ResearchPlan {
  const keys = stepKeys ?? (mode === 'deep' ? ['identity', 'filing', 'leadership', 'locations', 'website', 'hiring', 'activity', 'secondary', 'news'] : ['identity', 'filing', 'leadership', 'locations', 'website', 'hiring', 'activity']);
  return {
    requiresConfirmation: mode === 'deep' && !stepKeys,
    steps: keys.map((k) => ({ id: `s-${k}`, key: k, ...STEP_DEFS[k], status: 'pending' as const })),
    availableSteps: Object.entries(STEP_DEFS)
      .filter(([k]) => !keys.includes(k))
      .map(([key, d]) => ({ key, label: d.label, sourceKind: d.sourceKind })),
  };
}

export function buildScript(runId: string, org: string, plan: ResearchPlan, input: StartResearchInput, startSeq = 0, onlySteps?: string[]) {
  const spec = specsByOrg.get(org)!;
  const p = fullProfile(org);
  let seq = startSeq;
  let t = Date.now();
  const t0 = t;
  const out: { delay: number; event: ResearchEvent }[] = [];
  const at = () => new Date(t).toISOString().replace('.000', '');
  const push = (delay: number, e: Record<string, unknown>) => {
    t += delay;
    out.push({ delay, event: { ...e, seq: ++seq, runId, at: at() } as ResearchEvent });
  };
  const factOf = (field: string) => [p.identity.legalName, p.identity.status, p.identity.registeredAddress, ...p.keyMetrics].find((f) => f?.field === field);

  if (!onlySteps) {
    push(150, { type: 'run.started' });
    push(250, { type: 'stage.changed', stage: 'discover' });
    push(350, { type: 'stage.changed', stage: 'identify' });
  } else {
    push(150, { type: 'stage.changed', stage: 'gather' });
  }
  const steps = plan.steps.filter((s) => !onlySteps || onlySteps.includes(s.key));
  let gatherAnnounced = !!onlySteps;
  for (const step of steps) {
    if (step.key !== 'identity' && !gatherAnnounced) {
      push(200, { type: 'stage.changed', stage: 'gather' });
      gatherAnnounced = true;
    }
    const d = 550 + ((step.key.length * 137) % 700);
    switch (step.key) {
      case 'identity': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Brønnøysundregistrene' });
        push(d, { type: 'step.completed', stepId: step.id, sourceName: 'Brønnøysundregistrene', factCount: 7, evidenceCount: 7, durationMs: d, outcome: 'verified' });
        for (const f of ['identity.legalName', 'identity.registeredAddress']) {
          const fact = factOf(f);
          if (fact) push(80, { type: 'fact.confirmed', fact });
        }
        break;
      }
      case 'filing': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Regnskapsregisteret' });
        const pts = p.financials.series.reduce((n, s) => n + s.points.length, 0);
        push(d, {
          type: 'step.completed',
          stepId: step.id,
          sourceName: 'Regnskapsregisteret',
          factCount: pts,
          evidenceCount: pts,
          durationMs: d,
          outcome: pts ? 'verified' : 'not_available',
          message: pts ? undefined : 'No filed annual accounts found',
        });
        const rev = p.financials.series.find((s) => s.key === 'revenue')?.points.at(-1);
        if (rev) push(80, { type: 'fact.confirmed', fact: rev.fact });
        break;
      }
      case 'leadership': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Brønnøysundregistrene — roles' });
        push(d, { type: 'step.completed', stepId: step.id, sourceName: 'Brønnøysundregistrene — roles', factCount: p.people.people.length, evidenceCount: p.people.people.length, durationMs: d, outcome: p.people.people.length ? 'verified' : 'not_available' });
        const ceo = p.people.people.find((x) => x.role === 'CEO' && x.current);
        if (ceo) push(80, { type: 'fact.confirmed', fact: ceo.fact });
        break;
      }
      case 'locations': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Brønnøysundregistrene — sub-units' });
        const n = p.locations.locations.length;
        push(d, { type: 'step.completed', stepId: step.id, sourceName: 'Brønnøysundregistrene — sub-units', factCount: n, evidenceCount: n, durationMs: d, outcome: 'verified' });
        const loc = factOf('overview.locations');
        if (loc) push(80, { type: 'fact.confirmed', fact: loc });
        break;
      }
      case 'website': {
        if (!spec.domain) {
          push(120, { type: 'step.started', stepId: step.id, sourceName: 'Web search' });
          push(d, { type: 'step.completed', stepId: step.id, sourceName: 'Web search', factCount: 0, evidenceCount: 0, durationMs: d, outcome: 'not_available', message: 'No official website verified' });
        } else if (spec.websiteBlocked) {
          push(120, { type: 'step.started', stepId: step.id, sourceName: `Official website (${spec.domain})` });
          push(d, { type: 'step.blocked', stepId: step.id, sourceName: `Official website (${spec.domain})`, message: 'Source access blocked — the website refused automated access.' });
        } else {
          push(120, { type: 'step.started', stepId: step.id, sourceName: `Official website (${spec.domain})` });
          push(d, { type: 'step.completed', stepId: step.id, sourceName: `Official website (${spec.domain})`, factCount: 9, evidenceCount: 11, durationMs: d, outcome: 'verified' });
        }
        break;
      }
      case 'hiring': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'arbeidsplassen.nav.no' });
        const n = p.hiring.totalCurrent;
        push(d + 200, {
          type: 'step.completed',
          stepId: step.id,
          sourceName: 'arbeidsplassen.nav.no',
          factCount: n ?? 0,
          evidenceCount: p.hiring.jobs.length,
          durationMs: d + 200,
          outcome: n ? 'verified' : 'not_available',
          message: n ? undefined : 'No current verified openings found in searched sources',
        });
        const f = factOf('overview.openPositions');
        if (f && f.value != null) push(80, { type: 'fact.confirmed', fact: f });
        break;
      }
      case 'activity': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Kunngjøringer · Doffin' });
        if (spec.activityFailed && !onlySteps) {
          push(d + 900, { type: 'step.failed', stepId: step.id, sourceName: 'Doffin', message: 'Doffin did not respond (timeout). Registry announcements were checked.', retryable: true });
        } else {
          push(d, {
            type: 'step.completed',
            stepId: step.id,
            sourceName: 'Kunngjøringer · Doffin',
            factCount: p.activity.events.length,
            evidenceCount: p.activity.events.length,
            durationMs: d,
            outcome: p.activity.events.length ? 'verified' : 'not_available',
            message: p.activity.events.length ? undefined : 'No verified major public activity found',
          });
        }
        break;
      }
      case 'secondary': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'LinkedIn · Proff.no' });
        if (spec.linkedinBlocked) push(d, { type: 'step.blocked', stepId: step.id, sourceName: 'LinkedIn', message: 'Source access blocked — LinkedIn refused automated access. Proff.no checked.' });
        else push(d, { type: 'step.completed', stepId: step.id, sourceName: 'LinkedIn · Proff.no', factCount: 3, evidenceCount: 4, durationMs: d, outcome: 'verified' });
        break;
      }
      case 'news': {
        push(120, { type: 'step.started', stepId: step.id, sourceName: 'Web search' });
        push(d, { type: 'step.completed', stepId: step.id, sourceName: 'Web search', factCount: 2, evidenceCount: 3, durationMs: d, outcome: 'verified' });
        break;
      }
    }
  }
  push(300, { type: 'stage.changed', stage: 'verify' });
  push(400, { type: 'stage.changed', stage: 'reconcile' });
  push(350, { type: 'stage.changed', stage: 'synthesize' });
  const answer = answerFromProfile(p, input.prompt ?? 'Company brief', 'fresh_research');
  const text = answer.blocks.map((b) => b.text).join(' ');
  const words = text.split(' ');
  for (let i = 0; i < words.length; i += 6) push(70, { type: 'synthesis.delta', text: words.slice(i, i + 6).join(' ') + (i + 6 < words.length ? ' ' : '') });
  push(150, { type: 'synthesis.completed', answer });
  push(250, { type: 'stage.changed', stage: 'save' });
  const evs = out.map((x) => x.event);
  const completed = evs.filter((e): e is Extract<ResearchEvent, { type: 'step.completed' }> => e.type === 'step.completed');
  const summary: ResearchRunSummary = {
    coverage: p.company.coverage,
    sourcesVerified: p.sources.length,
    primarySources: p.quality.primarySources,
    secondarySources: p.quality.secondarySources,
    factsVerified: completed.reduce((n, e) => n + e.factCount, 0),
    conflicts: p.quality.conflicts,
    identityConflicts: 0,
    changesDetected: p.changes.changes.filter((c) => c.material).length,
    blockedSources: evs.filter((e) => e.type === 'step.blocked').length,
    failedSources: evs.filter((e) => e.type === 'step.failed').length,
    elapsedMs: t - t0 + 300,
  };
  push(300, { type: 'run.completed', artifactId: `art-${org}`, autoSaved: true, coverage: p.company.coverage, summary });
  return out;
}

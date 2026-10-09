import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './client';
import { highlightsApi, type EventEdit } from './highlights';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => new Response(JSON.stringify({ state: { revision: 8 } }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); });

function sent() {
  const [url, init] = fetchMock.mock.calls[0];
  return { url, method: init.method, body: init.body && JSON.parse(init.body), signal: init.signal };
}

describe('highlight API contracts', () => {
  it('encodes song IDs and forwards cancellation for reads', async () => {
    const signal = new AbortController().signal;
    await highlightsApi.get('song/name', signal);
    expect(sent()).toEqual({ url: '/api/v1/songs/song%2Fname/highlights', method: 'GET', body: undefined, signal });
  });

  it('sends source identity, revision and unsnapped review timing unchanged', async () => {
    const edit: EventEdit = {
      expected_revision: 7, source_sha256: 'a'.repeat(64), duration_ms: 16000,
      events: [{
        event: { event_id: 'wash', source_sha256: 'a'.repeat(64), source_revision: 'manual-v1',
          kind: 'sweep', timing: { start_ms: 8287, peak_ms: 9713, end_ms: 10117 },
          provenance: 'manual', detection_score: null, intensity: null, salience: null, evidence: [] },
        status: 'accepted', timing_override: null, importance: 2, locked: false, note: 'shhh',
      }],
    };
    const original = structuredClone(edit);
    const result = await highlightsApi.saveEvents('song', edit);
    expect(sent()).toMatchObject({ method: 'PUT', body: original });
    expect(edit).toEqual(original);
    expect(result.state.revision).toBe(8);
  });

  it('prepares a draft with supported recipe inputs and explicit seed', async () => {
    const draft = { expected_revision: 7, variation_seed: 42, treatments: [
      { treatment_id: 't1', event_id: 'wash', recipe_id: 'sustained_wash' as const, targets: ['MatrixCenter'] },
    ] };
    await highlightsApi.prepareDraft('song', draft);
    expect(sent()).toMatchObject({ url: '/api/v1/songs/song/highlights/draft', method: 'POST', body: draft });
  });

  it.each(['acceptDraft', 'rejectDraft'] as const)('includes revision and draft ID for %s', async method => {
    await highlightsApi[method]('song', 7, 'plan-1');
    expect(sent()).toMatchObject({
      url: `/api/v1/songs/song/highlights/${method === 'acceptDraft' ? 'accept' : 'reject'}`,
      method: 'POST', body: { expected_revision: 7, plan_id: 'plan-1' },
    });
  });

  it.each([true, false])('uses the correct enable action for %s', async enabled => {
    await highlightsApi.setEnabled('song', 7, enabled);
    expect(sent()).toMatchObject({ url: `/api/v1/songs/song/highlights/${enabled ? 'enable' : 'disable'}`,
      method: 'POST', body: { expected_revision: 7 } });
  });

  it('uses revision-checked undo', async () => {
    await highlightsApi.undo('song', 7);
    expect(sent()).toMatchObject({ url: '/api/v1/songs/song/highlights/undo', method: 'POST', body: { expected_revision: 7 } });
  });

  it('keeps omitted preview choice distinct from explicit baseline', async () => {
    await highlightsApi.preview('song');
    expect(sent().body).toEqual({});
    fetchMock.mockClear();
    await highlightsApi.preview('song', { highlights: false, variation_seed: 42, section_index: 0 });
    expect(sent()).toMatchObject({ url: '/api/v1/songs/song/preview', method: 'POST',
      body: { highlights: false, variation_seed: 42, section_index: 0 } });
  });

  it.each(['revision_conflict', 'stale_plan'])('preserves actionable %s errors', async code => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ error: { code, message: 'Reload current inputs' } }), { status: 409 }));
    const error = await highlightsApi.acceptDraft('song', 7, 'plan-1').catch(e => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code, status: 409, message: 'Reload current inputs' });
  });
});

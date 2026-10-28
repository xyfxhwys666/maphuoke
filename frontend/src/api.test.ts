import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createTask,
  cancelCollectionTask,
  deliverCollectionLead,
  deliverCollectionResults,
  listCollectionTasks,
  openAmapBrowser,
} from './api';

describe('task request contract', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends selected contact fields and the auto-delivery choice', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({}),
    } as unknown as Response;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
    const input = {
      company_name: '深圳示例科技有限公司',
      city: '深圳市',
      required_contacts: ['email'],
      auto_deliver: true,
    };

    await createTask(input);

    const request = fetchMock.mock.calls[0][1];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      required_contacts: ['email'],
      auto_deliver: true,
    });
  });

  it('loads the persisted collection queue and opens the dedicated map browser', async () => {
    const responses = [
      { items: [] },
      { url: 'https://www.amap.com/', state: 'ready' },
    ];
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValueOnce(responses[0]).mockResolvedValueOnce(responses[1]),
    } as unknown as Response;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await expect(listCollectionTasks()).resolves.toEqual({ items: [] });
    await expect(openAmapBrowser()).resolves.toEqual(responses[1]);
  });

  it('sends the target URL for batch and per-record collection delivery', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({ sent: 1, failed: 0, items: [] }),
    } as unknown as Response;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await deliverCollectionResults('collection-1', 'https://erp.example.test/leads', 'token');
    await deliverCollectionLead('collection-1', 'lead-1', 'https://erp.example.test/leads', 'token');

    expect(fetchMock.mock.calls[0][0]).toContain('/collection-tasks/collection-1/deliver');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      target_url: 'https://erp.example.test/leads', bearer_token: 'token',
    });
    expect(fetchMock.mock.calls[1][0]).toContain('/collection-tasks/collection-1/leads/lead-1/deliver');
  });

  it('posts a cancellation request for a collection task', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'cancelled' }),
    } as unknown as Response;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    await cancelCollectionTask('collection-1');

    expect(fetchMock.mock.calls[0][0]).toContain('/collection-tasks/collection-1/cancel');
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
  });
});

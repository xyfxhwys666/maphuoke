import { describe, expect, test } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as collectionWorkbench from './CollectionWorkbench';
import CollectionWorkbench, {
  attentionMessage,
  COLLECTION_RESULT_COLUMNS,
  collectionDeliveryAction,
  companyNameSourceLabel,
  collectionTargetLabel,
  collectionQueueActions,
  dailyDeliveryCount,
  DEFAULT_COLLECTION_REQUEST,
  initialDeliveryUrl,
  MOBILE_DELIVERY_NOTE,
  shouldStartCollectionAfterPlan,
  validMobile,
} from './CollectionWorkbench';
import { NATURAL_LANGUAGE_HERO_COPY } from './App';
import { DEFAULT_ERP_DELIVERY_URL } from './config';
import { collectionProgressPercent, collectionStatusLabel } from './labels';
import type { LeadRecord } from './types';

describe('collection workbench labels', () => {
  test('shows attention state as a manual browser action', () => {
    expect(collectionStatusLabel('needs_attention').text).toContain('需要处理');
  });

  test('calculates progress from terminal work units', () => {
    expect(collectionProgressPercent({ total: 4, completed: 1, failed: 1 })).toBe(50);
  });

  test('starts from a customer brief instead of a keyword list', () => {
    expect(DEFAULT_COLLECTION_REQUEST).toContain('我是做家具的');
    expect(DEFAULT_COLLECTION_REQUEST).toContain('需要手机号码');
    expect(DEFAULT_COLLECTION_REQUEST).not.toContain('软装设计、住宅软装');
  });

  test('only directs collection attention to the dedicated Amap browser', () => {
    expect(attentionMessage(['Amap login is required'])).toContain('高德');
    expect(attentionMessage(['Doubao login is required'])).not.toContain('豆包');
  });

  test('describes the public-company-name then Amap-exact workflow', () => {
    expect(NATURAL_LANGUAGE_HERO_COPY).toContain('公开网页');
    expect(NATURAL_LANGUAGE_HERO_COPY).toContain('高德');
    expect(NATURAL_LANGUAGE_HERO_COPY).not.toContain('模型判断');
    expect(NATURAL_LANGUAGE_HERO_COPY).not.toContain('豆包');
  });

  test('merges every lead returned by a batch delivery', () => {
    const mergeDeliveredLeads = (
      collectionWorkbench as unknown as {
        mergeDeliveredLeads?: (current: LeadRecord[], delivered: LeadRecord[]) => LeadRecord[];
      }
    ).mergeDeliveredLeads;
    expect(mergeDeliveredLeads).toBeTypeOf('function');
    if (!mergeDeliveredLeads) return;
    const current = [
      { id: 'lead-1', delivery_status: 'display_only' },
      { id: 'lead-2', delivery_status: 'display_only' },
    ] as LeadRecord[];
    const delivered = [
      { ...current[0], delivery_status: 'delivered' },
      { ...current[1], delivery_status: 'failed' },
    ] as LeadRecord[];

    expect(mergeDeliveredLeads(current, delivered).map((lead) => lead.delivery_status)).toEqual([
      'delivered',
      'failed',
    ]);
  });

  test('renders collection results after the complete workbench grid', () => {
    const html = renderToStaticMarkup(createElement(CollectionWorkbench));
    const layoutStart = html.indexOf('class="collection-layout"');
    const layoutEnd = html.indexOf('</div><section class="collection-results');
    const resultsStart = html.indexOf('class="collection-results');

    expect(layoutStart).toBeGreaterThan(-1);
    expect(resultsStart).toBeGreaterThan(layoutStart);
    expect(layoutEnd).toBeGreaterThan(layoutStart);
    expect(html).not.toContain('城市执行计划');
  });

  test('labels mobile-valid target progress and source exhaustion', () => {
    expect(collectionTargetLabel(37, 100, false)).toBe('有效手机 37 / 100');
    expect(collectionTargetLabel(37, 100, true)).toBe('有效手机 37 / 100 · 数据源已耗尽');
  });

  test('keeps the task queue ordered by newest creation time after task updates', () => {
    const sort = (collectionWorkbench as unknown as {
      sortCollectionTasksByCreatedAt?: (tasks: Array<{ id: string; created_at: string }>) => Array<{ id: string }>;
    }).sortCollectionTasksByCreatedAt;

    expect(sort).toBeTypeOf('function');
    if (!sort) return;

    expect(sort([
      { id: 'older', created_at: '2026-08-11T08:00:00Z' },
      { id: 'newer', created_at: '2026-08-11T09:00:00Z' },
    ]).map((task) => task.id)).toEqual(['newer', 'older']);
  });

  test('prefers a running task over a newer cancelled task when opening the queue', () => {
    const preferred = (collectionWorkbench as unknown as {
      preferredCollectionTask?: (tasks: Array<{ id: string; status: string; created_at: string }>) => { id: string } | undefined;
    }).preferredCollectionTask;

    expect(preferred).toBeTypeOf('function');
    if (!preferred) return;

    expect(preferred([
      { id: 'cancelled-newer', status: 'cancelled', created_at: '2026-08-13T09:00:00Z' },
      { id: 'shenzhen-running', status: 'running', created_at: '2026-08-12T09:00:00Z' },
    ])?.id).toBe('shenzhen-running');
  });

  test('formats task creation time in China Standard Time', () => {
    const format = (collectionWorkbench as unknown as {
      formatQueueCreatedAt?: (value: string) => string;
    }).formatQueueCreatedAt;

    expect(format).toBeTypeOf('function');
    if (!format) return;

    expect(format('2026-08-11T08:40:00Z')).toBe('2026-08-11 16:40');
  });

  test('shows pause, resume, and cancel controls for actionable queue tasks', () => {
    const actions = (collectionWorkbench as unknown as {
      collectionQueueActions?: (status: string) => string[];
    }).collectionQueueActions;

    expect(actions).toBeTypeOf('function');
    if (!actions) return;

    expect(actions('running')).toEqual(['pause', 'cancel']);
    expect(actions('paused')).toEqual(['resume', 'cancel']);
    expect(actions('needs_attention')).toEqual(['resume', 'cancel']);
    expect(actions('queued')).toEqual(['pause', 'cancel']);
    expect(actions('planned')).toEqual(['start', 'cancel']);
    expect(actions('completed')).toEqual([]);
    expect(actions('cancelled')).toEqual([]);
  });

  test('starts a newly generated plan when continuous collection is selected', () => {
    expect(shouldStartCollectionAfterPlan(true)).toBe(true);
    expect(shouldStartCollectionAfterPlan(false)).toBe(false);
  });

  test('counts successful deliveries by China date across collection tasks', () => {
    expect(dailyDeliveryCount([
      {
        results: [
          { delivery_status: 'delivered', delivery_at: '2026-08-18T16:30:00Z' },
          { delivery_status: 'delivered', delivery_at: '2026-08-18T15:59:00Z' },
          { delivery_status: 'duplicate', delivery_at: '2026-08-18T16:45:00Z' },
          { delivery_status: 'delivered', delivery_at: null },
        ],
      },
    ] as never[] , '2026-08-19')).toBe(1);
  });

  test('renders mobile-only result and delivery wording', () => {
    const html = renderToStaticMarkup(createElement(CollectionWorkbench));

    expect(html).toContain('高德手机');
    expect(MOBILE_DELIVERY_NOTE).toContain('仅推送含高德有效手机号的最终记录');
    expect(html).not.toContain('高德电话');
  });

  test('labels the company-name candidate source accurately', () => {
    expect(companyNameSourceLabel('public_web')).toBe('高德');
    expect(companyNameSourceLabel('amap_keyword')).toBe('高德');
  });

  test('uses the compact seven-column Amap result table', () => {
    expect(COLLECTION_RESULT_COLUMNS).toEqual([
      '城市',
      '公司',
      '高德手机',
      '地址',
      '公司名来源',
      '高德地图',
      '推送',
    ]);
    expect(COLLECTION_RESULT_COLUMNS).not.toContain('分类 / 坐标');
    expect(COLLECTION_RESULT_COLUMNS).not.toContain('推送状态');
    expect(COLLECTION_RESULT_COLUMNS).not.toContain('操作');
  });

  test('combines ERP delivery status and action into one button state', () => {
    expect(collectionDeliveryAction('display_only', false)).toEqual({ label: '人工推送', disabled: false });
    expect(collectionDeliveryAction('failed', false)).toEqual({ label: '重新推送', disabled: false });
    expect(collectionDeliveryAction('sending', false)).toEqual({ label: '推送中', disabled: true });
    expect(collectionDeliveryAction('delivered', false)).toEqual({ label: '已推送', disabled: true });
    expect(collectionDeliveryAction('duplicate', false)).toEqual({ label: '已推送', disabled: true });
    expect(collectionDeliveryAction('display_only', true)).toEqual({ label: '推送中', disabled: true });
  });

  test('prefills the documented ERP receiver URL', () => {
    expect(DEFAULT_ERP_DELIVERY_URL).toBe(
      'https://qingflow.com/api/qsource/eab3897c-4748-47b5-9121-96683b36cf0c',
    );
    expect(initialDeliveryUrl()).toBe(DEFAULT_ERP_DELIVERY_URL);
  });
});

describe('mobile delivery validation', () => {
  test('accepts only canonical mainland mobile numbers', () => {
    expect(validMobile('13800138000')).toBe('13800138000');
    expect(validMobile('0755-82793362')).toBeNull();
    expect(validMobile('138****8000')).toBeNull();
    expect(validMobile('4008001234')).toBeNull();
  });
});

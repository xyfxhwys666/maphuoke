import { describe, expect, it } from 'vitest';
import { batchItemLabel, batchLabel, deliveryLabel, evidenceStatus, shouldRetryDelivery, taskLabel } from './labels';

describe('workbench state labels', () => {
  it('explains display-only delivery with its gate reason', () => {
    expect(deliveryLabel('display_only', ['contact_unverified'])).toEqual({
      text: '仅展示',
      detail: '联系方式未核验',
      tone: 'muted',
    });
  });

  it('shows login and challenge pauses as actionable states', () => {
    expect(taskLabel('waiting_for_login')).toEqual({
      text: '等待登录',
      detail: '请在浏览器中完成登录后恢复任务',
      tone: 'warning',
    });
    expect(taskLabel('waiting_for_challenge').tone).toBe('warning');
  });

  it('preserves source-backed evidence instead of upgrading it to verified', () => {
    expect(evidenceStatus('captured', 'captured')).toBe('captured');
    expect(evidenceStatus('source_backed', 'source_backed')).toBe('source_backed');
    expect(evidenceStatus(undefined, 'verified_public_web')).toBe('verified');
  });

  it('explains batch progress and retryable item failures', () => {
    expect(batchLabel('completed_with_errors', 1, 3)).toEqual({
      text: '部分完成',
      detail: '2 家已完成，1 家需要重试',
      tone: 'danger',
    });
    expect(batchItemLabel('failed')).toEqual({
      text: '待重试',
      detail: '该公司处理失败',
      tone: 'danger',
    });
  });

  it('keeps a failed ERP delivery retryable from the workbench', () => {
    expect(shouldRetryDelivery('completed_with_errors', 'failed')).toBe(true);
    expect(shouldRetryDelivery('ready', 'failed')).toBe(false);
    expect(shouldRetryDelivery('completed_with_errors', 'display_only')).toBe(false);
  });
});

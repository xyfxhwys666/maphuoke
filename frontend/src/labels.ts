export type LabelTone = 'neutral' | 'muted' | 'warning' | 'success' | 'danger';

export interface StatusLabel {
  text: string;
  detail: string;
  tone: LabelTone;
}

export type EvidenceStatus = 'captured' | 'source_backed' | 'verified';

export function evidenceStatus(fieldStatus?: string, contactVerificationStatus?: string): EvidenceStatus {
  if (fieldStatus === 'verified' || contactVerificationStatus === 'verified_public_web') {
    return 'verified';
  }
  if (fieldStatus === 'source_backed' || contactVerificationStatus === 'source_backed') {
    return 'source_backed';
  }
  return 'captured';
}

const reasonText: Record<string, string> = {
  company_name_unverified: '公司名称未核验',
  contact_unverified: '联系方式未核验',
  missing_mobile_or_email: '缺少手机号或邮箱',
  missing_source_url: '缺少来源链接',
  duplicate_payload: '已投递过相同内容',
};

export function deliveryLabel(status: string, reasons: string[] = []): StatusLabel {
  if (status === 'delivered') {
    return { text: '已推送', detail: 'ERP 已接收', tone: 'success' };
  }
  if (status === 'failed') {
    return { text: '推送失败', detail: reasons.map((reason) => reasonText[reason] ?? reason).join('、'), tone: 'danger' };
  }
  return {
    text: status === 'duplicate' ? '已存在' : '仅展示',
    detail: reasons.map((reason) => reasonText[reason] ?? reason).join('、') || '满足核验后可推送',
    tone: 'muted',
  };
}

export function taskLabel(status: string): StatusLabel {
  const labels: Record<string, StatusLabel> = {
    created: { text: '待开始', detail: '输入公司后开始地图搜索', tone: 'neutral' },
    discovering_map: { text: '地图搜索中', detail: '正在读取高德搜索结果', tone: 'warning' },
    candidates_ready: { text: '候选已就绪', detail: '请选择正确的 POI', tone: 'success' },
    enriching_doubao: { text: '豆包补全中', detail: '正在查询公开联系方式', tone: 'warning' },
    verifying: { text: '核验中', detail: '正在整理来源和证据', tone: 'warning' },
    ready: { text: '可以处理', detail: '线索已完成当前阶段', tone: 'success' },
    delivering: { text: '推送中', detail: '正在提交 ERP', tone: 'warning' },
    completed: { text: '已完成', detail: '任务已结束', tone: 'success' },
    paused: { text: '已暂停', detail: '可以恢复任务', tone: 'muted' },
    waiting_for_login: { text: '等待登录', detail: '请在浏览器中完成登录后恢复任务', tone: 'warning' },
    waiting_for_challenge: { text: '等待人工处理', detail: '请完成安全验证后恢复任务', tone: 'warning' },
    completed_with_errors: { text: '部分失败', detail: '可以重试失败公司', tone: 'danger' },
  };
  return labels[status] ?? { text: status, detail: '状态待更新', tone: 'neutral' };
}

export function collectionStatusLabel(status: string): StatusLabel {
  const labels: Record<string, StatusLabel> = {
    planned: { text: '计划已生成', detail: '确认执行计划后开始采集', tone: 'neutral' },
    queued: { text: '等待执行', detail: '工作单元等待浏览器处理', tone: 'muted' },
    running: { text: '采集中', detail: '正在按城市和关键词搜索高德', tone: 'warning' },
    paused: { text: '已暂停', detail: '可以继续当前采集任务', tone: 'muted' },
    needs_attention: { text: '需要处理', detail: '请在独立 Chrome 中完成登录或安全验证', tone: 'warning' },
    completed: { text: '采集完成', detail: '结果已整理并保存', tone: 'success' },
    completed_with_errors: { text: '部分完成', detail: '有工作单元失败，可重试', tone: 'danger' },
    cancelled: { text: '已取消', detail: '任务不会继续执行', tone: 'muted' },
  };
  return labels[status] ?? { text: status, detail: '状态待更新', tone: 'neutral' };
}

export function collectionProgressPercent({
  total,
  completed,
  failed = 0,
}: {
  total: number;
  completed: number;
  failed?: number;
}): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round(((completed + failed) / total) * 100)));
}

export function batchLabel(status: string, failed: number, total: number): StatusLabel {
  const completed = Math.max(total - failed, 0);
  if (status === 'completed') {
    return { text: '全部完成', detail: `${total} 家已完成地图搜索`, tone: 'success' };
  }
  if (status === 'completed_with_errors') {
    return { text: '部分完成', detail: `${completed} 家已完成，${failed} 家需要重试`, tone: 'danger' };
  }
  if (status === 'running') {
    return { text: '批量处理中', detail: `${completed} / ${total} 家已完成`, tone: 'warning' };
  }
  if (status === 'paused') {
    return { text: '批量已暂停', detail: `${completed} / ${total} 家已完成，可继续处理`, tone: 'muted' };
  }
  return { text: '待开始', detail: `${total} 家公司等待地图搜索`, tone: 'neutral' };
}

export function batchItemLabel(status: string): StatusLabel {
  const labels: Record<string, StatusLabel> = {
    queued: { text: '排队中', detail: '等待处理', tone: 'muted' },
    running: { text: '处理中', detail: '正在搜索地图', tone: 'warning' },
    completed: { text: '已完成', detail: '候选已保存', tone: 'success' },
    failed: { text: '待重试', detail: '该公司处理失败', tone: 'danger' },
  };
  return labels[status] ?? { text: status, detail: '状态待更新', tone: 'neutral' };
}

export function shouldRetryDelivery(taskStatus: string, deliveryStatus?: string): boolean {
  return taskStatus === 'completed_with_errors' && deliveryStatus === 'failed';
}
